"""Render laboratory panels as HL7 v2 ORU^R01 messages.

Two responsibilities live here and are kept apart on purpose:

- :func:`sample_panel` invents the *clinical facts* — which analytes, measured
  when, with what values. It returns a :class:`~commissura.models.LabPanel` and
  knows nothing about HL7.
- :func:`render_panel` turns those facts into a message, and is the only place
  that knows about segments and field numbers.

The split means a value that looks wrong can be investigated without reading a
single pipe character, and the message layout can change without touching the
clinical sampling.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from random import Random

from commissura.annotate import Phi, Piece
from commissura.generate.defects import DefectInjector
from commissura.generate.vocabulary import Analyte, Panel, Site
from commissura.hl7 import (
    Message,
    Repeated,
    format_date,
    format_timestamp,
    new_msh,
)
from commissura.models import (
    AbnormalFlag,
    LabObservation,
    LabPanel,
    Person,
    PhiCategory,
    PhiSpan,
)

PLACEHOLDER_NATIONAL_ID = "UNKNOWN"
"""What a feed with no national-identifier field writes in its place.

Taken from :data:`commissura.read.identity.PLACEHOLDER_IDENTIFIERS`, which the
reader already recognises, and specifically the value the audit of 2026-11-13
used in its own reproduction -- "what a real interface writes when the field is
unavailable", in that document's words.

Named here rather than inlined because two sides have to agree on it: a value
the reader does not classify as a placeholder would be classified *malformed*
instead, which is a different diagnosis and a different `REASON_KEEPS_RECORD`
row. A test asserts the reader's own set contains it.
"""

_ABNORMAL_PROBABILITY = 0.18
"""Fraction of results that fall outside the reference interval.

