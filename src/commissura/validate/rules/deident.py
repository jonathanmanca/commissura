"""Rules that check the de-identification invariants the layout promises.

These are the rules that justify the command existing. Everything else here
checks that a dataset is well formed; these check that it is safe to release,
and they are deliberately expressed as *structural* requirements rather than as
advice. A dataset carrying a real calendar date is not weakly de-identified, it
is malformed, because the layout states that time is expressed only as an offset
from each subject's own baseline.

Two design choices worth stating.

**Column names are checked, not just values.** A column called ``mrn`` is wrong
whatever it happens to contain today. Checking the header catches the mistake at
the point it was made, and catches it even when the column is currently empty —
which it will not stay.

**Date detection is conservative by construction.** It matches date-shaped text
rather than trying to understand it, and the year and month ranges are anchored
so that an accession number is not mistaken for a date. A false positive costs
somebody a glance at one cell. A false negative ships a dataset with a real date
in it, to a recipient who was told there were none.
"""

from __future__ import annotations

from collections.abc import Iterator

from commissura import layout
from commissura.read.corpus import read_exact
from commissura.validate.context import DatasetContext, JsonFile, TsvFile
from commissura.validate.findings import Finding, Severity
from commissura.validate.rules._registry import rule


def _dates_in(text: str) -> list[str]:
    """Return every absolute-date-shaped substring of ``text``, without duplicates."""
    found: list[str] = []
    for pattern in layout.ABSOLUTE_DATE_PATTERNS:
        for match in pattern.findall(text):
            if match not in found:
                found.append(match)
    return found


def _all_tsv_files(context: DatasetContext) -> Iterator[TsvFile]:
    """Yield every tab-separated file in the dataset, participants table included."""
    if context.participants.exists:
        yield context.participants
    for data_file in context.data_files:
        if data_file.relative.endswith(".tsv"):
            yield context.read_tsv(data_file.relative)


def _all_json_files(context: DatasetContext) -> Iterator[JsonFile]:
    """Yield every JSON file the dataset carries, metadata included."""
    for candidate in (context.description, context.manifest, context.risk_report):
        if candidate.exists:
            yield candidate
    for data_file in context.data_files:
        if data_file.relative.endswith(".json"):
            yield context.read_json(data_file.relative)


@rule("DI001", "No tabular file carries an absolute date")
def no_absolute_dates_in_tables(context: DatasetContext) -> Iterator[Finding]:
    """Report date-shaped values in any TSV.

    The layout permits only ``day_offset``, an integer count of days from the
    subject's own baseline. Intervals stay exact; the calendar anchor is gone.
    """
    for table in _all_tsv_files(context):
        for number, row in enumerate(table.rows, start=2):
            for index, cell in enumerate(row):
                for found in _dates_in(cell):
                    column = (
                        table.header[index] if index < len(table.header) else f"column {index + 1}"
                    )
                    yield Finding(
                        rule_id="DI001",
                        severity=Severity.ERROR,
                        message=(
                            f"row {number}, column {column!r} of {table.relative} holds "
                            f"what looks like an absolute date: {found!r}"
                        ),
                        path=table.relative,
                        hint="Express it as day_offset from the subject's baseline.",
                    )


@rule("DI002", "No JSON file carries an absolute date")
def no_absolute_dates_in_json(context: DatasetContext) -> Iterator[Finding]:
    """Report date-shaped values anywhere in a JSON file.

    Scans the serialised text rather than walking the structure, so a date
    nested inside a list of objects is still found. ``generated_at`` in the
    manifest is excluded: the time the dataset was built says nothing about any
    patient, and recording it is part of the provenance the manifest exists for.
    """
    for document in _all_json_files(context):
        if document.data is None:
            continue
        for key, value in document.data.items():
            if key in {"generated_at", "checked_at", "DatasetDOI"}:
                continue
            for found in _dates_in(str(value)):
                yield Finding(
                    rule_id="DI002",
                    severity=Severity.ERROR,
                    message=(
                        f"key {key!r} of {document.relative} holds what looks like an "
                        f"absolute date: {found!r}"
                    ),
                    path=document.relative,
                    hint="Express it as day_offset from the subject's baseline.",
                )


