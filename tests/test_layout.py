"""The layout schema: filename grammar and the de-identification patterns."""

from __future__ import annotations

import pytest

from commissura import layout


@pytest.mark.parametrize(
    ("filename", "entities", "suffix", "extension"),
    [
        ("sub-a3f9c21b4e07_ses-01_lab.tsv", {"sub": "a3f9c21b4e07", "ses": "01"}, "lab", ".tsv"),
        (
            "sub-a3f9_ses-01_run-02_report.txt",
            {"sub": "a3f9", "ses": "01", "run": "02"},
            "report",
            ".txt",
        ),
        ("sub-a3f9_T1w.nii.gz", {"sub": "a3f9"}, "T1w", ".nii.gz"),
        ("sub-a3f9_lab.json", {"sub": "a3f9"}, "lab", ".json"),
    ],
)
def test_well_formed_names_parse(
    filename: str, entities: dict[str, str], suffix: str, extension: str
) -> None:
    parsed = layout.parse_bids_name(filename)
    assert parsed is not None
    assert dict(parsed.entities) == entities
    assert parsed.suffix == suffix
    assert parsed.extension == extension


def test_a_compound_extension_survives_intact() -> None:
    """``.nii.gz`` must not be split: the suffix ends at the first dot."""
    parsed = layout.parse_bids_name("sub-a3f9_T1w.nii.gz")
    assert parsed is not None
    assert parsed.extension == ".nii.gz"


@pytest.mark.parametrize(
    "filename",
    [
        "notes.txt",  # no entities and no suffix
        "sub-a3f9_ses-01.tsv",  # trailing token parses as an entity, so no suffix
        "sub-a3f9_bad name_lab.tsv",  # space in an entity
        "sub_a3f9_lab.tsv",  # underscore where a hyphen belongs
        "lab.tsv",  # nothing but a name
    ],
)
def test_malformed_names_are_rejected(filename: str) -> None:
    assert layout.parse_bids_name(filename) is None


def test_entity_lookup_returns_none_for_an_absent_key() -> None:
    parsed = layout.parse_bids_name("sub-a3f9_lab.tsv")
    assert parsed is not None
    assert parsed.get("sub") == "a3f9"
    assert parsed.get("ses") is None


@pytest.mark.parametrize(
    "text",
    [
        "2024-03-18",
        "18/03/2024",
        "18.03.2024",
        "20240318",
        "esame del 12/03/2023 presso",
        "AcquisitionDate: 1999-12-31",
    ],
)
def test_absolute_dates_are_detected(text: str) -> None:
    assert any(pattern.search(text) for pattern in layout.ABSOLUTE_DATE_PATTERNS), text


@pytest.mark.parametrize(
    "text",
    [
        "day_offset=-142",
        "LAB24031801",  # accession number
        "12345678",  # eight digits, not a plausible date
        "20249999",  # month 99, day 99
        "20241301",  # month 13
        "20240132",  # day 32
        "14.1",
        "2.25.3298007356985866292",  # a DICOM UID
        "150-400",  # a reference interval
    ],
)
def test_date_detection_does_not_fire_on_clinical_values(text: str) -> None:
    """A false positive costs a glance; a false negative ships a real date.

    The patterns are still anchored tightly enough that the values which
    genuinely appear in this schema do not trip them.
    """
    assert not any(pattern.search(text) for pattern in layout.ABSOLUTE_DATE_PATTERNS), text


@pytest.mark.parametrize("label", ["a3f9c21b4e07", "01", "ABC123"])
def test_valid_labels_are_accepted(label: str) -> None:
    assert layout.LABEL_PATTERN.match(label)


@pytest.mark.parametrize("label", ["bad_label", "bad-label", "bad.label", "", "with space"])
def test_invalid_labels_are_rejected(label: str) -> None:
    assert not layout.LABEL_PATTERN.match(label)


@pytest.mark.parametrize(
    "fingerprint", ["9f2c41ab77de0315", "a" * 64, "0123456789abcdef0123456789abcdef"]
)
def test_valid_key_fingerprints_are_accepted(fingerprint: str) -> None:
    assert layout.KEY_FINGERPRINT_PATTERN.match(fingerprint)


@pytest.mark.parametrize(
    "fingerprint",
    [
        "9F2C41AB77DE0315",  # uppercase
        "not-a-digest",
        "abc",  # too short to be a digest
        "a" * 65,  # too long
        "9f2c41ab77de031!",
    ],
)
def test_invalid_key_fingerprints_are_rejected(fingerprint: str) -> None:
    assert not layout.KEY_FINGERPRINT_PATTERN.match(fingerprint)


def test_the_two_extension_datatypes_are_not_bids_datatypes() -> None:
    """Lab and reports are this project's addition, and must not shadow BIDS names."""
    assert not (layout.COMMISSURA_DATATYPES & layout.BIDS_DATATYPES)
    assert layout.COMMISSURA_DATATYPES <= layout.KNOWN_DATATYPES


def test_required_top_level_files_are_also_known() -> None:
    """A required file reported as unexpected would contradict itself."""
    assert set(layout.REQUIRED_TOP_LEVEL) <= layout.KNOWN_TOP_LEVEL


def test_identifier_column_names_are_lowercase() -> None:
    """The rule lowercases before comparing, so an uppercase entry would never match."""
    assert all(name == name.lower() for name in layout.IDENTIFIER_COLUMN_NAMES)
    assert all(name == name.lower() for name in layout.FORBIDDEN_MANIFEST_KEYS)
