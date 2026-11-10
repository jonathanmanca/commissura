"""Where the codice fiscale lives in a PID segment, and how the reader finds it.

HL7 v2 table 0203 has no concrete code for Italy. It documents a pattern,
``NNxxx``, "National Person Identifier where the xxx is the ISO table 3166
3-character (alphabetic) country code", so ``NNITA`` is that pattern
instantiated rather than a listed concept, and ``NI`` is the listed generic the
same value sometimes carries. PID-19 was deprecated in v2.3.1 but is still sent.
So there are three shapes a real message can arrive in, and the reader has to
read all three without guessing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from commissura.read.corpus import (
    MEDICAL_RECORD_TYPE_CODE,
    NATIONAL_ID_TYPE_CODES,
    read_lab,
)
from commissura.read.hl7 import parse_message

CR = "\r"
CODICE_FISCALE = "RSSMRA80A01X000A"
RECORD_NUMBER = "0012345"


def message(pid: str) -> str:
    """Build a minimal ORU^R01 around one PID segment."""
    return (
        CR.join(
            [
                "MSH|^~\\&|LIS|SINTETIC LAB|EHR|SINTETIC HOSP|20240101120000||ORU^R01|1|P|2.5",
                pid,
                "OBR|1|ACC9|ACC9|PANEL^Pannello|||20240101110000",
                "OBX|1|NM|718-7^Emoglobina||13.0|g/dL|12.0-16.0|N|||F",
            ]
        )
        + CR
    )


def read(tmp_path: Path, pid: str) -> object:
    """Write one message and read it back."""
    path = tmp_path / "a.hl7"
    path.write_text(message(pid), encoding="utf-8", newline="")
    return read_lab(path, "lab/a.hl7")


@pytest.mark.parametrize("type_code", sorted(NATIONAL_ID_TYPE_CODES))
def test_the_codice_fiscale_is_read_from_the_pid_3_list(tmp_path: Path, type_code: str) -> None:
    """The modern form, and both spellings of the type code are accepted.

    A reader insisting on one of them would reject half the real messages over a
    difference that carries no information.
    """
    pid = (
        f"PID|1||{RECORD_NUMBER}^^^SINTETIC HOSP^MR"
        f"~{CODICE_FISCALE}^^^MINSAL^{type_code}"
        "||ROSSI^MARIO||19800101|M"
    )
    record = read(tmp_path, pid)

    assert record.identity.national_id == CODICE_FISCALE  # type: ignore[attr-defined]
    assert record.identity.mrn == RECORD_NUMBER  # type: ignore[attr-defined]


def test_pid_19_is_still_read_when_pid_3_carries_no_national_identifier(
    tmp_path: Path,
) -> None:
    """The legacy form. Deprecated in v2.3.1 is not the same as switched off."""
    pid = (
        f"PID|1||{RECORD_NUMBER}^^^SINTETIC HOSP^MR||ROSSI^MARIO||19800101|M"
        f"|||||||||||{CODICE_FISCALE}"
    )
    record = read(tmp_path, pid)

    assert record.identity.national_id == CODICE_FISCALE  # type: ignore[attr-defined]
    assert record.identity.mrn == RECORD_NUMBER  # type: ignore[attr-defined]


def test_pid_3_wins_when_both_positions_carry_a_value(tmp_path: Path) -> None:
    """An interface in transition sends both; the undeprecated field is authoritative."""
    pid = (
        f"PID|1||{RECORD_NUMBER}^^^SINTETIC HOSP^MR~{CODICE_FISCALE}^^^MINSAL^NNITA"
        "||ROSSI^MARIO||19800101|M|||||||||||VRDGPP85B02X000B"
    )
    record = read(tmp_path, pid)

    assert record.identity.national_id == CODICE_FISCALE  # type: ignore[attr-defined]


def test_a_message_with_no_national_identifier_anywhere_is_refused(tmp_path: Path) -> None:
    """A lab record creates a subject, so one without an identifier has nothing to be.

    The message names both positions, because "PID-19 is empty" sent somebody
    looking in the wrong field for as long as PID-3 went unread.
    """
    pid = f"PID|1||{RECORD_NUMBER}^^^SINTETIC HOSP^MR||ROSSI^MARIO||19800101|M"

    with pytest.raises(ValueError, match=r"PID-3.*PID-19"):
        read(tmp_path, pid)


def test_the_record_number_is_found_by_type_code_not_by_position(tmp_path: Path) -> None:
    """Nothing says the record number comes first in the list."""
    pid = (
        f"PID|1||{CODICE_FISCALE}^^^MINSAL^NNITA~{RECORD_NUMBER}^^^SINTETIC HOSP^MR"
        "||ROSSI^MARIO||19800101|M"
    )
    record = read(tmp_path, pid)

    assert record.identity.mrn == RECORD_NUMBER  # type: ignore[attr-defined]
    assert record.identity.national_id == CODICE_FISCALE  # type: ignore[attr-defined]


def test_a_bare_untyped_pid_3_is_taken_as_the_record_number(tmp_path: Path) -> None:
    """An interface that labels nothing can only mean the record number."""
    pid = f"PID|1||{RECORD_NUMBER}||ROSSI^MARIO||19800101|M|||||||||||{CODICE_FISCALE}"
    record = read(tmp_path, pid)

    assert record.identity.mrn == RECORD_NUMBER  # type: ignore[attr-defined]


def test_an_untyped_identifier_beside_typed_ones_is_not_guessed_at(tmp_path: Path) -> None:
    """The failure mode this rule exists to prevent.

    Once a sender labels any identifier, an unlabelled one is something it chose
    not to label. Treating it as the record number is how a codice fiscale gets
    filed as a hospital number, and the record number is what imaging links on.
    """
    pid = f"PID|1||{CODICE_FISCALE}^^^MINSAL^NNITA~999888777||ROSSI^MARIO||19800101|M"
    record = read(tmp_path, pid)

    assert record.identity.mrn == ""  # type: ignore[attr-defined]
    assert record.identity.national_id == CODICE_FISCALE  # type: ignore[attr-defined]


def test_the_two_separators_are_applied_in_the_right_order() -> None:
    """``component`` cannot read a repeating field, which is why the accessor exists.

    Splitting on ``^`` first attributes every later repetition to the first
    identifier, and reads component five as part of the second identifier's text.
    """
    pid = parse_message(
        message(f"PID|1||{RECORD_NUMBER}^^^HOSP^MR~{CODICE_FISCALE}^^^MINSAL^NNITA")
    ).require("PID")

    assert pid.repetition_components(3) == (
        (RECORD_NUMBER, "", "", "HOSP", "MR"),
        (CODICE_FISCALE, "", "", "MINSAL", "NNITA"),
    )
    # The old accessor still reads the first repetition's first component, which
    # is why the fallback built on it is safe, and reads component five wrongly.
    assert pid.component(3, 1) == RECORD_NUMBER
    assert pid.component(3, 5) != MEDICAL_RECORD_TYPE_CODE


def test_a_short_repetition_is_not_padded() -> None:
    """A caller reading component five has to check the length, and does."""
    pid = parse_message(message(f"PID|1||{RECORD_NUMBER}")).require("PID")

    assert pid.repetition_components(3) == ((RECORD_NUMBER,),)