@rule("DI003", "No report text carries an absolute date")
def no_absolute_dates_in_reports(context: DatasetContext) -> Iterator[Finding]:
    """Report date-shaped text surviving in a clinical report.

    The hardest case and the most important one. A date inside a sentence —
    ``si confronta con il precedente esame del 12/03/2023`` — is invisible to
    any field-based scrubber, and this is the only check that looks for it.
    """
    for data_file in context.data_files:
        if not data_file.relative.endswith(layout.REPORT_TEXT_EXTENSION):
            continue
        try:
            text = read_exact(data_file.path)
        except (OSError, UnicodeDecodeError) as exc:
            yield Finding(
                rule_id="DI003",
                severity=Severity.ERROR,
                message=f"{data_file.relative} could not be read: {exc}",
                path=data_file.relative,
            )
            continue
        for found in _dates_in(text):
            yield Finding(
                rule_id="DI003",
                severity=Severity.ERROR,
                message=(
                    f"{data_file.relative} contains what looks like an absolute date: {found!r}"
                ),
                path=data_file.relative,
                hint="A date written inside a sentence is invisible to field-based scrubbing. "
                "Replace it with an offset.",
            )


@rule("DI004", "Ages above the ceiling are truncated")
def ages_are_truncated(context: DatasetContext) -> Iterator[Finding]:
    """Report participant ages above the ceiling, however the column states them.

    In a small cohort an age of 97 is close to a unique identifier, and the
    information lost by truncating is negligible for most research questions.

    **What counts as a readable age comes from the layout and not from this
    rule**, which is a correction. The rule accepted an integer or the ceiling
    marker and warned on anything else, so from the day ``build --age-band``
    existed it emitted **one warning per participant** on every banded dataset
    -- the tool complaining about output it had just written, thirteen times on
    a twelve-subject corpus. Nothing caught it: the test asserting a banded
    dataset conforms was right and blind, because `is_conformant` means no
    *errors* and these were warnings.

    So the readable forms are :func:`commissura.layout.age_bounds`'s, which is
    the one place that defines what the column may hold. A rule that
    re-implements a schema it does not own will disagree with it the first time
    the schema moves.

    The ceiling check then applies to the upper bound, which is what the dataset
    actually states about the person: a band is clamped to the ceiling when it
    is written, so a band above it is a malformed dataset exactly as an integer
    above it is.
    """
    table = context.participants
    for value in table.column("age"):
        if value in {layout.AGE_ABOVE_CEILING, layout.NOT_APPLICABLE, ""}:
            continue
        bounds = layout.age_bounds(value)
        if bounds is None:
            yield Finding(
                rule_id="DI004",
                severity=Severity.WARNING,
                message=f"age {value!r} in {table.relative} is neither an age, a band "
                f"of two bounds, nor {layout.AGE_ABOVE_CEILING!r}",
                path=table.relative,
            )
            continue
        age = max(bounds)
        if age > layout.AGE_CEILING:
            yield Finding(
                rule_id="DI004",
                severity=Severity.ERROR,
                message=(
                    f"age {age} in {table.relative} exceeds the ceiling of {layout.AGE_CEILING}"
                ),
                path=table.relative,
                hint=f"Report it as {layout.AGE_ABOVE_CEILING!r}.",
            )


@rule("DI005", "No column is named after a direct identifier")
def no_identifier_columns(context: DatasetContext) -> Iterator[Finding]:
    """Report column names that name a direct identifier.

    Checked on the header rather than the values, so the finding appears at the
    point the mistake was made and survives a column that happens to be empty
    right now.
    """
    for table in _all_tsv_files(context):
        for column in table.header:
            if column.strip().lower() in layout.IDENTIFIER_COLUMN_NAMES:
                yield Finding(
                    rule_id="DI005",
                    severity=Severity.ERROR,
                    message=f"{table.relative} has a column named {column!r}",
                    path=table.relative,
                    hint="A column named after a direct identifier does not belong in a "
                    "de-identified dataset, whatever it currently holds.",
                )


