"""The paths a validator only takes when the input is already damaged.

The rule table in :mod:`tests.test_validate_rules` breaks one invariant per rule
and checks the rule notices. That exercises each rule's main path and almost
none of its guards — the branches that decide what to do about a file that will
not decode, a label that is malformed in a second way, a manifest that parsed to
a list instead of an object.

Those guards are where a validator fails worst. A crash while reporting on a
broken dataset is the one moment the tool had a job to do, so each one gets a
test here rather than a hope.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from commissura import layout
from commissura.validate import Finding, Severity, get_rule, validate_dataset
from commissura.validate.context import DatasetContext
from commissura.validate.rules._registry import rule

TAB = "\t"
INVALID_UTF8 = b"\xff\xfe\x00 not decodable as utf-8"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="")


def _findings(root: Path, rule_id: str) -> tuple[object, ...]:
    return validate_dataset(root, rules=(get_rule(rule_id),)).findings


def _ids(root: Path, rule_id: str) -> list[str]:
    return [f.message for f in validate_dataset(root, rules=(get_rule(rule_id),)).findings]


def _lab_table(root: Path) -> Path:
    return sorted(root.rglob("*_lab.tsv"))[0]


def _report_text(root: Path) -> Path:
    return sorted(p for p in root.rglob("*_report.txt") if p.parent.name == "reports")[0]


def _manifest(root: Path) -> Path:
    return root / layout.DEIDENT_DIR / layout.MANIFEST_JSON


# --------------------------------------------------------------------------
# The registry
# --------------------------------------------------------------------------


def test_registering_a_duplicate_rule_id_fails_at_import_time() -> None:
    """Two rules sharing an id would make a finding ambiguous and a test unreliable."""
    with pytest.raises(ValueError, match="duplicate rule id"):

        @rule("DS001", "a second rule claiming an existing identifier")
        def _colliding(context: DatasetContext) -> Iterator[Finding]:
            yield from ()


def test_looking_up_an_unknown_rule_fails_loudly() -> None:
    with pytest.raises(KeyError, match="unknown rule id"):
        get_rule("ZZ999")


# --------------------------------------------------------------------------
# The context
# --------------------------------------------------------------------------


def test_a_missing_root_yields_empty_collections_rather_than_raising(tmp_path: Path) -> None:
    context = DatasetContext(tmp_path / "nope")
    assert not context.root_exists
    assert context.top_level_entries == ()
    assert context.subject_dirs == ()
    assert context.datatype_dirs == ()
    assert context.data_files == ()


def test_json_that_is_not_an_object_is_reported_as_such(dataset: Path) -> None:
    """A list parses cleanly and is still not a dataset description."""
    _write(dataset / layout.DATASET_DESCRIPTION, '["not", "an", "object"]')
    context = DatasetContext(dataset)
    assert context.description.exists
    assert not context.description.is_object
    assert "expected a JSON object" in (context.description.error or "")
    assert "found list" in (context.description.error or "")


def test_a_tsv_that_cannot_be_decoded_is_reported_not_raised(dataset: Path) -> None:
    (dataset / layout.PARTICIPANTS_TSV).write_bytes(INVALID_UTF8)
    context = DatasetContext(dataset)
    assert context.participants.exists
    assert context.participants.error is not None
    assert context.participants.header == ()


def test_trailing_blank_lines_in_a_tsv_are_not_read_as_rows(dataset: Path) -> None:
    """An editor's trailing newline is an artefact, not a participant."""
    table = dataset / layout.PARTICIPANTS_TSV
    with table.open(encoding="utf-8", newline="") as handle:
        original = handle.read()
    _write(table, original + "\n\n\n")

    context = DatasetContext(dataset)
    assert context.participants.error is None
    assert len(context.participants.rows) == 2
    assert validate_dataset(dataset).is_conformant


def test_an_empty_tsv_is_reported_as_empty(dataset: Path) -> None:
    _write(dataset / layout.PARTICIPANTS_TSV, "")
    assert DatasetContext(dataset).participants.error == "file is empty"


def test_directories_inside_a_datatype_directory_are_not_treated_as_files(
    dataset: Path,
) -> None:
    (_lab_table(dataset).parent / "subdirectory").mkdir()
    context = DatasetContext(dataset)
    assert all(file.path.is_file() for file in context.data_files)


def test_a_column_lookup_for_an_absent_column_returns_nothing(dataset: Path) -> None:
    assert DatasetContext(dataset).participants.column("no_such_column") == ()


def test_a_column_lookup_skips_rows_too_short_to_have_it(dataset: Path) -> None:
    """A ragged row must not make an unrelated column lookup raise."""
    table = dataset / layout.PARTICIPANTS_TSV
    with table.open(encoding="utf-8", newline="") as handle:
        lines = handle.read().splitlines()
    lines.append("sub-a3f9c21b4e07")
    _write(table, "\n".join(lines) + "\n")

    assert len(DatasetContext(dataset).participants.column("sex")) == 2


