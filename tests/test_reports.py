"""Report rendering: the prose placements a field-based scrubber cannot see."""

from __future__ import annotations

from datetime import datetime
from random import Random

from commissura.generate import vocabulary as vocab
from commissura.generate.defects import DefectInjector
from commissura.generate.imaging import sample_study
from commissura.generate.reports import (
    render_report,
    sample_discharge_report,
    sample_radiology_report,
)
from commissura.models import Person, PhiCategory

_WHEN = datetime(2024, 5, 7, 9, 15)


def _report() -> object:
    study = sample_study(
        Random(3),
        protocol=vocab.PROTOCOLS[0],
        study_date=_WHEN,
        accession="RAD1",
        site=vocab.SITES[0],
        referring_physician="CONTI MARCO",
        performing_physician="SERRA LUCIA",
    )
    return sample_radiology_report(
        Random(3),
        study=study,
        author_name="MARTINI TERESA",
        author_role=vocab.RADIOLOGIST_ROLES[0],
        site=vocab.SITES[0],
    )


def test_a_comparison_without_a_named_institution_still_records_the_date(person: Person) -> None:
    """The library allows citing an earlier study without saying where it was done."""
    content, spans = render_report(
        _report(),  # type: ignore[arg-type]
        person=person,
        site=vocab.SITES[0],
        path="reports/x.txt",
        rng=Random(1),
        injector=DefectInjector(Random(1), 0.0),
        previous_study_date=datetime(2024, 4, 20, 8, 0),
        previous_site=None,
    )

    assert "Si confronta con il precedente esame del 20/04/2024." in content
    prose = [s for s in spans if s.note and "running prose" in s.note]
    assert [s.text for s in prose] == ["20/04/2024"]
    assert not [s for s in spans if s.category is PhiCategory.INSTITUTION and s.note == "x"]


def test_without_an_earlier_study_no_comparison_sentence_appears(person: Person) -> None:
    content, _ = render_report(
        _report(),  # type: ignore[arg-type]
        person=person,
        site=vocab.SITES[0],
        path="reports/x.txt",
        rng=Random(1),
        injector=DefectInjector(Random(1), 0.0),
    )
    assert "Si confronta" not in content


def test_the_header_and_the_signature_both_name_the_author(person: Person) -> None:
    """A scrubber that stops at the first match under-reports."""
    content, spans = render_report(
        _report(),  # type: ignore[arg-type]
        person=person,
        site=vocab.SITES[0],
        path="reports/x.txt",
        rng=Random(1),
        injector=DefectInjector(Random(1), 0.0),
    )
    institution_spans = [s for s in spans if s.category is PhiCategory.INSTITUTION]
    assert len(institution_spans) >= 2, "institution appears in the header and the signature"
    assert content.count(vocab.SITES[0].name) >= 2


def _discharge() -> object:
    return sample_discharge_report(
        Random(3),
        admitted_at=_WHEN,
        author_name="MARTINI TERESA",
        specialty=vocab.CLINICAL_SPECIALTIES[0],
        site=vocab.SITES[0],
    )


def test_a_discharge_letter_carries_the_patients_contact_in_prose(person: Person) -> None:
    """The one path through the scrubber that no generated corpus used to exercise.

    Written as a sentence and not as a "Recapiti:" header on purpose: a labelled
    field would be caught by the scrubber's exact-match pass, which already
    knows the email from HL7 PID-13. In prose only the patterns can find it.
    """
    content, spans = render_report(
        _discharge(),  # type: ignore[arg-type]
        person=person,
        site=vocab.SITES[0],
        path="reports/d.txt",
        rng=Random(3),
        injector=DefectInjector(Random(3), rate=0.0),
    )

    contacts = [span for span in spans if span.category is PhiCategory.CONTACT]
    assert len(contacts) == 2, "the email and the telephone"
    assert {person.email, person.phone} == {span.text for span in contacts}
    # The offsets have to address the text, not merely accompany it.
    for span in contacts:
        assert content[span.start : span.end] == span.text
    assert "Per comunicazioni contattare il paziente" in content


def test_the_contact_sentence_is_not_a_labelled_field(person: Person) -> None:
    """No "label: value" shape, so the field observer does not see a new header.

    If this became a labelled line, the manifest would grow a header row and the
    pattern path would stop being the only way the contact is found.
    """
    content, _ = render_report(
        _discharge(),  # type: ignore[arg-type]
        person=person,
        site=vocab.SITES[0],
        path="reports/d.txt",
        rng=Random(3),
        injector=DefectInjector(Random(3), rate=0.0),
    )

    sentence = next(line for line in content.splitlines() if "Per comunicazioni" in line)
    assert ": " not in sentence


def test_a_radiology_report_carries_no_contact(person: Person) -> None:
    """A radiology report has no reason to hold a follow-up contact.

    Which is the point: the category then covers some documents and not others,
    and the manifest's coverage count measures something.
    """
    _, spans = render_report(
        _report(),  # type: ignore[arg-type]
        person=person,
        site=vocab.SITES[0],
        path="reports/r.txt",
        rng=Random(3),
        injector=DefectInjector(Random(3), rate=0.0),
    )

    assert not [span for span in spans if span.category is PhiCategory.CONTACT]
