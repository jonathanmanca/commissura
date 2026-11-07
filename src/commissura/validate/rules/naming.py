"""Rules about directory and file naming inside subjects.

The single most valuable check here is NM003: a file's entities must agree with
the directories containing it. BIDS encodes the same fact twice — once in the
path and once in the filename — and the redundancy is the point. When they
disagree, every tool that reads one of the two gets a different answer, and the
usual outcome is a scan silently attributed to the wrong subject.
"""

from __future__ import annotations

from collections.abc import Iterator

from commissura import layout
from commissura.validate.context import DatasetContext
from commissura.validate.findings import Finding, Severity
from commissura.validate.rules._registry import rule


@rule("NM001", "Subject and session labels are alphanumeric")
def labels_are_well_formed(context: DatasetContext) -> Iterator[Finding]:
    """Report subject or session directories whose labels break the grammar."""
    for directory in context.subject_dirs:
        label = directory.removeprefix(layout.SUBJECT_PREFIX)
        if not layout.LABEL_PATTERN.match(label):
            yield Finding(
                rule_id="NM001",
                severity=Severity.ERROR,
                message=f"subject directory {directory!r} has a non-alphanumeric label",
                path=directory,
                hint="Underscores separate entities and hyphens separate key from value, so "
                "neither may appear in a label.",
            )

    seen: set[str] = set()
    for datatype_dir in context.datatype_dirs:
        if datatype_dir.session is None or datatype_dir.session in seen:
            continue
        seen.add(datatype_dir.session)
        label = datatype_dir.session.removeprefix(layout.SESSION_PREFIX)
        if not layout.LABEL_PATTERN.match(label):
            yield Finding(
                rule_id="NM001",
                severity=Severity.ERROR,
                message=f"session directory {datatype_dir.session!r} has a non-alphanumeric label",
                path=f"{datatype_dir.subject}/{datatype_dir.session}",
            )


@rule("NM002", "Datatype directories are ones the schema knows")
def datatypes_are_known(context: DatasetContext) -> Iterator[Finding]:
    """Report datatype directories outside BIDS and this project's extension.

    A warning: an unknown datatype directory is ignored rather than
    misinterpreted, so it does not endanger a reader. It is almost always a
    typo, though — ``report`` for ``reports`` — and a typo means the data is
    invisible to everything that looks for the real name.
    """
    for datatype_dir in context.datatype_dirs:
        if datatype_dir.datatype not in layout.KNOWN_DATATYPES:
            yield Finding(
                rule_id="NM002",
                severity=Severity.WARNING,
                message=f"unknown datatype directory {datatype_dir.datatype!r}",
                path=datatype_dir.relative,
                hint="Known datatypes: "
                + ", ".join(sorted(layout.COMMISSURA_DATATYPES))
                + " and the BIDS datatypes.",
            )


@rule("NM003", "File entities agree with the directories containing the file")
def entities_match_directories(context: DatasetContext) -> Iterator[Finding]:
    """Report files whose ``sub-``/``ses-`` entities contradict their path.

    BIDS states the same fact in the path and in the filename on purpose. When
    the two disagree, one tool reads the path, another reads the name, and a
    study ends up attributed to the wrong subject with nothing raising.
    """
    for data_file in context.data_files:
        if data_file.name is None:
            continue

        expected_subject = data_file.subject.removeprefix(layout.SUBJECT_PREFIX)
        actual_subject = data_file.name.get("sub")
        if actual_subject is None:
            yield Finding(
                rule_id="NM003",
                severity=Severity.ERROR,
                message=f"{data_file.relative} carries no sub- entity",
                path=data_file.relative,
                hint=f"Expected sub-{expected_subject}.",
            )
        elif actual_subject != expected_subject:
            yield Finding(
                rule_id="NM003",
                severity=Severity.ERROR,
                message=(
                    f"{data_file.relative} names sub-{actual_subject} but sits under "
                    f"{data_file.subject}"
                ),
                path=data_file.relative,
                hint="The path and the filename must agree about who this belongs to.",
            )

        actual_session = data_file.name.get("ses")
        if data_file.session is None:
            if actual_session is not None:
                yield Finding(
                    rule_id="NM003",
                    severity=Severity.ERROR,
                    message=(
                        f"{data_file.relative} names ses-{actual_session} but is not inside a "
                        "session directory"
                    ),
                    path=data_file.relative,
                )
            continue

        expected_session = data_file.session.removeprefix(layout.SESSION_PREFIX)
        if actual_session is None:
            yield Finding(
                rule_id="NM003",
                severity=Severity.ERROR,
                message=f"{data_file.relative} carries no ses- entity",
                path=data_file.relative,
                hint=f"Expected ses-{expected_session}.",
            )
        elif actual_session != expected_session:
            yield Finding(
                rule_id="NM003",
                severity=Severity.ERROR,
                message=(
                    f"{data_file.relative} names ses-{actual_session} but sits under "
                    f"{data_file.session}"
                ),
                path=data_file.relative,
            )


@rule("NM004", "Filenames follow the BIDS entity grammar")
def filenames_follow_the_grammar(context: DatasetContext) -> Iterator[Finding]:
    """Report files inside datatype directories that are not BIDS-named."""
    for data_file in context.data_files:
        if data_file.name is None:
            yield Finding(
                rule_id="NM004",
                severity=Severity.ERROR,
                message=f"{data_file.relative} does not follow the BIDS filename grammar",
                path=data_file.relative,
                hint="Expected key-value entities joined by underscores, then a suffix: "
                "sub-<label>[_ses-<label>]_<suffix>.<ext>",
            )


@rule("NM005", "Datatype directories are not empty")
def datatype_dirs_are_not_empty(context: DatasetContext) -> Iterator[Finding]:
    """Report datatype directories containing no files.

    An empty directory usually means a conversion step failed quietly, and it
    reads to a human as though the data is there.
    """
    for datatype_dir in context.datatype_dirs:
        if not datatype_dir.files:
            yield Finding(
                rule_id="NM005",
                severity=Severity.WARNING,
                message=f"{datatype_dir.relative} contains no files",
                path=datatype_dir.relative,
                hint="An empty directory reads as though the data is present.",
            )


@rule("NM006", "Sessions are used consistently across subjects")
def session_layout_is_consistent(context: DatasetContext) -> Iterator[Finding]:
    """Report a dataset where some subjects use sessions and others do not.

    BIDS allows either layout, but not both in one dataset: a reader that
    assumes one has to special-case the other, and the usual special case is to
    skip the subject.
    """
    with_sessions = {d.subject for d in context.datatype_dirs if d.session is not None}
    without_sessions = {d.subject for d in context.datatype_dirs if d.session is None}
    overlap = with_sessions & without_sessions

    for subject in sorted(overlap):
        yield Finding(
            rule_id="NM006",
            severity=Severity.ERROR,
            message=f"{subject} has datatype directories both inside and outside a session",
            path=subject,
            hint="Put every datatype directory under a ses- directory, or none of them.",
        )

    if with_sessions and without_sessions and not overlap:
        yield Finding(
            rule_id="NM006",
            severity=Severity.ERROR,
            message=(
                f"{len(with_sessions)} subject(s) use session directories and "
                f"{len(without_sessions)} do not"
            ),
            hint="Choose one layout for the whole dataset.",
        )