def test_relative_paths_use_forward_slashes_on_every_platform(dataset: Path) -> None:
    """A report made on Windows has to be comparable with one made on Linux."""
    context = DatasetContext(dataset)
    assert context.data_files
    assert all("\\" not in file.relative for file in context.data_files)


# --------------------------------------------------------------------------
# Structure rules: unreadable metadata
# --------------------------------------------------------------------------


def test_an_unparseable_manifest_is_reported_as_an_error(dataset: Path) -> None:
    _write(_manifest(dataset), "{ truncated")
    messages = _ids(dataset, "DS009")
    assert any("could not be parsed" in message for message in messages)


def test_an_unparseable_risk_report_is_reported_as_an_error(dataset: Path) -> None:
    _write(dataset / layout.DEIDENT_DIR / layout.RISK_REPORT_JSON, "{ truncated")
    report = validate_dataset(dataset, rules=(get_rule("DS010"),))
    assert not report.is_conformant
    assert any("could not be parsed" in f.message for f in report.findings)


def test_rules_reading_the_description_stay_quiet_when_it_is_malformed(dataset: Path) -> None:
    """DS003 reports the parse failure; DS004 to DS006 must not pile on."""
    _write(dataset / layout.DATASET_DESCRIPTION, "{ truncated")
    assert _findings(dataset, "DS003")
    for rule_id in ("DS004", "DS005", "DS006"):
        assert _findings(dataset, rule_id) == (), rule_id


def test_a_non_string_bids_version_is_not_reported_as_a_mismatch(dataset: Path) -> None:
    path = dataset / layout.DATASET_DESCRIPTION
    data = json.loads(path.read_text(encoding="utf-8"))
    data["BIDSVersion"] = 1.9
    _write(path, json.dumps(data))
    assert _findings(dataset, "DS006") == ()


# --------------------------------------------------------------------------
# Participants: the second way a label can be wrong
# --------------------------------------------------------------------------


def test_a_prefixed_but_non_alphanumeric_participant_id_is_reported(dataset: Path) -> None:
    """``patient_1`` fails for lacking the prefix; ``sub-bad_label`` for its label."""
    table = dataset / layout.PARTICIPANTS_TSV
    with table.open(encoding="utf-8", newline="") as handle:
        lines = handle.read().splitlines()
    lines[1] = TAB.join([f"{layout.SUBJECT_PREFIX}bad_label", *lines[1].split(TAB)[1:]])
    _write(table, "\n".join(lines) + "\n")

    messages = _ids(dataset, "PT003")
    assert any("non-alphanumeric label" in message for message in messages)


def test_participant_rules_stay_quiet_when_the_table_is_unreadable(dataset: Path) -> None:
    """PT001 reports the read failure. The rest have nothing to say."""
    (dataset / layout.PARTICIPANTS_TSV).write_bytes(INVALID_UTF8)
    assert _findings(dataset, "PT001")
    for rule_id in ("PT002", "PT005", "PT006", "PT007", "PT008", "PT009"):
        assert _findings(dataset, rule_id) == (), rule_id


# --------------------------------------------------------------------------
# Naming: every branch of the path-versus-filename check
# --------------------------------------------------------------------------


def test_a_malformed_session_label_is_reported(dataset: Path) -> None:
    session = _lab_table(dataset).parent.parent
    session.rename(session.parent / f"{layout.SESSION_PREFIX}bad_label")
    messages = _ids(dataset, "NM001")
    assert any("session directory" in message for message in messages)


def test_a_file_with_no_subject_entity_is_reported(dataset: Path) -> None:
    table = _lab_table(dataset)
    table.rename(table.parent / "ses-01_lab.tsv")
    messages = _ids(dataset, "NM003")
    assert any("carries no sub- entity" in message for message in messages)


def test_a_file_with_no_session_entity_inside_a_session_is_reported(dataset: Path) -> None:
    table = _lab_table(dataset)
    subject = table.parent.parent.parent.name
    table.rename(table.parent / f"{subject}_lab.tsv")
    messages = _ids(dataset, "NM003")
    assert any("carries no ses- entity" in message for message in messages)


def test_a_session_entity_outside_a_session_directory_is_reported(
    make_dataset: Callable[..., Path],
) -> None:
    root = make_dataset("dataset", with_sessions=False)
    table = _lab_table(root)
    subject = table.parent.parent.name
    table.rename(table.parent / f"{subject}_ses-01_lab.tsv")
    messages = _ids(root, "NM003")
    assert any("is not inside a session directory" in message for message in messages)


def test_a_mismatched_session_entity_is_reported(dataset: Path) -> None:
    table = _lab_table(dataset)
    subject = table.parent.parent.parent.name
    table.rename(table.parent / f"{subject}_ses-99_lab.tsv")
    messages = _ids(dataset, "NM003")
    assert any("sits under" in message and "ses-99" in message for message in messages)


def test_a_dataset_split_between_both_layouts_is_reported(dataset: Path) -> None:
    """Some subjects using sessions and others not, with no subject doing both."""
    subjects = sorted(p for p in dataset.iterdir() if p.name.startswith(layout.SUBJECT_PREFIX))
    second = subjects[1]
    session = next(p for p in second.iterdir() if p.name.startswith(layout.SESSION_PREFIX))
    for datatype in sorted(session.iterdir()):
        datatype.rename(second / datatype.name)
    session.rmdir()

    messages = _ids(dataset, "NM006")
    assert any("use session directories and" in message for message in messages)


