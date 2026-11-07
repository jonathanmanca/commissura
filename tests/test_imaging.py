"""DICOM JSON Model serialisation, and the encoding choices that carry meaning."""

from __future__ import annotations

import json
from datetime import datetime
from random import Random

import pytest

from commissura.annotate import AnnotatedText, Phi
from commissura.generate import vocabulary as vocab
from commissura.generate.defects import DefectInjector
from commissura.generate.imaging import (
    _check_json_safe,
    _person_name,
    _Tag,
    _write_object,
    render_study,
    sample_study,
)
from commissura.models import Person, PhiCategory


def _render(tags: list[_Tag]) -> str:
    text = AnnotatedText("imaging/x.json")
    _write_object(text, tags, "")
    return text.render()


def test_person_names_use_the_dicom_pn_object_form() -> None:
    """PN is the one value representation that always carries a name.

    Encoding it as a bare string rather than ``{"Alphabetic": ...}`` would
    mislead exactly the tools that care most about finding names.
    """
    rendered = _render([_Tag("00100010", "PN", "PIRAS^GIOVANNI")])
    payload = json.loads(rendered)
    assert payload["00100010"]["Value"][0] == {"Alphabetic": "PIRAS^GIOVANNI"}


def test_numeric_value_representations_are_not_quoted() -> None:
    payload = json.loads(_render([_Tag("00200011", "IS", "3")]))
    assert payload["00200011"]["Value"][0] == 3


def test_string_value_representations_are_quoted() -> None:
    payload = json.loads(_render([_Tag("00080060", "CS", "CT")]))
    assert payload["00080060"]["Value"][0] == "CT"


def test_an_empty_attribute_omits_the_value_member() -> None:
    """The standard represents a zero-length value by absence, not by ``[""]``."""
    payload = json.loads(_render([_Tag("00081030", "LO", "")]))
    assert payload["00081030"] == {"vr": "LO"}
    assert "Value" not in payload["00081030"]


def test_multiple_values_are_separated_correctly() -> None:
    payload = json.loads(_render([_Tag("00080008", "CS", "ORIGINAL", "PRIMARY", "AXIAL")]))
    assert payload["00080008"]["Value"] == ["ORIGINAL", "PRIMARY", "AXIAL"]


def test_attributes_are_written_in_tag_order() -> None:
    """DICOM orders attributes by tag, and a reader may rely on it."""
    rendered = _render(
        [_Tag("00100020", "LO", "X"), _Tag("00080060", "CS", "CT"), _Tag("00100010", "PN", "A^B")]
    )
    assert rendered.index("00080060") < rendered.index("00100010") < rendered.index("00100020")


@pytest.mark.parametrize("value", ['NAME"WITH QUOTE', "BACK\\SLASH", "CONTROL\x01CHAR"])
def test_values_needing_json_escaping_are_refused(value: str) -> None:
    """Escaping would rewrite characters after their offsets had been recorded."""
    with pytest.raises(ValueError, match="would require JSON escaping"):
        _check_json_safe(value)


def test_refusal_also_applies_to_recorded_identifiers() -> None:
    with pytest.raises(ValueError, match="would require JSON escaping"):
        _render([_Tag("00100010", "PN", Phi('A"B', PhiCategory.PERSON_NAME))])


@pytest.mark.parametrize(
    ("full_name", "expected"),
    [
        ("CONTI MARCO", "CONTI^MARCO"),
        ("DE LUCA FRANCESCA", "DE^LUCA FRANCESCA"),
        ("ROSSI", "ROSSI^"),
    ],
)
def test_person_name_formatting(full_name: str, expected: str) -> None:
    assert _person_name(full_name) == expected


def test_study_level_attributes_repeat_in_every_series(person: Person) -> None:
    """DICOM repeats them, so identifiers appear many times in one file.

    A scrubber that stops at the first occurrence under-reports, and this corpus
    has to be able to expose that.
    """
    rng = Random(21)
    study = sample_study(
        rng,
        protocol=vocab.PROTOCOLS[1],
        study_date=datetime(2024, 5, 7, 9, 15),
        accession="RAD24050701",
        site=vocab.SITES[3],
        referring_physician="CONTI MARCO",
        performing_physician="SERRA LUCIA",
    )
    content, spans = render_study(
        study,
        person=person,
        path="imaging/x.json",
        injector=DefectInjector(Random(1), 0.0),
    )
    payload = json.loads(content)

    assert len(payload) == len(study.series) >= 2
    patient_ids = {series["00100020"]["Value"][0] for series in payload}
    assert patient_ids == {person.mrn}, "every series object must agree on the patient"

    name_spans = [s for s in spans if s.category is PhiCategory.PERSON_NAME]
    assert len(name_spans) == len(study.series), "one PatientName span per series object"


def test_series_identifiers_are_unique_within_a_study() -> None:
    rng = Random(5)
    study = sample_study(
        rng,
        protocol=vocab.PROTOCOLS[1],
        study_date=datetime(2024, 5, 7, 9, 15),
        accession="RAD1",
        site=vocab.SITES[0],
        referring_physician="CONTI MARCO",
        performing_physician="SERRA LUCIA",
    )
    uids = [series.series_uid for series in study.series]
    assert len(set(uids)) == len(uids)
    assert study.study_uid not in uids


def test_a_clean_study_still_declares_no_burned_in_annotation(person: Person) -> None:
    rng = Random(3)
    study = sample_study(
        rng,
        protocol=vocab.PROTOCOLS[0],
        study_date=datetime(2024, 1, 2, 10, 0),
        accession="RAD2",
        site=vocab.SITES[0],
        referring_physician="CONTI MARCO",
        performing_physician="SERRA LUCIA",
    )
    content, _ = render_study(
        study,
        person=person,
        path="imaging/y.json",
        injector=DefectInjector(Random(1), 0.0),
    )
    for series in json.loads(content):
        assert series["00280301"]["Value"][0] == "NO"
        assert "00291010" not in series, "no private block without the defect"
