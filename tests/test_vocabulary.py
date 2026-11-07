"""The vocabulary tables, checked for the gaps that only show up in output."""

from __future__ import annotations

import pytest

from commissura.generate import vocabulary as vocab
from commissura.models import Sex


def test_every_imaging_protocol_has_phrasing_for_its_body_part() -> None:
    """A protocol with no matching phrase pool would produce a report that reads wrong.

    This is the check that catches the whole class of bug where someone adds a
    protocol and the reports silently fall back to the phrasing of another
    modality.
    """
    for protocol in vocab.PROTOCOLS:
        assert protocol.body_part in vocab.RADIOLOGY_INDICATIONS, protocol.body_part
        assert protocol.body_part in vocab.RADIOLOGY_FINDINGS, protocol.body_part


def test_finding_pools_are_large_enough_for_one_report() -> None:
    """A report draws up to four findings without replacement."""
    for body_part, findings in vocab.RADIOLOGY_FINDINGS.items():
        assert len(findings) >= 4, body_part


def test_phrase_pools_hold_no_duplicates() -> None:
    for body_part, findings in vocab.RADIOLOGY_FINDINGS.items():
        assert len(set(findings)) == len(findings), body_part
    for body_part, indications in vocab.RADIOLOGY_INDICATIONS.items():
        assert len(set(indications)) == len(indications), body_part


@pytest.mark.parametrize("panel", vocab.PANELS, ids=lambda p: p.code)
def test_panels_hold_analytes_with_ordered_reference_intervals(panel: vocab.Panel) -> None:
    assert panel.analytes
    for analyte in panel.analytes:
        for sex in (Sex.MALE, Sex.FEMALE):
            low, high = analyte.reference_for(sex)
            assert low < high, f"{analyte.loinc_code} {sex}"
        assert analyte.unit
        assert analyte.decimals >= 0


def test_loinc_codes_are_unique_across_panels() -> None:
    """A duplicated code would make two different analytes indistinguishable."""
    codes = [a.loinc_code for panel in vocab.PANELS for a in panel.analytes]
    assert len(set(codes)) == len(codes)


def test_panel_codes_are_unique() -> None:
    codes = [panel.code for panel in vocab.PANELS]
    assert len(set(codes)) == len(codes)


def test_every_institution_name_is_marked_as_synthetic() -> None:
    """No exceptions, so the rule is an invariant rather than a convention.

    An earlier version of this test allowed a second spelling as an escape
    hatch, and the hatch hid two site names that were real hospitals at their
    real street addresses. Fabricated clinical records must not be attributable
    to an existing organisation, and a marker appended to a real name does not
    achieve that.
    """
    unmarked = [site.name for site in vocab.SITES if "SINTETIC" not in site.name]
    assert not unmarked, f"institution names without a synthetic marker: {unmarked}"


def test_cities_carry_consistent_postal_and_area_codes() -> None:
    for city, province, postal_code, area_code in vocab.CITIES:
        assert city
        assert len(province) == 2 and province.isupper()
        assert len(postal_code) == 5 and postal_code.isdigit()
        assert area_code.isdigit() and not area_code.startswith("0")