def test_grammar_failures_are_not_also_reported_as_entity_mismatches(dataset: Path) -> None:
    """NM004 owns malformed names; NM003 must not duplicate the complaint."""
    _write(_lab_table(dataset).parent / "notes.txt", "no entities here")
    assert _findings(dataset, "NM004")
    assert _findings(dataset, "NM003") == ()


# --------------------------------------------------------------------------
# De-identification: unreadable and unexpected values
# --------------------------------------------------------------------------


def test_an_unreadable_report_is_reported_rather_than_crashing_the_scan(dataset: Path) -> None:
    _report_text(dataset).write_bytes(INVALID_UTF8)
    messages = _ids(dataset, "DI003")
    assert any("could not be read" in message for message in messages)


def test_an_age_that_is_neither_a_number_nor_the_ceiling_is_a_warning(dataset: Path) -> None:
    table = dataset / layout.PARTICIPANTS_TSV
    with table.open(encoding="utf-8", newline="") as handle:
        lines = handle.read().splitlines()
    parts = lines[1].split(TAB)
    parts[1] = "sessantaquattro"
    lines[1] = TAB.join(parts)
    _write(table, "\n".join(lines) + "\n")

    report = validate_dataset(dataset, rules=(get_rule("DI004"),))
    assert report.findings
    assert all(f.severity is Severity.WARNING for f in report.findings)
    assert report.is_conformant, "an unparseable age is a warning, not a rejection"


def test_the_build_timestamp_in_the_manifest_is_not_reported_as_a_date(dataset: Path) -> None:
    """When the dataset was built says nothing about any patient."""
    path = _manifest(dataset)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["generated_at"] = "2024-03-18T09:20:00+00:00"
    _write(path, json.dumps(data))
    assert _findings(dataset, "DI002") == ()


def test_manifest_rules_stay_quiet_when_the_manifest_is_unreadable(dataset: Path) -> None:
    """DS009 reports the parse failure; the manifest content rules have no input."""
    _write(_manifest(dataset), "[]")
    for rule_id in ("DI002", "DI006", "DI007", "DI008"):
        assert _findings(dataset, rule_id) == (), rule_id


def test_a_manifest_without_a_fingerprint_is_reported_by_one_rule_only(dataset: Path) -> None:
    """DI006 reports the absence; DI007 only judges a fingerprint that is there."""
    path = _manifest(dataset)
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["key_fingerprint"]
    _write(path, json.dumps(data))

    assert _findings(dataset, "DI006")
    assert _findings(dataset, "DI007") == ()


# --------------------------------------------------------------------------
# The lab and reports extension
# --------------------------------------------------------------------------


def test_lab_sidecars_are_not_checked_for_table_columns(dataset: Path) -> None:
    """``*_lab.json`` is a sidecar, not a table, and has no required columns."""
    for rule_id in ("LB001", "LB002"):
        assert _findings(dataset, rule_id) == (), rule_id


def test_an_unreadable_lab_table_is_not_reported_as_missing_columns(dataset: Path) -> None:
    _lab_table(dataset).write_bytes(INVALID_UTF8)
    for rule_id in ("LB001", "LB002"):
        assert _findings(dataset, rule_id) == (), rule_id


def test_a_wrongly_named_file_in_lab_is_left_to_the_naming_rule(dataset: Path) -> None:
    """NM004 owns the grammar; the lab rules skip what they cannot address."""
    _write(_lab_table(dataset).parent / "stray.tsv", "no entities")
    for rule_id in ("LB001", "LB002", "LB003"):
        assert _findings(dataset, rule_id) == (), rule_id
    assert _findings(dataset, "NM004")


def test_a_stray_file_directly_inside_a_subject_is_not_a_datatype(dataset: Path) -> None:
    """Only directories are datatypes; a loose file beside them must be skipped."""
    subject = _lab_table(dataset).parent.parent.parent
    _write(subject / "scanner_notes.txt", "left behind by an export")
    context = DatasetContext(dataset)
    assert all(directory.datatype != "scanner_notes.txt" for directory in context.datatype_dirs)
    assert validate_dataset(dataset).is_conformant


def test_a_lab_file_with_an_unexpected_extension_is_reported(dataset: Path) -> None:
    table = _lab_table(dataset)
    stem = table.name.removesuffix(".tsv")
    _write(table.parent / f"{stem}.csv", "day_offset,loinc_code")
    messages = _ids(dataset, "LB003")
    assert any("expected .tsv or .json" in message for message in messages)


def test_an_unparseable_report_sidecar_is_not_reported_as_missing_keys(dataset: Path) -> None:
    """DS-level parsing is not RP002's job; it only judges sidecars it can read."""
    sidecar = sorted(p for p in dataset.rglob("*_report.json") if p.parent.name == "reports")[0]
    _write(sidecar, "[ ]")
    assert _findings(dataset, "RP002") == ()
