"""Rules about the dataset's skeleton: which files and directories must exist."""

from __future__ import annotations

from collections.abc import Iterator

from commissura import layout
from commissura.validate.context import DatasetContext
from commissura.validate.findings import Finding, Severity
from commissura.validate.rules._registry import rule


@rule("DS001", "The dataset root exists and is a directory")
def dataset_root_exists(context: DatasetContext) -> Iterator[Finding]:
    """Report a missing or non-directory dataset root.

    Checked first and reported plainly, because every other rule will find
    nothing and a report full of silence is easy to mistake for a pass.
    """
    if not context.root_exists:
        yield Finding(
            rule_id="DS001",
            severity=Severity.ERROR,
            message=f"dataset root {context.root} is not an existing directory",
            hint="Check the path. No other rule can report anything useful until this is fixed.",
        )


@rule("DS002", "Required top-level files are present")
def required_top_level_files(context: DatasetContext) -> Iterator[Finding]:
    """Report any of the files without which this is not a dataset."""
    if not context.root_exists:
        return
    for required in layout.REQUIRED_TOP_LEVEL:
        if required not in context.top_level_entries:
            yield Finding(
                rule_id="DS002",
                severity=Severity.ERROR,
                message=f"required file {required} is missing from the dataset root",
                path=required,
                hint=f"Every dataset must carry {required}.",
            )


@rule("DS003", "dataset_description.json is a readable JSON object")
def description_parses(context: DatasetContext) -> Iterator[Finding]:
    """Report a dataset description that exists but cannot be read."""
    description = context.description
    if description.exists and description.error is not None:
        yield Finding(
            rule_id="DS003",
            severity=Severity.ERROR,
            message=f"{layout.DATASET_DESCRIPTION} could not be parsed: {description.error}",
            path=layout.DATASET_DESCRIPTION,
            hint="The file must contain a single JSON object.",
        )


@rule("DS004", "dataset_description.json carries the keys BIDS requires")
def description_required_keys(context: DatasetContext) -> Iterator[Finding]:
    """Report missing required description keys."""
    description = context.description
    if not description.is_object or description.data is None:
        return
    for key in layout.REQUIRED_DESCRIPTION_KEYS:
        if key not in description.data:
            yield Finding(
                rule_id="DS004",
                severity=Severity.ERROR,
                message=f"{layout.DATASET_DESCRIPTION} is missing the required key {key!r}",
                path=layout.DATASET_DESCRIPTION,
                hint=f"BIDS requires {key!r} in every dataset description.",
            )


@rule("DS005", "dataset_description.json carries the recommended provenance keys")
def description_recommended_keys(context: DatasetContext) -> Iterator[Finding]:
    """Report missing recommended description keys.

    A warning rather than an error: the dataset is usable without them, but a
    dataset that cannot say which tool and schema revision produced it cannot be
    reproduced, and reproducibility is the claim being made when it is handed
    over under a data permit.
    """
    description = context.description
    if not description.is_object or description.data is None:
        return
    for key in layout.RECOMMENDED_DESCRIPTION_KEYS:
        if key not in description.data:
            yield Finding(
                rule_id="DS005",
                severity=Severity.WARNING,
                message=f"{layout.DATASET_DESCRIPTION} does not record {key!r}",
                path=layout.DATASET_DESCRIPTION,
                hint="Recommended so the dataset can state its own provenance.",
            )


@rule("DS006", "The declared BIDS version is the one this schema follows")
def description_bids_version(context: DatasetContext) -> Iterator[Finding]:
    """Report a BIDS version other than the one the layout was written against."""
    description = context.description
    if not description.is_object or description.data is None:
        return
    declared = description.data.get("BIDSVersion")
    if isinstance(declared, str) and declared != layout.BIDS_VERSION:
        yield Finding(
            rule_id="DS006",
            severity=Severity.NOTICE,
            message=(
                f"dataset declares BIDSVersion {declared!r}; this validator follows "
                f"{layout.BIDS_VERSION!r}"
            ),
            path=layout.DATASET_DESCRIPTION,
            hint="Naming rules rarely change between minor versions, but check before relying "
            "on the result.",
        )


@rule("DS007", "The dataset contains at least one subject")
def has_subjects(context: DatasetContext) -> Iterator[Finding]:
    """Report a dataset with no subject directories."""
    if not context.root_exists:
        return
    if not context.subject_dirs:
        yield Finding(
            rule_id="DS007",
            severity=Severity.ERROR,
            message="the dataset contains no sub-* directories",
            hint="A dataset with no subjects has nothing in it to validate or to analyse.",
        )


@rule("DS008", "The dataset root holds nothing unexpected")
def unexpected_top_level_entries(context: DatasetContext) -> Iterator[Finding]:
    """Report entries at the root that are neither known files nor subjects.

    A warning, never an error. A stray entry is almost always a working copy or
    an editor artefact, and a validator that refuses a dataset over
    ``participants.tsv.bak`` is one people learn to route around.
    """
    if not context.root_exists:
        return
    for entry in context.top_level_entries:
        if entry in layout.KNOWN_TOP_LEVEL or entry.startswith(layout.SUBJECT_PREFIX):
            continue
        yield Finding(
            rule_id="DS008",
            severity=Severity.WARNING,
            message=f"unexpected entry {entry!r} at the dataset root",
            path=entry,
            hint="Remove it, or move it under derivatives/ if it is generated output.",
        )


@rule("DS009", "The de-identification manifest is present and readable")
def manifest_present(context: DatasetContext) -> Iterator[Finding]:
    """Report a missing or unreadable manifest.

    An error, because the manifest is what makes the dataset auditable. Without
    it there is no record of which fields were removed, replaced or kept, and
    no way to tell whether the de-identification claimed was the one performed.
    """
    if not context.root_exists:
        return
    manifest = context.manifest
    if not manifest.exists:
        yield Finding(
            rule_id="DS009",
            severity=Severity.ERROR,
            message=f"{manifest.relative} is missing",
            path=manifest.relative,
            hint="Without the manifest the dataset cannot state what was done to it.",
        )
    elif manifest.error is not None:
        yield Finding(
            rule_id="DS009",
            severity=Severity.ERROR,
            message=f"{manifest.relative} could not be parsed: {manifest.error}",
            path=manifest.relative,
        )


@rule("DS010", "The re-identification risk report is present")
def risk_report_present(context: DatasetContext) -> Iterator[Finding]:
    """Report a missing risk report.

    A warning rather than an error: the dataset is structurally complete without
    it, but nobody can judge whether releasing it is safe.
    """
    if not context.root_exists:
        return
    report = context.risk_report
    if not report.exists:
        yield Finding(
            rule_id="DS010",
            severity=Severity.WARNING,
            message=f"{report.relative} is missing",
            path=report.relative,
            hint="Run the risk report so the k-anonymity of the participant attributes is on "
            "record.",
        )
    elif report.error is not None:
        yield Finding(
            rule_id="DS010",
            severity=Severity.ERROR,
            message=f"{report.relative} could not be parsed: {report.error}",
            path=report.relative,
        )
