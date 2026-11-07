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

from commissura import __version__, layout
from commissura.build.manifest import write_healthdcat_description, write_manifest
from commissura.build.risk import K_THRESHOLD, assess, write_risk_report
from commissura.build.writer import BuildSpec, build_dataset
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
from commissura.healthdcat import RELEASE as HEALTHDCAT_RELEASE
from commissura.healthdcat import Tier as HealthTier
from commissura.read.corpus import read_corpus
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
    - a de-identifier cannot be tested on data with nothing to remove. Every
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


@app.command()
def build(
    source: Annotated[
        Path,
        typer.Argument(help="The raw corpus to read."),
    ],
    out: Annotated[
        Path,
        typer.Option("--out", "-o", help="Directory to write the dataset into."),
    ] = Path("dataset"),
    key_file: Annotated[
        Path | None,
        typer.Option("--key-file", help="The pseudonymisation key."),
    ] = None,
    name: Annotated[
        str,
        typer.Option("--name", help="Dataset title, written to both descriptions."),
    ] = "De-identified multimodal clinical dataset",
    description: Annotated[
        str,
        typer.Option("--description", help="Dataset description, required by the profile."),
    ] = (
        "Laboratory results, clinical reports and imaging metadata for a cohort of "
        "subjects, de-identified and linked across modalities."
    ),
    hdab: Annotated[
        str | None,
        typer.Option(
            "--hdab",
            help="The Health Data Access Body governing this dataset. Mandatory for "
            "HealthDCAT-AP conformance and deliberately not invented.",
        ),
    ] = None,
    publisher: Annotated[
        str | None,
        typer.Option("--publisher", help="The organisation releasing the dataset."),
    ] = None,
    tier: Annotated[
        str,
        typer.Option(
            "--tier",
            help="Which HealthDCAT-AP tier applies: public, non-public or restricted. "
            "This is a fact about the release arrangement, so it is yours to declare.",
        ),
    ] = "non-public",
    validate_output: Annotated[
        bool,
        typer.Option(
            "--validate/--no-validate",
            help="Validate the dataset after writing it, and fail if it does not conform.",
        ),
    ] = True,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print the summary as JSON instead of text.")
    ] = False,
) -> None:
    """Pseudonymise a raw corpus into a dataset, with a manifest and a description.

    Reads the three exports under the source directory, links them to the same
    people, derives every pseudonym from one secret key, expresses dates only as
    offsets from each subject's own earliest event, scrubs the free text using
    the identifiers the structured exports declared, and writes a BIDS-shaped
    dataset.

    Two documents accompany it. `.deident/manifest.json` records what was done
    and what the method could not reach. `healthdcat-ap.jsonld` describes the
    dataset against HealthDCAT-AP, which is what a Health Data Access Body
    reads.

    The command reports rather than refuses when it cannot be fully conformant.
    `healthdcatap:hdab` is mandatory in the profile and Italy has not designated
    its access body yet, so a dataset that names none is the normal case until
    2027 and should still be buildable.
    """
    try:
        selected_tier = HealthTier(tier)
    except ValueError:
        typer.echo(
            f"Unknown tier {tier!r}. Expected one of: " + ", ".join(t.value for t in HealthTier),
            err=True,
        )
        raise typer.Exit(2) from None

    try:
        key = resolve_key(key_file)
    except KeyMaterialError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None

    if not source.is_dir():
        typer.echo(f"No raw corpus at {source}.", err=True)
        raise typer.Exit(1)

    corpus = read_corpus(source)
    if not corpus.subjects:
        typer.echo(
            f"No subjects could be established from {source}. A subject is created by a "
            "laboratory message carrying a national identifier in PID-19; without one "
            "there is nothing to attribute records to.",
            err=True,
        )
        raise typer.Exit(1)

    spec = BuildSpec(
        dataset_name=name,
        description=description,
        tier=selected_tier,
        hdab=hdab,
        publisher=publisher,
    )
    summary = build_dataset(corpus, key, spec, out)
    write_manifest(out, corpus=corpus, summary=summary, key=key, spec=spec)
    write_healthdcat_description(out, spec=spec, summary=summary)
    risk = write_risk_report(out)

    report = validate_dataset(out) if validate_output else None

    if as_json:
        typer.echo(
            json.dumps(
                {
                    "dataset_root": str(summary.root),
                    "subjects": summary.subject_count,
                    "sessions": summary.session_count,
                    "files": summary.file_count,
                    "linkage_issues": summary.linkage_issues,
                    "free_text_redactions": summary.redaction_count,
                    "key_fingerprint": key.fingerprint,
                    "profile": {
                        "release": HEALTHDCAT_RELEASE,
                        "tier": selected_tier.value,
                        "mandatory_properties_unsatisfied": list(summary.missing_for_conformance),
                    },
                    "residual_risk": list(summary.residual_risks()),
                    "k_anonymity": {
                        "minimum_k": risk["minimum_k"],
                        "below_threshold": len(risk["combinations_below_threshold"]),  # type: ignore[arg-type]
                    },
                    "validation": None
                    if report is None
                    else {
                        "conformant": report.is_conformant,
                        "counts": report.counts_by_severity(),
                    },
                },
                indent=2,
            )
        )
    else:
        typer.echo(f"Wrote {summary.file_count} files to {summary.root}")
        typer.echo(f"  subjects   {summary.subject_count:6d}  sessions {summary.session_count}")
        typer.echo(f"  lab        {summary.lab_files:6d}  tables and sidecars")
        typer.echo(f"  reports    {summary.report_files:6d}  documents and sidecars")
        typer.echo(f"  imaging    {summary.imaging_files:6d}  metadata sidecars in derivatives/")
        typer.echo("")
        typer.echo(f"  key fingerprint        {key.fingerprint}")
        typer.echo(f"  free-text redactions   {summary.redaction_count}")
        typer.echo(f"  linkage issues         {summary.linkage_issues}")
        typer.echo(
            f"  minimum k              {risk['minimum_k']}"
            f"  ({len(risk['combinations_below_threshold'])} combination(s) below "  # type: ignore[arg-type]
            f"{K_THRESHOLD})"
        )
        typer.echo(
            f"  profile                HealthDCAT-AP {HEALTHDCAT_RELEASE}, "
            f"{selected_tier.value} tier"
        )
        if summary.missing_for_conformance:
            typer.echo("")
            typer.echo("  Not yet conformant. Mandatory properties with no value:")
            for term in summary.missing_for_conformance:
                typer.echo(f"    {term}")
            typer.echo("    Supply them with --hdab and --publisher.")
        if summary.residual_risks():
            typer.echo("")
            typer.echo("  Residual risk the method cannot reach:")
            for entry in summary.residual_risks():
                typer.echo(f"    {entry}")
        if report is not None:
            typer.echo("")
            counts = report.counts_by_severity()
            verdict = "conforms" if report.is_conformant else "DOES NOT CONFORM"
            typer.echo(
                f"  Validation: {verdict} - {counts['error']} error(s), "
                f"{counts['warning']} warning(s)"
            )
            for finding in report.errors[:5]:
                typer.echo(f"    {finding.format_line()}")

    if report is not None and not report.is_conformant:
        raise typer.Exit(1)


