"""Rules for the two datatypes this project adds to BIDS: lab and reports.

BIDS has no concept of a laboratory result or a clinical report, so these rules
check a schema defined here rather than one inherited. That makes them the part
of the validator most likely to need revision, and the reason the required
column sets live in :mod:`commissura.layout` rather than inline: changing the
schema should be an edit in one place, not a hunt through the rules.
"""

from __future__ import annotations

from collections.abc import Iterator

from commissura import layout
from commissura.validate.context import DatasetContext
from commissura.validate.findings import Finding, Severity
from commissura.validate.rules._registry import rule


@rule("LB001", "Lab tables carry the required columns")
def lab_required_columns(context: DatasetContext) -> Iterator[Finding]:
    """Report lab tables missing a column the schema requires.

    Without ``day_offset`` the result cannot be placed in time; without
    ``loinc_code`` it cannot be compared across sites; without ``unit`` the
    number is unusable. Each of the four is load-bearing.
    """
    for data_file in context.files_of_datatype("lab"):
        if data_file.name is None or data_file.name.suffix != layout.LAB_SUFFIX:
            continue
        if data_file.name.extension != ".tsv":
            continue
        table = context.read_tsv(data_file.relative)
        if not table.header:
            continue
        for column in layout.LAB_REQUIRED_COLUMNS:
            if column not in table.header:
                yield Finding(
                    rule_id="LB001",
                    severity=Severity.ERROR,
                    message=f"{data_file.relative} is missing the required column {column!r}",
                    path=data_file.relative,
                    hint="Required columns: " + ", ".join(layout.LAB_REQUIRED_COLUMNS),
                )


@rule("LB002", "Lab tables carry the recommended columns")
def lab_recommended_columns(context: DatasetContext) -> Iterator[Finding]:
    """Report lab tables missing a recommended column.

    A result with no reference interval parses cleanly and cannot be
    interpreted, which is why the generator models that case as a defect.
    """
    for data_file in context.files_of_datatype("lab"):
        if data_file.name is None or data_file.name.suffix != layout.LAB_SUFFIX:
            continue
        if data_file.name.extension != ".tsv":
            continue
        table = context.read_tsv(data_file.relative)
        if not table.header:
            continue
        missing = [c for c in layout.LAB_RECOMMENDED_COLUMNS if c not in table.header]
        if missing:
            yield Finding(
                rule_id="LB002",
                severity=Severity.WARNING,
                message=f"{data_file.relative} does not carry {', '.join(missing)}",
                path=data_file.relative,
            )


@rule("LB003", "The lab directory holds lab tables")
def lab_directory_contents(context: DatasetContext) -> Iterator[Finding]:
    """Report files in a lab directory that are not lab tables or their sidecars."""
    for data_file in context.files_of_datatype("lab"):
        if data_file.name is None:
            continue  # NM004 reports grammar failures
        if data_file.name.suffix != layout.LAB_SUFFIX:
            yield Finding(
                rule_id="LB003",
                severity=Severity.WARNING,
                message=(
                    f"{data_file.relative} has suffix {data_file.name.suffix!r} inside a lab "
                    f"directory, expected {layout.LAB_SUFFIX!r}"
                ),
                path=data_file.relative,
            )
        elif data_file.name.extension not in {".tsv", ".json"}:
            yield Finding(
                rule_id="LB003",
                severity=Severity.WARNING,
                message=(
                    f"{data_file.relative} has extension {data_file.name.extension!r}, "
                    "expected .tsv or .json"
                ),
                path=data_file.relative,
            )


@rule("RP001", "Every report text has a JSON sidecar")
def reports_have_sidecars(context: DatasetContext) -> Iterator[Finding]:
    """Report report text with no accompanying sidecar.

    The text alone carries no structure: nothing says what kind of report it is
    or when it was written relative to the subject's baseline. Without the
    sidecar it is a file somebody has to read to classify.
    """
    reports = context.files_of_datatype("reports")
    present = {file.relative for file in reports}
    for data_file in reports:
        if not data_file.relative.endswith(layout.REPORT_TEXT_EXTENSION):
            continue
        sidecar = data_file.relative.removesuffix(layout.REPORT_TEXT_EXTENSION) + (
            layout.REPORT_SIDECAR_EXTENSION
        )
        if sidecar not in present:
            yield Finding(
                rule_id="RP001",
                severity=Severity.ERROR,
                message=f"{data_file.relative} has no {layout.REPORT_SIDECAR_EXTENSION} sidecar",
                path=data_file.relative,
                hint="The sidecar carries the report kind and its day_offset.",
            )


@rule("RP002", "Report sidecars carry the required keys")
def report_sidecar_keys(context: DatasetContext) -> Iterator[Finding]:
    """Report sidecars missing a required key."""
    for data_file in context.files_of_datatype("reports"):
        if not data_file.relative.endswith(layout.REPORT_SIDECAR_EXTENSION):
            continue
        document = context.read_json(data_file.relative)
        if not document.is_object or document.data is None:
            continue
        for key in layout.REPORT_REQUIRED_SIDECAR_KEYS:
            if key not in document.data:
                yield Finding(
                    rule_id="RP002",
                    severity=Severity.ERROR,
                    message=f"{data_file.relative} is missing the required key {key!r}",
                    path=data_file.relative,
                )


@rule("RP003", "Every report sidecar has its text")
def sidecars_have_text(context: DatasetContext) -> Iterator[Finding]:
    """Report a sidecar with no corresponding text file.

    The reverse of RP001, and the sign of a conversion that wrote metadata and
    then failed before writing the document it describes.
    """
    reports = context.files_of_datatype("reports")
    present = {file.relative for file in reports}
    for data_file in reports:
        if not data_file.relative.endswith(layout.REPORT_SIDECAR_EXTENSION):
            continue
        text = data_file.relative.removesuffix(layout.REPORT_SIDECAR_EXTENSION) + (
            layout.REPORT_TEXT_EXTENSION
        )
        if text not in present:
            yield Finding(
                rule_id="RP003",
                severity=Severity.WARNING,
                message=f"{data_file.relative} describes a report whose text is missing",
                path=data_file.relative,
            )