Chosen so that most subjects have at least one abnormal value across a few
panels, which is what makes the corpus interesting to filter on, while leaving
the majority of individual results normal, which is what makes it plausible.
"""


def _sample_value(
    rng: Random, analyte: Analyte, low: float, high: float
) -> tuple[float, AbnormalFlag]:
    """Draw one result, occasionally outside the reference interval.

    In-range values are drawn from a normal distribution centred on the
    interval, with the interval spanning roughly four standard deviations, then
    clamped. That shape puts most results near the middle rather than spreading
    them evenly, which is how real populations behave and what makes a histogram
    of the output look credible.

    Args:
        rng: Seeded random source.
        analyte: The analyte, consulted for rounding.
        low: Lower reference bound.
        high: Upper reference bound.

    Returns:
        The rounded value and the HL7 interpretation flag that goes with it.
    """
    span = high - low
    if rng.random() < _ABNORMAL_PROBABILITY:
        if rng.random() < 0.5:
            value = low - span * rng.uniform(0.05, 0.4)
            flag = AbnormalFlag.LOW
        else:
            value = high + span * rng.uniform(0.05, 0.6)
            flag = AbnormalFlag.HIGH
        value = max(value, 0.0)
    else:
        value = min(max(rng.gauss((low + high) / 2, span / 4), low), high)
        flag = AbnormalFlag.NORMAL
    return round(value, analyte.decimals), flag


def sample_panel(
    rng: Random,
    *,
    person: Person,
    panel: Panel,
    collected_at: datetime,
    accession: str,
    ordering_provider: str,
    performing_lab: str,
) -> LabPanel:
    """Invent one complete panel of results for a person.

    Args:
        rng: Seeded random source.
        person: Whose sample this is; consulted for sex-specific intervals.
        panel: Which panel to report.
        collected_at: When the sample was taken. Order, collection and report
            times are derived from it so the intervals stay realistic.
        accession: Laboratory accession number.
        ordering_provider: Name of the clinician who ordered the panel.
        performing_lab: Name of the laboratory that ran it.

    Returns:
        The populated panel.
    """
    ordered_at = collected_at - timedelta(minutes=rng.randrange(20, 240))
    reported_at = collected_at + timedelta(minutes=rng.randrange(45, 600))

    observations: list[LabObservation] = []
    for analyte in panel.analytes:
        low, high = analyte.reference_for(person.sex)
        value, flag = _sample_value(rng, analyte, low, high)
        observations.append(
            LabObservation(
                loinc_code=analyte.loinc_code,
                display=analyte.display,
                value=value,
                unit=analyte.unit,
                reference_low=low,
                reference_high=high,
                abnormal_flag=flag,
                observed_at=collected_at,
                decimals=analyte.decimals,
            )
        )

    return LabPanel(
        accession=accession,
        panel_code=panel.code,
        panel_name=panel.name,
        ordered_at=ordered_at,
        collected_at=collected_at,
        reported_at=reported_at,
        ordering_provider=ordering_provider,
        performing_lab=performing_lab,
        observations=tuple(observations),
    )


def _format_number(value: float, decimals: int) -> str:
    """Return a measurement with the precision the analyte is reported to."""
    return f"{value:.{decimals}f}"


def _value_type(observation: LabObservation) -> str:
    """Return OBX-2, the HL7 value type that describes OBX-5.

    ``ST`` for a coded or textual result, ``NM`` for a measurement. Laboratories
    report both: a haemoglobin is a number, a direct Coombs test is ``NEGATIVO``.

    Args:
        observation: The result.

    Returns:
        An HL7 table 0125 value type code.
    """
    return "ST" if isinstance(observation.value, str) else "NM"


def _format_value(observation: LabObservation) -> str:
    """Return OBX-5, the observation value."""
    if isinstance(observation.value, str):
        return observation.value
    return _format_number(observation.value, observation.decimals)


def _format_reference_range(observation: LabObservation) -> str:
    """Return OBX-7 as a laboratory would print it, at matching precision."""
    if observation.reference_low is None or observation.reference_high is None:
        return ""
    low = _format_number(observation.reference_low, observation.decimals)
    high = _format_number(observation.reference_high, observation.decimals)
    return f"{low}-{high}"


def render_panel(
    panel: LabPanel,
    *,
    person: Person,
    site: Site,
    path: str,
    control_id: str,
    injector: DefectInjector,
) -> tuple[str, tuple[PhiSpan, ...]]:
    """Render a panel as an ORU^R01 message, injecting laboratory defects.

    Every identifier is written through :class:`~commissura.annotate.Phi`, so the
    returned spans are exact positions rather than search results.

    Args:
        panel: The facts to render.
        person: The patient.
        site: The institution sending the message.
        path: Corpus-relative path, recorded on every span.
        control_id: MSH-10.
        injector: Decides and records defects.

    Returns:
        The message text and its identifier spans.
    """
    message = Message()
    message.append(
        new_msh(
            sending_application="LIS",
            sending_facility=Phi(site.name, PhiCategory.INSTITUTION),
            receiving_application="COMMISSURA",
            receiving_facility="RESEARCH",
            sent_at=panel.reported_at,
            message_type=("ORU", "R01"),
            control_id=control_id,
        )
    )

    # --- PID: who the patient is. Nearly every field here is an identifier. ---
    pid = message.add("PID")
    pid.set(1, "1")
    # PID-3 is a *list* of identifiers, each with its own type code, and a
    # modern Italian interface puts the codice fiscale in it beside the record
    # number. HL7 v2 table 0203 has no concrete code for Italy; it documents the
    # pattern NNxxx, "National Person Identifier where the xxx is the ISO table
    # 3166 3-character (alphabetic) country code", so NNITA is that pattern
    # instantiated rather than a listed concept.
    record_number = (Phi(person.mrn, PhiCategory.PATIENT_ID), "", "", site.name, "MR")
    if site.national_id_in_pid_19:
        pid.set(3, record_number)
    else:
        # A site whose source system has no national-identifier field sends a
        # placeholder where the codice fiscale belongs. Written as a plain
        # string and **not** as a `Phi` span, deliberately: `UNKNOWN` is not an
        # identifier, so recording it as ground truth would put a value in the
        # annotations that nothing could ever leak and that would count as
        # removed for free -- the same reasoning as the unfilled date
        # placeholder in a report. The reader classifies it as a placeholder
        # and falls back to the record number, which is the whole point.
        national = (
            PLACEHOLDER_NATIONAL_ID
            if site.national_id_is_placeholder
            else Phi(person.codice_fiscale, PhiCategory.NATIONAL_ID)
        )
        pid.set(
            3,
            Repeated(
                (
                    record_number,
                    (national, "", "", "MINSAL", "NNITA"),
                )
            ),
        )
    pid.set(
        5,
        (
            Phi(person.family_name, PhiCategory.PERSON_NAME),
            Phi(person.given_name, PhiCategory.PERSON_NAME),
            "",
            "",
            "",
            "",
            "L",
        ),
    )
    pid.set(7, Phi(format_date(person.birth_date), PhiCategory.DATE, "date of birth"))
    pid.set(8, person.sex.value)
    pid.set(
        11,
        (
            Phi(person.street, PhiCategory.ADDRESS),
            "",
            Phi(person.city, PhiCategory.ADDRESS),
            person.province,
            Phi(person.postal_code, PhiCategory.ADDRESS),
            "IT",
        ),
    )
    pid.set(
        13,
        Repeated(
            (
                Phi(person.phone, PhiCategory.CONTACT),
                ("", "NET", "Internet", Phi(person.email, PhiCategory.CONTACT)),
            )
        ),
    )
    # PID-19 only for the legacy interface, and only there. HL7 deprecated the
    # field in v2.3.1, so a corpus that put the codice fiscale here in every
    # message would be modelling an interface nobody deploys new today — while
    # dropping it entirely would model a world where the old ones were all
    # switched off. One site sends it, the rest do not.
    if site.national_id_in_pid_19:
        pid.set(19, Phi(person.codice_fiscale, PhiCategory.NATIONAL_ID))

    # --- PV1: the encounter. A defect can remove it entirely. ---
    if not injector.apply(
        "lab.missing_segment", path, "PV1 omitted: result has no encounter context"
    ):
        pv1 = message.add("PV1")
        pv1.set(1, "1")
        pv1.set(2, "O")
        pv1.set(3, ("LAB", "", "", site.name))

    # --- OBR: the order. ---
    obr = message.add("OBR")
    obr.set(1, "1")
    obr.set(2, (Phi(panel.accession, PhiCategory.ACCESSION), "LIS"))
    obr.set(3, (Phi(panel.accession, PhiCategory.ACCESSION), "LAB"))
    obr.set(4, (panel.panel_code, panel.panel_name, "L"))

    if injector.apply(
        "lab.nonstandard_date_format",
        path,
        "OBR-7 written as DD/MM/YYYY instead of YYYYMMDDHHMMSS",
    ):
        collected = panel.collected_at.strftime("%d/%m/%Y")
    else:
        collected = format_timestamp(panel.collected_at)

    obr.set(6, format_timestamp(panel.ordered_at))
    obr.set(7, Phi(collected, PhiCategory.DATE, "specimen collection time"))
    obr.set(16, _provider_components(panel.ordering_provider))
    obr.set(22, format_timestamp(panel.reported_at))
    obr.set(25, "F")

    # --- OBX: one per analyte. ---
    for position, observation in enumerate(panel.observations, start=1):
        obx = message.add("OBX")
        obx.set(1, str(position))
        # OBX-2 must describe what OBX-5 actually holds. Hard-coding "NM" would
        # declare a numeric result for a coded one such as NEGATIVO, and a
        # receiver that trusts the declared type would fail to parse the value
        # or, worse, coerce it.
        obx.set(2, _value_type(observation))

        if injector.apply(
            "lab.unknown_code",
            path,
            f"OBX-3 for {observation.display} uses local code instead of LOINC",
        ):
            identifier = (f"L{observation.loinc_code.replace('-', '')}", observation.display, "L")
        else:
            identifier = (observation.loinc_code, observation.display, "LN")
        obx.set(3, identifier)

        if injector.apply(
            "lab.impossible_value",
            path,
            f"OBX-5 for {observation.display} set to the sentinel -999",
        ):
            obx.set(5, "-999")
        else:
            obx.set(5, _format_value(observation))

        if injector.apply("lab.missing_unit", path, f"OBX-6 cleared for {observation.display}"):
            obx.set(6, "")
        else:
            obx.set(6, (observation.unit, "", "UCUM"))

        if injector.apply(
            "lab.missing_reference_range", path, f"OBX-7 cleared for {observation.display}"
        ):
            obx.set(7, "")
        else:
            obx.set(7, _format_reference_range(observation))

        obx.set(8, observation.abnormal_flag.value)
        obx.set(11, "F")
        obx.set(14, format_timestamp(observation.observed_at))

    return message.render(path)


def _provider_components(provider: str) -> tuple[Piece, ...]:
    """Split a provider name into HL7 XCN components, recorded as identifiers.

    XCN.1 carries an internal person identifier, which we leave empty, so the
    name starts at XCN.2. The ordering clinician is an identifier in their own
    right: a named consultant plus a date narrows a cohort sharply, which is why
    these components are wrapped rather than written as plain text.

    Args:
        provider: A name written as ``FAMILY GIVEN``.

    Returns:
        An empty XCN.1 followed by the family and given name components.
    """
    family, _, given = provider.partition(" ")
    components: list[Piece] = ["", Phi(family, PhiCategory.PROVIDER_NAME)]
    if given:
        components.append(Phi(given, PhiCategory.PROVIDER_NAME))
    return tuple(components)
