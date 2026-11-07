"""Rules about participants.tsv and its agreement with the directories on disk."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator

from commissura import layout
from commissura.validate.context import DatasetContext
from commissura.validate.findings import Finding, Severity
from commissura.validate.rules._registry import rule


@rule("PT001", "participants.tsv is readable and not empty")
def participants_readable(context: DatasetContext) -> Iterator[Finding]:
    """Report a participants table that exists but cannot be read."""
    table = context.participants
    if table.exists and table.error is not None:
        yield Finding(
            rule_id="PT001",
            severity=Severity.ERROR,
            message=f"{table.relative} could not be read: {table.error}",
            path=table.relative,
            hint="The file must be tab-separated UTF-8 with a header row.",
        )


@rule("PT002", "participant_id is the first column")
def participant_id_first(context: DatasetContext) -> Iterator[Finding]:
    """Report a participants table whose first column is not ``participant_id``.

    Required by BIDS, and relied upon by tools that read the column positionally
    rather than by name.
    """
    table = context.participants
    if not table.header:
        return
    if table.header[0] != layout.PARTICIPANT_ID_COLUMN:
        yield Finding(
            rule_id="PT002",
            severity=Severity.ERROR,
            message=(
                f"first column of {table.relative} is {table.header[0]!r}, "
                f"expected {layout.PARTICIPANT_ID_COLUMN!r}"
            ),
            path=table.relative,
            hint="BIDS requires participant_id first; some readers take it by position.",
        )


@rule("PT003", "Every participant_id is a well-formed sub-<label>")
def participant_id_format(context: DatasetContext) -> Iterator[Finding]:
    """Report participant identifiers that do not follow the BIDS label grammar."""
    table = context.participants
    for value in table.column(layout.PARTICIPANT_ID_COLUMN):
        if not value.startswith(layout.SUBJECT_PREFIX):
            yield Finding(
                rule_id="PT003",
                severity=Severity.ERROR,
                message=f"participant_id {value!r} does not start with {layout.SUBJECT_PREFIX!r}",
                path=table.relative,
            )
            continue
        label = value.removeprefix(layout.SUBJECT_PREFIX)
        if not layout.LABEL_PATTERN.match(label):
            yield Finding(
                rule_id="PT003",
                severity=Severity.ERROR,
                message=f"participant_id {value!r} has a non-alphanumeric label",
                path=table.relative,
                hint="Labels may contain only letters and digits: an underscore or hyphen "
                "makes the filename grammar ambiguous.",
            )


@rule("PT004", "No participant is listed twice")
def participant_id_unique(context: DatasetContext) -> Iterator[Finding]:
    """Report duplicated participant identifiers.

    A duplicate silently halves a cohort when a reader builds a dictionary
    keyed by participant, and nothing warns them.
    """
    table = context.participants
    tally = Counter(table.column(layout.PARTICIPANT_ID_COLUMN))
    for value, count in sorted(tally.items()):
        if count > 1:
            yield Finding(
                rule_id="PT004",
                severity=Severity.ERROR,
                message=f"participant_id {value!r} appears {count} times",
                path=table.relative,
            )


@rule("PT005", "Every listed participant has a directory")
def listed_participants_have_directories(context: DatasetContext) -> Iterator[Finding]:
    """Report participants in the table with no matching ``sub-*`` directory."""
    table = context.participants
    if not table.header:
        return
    directories = set(context.subject_dirs)
    for value in sorted(set(table.column(layout.PARTICIPANT_ID_COLUMN))):
        if value and value not in directories:
            yield Finding(
                rule_id="PT005",
                severity=Severity.ERROR,
                message=f"{value} is listed in {table.relative} but has no directory",
                path=value,
                hint="Either the data is missing or the row is stale.",
            )


@rule("PT006", "Every subject directory is listed")
def directories_are_listed(context: DatasetContext) -> Iterator[Finding]:
    """Report ``sub-*`` directories absent from the participants table.

    The counterpart of PT005, and the more dangerous direction: an unlisted
    subject is present in the data but invisible to anyone who builds their
    cohort from the table, so it is silently excluded from the analysis and
    silently included in the release.
    """
    table = context.participants
    if not table.header:
        return
    listed = set(context.participants.column(layout.PARTICIPANT_ID_COLUMN))
    for directory in context.subject_dirs:
        if directory not in listed:
            yield Finding(
                rule_id="PT006",
                severity=Severity.ERROR,
                message=f"directory {directory} is not listed in {table.relative}",
                path=directory,
                hint="An unlisted subject ships with the data but is invisible to anyone "
                "building a cohort from the table.",
            )


@rule("PT007", "Every row has as many cells as the header")
def rows_are_rectangular(context: DatasetContext) -> Iterator[Finding]:
    """Report rows whose cell count disagrees with the header.

    A ragged row shifts every later value into the wrong column, so a sex ends
    up in the age field and nothing raises.
    """
    table = context.participants
    if not table.header:
        return
    width = len(table.header)
    for number, row in enumerate(table.rows, start=2):  # row 1 is the header
        if len(row) != width:
            yield Finding(
                rule_id="PT007",
                severity=Severity.ERROR,
                message=(
                    f"row {number} of {table.relative} has {len(row)} cells, header has {width}"
                ),
                path=table.relative,
                hint="Values past the mismatch are read into the wrong columns.",
            )


@rule("PT008", "Missing values are written as n/a")
def missing_values_are_explicit(context: DatasetContext) -> Iterator[Finding]:
    """Report empty cells, which BIDS spells ``n/a``.

    An empty cell is ambiguous: it could mean not measured, not applicable, or
    lost in export. ``n/a`` at least says somebody decided.
    """
    table = context.participants
    if not table.header:
        return
    for number, row in enumerate(table.rows, start=2):
        for index, cell in enumerate(row):
            if cell == "":
                column = table.header[index] if index < len(table.header) else f"column {index + 1}"
                yield Finding(
                    rule_id="PT008",
                    severity=Severity.WARNING,
                    message=f"row {number} of {table.relative} has an empty {column} cell",
                    path=table.relative,
                    hint=f"Write {layout.NOT_APPLICABLE!r} instead of leaving it blank.",
                )


@rule("PT009", "The recommended participant columns are present")
def recommended_columns(context: DatasetContext) -> Iterator[Finding]:
    """Report missing recommended columns such as age and sex."""
    table = context.participants
    if not table.header:
        return
    for column in layout.RECOMMENDED_PARTICIPANT_COLUMNS:
        if column not in table.header:
            yield Finding(
                rule_id="PT009",
                severity=Severity.WARNING,
                message=f"{table.relative} has no {column!r} column",
                path=table.relative,
                hint="Recommended for almost any secondary use of the dataset.",
            )
