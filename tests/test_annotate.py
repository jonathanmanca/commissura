"""The PHI span invariant, and the cases a post-hoc text search would get wrong."""

from __future__ import annotations

import pytest

from commissura.annotate import AnnotatedText, Phi, check_spans
from commissura.models import PhiCategory, PhiSpan


def test_spans_quote_exactly_what_was_written() -> None:
    text = AnnotatedText("reports/x.txt")
    text.write("Paziente: ", Phi("MARIO ROSSI", PhiCategory.PERSON_NAME), " (", "65", " anni)")
    content, spans = text.finish()

    assert content == "Paziente: MARIO ROSSI (65 anni)"
    assert len(spans) == 1
    assert content[spans[0].start : spans[0].end] == "MARIO ROSSI"


def test_repeated_identifier_produces_one_span_per_occurrence() -> None:
    """A search would find the first occurrence only and under-report the rest."""
    text = AnnotatedText("reports/x.txt")
    text.line("Paziente: ", Phi("RUSSO MARIA", PhiCategory.PERSON_NAME))
    text.line("Firmato per ", Phi("RUSSO MARIA", PhiCategory.PERSON_NAME))
    content, spans = text.finish()

    assert len(spans) == 2
    assert spans[0].start != spans[1].start
    assert all(content[s.start : s.end] == "RUSSO MARIA" for s in spans)


def test_identifier_that_is_a_substring_of_prose_is_not_over_reported() -> None:
    """``RUSSO`` occurs inside ``RUSSOLO``; only the real identifier is recorded."""
    text = AnnotatedText("reports/x.txt")
    text.write(Phi("RUSSO", PhiCategory.PERSON_NAME), " refertato da Dott. RUSSOLO")
    content, spans = text.finish()

    assert content.count("RUSSO") == 2
    assert len(spans) == 1
    assert spans[0].end == 5


def test_clinical_word_identical_to_a_name_is_left_alone() -> None:
    """A patient named Rene must not make the Italian word for kidney an identifier."""
    text = AnnotatedText("reports/x.txt")
    text.write(Phi("RENE", PhiCategory.PERSON_NAME), ": non alterazioni del rene destro.")
    _, spans = text.finish()

    assert len(spans) == 1
    assert spans[0].category is PhiCategory.PERSON_NAME


def test_empty_identifier_is_rejected() -> None:
    """A zero-length span can never be found, so it would silently depress recall."""
    with pytest.raises(ValueError, match="must not be empty"):
        Phi("", PhiCategory.PERSON_NAME)


def test_write_joined_puts_separators_outside_identifiers() -> None:
    text = AnnotatedText("lab/x.hl7")
    text.write_joined(
        "^", Phi("ROSSI", PhiCategory.PERSON_NAME), Phi("MARIO", PhiCategory.PERSON_NAME), "L"
    )
    content, spans = text.finish()

    assert content == "ROSSI^MARIO^L"
    assert [s.text for s in spans] == ["ROSSI", "MARIO"]
    assert "^" not in "".join(s.text for s in spans)


def test_length_tracks_characters_written() -> None:
    text = AnnotatedText("x")
    assert len(text) == 0
    text.write("abc")
    assert len(text) == 3
    text.newline()
    assert len(text) == 4


def test_check_spans_detects_an_off_by_one() -> None:
    bad = (PhiSpan(path="x", start=0, end=4, text="MARI", category=PhiCategory.PERSON_NAME),)
    check_spans("MARI", bad)
    with pytest.raises(AssertionError, match="span mismatch"):
        check_spans("XMARI", bad)


def test_path_travels_with_the_builder() -> None:
    """Spans must stay meaningful after the content has left the builder."""
    text = AnnotatedText("reports/0012345_rad_1.txt")
    assert text.path == "reports/0012345_rad_1.txt"
    text.write(Phi("MARIO ROSSI", PhiCategory.PERSON_NAME))
    assert all(span.path == text.path for span in text.spans())
