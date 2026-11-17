"""The CDA generator, and the cases a generated cohort cannot reach.

The round trip is covered in ``test_cda_corpus.py``, which generates documents
and reads them back. What is here is the handful of branches a cohort of
Italian residents with numeric laboratory results never exercises — a reserved
character, a coded result, a single-word clinician, an analyte with no reference
interval — each of which a real deployment would meet on its first day.
"""

from __future__ import annotations

from datetime import datetime
from random import Random

import pytest

from commissura.generate.cda import SPECIALTY_BY_PANEL, render_lab_cda
from commissura.generate.defects import DefectInjector
from commissura.generate.vocabulary import PANELS, SITES
from commissura.models import AbnormalFlag, LabObservation, LabPanel, Person
from commissura.read.cda import parse_clinical_document

COLLECTED = datetime(2024, 1, 15, 9, 0)


def panel(*observations: LabObservation, code: str = "CBC") -> LabPanel:
    """Return a panel holding exactly the observations a test needs."""
    return LabPanel(
        accession="LAB00001",
        panel_code=code,
        panel_name="Emocromo completo",
        ordered_at=COLLECTED,
        collected_at=COLLECTED,
        reported_at=COLLECTED,
        ordering_provider="ROSSI MARIO",
        performing_lab="LABORATORIO SINTETICO",
        observations=observations,
    )


def observation(**overrides: object) -> LabObservation:
    """Return one analyte result, overridable field by field."""
    defaults: dict[str, object] = {
        "loinc_code": "718-7",
        "display": "Emoglobina",
        "value": 13.2,
        "unit": "g/dL",
        "reference_low": 12.0,
        "reference_high": 15.5,
        "abnormal_flag": AbnormalFlag.NORMAL,
        "observed_at": COLLECTED,
        "decimals": 1,
    }
    return LabObservation(**{**defaults, **overrides})


def render(person: Person, lab: LabPanel, *, signed_by: str = "BIANCHI ANNA") -> str:
    """Render one document with defects switched off."""
    content, _ = render_lab_cda(
        lab,
        person=person,
        site=SITES[0],
        path="cda/x.xml",
        document_id="DOC1",
        signed_by=signed_by,
        injector=DefectInjector(Random(0), 0.0),
    )
    return content


def test_every_generated_panel_has_a_laboratory_specialty() -> None:
    """A specialty section's code is the one code the specification fixes to LOINC.

    So a panel with no entry here would emit a document that is well-formed,
    plausible and not conformant — which is why the lookup has no default and
    this test exists rather than a ``dict.get``.
    """
    assert {item.code for item in PANELS} == set(SPECIALTY_BY_PANEL)


@pytest.mark.parametrize("reserved", ["<", "&", '"'])
def test_a_reserved_character_is_refused_rather_than_escaped(person: Person, reserved: str) -> None:
    """The decision of 2026-11-06, applied to a third format.

    Escaping would rewrite characters after their PHI offsets had been recorded,
    which silently corrupts every measurement built on the corpus. A writer that
    controls what it emits can refuse; a reader for real documents unescapes
    before any offset is taken, which is where that belongs.
    """
    with pytest.raises(ValueError, match="reserved XML character"):
        render(person, panel(observation(display=f"Emo{reserved}globina")))


@pytest.mark.parametrize("safe", [">", "'"])
def test_characters_that_need_no_escaping_are_not_refused(person: Person, safe: str) -> None:
    """Refusing more than necessary would reject ordinary Italian street names.

    ``>`` and ``'`` are legal in element text and in a double-quoted attribute
    value alike, so there is nothing to protect against and a writer that
    refused them would be one somebody works around.
    """
    content = render(person, panel(observation(display=f"Emo{safe}globina")))

    assert f"Emo{safe}globina" in parse_clinical_document(content).narrative


def test_a_coded_result_is_written_as_text_and_read_back_as_text(person: Person) -> None:
    """A direct Coombs test reports NEGATIVO, which no generated cohort produces.

    The cohort generator draws numbers, so the ``xsi:type="ST"`` path is
    reachable from no corpus — recorded here rather than left as a branch that
    looks covered because the file around it is.
    """
    content = render(person, panel(observation(value="NEGATIVO", unit="", decimals=0)))
    parsed = parse_clinical_document(content)

    assert 'xsi:type="ST"' in content
    assert parsed.observations[0].value == "NEGATIVO"
    assert parsed.observations[0].unit == ""


def test_an_analyte_with_no_reference_interval_emits_no_reference_range(
    person: Person,
) -> None:
    """Endemic in real laboratories, and the generator models it as a defect.

    Here it is the writer's side of the same case: an absent interval must
    produce no ``referenceRange`` element at all rather than an empty one, so a
    reader cannot mistake "not reported" for "reported as nothing".
    """
    content = render(person, panel(observation(reference_low=None, reference_high=None)))
    parsed = parse_clinical_document(content)

    assert "<referenceRange>" not in content
    assert parsed.observations[0].reference_low == ""
    assert parsed.observations[0].reference_high == ""


def test_a_single_word_clinician_name_emits_only_a_family_element(person: Person) -> None:
    """``given`` is obligatory, and an export that omits it still has to render.

    This project's vocabulary writes clinicians as ``FAMILY GIVEN``, so a name
    with no space is a case only a real deployment supplies.
    """
    content = render(person, panel(observation()), signed_by="ESPOSITO")
    parsed = parse_clinical_document(content)

    assert parsed.signed_by == "ESPOSITO"
    assert "<given></given>" not in content


def test_the_signer_differs_from_the_author(person: Person) -> None:
    """Two elements, two names, because a corpus where they coincided measures less.

    The signer is the one name a plain-text report declares nowhere except its
    signature line, so a document in which it equalled the author could not show
    whether the reader found the second element at all.
    """
    parsed = parse_clinical_document(render(person, panel(observation())))

    assert parsed.author_name == "MARIO ROSSI"
    assert parsed.signed_by == "ANNA BIANCHI"
    assert parsed.author_name != parsed.signed_by


def test_the_rendered_document_round_trips_through_the_reader(person: Person) -> None:
    """The writer and the reader agree, which is the cheapest guard against drift."""
    parsed = parse_clinical_document(
        render(
            person,
            panel(
                observation(),
                observation(loinc_code="4544-3", display="Ematocrito", value=41.0, unit="%"),
            ),
        )
    )

    assert parsed.codice_fiscale == person.codice_fiscale
    assert parsed.family_name == person.family_name
    assert parsed.given_name == person.given_name
    assert parsed.record_number == person.mrn
    assert parsed.birth_date == person.birth_date
    assert parsed.sex == person.sex.value
    assert parsed.custodian_name == SITES[0].name
    assert len(parsed.observations) == 2
    assert parsed.specialty is not None
    assert parsed.specialty.code == SPECIALTY_BY_PANEL["CBC"][0]
