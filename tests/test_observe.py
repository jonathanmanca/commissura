"""The field ledger: what the input held, counted per file rather than claimed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from commissura.build.observe import (
    CARRIED_FIELDS,
    DICOM_KEYWORDS,
    imaging_fields,
    lab_fields,
    observe_corpus,
    observe_modality,
    report_fields,
)
from commissura.read.corpus import RAW_SOURCES

CR = "\r"


def write_exact(path: Path, text: str) -> None:
    """Write text with no newline translation, so HL7 keeps its bare returns."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")


def lab_message(*, observations: int = 1, with_pv1: bool = False) -> str:
    """Build a minimal ORU^R01 with a controllable number of OBX segments."""
    segments = [
        "MSH|^~\\&|LIS|SINTETIC LAB|EHR|SINTETIC HOSP|20240101120000||ORU^R01|1|P|2.5",
        "PID|1||0012345^^^SINTETIC||ROSSI^MARIO||19800101|M|||VIA FINTA 1^^ROMA"
        "||555^^^a.b@posta.invalid|||||||RSSMRA80A01X000A",
        "OBR|1|ACC9|ACC9|PANEL^Pannello|||20240101110000||||||||||DOC^BIANCHI^ANNA",
    ]
    if with_pv1:
        segments.append("PV1|1|O|AMB")
    for index in range(1, observations + 1):
        segments.append(f"OBX|{index}|NM|718-7^Emoglobina||1{index}.0|g/dL|12.0-16.0|N|||F")
    return CR.join(segments) + CR


def test_a_field_is_counted_once_per_file_not_once_per_occurrence(tmp_path: Path) -> None:
    """Twelve OBX segments in one message are one file carrying ``OBX-5``."""
    write_exact(tmp_path / "lab" / "a.hl7", lab_message(observations=12))

    ledger = observe_modality(tmp_path, "lab")

    assert ledger.files_read == 1
    counts = {item.key: item.files_present for item in ledger.fields}
    assert counts["OBX-5"] == 1


def test_a_field_only_some_files_carry_gets_a_partial_count(tmp_path: Path) -> None:
    """The count is the point: a static table could not have said "two of three"."""
    write_exact(tmp_path / "lab" / "a.hl7", lab_message(with_pv1=True))
    write_exact(tmp_path / "lab" / "b.hl7", lab_message(with_pv1=True))
    write_exact(tmp_path / "lab" / "c.hl7", lab_message(with_pv1=False))

    ledger = observe_modality(tmp_path, "lab")
    counts = {item.key: item.files_present for item in ledger.fields}

    assert ledger.files_read == 3
    assert counts["PID-5"] == 3
    assert counts["PV1-2"] == 2


def test_an_unobserved_field_is_reported_as_removed_without_being_listed(
    tmp_path: Path,
) -> None:
    """Nothing declares PID-5, and it is accounted for because it was there.

    This is the whole difference from the static table it replaced: that table
    could only report what somebody had remembered to write down.
    """
    write_exact(tmp_path / "lab" / "a.hl7", lab_message())

    ledger = observe_modality(tmp_path, "lab")
    outcome = next(item for item in ledger.fields if item.key == "PID-5")

    assert "PID-5" not in CARRIED_FIELDS["lab"]
    assert outcome.disposition == "removed"
    assert outcome.note == ""


def test_a_declared_field_the_corpus_never_carried_is_shown_as_absent(
    tmp_path: Path,
) -> None:
    """Reported at zero rather than dropped, which is how a wrong declaration shows.

    An ``Eta`` header carried in zero files is exactly how the header pattern's
    own blind spot was found: the declaration was right and the observer was
    looking only at line starts.
    """
    write_exact(tmp_path / "reports" / "a.txt", "Paziente: MARIO ROSSI\n")

    ledger = observe_modality(tmp_path, "reports")
    outcome = next(item for item in ledger.fields if item.key == "Eta")

    assert outcome.files_present == 0
    assert outcome.disposition == "kept"
    # It did not happen in this corpus, so it is not counted as having happened.
    assert ledger.count("kept") == 0


def test_an_unreadable_file_is_named_and_not_counted_as_read(tmp_path: Path) -> None:
    """A file whose fields were never seen is one this table cannot vouch for."""
    write_exact(tmp_path / "imaging" / "good.json", json.dumps([{"00080060": {"Value": ["CT"]}}]))
    write_exact(tmp_path / "imaging" / "bad.json", "{ not json")

    ledger = observe_modality(tmp_path, "imaging")

    assert ledger.files_read == 1
    assert len(ledger.unreadable) == 1
    assert ledger.unreadable[0].startswith("imaging/bad.json: ")


