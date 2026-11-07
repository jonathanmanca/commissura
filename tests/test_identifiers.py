"""Identifier generation: correctness of the formats, and non-existence by design."""

from __future__ import annotations

import re
from datetime import date
from random import Random

import pytest

from commissura import identifiers as ids
from commissura.models import Sex


@pytest.mark.parametrize(
    ("family_name", "expected"),
    [
        ("ROSSI", "RSS"),
        ("DE LUCA", "DLC"),
        ("EVA", "VEA"),  # fewer than three consonants: vowels follow
        ("BO", "BOX"),  # shorter than three characters: padded with X
    ],
)
def test_family_name_code(family_name: str, expected: str) -> None:
    assert ids.cf_family_name_code(family_name) == expected


@pytest.mark.parametrize(
    ("given_name", "expected"),
    [
        # Four or more consonants takes the first, third and fourth, skipping
        # the second. This is the rule that differs from the family name, and
        # the one reimplementations get wrong.
        ("FRANCESCO", "FNC"),
        ("GIOVANNI", "GNN"),
        # Fewer than four falls back to the family-name rule.
        ("MARIO", "MRA"),
        ("LUCA", "LCU"),
        ("EVA", "VEA"),
    ],
)
def test_given_name_code(given_name: str, expected: str) -> None:
    assert ids.cf_given_name_code(given_name) == expected


def test_complete_codice_fiscale_matches_published_example() -> None:
    assert (
        ids.codice_fiscale("ROSSI", "MARIO", date(1980, 1, 1), Sex.MALE, "H501")
        == "RSSMRA80A01H501U"
    )


def test_female_codes_add_forty_to_the_day() -> None:
    male = ids.codice_fiscale("ROSSI", "MARIO", date(1980, 1, 1), Sex.MALE, "H501")
    female = ids.codice_fiscale("ROSSI", "MARIO", date(1980, 1, 1), Sex.FEMALE, "H501")
    assert male[9:11] == "01"
    assert female[9:11] == "41"


def test_check_character_rejects_wrong_length() -> None:
    with pytest.raises(ValueError, match="15 characters"):
        ids.cf_check_character("TOOSHORT")


def test_synthetic_place_codes_are_outside_every_assigned_range() -> None:
    """Assigned codes are A-M for municipalities and Z for foreign states."""
    rng = Random(0)
    for _ in range(200):
        code = ids.synthetic_place_code(rng)
        assert re.fullmatch(r"X\d{3}", code), code


def test_generated_codes_are_checksum_valid_but_unassignable() -> None:
    rng = Random(1)
    for _ in range(50):
        code = ids.codice_fiscale(
            "BIANCHI", "ANNA", date(1965, 7, 23), Sex.FEMALE, ids.synthetic_place_code(rng)
        )
        assert len(code) == 16
        assert ids.cf_check_character(code[:15]) == code[15]
        assert code[11] == "X"


def test_telephone_numbers_cannot_be_dialled() -> None:
    """Italian subscriber numbers never start with zero after the area code."""
    rng = Random(2)
    for _ in range(50):
        number = ids.landline_number(rng, "11")
        subscriber = number.rsplit(" ", 1)[1]
        assert subscriber.startswith("0")


def test_email_domains_are_reserved_as_unresolvable() -> None:
    rng = Random(3)
    for _ in range(50):
        assert ids.email_address("Mario", "Rossi", rng).endswith(".invalid")


def test_dicom_uids_use_the_registration_free_arc_and_fit_the_length_limit() -> None:
    rng = Random(4)
    for _ in range(50):
        uid = ids.dicom_uid(rng)
        assert uid.startswith("2.25.")
        assert len(uid) <= 64
        assert re.fullmatch(r"2\.25\.\d+", uid)


def test_identifier_generation_is_reproducible_from_the_seed() -> None:
    def draw() -> list[str]:
        rng = Random(99)
        return [
            ids.medical_record_number(rng),
            ids.dicom_uid(rng),
            ids.accession_number(rng, "LAB"),
            ids.landline_number(rng, "2"),
            ids.device_serial_number(rng),
        ]

    assert draw() == draw()


def test_no_global_random_state_is_used() -> None:
    """Seeding the module-level generator must not change our output.

    A function that reached for ``random.random()`` would make its output depend
    on whatever else ran first in the process.
    """
    import random

    random.seed(1)
    first = ids.medical_record_number(Random(7))
    random.seed(2)
    second = ids.medical_record_number(Random(7))
    assert first == second
