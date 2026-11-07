"""Command-line interface.

The CLI is a thin shell over the library: every command parses arguments, calls
one library function and prints the result. Nothing in here contains logic that
a programmer importing ``commissura`` could not reach, which is the property that
keeps the tool usable both ways and keeps the interesting code testable without
a subprocess.

``--json`` is offered on every command that reports anything, because a tool
that will be run inside somebody else's pipeline should not force them to parse
a human-readable table.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from commissura import __version__
from commissura.deident.keys import (
    KEY_FILE_ENV_VAR,
    KeyMaterialError,
    generate_key,
    resolve_key,
    write_key_file,
)
from commissura.deident.pseudonymise import RULE_VERSION
from commissura.generate.cohort import DEFAULT_REFERENCE_DATE, CohortSpec
from commissura.generate.defects import CATALOGUE, Modality, defects_for
from commissura.generate.writer import verify_corpus, write_corpus
from commissura.validate import registered_rules, validate_dataset

app = typer.Typer(
    name="commissura",
    help="Build standardised, de-identified, research-ready clinical datasets.",
    no_args_is_help=True,
    add_completion=True,
)


def _version_callback(requested: bool) -> None:
    """Print the version and exit, if requested."""
    if requested:
        typer.echo(__version__)
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the installed version and exit.",
        ),
    ] = False,
) -> None:
    """Build standardised, de-identified, research-ready clinical datasets."""


@app.command()
def generate(
    out: Annotated[
        Path,
        typer.Option("--out", "-o", help="Directory to write the corpus into."),
    ] = Path("raw"),
    subjects: Annotated[
        int, typer.Option("--subjects", "-n", min=1, help="How many subjects to generate.")
    ] = 10,
    seed: Annotated[
        int,
        typer.Option(
            "--seed",
            "-s",
            help="Master seed. The same seed and version always produce the same corpus.",
        ),
    ] = 0,
    defect_rate: Annotated[
        float,
        typer.Option(
            "--defect-rate",
            "-d",
            min=0.0,
            max=1.0,
            help="Probability that any given defect opportunity is taken. "
            "0 gives a clean corpus, 1 one that is maximally hostile to a validator.",
        ),
    ] = 0.15,
    max_encounters: Annotated[
        int,
        typer.Option("--max-encounters", min=1, help="Upper bound on encounters per subject."),
    ] = 3,
    verify: Annotated[
        bool,
        typer.Option(
            "--verify/--no-verify",
            help="Re-read every file from disk and confirm the recorded PHI offsets match.",
        ),
    ] = True,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print the summary as JSON instead of text.")
    ] = False,
) -> None:
    """Write a synthetic raw clinical corpus with ground-truth PHI annotations.

    The generated material deliberately contains synthetic identifiers: names,
    codici fiscali, absolute dates, addresses and clinicians. That is the point
    — a de-identifier cannot be tested on data with nothing to remove. Every
    identifier is recorded in ``_generator/phi_annotations.json`` with its exact
    position, which is what makes de-identification recall measurable.

    All of it is fabricated. Where the format allows it, the identifiers are
    provably not real: codici fiscali use an unassigned place-of-birth range,
    telephone numbers cannot be dialled, and email domains end in ``.invalid``.
    """
    spec = CohortSpec(
        subjects=subjects,
        seed=seed,
        defect_rate=defect_rate,
        reference_date=DEFAULT_REFERENCE_DATE,
        max_encounters=max_encounters,
    )
    summary = write_corpus(spec, out)
    if verify:
        verify_corpus(summary)

    manifest = summary.manifest
    if as_json:
        typer.echo(json.dumps(manifest.model_dump(mode="json"), indent=2))
        return

    counts = manifest.files
    typer.echo(f"Wrote {summary.file_count} files to {summary.root}")
    typer.echo(f"  lab       {counts.lab:6d}  HL7 v2 ORU^R01 messages")
    typer.echo(f"  reports   {counts.reports:6d}  free-text documents")
    typer.echo(f"  imaging   {counts.imaging:6d}  DICOM JSON Model sidecars")
    typer.echo("")
    typer.echo(f"  subjects  {manifest.subject_count:6d}  seed {manifest.seed}")
    typer.echo(f"  PHI spans {manifest.phi_span_count:6d}  recorded as ground truth")
    typer.echo(f"  defects   {len(manifest.defects):6d}  injected at rate {defect_rate}")
    if verify:
        typer.echo("")
        typer.echo("  Verified: every recorded PHI offset matches the file on disk.")


@app.command("defects")
def list_defects(
    as_json: Annotated[
        bool, typer.Option("--json", help="Print the catalogue as JSON instead of text.")
    ] = False,
) -> None:
    """List the defects the generator can inject, and why each one occurs.

    Useful on its own: the catalogue is a checklist of what clinical data
    exports actually get wrong, with the real-world cause recorded next to each
    entry.
    """
    if as_json:
        typer.echo(
            json.dumps(
                [
                    {
                        "id": defect.defect_id,
                        "modality": defect.modality.value,
                        "class": defect.defect_class.value,
                        "summary": defect.summary,
                        "why_it_happens": defect.why_it_happens,
                    }
                    for defect in CATALOGUE
                ],
                indent=2,
            )
        )
        return

    # Iterating the enum rather than a hard-coded list of names means a new
    # modality shows up here without anyone remembering to add it.
    for modality in Modality:
        group = defects_for(modality)
        typer.echo(f"{modality.value.upper()}  ({len(group)})")
        for defect in group:
            typer.echo(f"  {defect.defect_id:40s} [{defect.defect_class.value}]")
            typer.echo(f"      {defect.summary}")
        typer.echo("")


if __name__ == "__main__":  # pragma: no cover
    app()


@app.command()
def validate(
    dataset: Annotated[
        Path,
        typer.Argument(help="The dataset directory to check."),
    ],
    as_json: Annotated[
        bool, typer.Option("--json", help="Print the full report as JSON instead of text.")
    ] = False,
    strict: Annotated[
        bool,
        typer.Option(
            "--strict",
            help="Treat warnings as failures. Off by default, so a dataset is not rejected "
            "for something that is merely inadvisable.",
        ),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="Print only the summary line, not each finding."),
    ] = False,
    notices: Annotated[
        bool,
        typer.Option("--notices/--no-notices", help="Include observations that imply no fault."),
    ] = True,
) -> None:
    """Check whether a dataset conforms to the layout, and report what is missing.

    Reports everything it finds rather than stopping at the first problem: the
    question is what is missing, in the plural, and a validator that answers one
    item at a time turns a single review into a dozen round trips.

    Exits 0 when the dataset conforms, 1 when it does not. Warnings do not
    affect the exit code unless ``--strict`` is passed, because a dataset can
    conform and still have things worth improving.
    """
    report = validate_dataset(dataset, include_notices=notices)

    if as_json:
        typer.echo(json.dumps(report.model_dump(mode="json"), indent=2))
    else:
        if not quiet:
            for finding in report.findings:
                typer.echo(finding.format_line())
                if finding.hint:
                    typer.echo(f"        {finding.hint}")
            if report.findings:
                typer.echo("")

        counts = report.counts_by_severity()
        verdict = "CONFORMANT" if report.is_conformant else "NOT CONFORMANT"
        typer.echo(
            f"{verdict}: {counts['error']} error(s), {counts['warning']} warning(s), "
            f"{counts['notice']} notice(s) from {report.rules_run} rules"
        )

    failed = not report.is_conformant or (strict and report.warnings)
    if failed:
        raise typer.Exit(1)


@app.command("rules")
def list_rules(
    as_json: Annotated[
        bool, typer.Option("--json", help="Print the rule set as JSON instead of text.")
    ] = False,
) -> None:
    """List every validation rule, with its identifier and what it checks.

    The rule set is the schema. Printing it means somebody can see what a
    conformant dataset has to satisfy without reading the source, and can quote
    a rule identifier when asking why their dataset was rejected.
    """
    rules = registered_rules()
    if as_json:
        typer.echo(
            json.dumps(
                [{"id": entry.rule_id, "summary": entry.summary} for entry in rules], indent=2
            )
        )
        return

    for entry in rules:
        typer.echo(f"  {entry.rule_id}  {entry.summary}")
    typer.echo("")
    typer.echo(f"{len(rules)} rules")


@app.command()
def keygen(
    out: Annotated[
        Path,
        typer.Option("--out", "-o", help="Where to write the key file."),
    ],
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Replace an existing key file. Every dataset built with the old key "
            "becomes permanently unlinkable, so this is never the default.",
        ),
    ] = False,
) -> None:
    """Create a new pseudonymisation key.

    The key is written to a file and never printed. There is no option to pass a
    key as a command-line argument, here or anywhere else in this tool: an
    argument lands in shell history, in the output of `ps` for every other user
    on the machine, and in the logs of any CI system that runs the command.

    What is printed is the key's *fingerprint*, which identifies the key without
    carrying it. It is safe to record, and it is what the manifest stores, so two
    datasets can be shown to be linkable without either revealing the secret.
    """
    key = generate_key()
    try:
        report = write_key_file(key, out, overwrite=force)
    except FileExistsError:
        typer.echo(f"Refusing to overwrite the existing key file at {out}.", err=True)
        typer.echo(
            "Every dataset built with that key becomes permanently unlinkable if it is "
            "replaced. Pass --force only if you are certain no dataset depends on it.",
            err=True,
        )
        raise typer.Exit(1) from None

    typer.echo(f"Wrote a new key to {report.path}")
    typer.echo(f"  fingerprint        {report.fingerprint}")
    typer.echo(f"  owner-only access  {'yes' if report.permissions_restricted else 'NO'}")
    typer.echo("")
    typer.echo(f"  {report.advice}")
    typer.echo("")
    typer.echo("  Point future commands at it with:")
    typer.echo(f"    {KEY_FILE_ENV_VAR}={report.path}")


@app.command("key-info")
def key_info(
    key_file: Annotated[
        Path | None,
        typer.Option("--key-file", help="The key file to inspect."),
    ] = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print the result as JSON instead of text.")
    ] = False,
) -> None:
    """Show a key's fingerprint, without revealing the key.

    Answers the question somebody will ask years later: were these two datasets
    built from the same key, and are they therefore linkable? Compare the
    fingerprint printed here against the one recorded in a dataset's manifest.
    """
    try:
        key = resolve_key(key_file)
    except KeyMaterialError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None

    if as_json:
        typer.echo(
            json.dumps(
                {
                    "key_fingerprint": key.fingerprint,
                    "deidentification_rule_version": RULE_VERSION,
                },
                indent=2,
            )
        )
        return

    typer.echo(f"  fingerprint                     {key.fingerprint}")
    typer.echo(f"  de-identification rule version  {RULE_VERSION}")