def test_a_tag_present_with_no_value_does_not_count_as_populated(tmp_path: Path) -> None:
    """DICOM sends an empty tag to say a value is absent, which is not a value."""
    write_exact(
        tmp_path / "imaging" / "a.json",
        json.dumps([{"00080060": {"Value": ["CT"]}, "00100010": {"vr": "PN"}}]),
    )

    assert imaging_fields(tmp_path / "imaging" / "a.json") == {"00080060"}


def test_two_labels_on_one_line_are_both_found(tmp_path: Path) -> None:
    """The generated reports write the birth date and the age side by side."""
    write_exact(
        tmp_path / "reports" / "a.txt",
        "Nato/a il: 01/01/2000   Eta: 25 anni\n",
    )

    assert report_fields(tmp_path / "reports" / "a.txt") == {"Nato/a il", "Eta"}


def test_a_prose_heading_is_not_mistaken_for_a_labelled_field(tmp_path: Path) -> None:
    """A section heading ends its line; a field is followed by its value."""
    write_exact(
        tmp_path / "reports" / "a.txt",
        "QUESITO CLINICO:\nEpisodio sincopale.\nPaziente: MARIO ROSSI\n",
    )

    assert report_fields(tmp_path / "reports" / "a.txt") == {"Paziente"}


def test_the_segment_name_is_not_reported_as_a_field(tmp_path: Path) -> None:
    """Index 0 holds the segment name, which is not data the dataset could carry."""
    write_exact(tmp_path / "lab" / "a.hl7", lab_message())

    keys = lab_fields(tmp_path / "lab" / "a.hl7")

    assert "PID-0" not in keys
    assert "PID-1" in keys


def test_every_modality_is_observed_laboratory_first(tmp_path: Path) -> None:
    """Order matters downstream: a subject exists only once a lab message made one."""
    ledgers = observe_corpus(tmp_path)

    assert [ledger.modality for ledger in ledgers] == list(RAW_SOURCES)
    assert ledgers[0].modality == "lab"


def test_a_missing_corpus_directory_is_an_empty_ledger_not_a_crash(tmp_path: Path) -> None:
    """``build`` already refuses a corpus it cannot read; this must not raise first."""
    ledger = observe_modality(tmp_path, "imaging")

    assert ledger.files_read == 0
    assert ledger.unreadable == ()


@pytest.mark.parametrize("modality", list(RAW_SOURCES))
def test_every_modality_has_a_carried_declaration(modality: str) -> None:
    """A modality with no declaration would report everything as removed."""
    assert CARRIED_FIELDS[modality], f"{modality} carries nothing into the dataset"


def test_the_linkage_identifiers_are_declared_removed_by_being_left_out() -> None:
    """PID-3 and PatientID are read to link records, then dropped.

    Pinned because the table this replaced described both as replaced by the
    subject label, which would tell an auditor that a medical record number is
    recoverable from the dataset with the key. It is not in the dataset at all.
    """
    assert "PID-3" not in CARRIED_FIELDS["lab"]
    assert "00100020" not in CARRIED_FIELDS["imaging"]


def test_a_known_dicom_tag_is_named_and_an_unknown_one_is_not(tmp_path: Path) -> None:
    """A tag number alone is unreadable; a dictionary of every tag is a fiction."""
    write_exact(
        tmp_path / "imaging" / "a.json",
        json.dumps([{"00100010": {"Value": ["ROSSI^MARIO"]}, "00291010": {"Value": ["x"]}}]),
    )

    named = {item.key: item.name for item in observe_modality(tmp_path, "imaging").fields}

    assert named["00100010"] == "PatientName"
    # Group 0029 is odd, so it is a private tag: its meaning belongs to the
    # vendor and is in no dictionary. Reported by number, and still reported.
    assert named["00291010"] == ""


def test_only_dicom_keys_are_named() -> None:
    """HL7 and report keys are already readable, so naming them would be noise."""
    assert all(name for name in DICOM_KEYWORDS.values())
    assert all(len(tag) == 8 and tag == tag.upper() for tag in DICOM_KEYWORDS)
    assert len(set(DICOM_KEYWORDS.values())) == len(DICOM_KEYWORDS)
