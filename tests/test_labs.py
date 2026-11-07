"""Laboratory results: value typing, precision, and sex-specific intervals."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from random import Random

import pytest

from commissura.generate import vocabulary as vocab
from commissura.generate.defects import DefectInjector
from commissura.generate.labs import (
    _format_reference_range,
    _format_value,
    _value_type,
    render_panel,
    sample_panel,
)
from commissura.models import AbnormalFlag, LabObservation, LabPanel, Person, Sex

_OBSERVED = datetime(2024, 3, 18, 8, 20)


def _observation(**overrides: object) -> LabObservation:
    defaults: dict[str, object] = {
        "loinc_code": "718-7",
        "display": "Hemoglobin",
        "value": 14.1,
        "unit": "g/dL",
        "reference_low": 12.0,
        "reference_high": 15.5,
        "observed_at": _OBSERVED,
        "decimals": 1,
    }
    return LabObservation(**{**defaults, **overrides})


def test_a_measurement_is_declared_numeric() -> None:
    assert _value_type(_observation(value=14.1)) == "NM"


def test_a_coded_result_is_declared_as_text() -> None:
    """A laboratory reports both: a haemoglobin is a number, a Coombs is NEGATIVO.

    Declaring ``NM`` for a coded value would tell the receiver to parse text as
    a number.
    """
    assert _value_type(_observation(value="NEGATIVO")) == "ST"


def test_coded_results_reach_obx_2_end_to_end(person: Person) -> None:
    panel = LabPanel(
        accession="LAB1",
        panel_code="COOMBS",
        panel_name="Test di Coombs diretto",
        ordered_at=_OBSERVED,
        collected_at=_OBSERVED,
        reported_at=_OBSERVED,
        ordering_provider="MORETTI GIULIA",
        performing_lab=vocab.LABORATORIES[0],
        observations=(
            _observation(value="NEGATIVO", reference_low=None, reference_high=None, unit=""),
        ),
    )
    content, _ = render_panel(
        panel,
        person=person,
        site=vocab.SITES[0],
        path="lab/x.hl7",
        control_id="MSG1",
        injector=DefectInjector(Random(0), 0.0),
    )
    obx = next(line for line in content.split("\r") if line.startswith("OBX"))
    fields = obx.split("|")
    assert fields[2] == "ST"
    assert fields[5] == "NEGATIVO"


@pytest.mark.parametrize(
    ("value", "decimals", "expected"),
    [
        (535.0, 0, "535"),
        (535.4, 0, "535"),
        (14.1, 1, "14.1"),
        (14.0, 1, "14.0"),
        (0.94, 2, "0.94"),
        (0.9, 2, "0.90"),
    ],
)
def test_values_are_printed_at_the_reported_precision(
    value: float, decimals: int, expected: str
) -> None:
    """A laboratory printing ``535.0`` would claim a precision it does not have."""
    assert _format_value(_observation(value=value, decimals=decimals)) == expected


def test_a_coded_value_is_printed_verbatim() -> None:
    assert _format_value(_observation(value="TRACCE")) == "TRACCE"


def test_reference_range_matches_the_value_precision() -> None:
    observation = _observation(reference_low=150.0, reference_high=400.0, decimals=0)
    assert _format_reference_range(observation) == "150-400"


def test_a_missing_reference_bound_yields_an_empty_range() -> None:
    """Some analytes genuinely have no two-sided interval."""
    assert _format_reference_range(_observation(reference_low=None)) == ""
    assert _format_reference_range(_observation(reference_high=None)) == ""
    assert _format_reference_range(_observation(reference_low=None, reference_high=None)) == ""


@pytest.mark.parametrize("sex", [Sex.MALE, Sex.FEMALE])
def test_sampling_uses_the_interval_for_the_patients_sex(
    sex: Sex, make_person: Callable[..., Person]
) -> None:
    panel = sample_panel(
        Random(5),
        person=make_person(sex=sex),
        panel=vocab.PANELS[0],
        collected_at=_OBSERVED,
        accession="LAB1",
        ordering_provider="MORETTI GIULIA",
        performing_lab=vocab.LABORATORIES[0],
    )
    haemoglobin = next(o for o in panel.observations if o.loinc_code == "718-7")
    expected = vocab.PANELS[0].analytes[0].reference_for(sex)
    assert (haemoglobin.reference_low, haemoglobin.reference_high) == expected


def test_abnormal_flags_agree_with_the_reference_interval(person: Person) -> None:
    """A flag that contradicts the value would make the corpus internally false."""
    for seed in range(40):
        panel = sample_panel(
            Random(seed),
            person=person,
            panel=vocab.PANELS[1],
            collected_at=_OBSERVED,
            accession="LAB1",
            ordering_provider="MORETTI GIULIA",
            performing_lab=vocab.LABORATORIES[0],
        )
        for observation in panel.observations:
            assert isinstance(observation.value, float)
            assert observation.reference_low is not None
            assert observation.reference_high is not None
            if observation.abnormal_flag is AbnormalFlag.NORMAL:
                assert observation.reference_low <= observation.value <= observation.reference_high
            elif observation.abnormal_flag is AbnormalFlag.LOW:
                assert observation.value < observation.reference_low
            else:
                assert observation.value > observation.reference_high


def test_order_collection_and_report_times_are_ordered(person: Person) -> None:
    for seed in range(30):
        panel = sample_panel(
            Random(seed),
            person=person,
            panel=vocab.PANELS[0],
            collected_at=_OBSERVED,
            accession="LAB1",
            ordering_provider="MORETTI GIULIA",
            performing_lab=vocab.LABORATORIES[0],
        )
        assert panel.ordered_at < panel.collected_at < panel.reported_at


def test_sampled_values_are_never_negative(person: Person) -> None:
    """Without the clamp, a wide interval could produce an impossible result.

    Impossible values are supposed to appear only when the matching defect is
    injected, never by accident.
    """
    for seed in range(60):
        for template in vocab.PANELS:
            panel = sample_panel(
                Random(seed),
                person=person,
                panel=template,
                collected_at=_OBSERVED,
                accession="LAB1",
                ordering_provider="MORETTI GIULIA",
                performing_lab=vocab.LABORATORIES[0],
            )
            for observation in panel.observations:
                assert isinstance(observation.value, float)
                assert observation.value >= 0.0, f"{template.code} {observation.loinc_code}"


def test_a_provider_with_no_given_name_omits_the_component(person: Person) -> None:
    """XCN permits a family name alone, and some interfaces send exactly that."""
    panel = LabPanel(
        accession="LAB1",
        panel_code="CBC",
        panel_name="Emocromo completo",
        ordered_at=_OBSERVED,
        collected_at=_OBSERVED,
        reported_at=_OBSERVED,
        ordering_provider="MORETTI",
        performing_lab=vocab.LABORATORIES[0],
        observations=(_observation(),),
    )
    content, _ = render_panel(
        panel,
        person=person,
        site=vocab.SITES[0],
        path="lab/x.hl7",
        control_id="MSG1",
        injector=DefectInjector(Random(0), 0.0),
    )
    obr = next(line for line in content.split("\r") if line.startswith("OBR"))
    assert obr.split("|")[16] == "^MORETTI"