@rule("DI006", "The manifest records everything needed to audit the run")
def manifest_required_keys(context: DatasetContext) -> Iterator[Finding]:
    """Report missing manifest keys.

    Each one answers a question somebody will ask years later: which rules were
    applied, which key produced the pseudonyms, which tool versions, and what
    was done per modality.
    """
    manifest = context.manifest
    if not manifest.is_object or manifest.data is None:
        return
    for key in layout.MANIFEST_REQUIRED_KEYS:
        if key not in manifest.data:
            yield Finding(
                rule_id="DI006",
                severity=Severity.ERROR,
                message=f"{manifest.relative} is missing the required key {key!r}",
                path=manifest.relative,
            )


@rule("DI007", "The key fingerprint is a fingerprint, not a key")
def key_fingerprint_is_well_formed(context: DatasetContext) -> Iterator[Finding]:
    """Report a key fingerprint that is not a lowercase hex digest.

    The fingerprint says *which* secret key produced the pseudonyms without
    carrying it, which is what makes two datasets provably relinkable and a
    dataset whose key was lost provably orphaned. A value in any other shape may
    be the key itself.
    """
    manifest = context.manifest
    if not manifest.is_object or manifest.data is None:
        return
    fingerprint = manifest.data.get("key_fingerprint")
    if fingerprint is None:
        return
    if not isinstance(fingerprint, str) or not layout.KEY_FINGERPRINT_PATTERN.match(fingerprint):
        yield Finding(
            rule_id="DI007",
            severity=Severity.ERROR,
            message=f"key_fingerprint in {manifest.relative} is not a lowercase hex digest",
            path=manifest.relative,
            hint="Expected 16 to 64 lowercase hex characters. Anything else may be the key.",
        )


@rule("DI009", "Imaging with identifiers burned into the pixels is flagged")
def burned_in_annotation_is_reported(context: DatasetContext) -> Iterator[Finding]:
    """Warn for every imaging study whose metadata says the pixels carry text.

    This project does not read pixel data — it orchestrates ``dcm2bids`` rather
    than reimplementing DICOM — so it cannot remove a name that a scanner
    rendered into the image. That is a documented limit, and the audit of
    2026-11-13 found the limit being documented in the same sentence whether a
    dataset held four such studies or none, while ``validate`` reported
    ``conforms`` with zero warnings over a dataset in which every study was
    flagged.

    A warning rather than an error, deliberately. The dataset is not malformed:
    ``burned_in_annotation`` is *carried on purpose* so that a downstream
    converter knows to beware, and refusing to build would leave the holder
    worse off than telling them. But a dataset nobody warned about is one
    somebody converts without looking.
    """
    for relative, payload in context.imaging_metadata():
        if payload.get("burned_in_annotation") is True:
            yield Finding(
                rule_id="DI009",
                severity=Severity.WARNING,
                message=f"{relative} records BurnedInAnnotation=YES",
                path=relative,
                hint=(
                    "Identifiers may be rendered into the image itself. This tool "
                    "does not inspect pixel data, so they are still there. Remove "
                    "or redact the pixels before release."
                ),
            )


@rule("DI008", "The secret key has not leaked into the manifest")
def no_secret_in_manifest(context: DatasetContext) -> Iterator[Finding]:
    """Report manifest keys whose names suggest the secret was written out.

    The pseudonymisation design makes the dataset useless without the key. A
    manifest carrying the key undoes that in one step, and writing it there is
    an easy thing to do while debugging and an easy thing to forget to remove.
    """
    manifest = context.manifest
    if not manifest.is_object or manifest.data is None:
        return
    for key in manifest.data:
        if key.strip().lower() in layout.FORBIDDEN_MANIFEST_KEYS:
            yield Finding(
                rule_id="DI008",
                severity=Severity.ERROR,
                message=f"{manifest.relative} contains a key named {key!r}",
                path=manifest.relative,
                hint="The secret key must never enter the dataset. Remove it and treat the "
                "key as compromised.",
            )
