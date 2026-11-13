"""Every validation rule, exercised in both directions.

The table below pairs each rule with one deliberate way of breaking exactly the
invariant it checks. A single parametrised test then asserts both halves of what
a rule has to do:

- it stays silent on a conformant dataset, and
- it fires on a dataset where its invariant is broken.

Asserting only the second half would pass for a rule that fires on everything,
which is the more common bug in a validator and the harder one to notice: the
output still looks like diligence.

:data:`CASES` is also checked for completeness, so a rule added without a case
here fails the suite rather than shipping untested.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from commissura import layout
from commissura.validate import Finding, Severity, get_rule, registered_rules, validate_dataset

Mutation = Callable[[Path], Path]
"""Breaks one invariant and returns the root to validate."""

TAB = "\t"


# --------------------------------------------------------------------------
# Small file helpers, kept local so this module couples to nothing
# --------------------------------------------------------------------------


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="")


def _read(path: Path) -> str:
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


def _edit_json(path: Path, mutate: Callable[[dict[str, object]], object]) -> None:
    data = json.loads(_read(path))
    mutate(data)
    _write(path, json.dumps(data, indent=2) + "\n")


def _rows(path: Path) -> list[list[str]]:
    return [line.split(TAB) for line in _read(path).splitlines() if line]


def _write_rows(path: Path, rows: list[list[str]]) -> None:
    _write(path, "\n".join(TAB.join(row) for row in rows) + "\n")


def _first(root: Path, pattern: str) -> Path:
    found = sorted(root.rglob(pattern))
    assert found, f"fixture should contain a file matching {pattern!r}"
    return found[0]


def _in_reports(root: Path, pattern: str) -> Path:
    """Return the first match inside a ``reports`` datatype directory.

    Scoped deliberately: a bare ``*_report.json`` also matches
    ``.deident/risk_report.json``, which sorts first and is a different file
    entirely.
    """
    found = sorted(p for p in root.rglob(pattern) if p.parent.name == "reports")
    assert found, f"fixture should contain a reports/ file matching {pattern!r}"
    return found[0]


def _participants(root: Path) -> Path:
    return root / layout.PARTICIPANTS_TSV


def _manifest(root: Path) -> Path:
    return root / layout.DEIDENT_DIR / layout.MANIFEST_JSON


def _findings(root: Path, rule_id: str) -> tuple[Finding, ...]:
    return validate_dataset(root, rules=(get_rule(rule_id),)).findings


# --------------------------------------------------------------------------
# One deliberate break per rule
# --------------------------------------------------------------------------


def _missing_root(root: Path) -> Path:
    return root / "no-such-directory"


def _delete_participants(root: Path) -> Path:
    _participants(root).unlink()
    return root


def _corrupt_description(root: Path) -> Path:
    _write(root / layout.DATASET_DESCRIPTION, "{ this is not json")
    return root


def _drop_required_description_key(root: Path) -> Path:
    _edit_json(root / layout.DATASET_DESCRIPTION, lambda data: data.pop("Name"))
    return root


def _drop_recommended_description_key(root: Path) -> Path:
    _edit_json(root / layout.DATASET_DESCRIPTION, lambda data: data.pop("GeneratedBy"))
    return root


def _wrong_bids_version(root: Path) -> Path:
    _edit_json(root / layout.DATASET_DESCRIPTION, lambda d: d.__setitem__("BIDSVersion", "1.6.0"))
    return root


def _remove_all_subjects(root: Path) -> Path:
    for entry in root.iterdir():
        if entry.is_dir() and entry.name.startswith(layout.SUBJECT_PREFIX):
            for path in sorted(entry.rglob("*"), reverse=True):
                path.unlink() if path.is_file() else path.rmdir()
            entry.rmdir()
    return root


def _add_stray_top_level_file(root: Path) -> Path:
    _write(root / "participants.tsv.bak", "leftover")
    return root


def _delete_manifest(root: Path) -> Path:
    _manifest(root).unlink()
    return root


def _delete_risk_report(root: Path) -> Path:
    (root / layout.DEIDENT_DIR / layout.RISK_REPORT_JSON).unlink()
    return root


def _empty_participants(root: Path) -> Path:
    _write(_participants(root), "")
    return root


def _reorder_participant_columns(root: Path) -> Path:
    rows = _rows(_participants(root))
    reordered = [[row[1], row[0], *row[2:]] for row in rows]
    _write_rows(_participants(root), reordered)
    return root


def _malformed_participant_id(root: Path) -> Path:
    rows = _rows(_participants(root))
    rows[1][0] = "patient_0001"
    _write_rows(_participants(root), rows)
    return root


def _duplicate_participant(root: Path) -> Path:
    rows = _rows(_participants(root))
    rows.append(list(rows[1]))
    _write_rows(_participants(root), rows)
    return root


def _participant_without_directory(root: Path) -> Path:
    rows = _rows(_participants(root))
    rows.append([f"{layout.SUBJECT_PREFIX}ffffffffffff", "55", "M"])
    _write_rows(_participants(root), rows)
    return root


def _directory_without_participant(root: Path) -> Path:
    unlisted = root / f"{layout.SUBJECT_PREFIX}ffffffffffff" / "lab"
    unlisted.mkdir(parents=True)
    _write(unlisted / "placeholder", "")
    return root


def _ragged_row(root: Path) -> Path:
    rows = _rows(_participants(root))
    rows.append([f"{layout.SUBJECT_PREFIX}{'a3f9c21b4e07'}"])
    _write_rows(_participants(root), rows)
    return root


def _blank_cell(root: Path) -> Path:
    rows = _rows(_participants(root))
    rows[1][2] = ""
    _write_rows(_participants(root), rows)
    return root


def _drop_age_column(root: Path) -> Path:
    rows = _rows(_participants(root))
    _write_rows(_participants(root), [[row[0], row[2]] for row in rows])
    return root


def _underscore_in_subject_label(root: Path) -> Path:
    subject = next(d for d in sorted(root.iterdir()) if d.name.startswith(layout.SUBJECT_PREFIX))
    subject.rename(root / f"{layout.SUBJECT_PREFIX}bad_label")
    return root


def _unknown_datatype_directory(root: Path) -> Path:
    lab = _first(root, "*_lab.tsv").parent
    typo = lab.parent / "report"  # the real datatype is "reports"
    typo.mkdir()
    _write(typo / "placeholder", "")
    return root


def _entities_disagree_with_path(root: Path) -> Path:
    table = _first(root, "*_lab.tsv")
    table.rename(table.parent / f"{layout.SUBJECT_PREFIX}zzzzzzzzzzzz_ses-01_lab.tsv")
    return root


def _filename_without_entities(root: Path) -> Path:
    lab = _first(root, "*_lab.tsv").parent
    _write(lab / "notes.txt", "a file that follows no naming convention")
    return root


def _empty_datatype_directory(root: Path) -> Path:
    lab = _first(root, "*_lab.tsv").parent
    (lab.parent / "pet").mkdir()
    return root


def _mixed_session_layout(root: Path) -> Path:
    subject = _first(root, "*_lab.tsv").parent.parent.parent
    outside = subject / "lab"
    outside.mkdir()
    _write(outside / f"{subject.name}_lab.tsv", TAB.join(layout.LAB_REQUIRED_COLUMNS) + "\n")
    return root


def _drop_lab_required_column(root: Path) -> Path:
    table = _first(root, "*_lab.tsv")
    rows = _rows(table)
    _write_rows(table, [row[1:] for row in rows])  # drops day_offset
    return root


def _drop_lab_recommended_columns(root: Path) -> Path:
    table = _first(root, "*_lab.tsv")
    rows = _rows(table)
    keep = len(layout.LAB_REQUIRED_COLUMNS)
    _write_rows(table, [row[:keep] for row in rows])
    return root


def _wrong_suffix_in_lab_directory(root: Path) -> Path:
    lab = _first(root, "*_lab.tsv").parent
    stem = _first(root, "*_lab.tsv").name.removesuffix("_lab.tsv")
    _write(lab / f"{stem}_bloodwork.tsv", TAB.join(layout.LAB_REQUIRED_COLUMNS) + "\n")
    return root


def _delete_report_sidecar(root: Path) -> Path:
    _in_reports(root, "*_report.json").unlink()
    return root


def _drop_sidecar_required_key(root: Path) -> Path:
    _edit_json(_in_reports(root, "*_report.json"), lambda data: data.pop("kind"))
    return root


def _delete_report_text(root: Path) -> Path:
    _in_reports(root, "*_report.txt").unlink()
    return root


def _absolute_date_in_lab_table(root: Path) -> Path:
    table = _first(root, "*_lab.tsv")
    rows = _rows(table)
    rows[1][0] = "2024-03-18"
    _write_rows(table, rows)
    return root


def _absolute_date_in_sidecar(root: Path) -> Path:
    _edit_json(
        _in_reports(root, "*_report.json"), lambda d: d.__setitem__("AcquisitionDate", "2024-03-18")
    )
    return root


def _absolute_date_in_report_text(root: Path) -> Path:
    report = _in_reports(root, "*_report.txt")
    _write(report, _read(report) + "Si confronta con il precedente esame del 12/03/2023.\n")
    return root


def _untruncated_age(root: Path) -> Path:
    rows = _rows(_participants(root))
    rows[1][1] = "97"
    _write_rows(_participants(root), rows)
    return root


def _identifier_column(root: Path) -> Path:
    rows = _rows(_participants(root))
    rows[0].append("mrn")
    for row in rows[1:]:
        row.append("0048812")
    _write_rows(_participants(root), rows)
    return root


def _drop_manifest_required_key(root: Path) -> Path:
    _edit_json(_manifest(root), lambda data: data.pop("deidentification_rule_version"))
    return root


def _malformed_key_fingerprint(root: Path) -> Path:
    _edit_json(_manifest(root), lambda d: d.__setitem__("key_fingerprint", "not-a-digest-at-all!!"))
    return root


def _secret_in_manifest(root: Path) -> Path:
    _edit_json(_manifest(root), lambda d: d.__setitem__("secret_key", "hunter2-but-longer"))
    return root


def _burned_in_imaging(root: Path) -> Path:
    """Add imaging metadata whose pixels are said to carry text.

    Written rather than mutated: the conformant fixture has no
    ``derivatives/imaging-metadata/`` tree, and this rule is about what a real
    export can contain rather than about a field going missing.
    """
    directory = root / "derivatives" / "imaging-metadata"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "sub-a3f9c21b4e07_abcdef0123456789_imaging.json").write_text(
        json.dumps(
            {
                "study_uid": "2.25.1",
                "series_uids": ["2.25.2"],
                "accession": "abcdef0123456789",
                "day_offset": 0,
                "modality": "CT",
                "burned_in_annotation": True,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="",
    )
    return root


CASES: tuple[tuple[str, Mutation], ...] = (
    ("DS001", _missing_root),
    ("DS002", _delete_participants),
    ("DS003", _corrupt_description),
    ("DS004", _drop_required_description_key),
    ("DS005", _drop_recommended_description_key),
    ("DS006", _wrong_bids_version),
    ("DS007", _remove_all_subjects),
    ("DS008", _add_stray_top_level_file),
    ("DS009", _delete_manifest),
    ("DS010", _delete_risk_report),
    ("PT001", _empty_participants),
    ("PT002", _reorder_participant_columns),
    ("PT003", _malformed_participant_id),
    ("PT004", _duplicate_participant),
    ("PT005", _participant_without_directory),
    ("PT006", _directory_without_participant),
    ("PT007", _ragged_row),
    ("PT008", _blank_cell),
    ("PT009", _drop_age_column),
    ("NM001", _underscore_in_subject_label),
    ("NM002", _unknown_datatype_directory),
    ("NM003", _entities_disagree_with_path),
    ("NM004", _filename_without_entities),
    ("NM005", _empty_datatype_directory),
    ("NM006", _mixed_session_layout),
    ("LB001", _drop_lab_required_column),
    ("LB002", _drop_lab_recommended_columns),
    ("LB003", _wrong_suffix_in_lab_directory),
    ("RP001", _delete_report_sidecar),
    ("RP002", _drop_sidecar_required_key),
    ("RP003", _delete_report_text),
    ("DI001", _absolute_date_in_lab_table),
    ("DI002", _absolute_date_in_sidecar),
    ("DI003", _absolute_date_in_report_text),
    ("DI004", _untruncated_age),
    ("DI005", _identifier_column),
    ("DI006", _drop_manifest_required_key),
    ("DI007", _malformed_key_fingerprint),
    ("DI008", _secret_in_manifest),
    ("DI009", _burned_in_imaging),
)


# --------------------------------------------------------------------------
# The tests
# --------------------------------------------------------------------------


def test_every_registered_rule_has_a_case() -> None:
    """A rule added without a case here must fail the suite, not ship untested."""
    covered = {rule_id for rule_id, _ in CASES}
    registered = {entry.rule_id for entry in registered_rules()}
    assert covered == registered, (
        f"rules with no case: {sorted(registered - covered)}; "
        f"cases for unknown rules: {sorted(covered - registered)}"
    )


def test_case_table_has_no_duplicates() -> None:
    assert len({rule_id for rule_id, _ in CASES}) == len(CASES)


@pytest.mark.parametrize(("rule_id", "mutate"), CASES, ids=[case[0] for case in CASES])
def test_rule_fires_only_when_its_invariant_is_broken(
    rule_id: str, mutate: Mutation, make_dataset: Callable[..., Path]
) -> None:
    """Both halves of what a rule must do.

    Checking that a rule stays quiet on good data matters as much as checking it
    speaks up on bad: a rule that fires on everything still produces output that
    looks like diligence.
    """
    clean = make_dataset("clean")
    assert _findings(clean, rule_id) == (), f"{rule_id} fires on a conformant dataset"

    broken = mutate(make_dataset("broken"))
    found = _findings(broken, rule_id)
    assert found, f"{rule_id} did not fire on a dataset that breaks its invariant"
    assert all(f.rule_id == rule_id for f in found)
    assert all(f.message for f in found), "every finding must say what is wrong"


def test_a_conformant_dataset_produces_no_findings_at_all(dataset: Path) -> None:
    """The baseline the whole table rests on."""
    report = validate_dataset(dataset)
    assert report.findings == ()
    assert report.is_conformant
    assert report.rules_run == len(registered_rules())


@pytest.mark.parametrize("subjects", [1, 2, 4])
@pytest.mark.parametrize("sessions", [1, 2])
def test_conformance_holds_across_dataset_shapes(
    subjects: int, sessions: int, make_dataset: Callable[..., Path]
) -> None:
    root = make_dataset("dataset", subjects=subjects, sessions=sessions)
    report = validate_dataset(root)
    assert report.is_conformant, [f.format_line() for f in report.findings]


def test_a_session_free_layout_is_also_conformant(make_dataset: Callable[..., Path]) -> None:
    """BIDS allows omitting the session level; NM006 only forbids mixing the two."""
    root = make_dataset("dataset", with_sessions=False)
    report = validate_dataset(root)
    assert report.is_conformant, [f.format_line() for f in report.findings]


def test_notices_can_be_excluded(make_dataset: Callable[..., Path]) -> None:
    root = _wrong_bids_version(make_dataset("dataset"))
    assert any(f.severity is Severity.NOTICE for f in validate_dataset(root).findings)
    assert not [
        f
        for f in validate_dataset(root, include_notices=False).findings
        if f.severity is Severity.NOTICE
    ]


def test_warnings_do_not_make_a_dataset_non_conformant(
    make_dataset: Callable[..., Path],
) -> None:
    """A dataset can conform and still have things worth improving."""
    root = _add_stray_top_level_file(make_dataset("dataset"))
    report = validate_dataset(root)
    assert report.warnings
    assert report.is_conformant


def test_a_rule_that_raises_is_reported_without_ending_the_run(dataset: Path) -> None:
    """A validator that dies on one dataset tells the user nothing about the rest."""
    from commissura.validate.rules._registry import Rule

    def exploding(_: object) -> object:
        raise RuntimeError("deliberate failure")

    broken_rule = Rule(rule_id="XX999", summary="always raises", check=exploding)  # type: ignore[arg-type]
    report = validate_dataset(dataset, rules=(broken_rule, get_rule("DS001")))

    assert report.rules_run == 2
    failure = next(f for f in report.findings if f.rule_id == "XX999")
    assert failure.severity is Severity.ERROR
    assert "deliberate failure" in failure.message
    assert "bug in the validator" in (failure.hint or "")