@app.command()
def risk(
    dataset: Annotated[Path, typer.Argument(help="The dataset to assess.")],
    threshold: Annotated[
        int,
        typer.Option("--threshold", "-k", min=1, help="Flag combinations shared by fewer."),
    ] = K_THRESHOLD,
    write: Annotated[
        bool,
        typer.Option("--write/--no-write", help="Write .deident/risk_report.json."),
    ] = True,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print the report as JSON instead of text.")
    ] = False,
) -> None:
    """Measure k-anonymity over the participant attributes.

    A dataset with no name in it can still identify somebody. If one participant
    is the only 94-year-old woman in the cohort, that row is unique on attributes
    nobody thinks of as identifiers.

    Not an Article 78 quality label: those criteria are not published yet.
    """
    if not (dataset / layout.PARTICIPANTS_TSV).is_file():
        typer.echo(f"No {layout.PARTICIPANTS_TSV} under {dataset}.", err=True)
        raise typer.Exit(1)

    payload = (
        write_risk_report(dataset, threshold=threshold)
        if write
        else assess(dataset, threshold=threshold)
    )

    if as_json:
        typer.echo(json.dumps(payload, indent=2))
        return

    below = payload["combinations_below_threshold"]
    identifiers = payload["quasi_identifiers"]
    assert isinstance(below, list)
    assert isinstance(identifiers, list)
    typer.echo(f"  participants           {payload['participants']}")
    typer.echo(f"  quasi-identifiers      {', '.join(identifiers)}")
    typer.echo(f"  minimum k              {payload['minimum_k']}")
    typer.echo(f"  below k={threshold}              {len(below)} combination(s)")
    for entry in below[:10]:
        values = ", ".join(f"{k}={v}" for k, v in entry["values"].items())
        typer.echo(f"    k={entry['k']}  {values}")
    if len(below) > 10:
        typer.echo(f"    ... and {len(below) - 10} more")
