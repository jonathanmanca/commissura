"""HL7 v2 serialisation: field numbering, the MSH quirk, terminators, delimiters."""

from __future__ import annotations

from datetime import datetime

import pytest

from commissura.annotate import AnnotatedText, Phi
from commissura.hl7 import (
    ENCODING_CHARACTERS,
    SEGMENT_TERMINATOR,
    Message,
    Raw,
    Repeated,
    Segment,
    format_date,
    format_timestamp,
    new_msh,
)
from commissura.models import PhiCategory


def _render(segment: Segment) -> str:
    text = AnnotatedText("x")
    segment.render(text)
    return text.render()


def test_field_numbers_place_the_right_number_of_separators() -> None:
    """PID-19 must sit after eighteen separators, not seventeen or nineteen."""
    pid = Segment("PID")
    pid.set(1, "1")
    pid.set(19, "RSSMRA80A01H501U")
    rendered = _render(pid).rstrip(SEGMENT_TERMINATOR)

    fields = rendered.split("|")
    assert fields[0] == "PID"
    assert fields[1] == "1"
    assert fields[19] == "RSSMRA80A01H501U"
    assert len(fields) == 20


def test_msh_is_numbered_differently_from_every_other_segment() -> None:
    """MSH-1 is the separator itself, so MSH-3 lands where field two would be."""
    msh = new_msh(
        sending_application="LIS",
        sending_facility="OSP",
        receiving_application="COMMISSURA",
        receiving_facility="RESEARCH",
        sent_at=datetime(2024, 3, 18, 17, 1),
        message_type=("ORU", "R01"),
        control_id="MSG1",
    )
    rendered = _render(msh).rstrip(SEGMENT_TERMINATOR)
    fields = rendered.split("|")

    assert fields[0] == "MSH"
    assert fields[1] == ENCODING_CHARACTERS  # MSH-2
    assert fields[2] == "LIS"  # MSH-3
    assert fields[8] == "ORU^R01"  # MSH-9
    assert fields[11] == "2.5.1"  # MSH-12


def test_segments_are_terminated_with_carriage_return_not_newline() -> None:
    """The classic HL7 mistake, and invisible in most editors."""
    message = Message()
    message.add("MSH").set(2, Raw(ENCODING_CHARACTERS))
    message.add("PID").set(1, "1")
    content, _ = message.render("lab/x.hl7")

    assert "\n" not in content
    assert content.count("\r") == 2
    assert content.endswith("\r")


def test_components_and_repetitions_use_their_own_separators() -> None:
    pid = Segment("PID")
    pid.set(5, ("ROSSI", "MARIO", "", "", "", "", "L"))
    pid.set(13, Repeated(("+39 011 0345678", ("", "NET", "Internet", "a@b.invalid"))))
    rendered = _render(pid).rstrip(SEGMENT_TERMINATOR)

    assert "ROSSI^MARIO^^^^^L" in rendered
    assert "+39 011 0345678~^NET^Internet^a@b.invalid" in rendered


def test_reserved_delimiters_in_data_are_refused_not_escaped() -> None:
    """Escaping would rewrite characters after their offsets were recorded."""
    pid = Segment("PID")
    pid.set(5, "ROSSI|MARIO")
    with pytest.raises(ValueError, match="reserved HL7 delimiter"):
        _render(pid)


def test_raw_exempts_only_the_field_that_declares_the_delimiters() -> None:
    segment = Segment("MSH")
    segment.set(2, Raw(ENCODING_CHARACTERS))
    assert ENCODING_CHARACTERS in _render(segment)


def test_empty_fields_still_emit_their_separators() -> None:
    segment = Segment("OBX")
    segment.set(1, "1")
    segment.set(5, "14.1")
    rendered = _render(segment).rstrip(SEGMENT_TERMINATOR)
    assert rendered == "OBX|1||||14.1"


def test_field_numbers_below_one_are_rejected() -> None:
    with pytest.raises(ValueError, match="start at 1"):
        Segment("PID").set(0, "x")


def test_identifier_offsets_survive_serialisation() -> None:
    pid = Segment("PID")
    pid.set(5, (Phi("ROSSI", PhiCategory.PERSON_NAME), Phi("MARIO", PhiCategory.PERSON_NAME)))
    message = Message()
    message.append(pid)
    content, spans = message.render("lab/x.hl7")

    assert len(spans) == 2
    assert all(content[s.start : s.end] == s.text for s in spans)


def test_timestamp_formats() -> None:
    assert format_timestamp(datetime(2024, 3, 18, 8, 20, 5)) == "20240318082005"
    assert format_date(datetime(2024, 3, 18).date()) == "20240318"


def test_a_segment_with_no_fields_renders_as_its_name_alone() -> None:
    """A header-only segment is legal, and must not emit a stray separator."""
    assert _render(Segment("NTE")) == "NTE" + SEGMENT_TERMINATOR
