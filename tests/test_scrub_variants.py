"""An identifier written another way is the same identifier.

Found on 2026-11-25 by an adversarial pass before the project was pointed at
from somewhere people read: a report was given the patient's own identifiers
in the spellings a human types, and three of seven survived. Two are fixed
here and one is recorded as a limit.

**The record number without its leading zeros is the sharp one, because the
tool was disagreeing with itself.** `read.identity.normalise_record_number`
strips them on purpose, so that `0012345` in one export and `12345` in another
resolve to one patient — the mechanism that recovers the
`imaging.mrn_format_drift` defect. The redactor matched only the padded form,
so a document writing the unpadded number kept it, in a dataset whose linkage
had already treated the two as equal.

**The telephone pattern accepted only spaces between digits.** It exists for
the number a document states that no structured field declared, and
`010-0310547` is how somebody writes one down. Widening it needed a digit
floor, because digits with separators also describe a date, and turning
`22/11/2023` into `[CONTACT]` would destroy the one value this pipeline
converts to an offset rather than removing.

**Still a limit, recorded rather than fixed**: a codice fiscale written with
spaces, `LMB DVD 63H13 X767I`, survives. Matching it needs a
separator-tolerant form of the declared value, which is a third mechanism and
a deliberate change rather than one made in passing.
"""

from __future__ import annotations

import pytest

from commissura.build.scrub import (
    _PHONE_PATTERN,
    PLACEHOLDER_CONTACT,
    PLACEHOLDER_PATIENT_ID,
    _identity_entries,
)
from commissura.read.corpus import Identity
from commissura.read.identity import normalise_record_number


def identity(mrn: str) -> Identity:
    return Identity(
        national_id="LMBDVD63H13X767I",
        mrn=mrn,
        family_name="LOMBARDI",
        given_name="DAVIDE",
        sex=None,
        birth_date=None,
    )


def test_a_padded_record_number_is_redacted_in_both_spellings() -> None:
    values = [value for _, value, _ in _identity_entries((identity("0584198"),))]
    assert "0584198" in values
    assert "584198" in values
    assert values.index("0584198") < values.index("584198"), (
        "the padded form has to go first, or the unpadded one leaves a fragment"
    )


def test_the_two_spellings_are_the_ones_the_reader_calls_equal() -> None:
    """The redactor's second spelling is the reader's normalised one.

    Asserted against `normalise_record_number` rather than against the string,
    because the point is not that `584198` is covered but that whatever the
    reader folds together, the redactor removes together.
    """
    padded = "0584198"
    unpadded = next(
        value
        for _, value, placeholder in _identity_entries((identity(padded),))
        if placeholder == PLACEHOLDER_PATIENT_ID and value != padded
    )
    assert normalise_record_number(unpadded) == normalise_record_number(padded)


def test_an_unpadded_number_adds_nothing_when_there_is_nothing_to_strip() -> None:
    values = [value for _, value, _ in _identity_entries((identity("584198"),))]
    assert values.count("584198") == 1


@pytest.mark.parametrize(
    "written",
    ["+39 010 0310547", "010-0310547", "010.031.0547", "010/0310547", "0100310547"],
)
def test_a_telephone_number_is_caught_however_it_is_punctuated(written: str) -> None:
    assert _PHONE_PATTERN.fullmatch(written), written


@pytest.mark.parametrize(
    "written",
    ["22/11/2023", "2023-11-22", "13.0-17.0", "40.0-52.0", "1963"],
)
def test_a_date_or_a_reference_range_is_not_a_telephone_number(written: str) -> None:
    """The digit floor, asserted on the values that would be destroyed without it.

    A date becomes `[day_offset:N]` and a reference range is clinical content;
    either one turning into `{placeholder}` would be a worse defect than the
    leak this pattern was widened to close.
    """
    assert not _PHONE_PATTERN.search(written), written


def test_a_date_range_is_not_spanned() -> None:
    """` - ` is three characters, and the pattern allows one between digits."""
    found = _PHONE_PATTERN.findall("ricovero dal 22/11/2023 - 24/11/2023 come da cartella")
    assert found == [], found


def test_the_placeholders_are_the_ones_the_scrubber_declares() -> None:
    """A guard on the guards above: they assert on names, not on spellings."""
    assert PLACEHOLDER_CONTACT and PLACEHOLDER_PATIENT_ID
    assert PLACEHOLDER_CONTACT != PLACEHOLDER_PATIENT_ID
