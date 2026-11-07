"""Render imaging studies as DICOM JSON Model metadata.

This module emits metadata, not pixel data, which is a deliberate scope
decision: the project orchestrates ``dcm2bids`` and ``HeuDiConv`` rather than
reimplementing a DICOM converter, and every identifier problem worth testing
lives in the header anyway.

The format is the DICOM JSON Model from PS3.18 — tags as eight-character hex
keys, each carrying a value representation and a ``Value`` array — and the file
is an array of series-level objects, which is the shape a DICOMweb metadata
request returns. Using the real encoding rather than an invented one means the
output can be fed to tools that already exist.

Two details are faithful because they matter:

- Study-level tags are repeated in every series object, exactly as DICOM does.
  Identifiers therefore appear many times per file, and a scrubber that stops at
  the first occurrence under-reports in a way this corpus will expose.
- ``PersonName`` is encoded as ``{"Alphabetic": "FAMILY^GIVEN"}`` rather than a
  bare string. It is the one value representation that always carries a name, so
  getting its encoding wrong would mislead exactly the tools that care most.

The identifiers planted here are the ones that are genuinely missed in practice:
a name typed into ``SeriesDescription`` at the console, an accession number left
in a vendor private block, and ``BurnedInAnnotation`` marking pixels that no
header-level scrubber can reach.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from random import Random

from commissura.annotate import AnnotatedText, Phi, Piece
from commissura.generate.defects import DefectInjector
from commissura.generate.vocabulary import ImagingProtocol, Site
from commissura.identifiers import device_serial_number, dicom_uid
from commissura.models import (
    ImagingSeries,
    ImagingStudy,
    Person,
    PhiCategory,
    PhiSpan,
)

_SCANNERS: tuple[tuple[str, str], ...] = (
    ("SIEMENS", "SOMATOM Definition AS"),
    ("SIEMENS", "Biograph mCT"),
    ("GE MEDICAL SYSTEMS", "Discovery MI"),
    ("GE MEDICAL SYSTEMS", "Revolution CT"),
    ("Philips", "Ingenuity Core"),
    ("Philips", "Achieva dStream"),
)

_STATIONS: tuple[str, ...] = ("CT01-RAD", "MR02-NEURO", "PETCT01-NM", "CT03-URG")

_JSON_UNSAFE = frozenset('"\\')


def _check_json_safe(value: str) -> None:
    """Reject a value that would need JSON escaping.

    Same reasoning as the HL7 writer: escaping would change the characters of a
    value after its position had been recorded, so a span would end up quoting
    text that is not what is on disk. Generated vocabulary never contains these
    characters, so refusing is free; silently escaping would not be.

    Args:
        value: The candidate text.

    Raises:
        ValueError: If the value contains a quote, a backslash or a control
            character.
    """
    if _JSON_UNSAFE.intersection(value) or any(ord(c) < 0x20 for c in value):
        raise ValueError(
            f"value {value!r} would require JSON escaping. This writer refuses rather "
            "than escapes, so that recorded PHI offsets always match the file on disk."
        )


class _Tag:
    """One DICOM attribute: its tag, value representation and values."""

    __slots__ = ("tag", "values", "vr")

    def __init__(self, tag: str, vr: str, *values: Piece) -> None:
        """Create an attribute.

        Args:
            tag: Eight hex characters, for example ``00100010``.
            vr: Two-character value representation, for example ``PN``.
            *values: The values, plain or recorded as identifiers.
        """
        self.tag = tag
        self.vr = vr
        self.values = values


_NUMERIC_VRS = frozenset({"IS", "US", "UL", "SS", "SL", "FL", "FD", "DS"})


def _write_tag(text: AnnotatedText, tag: _Tag, indent: str) -> None:
    """Append one attribute as a DICOM JSON Model member.

    An attribute present but empty is written without a ``Value`` member, which
    is how the standard represents a zero-length value. Writing ``[""]`` instead
    would claim the attribute holds an empty string, which is a different
    statement and one that some readers reject.
    """
    if not tag.values or all(value == "" for value in tag.values):
        text.write(f'{indent}"{tag.tag}": {{"vr": "{tag.vr}"}}')
        return
    text.write(f'{indent}"{tag.tag}": {{"vr": "{tag.vr}", "Value": [')
    for position, value in enumerate(tag.values):
        if position:
            text.write(", ")
        _check_json_safe(value.text if isinstance(value, Phi) else value)
        if tag.vr == "PN":
            text.write('{"Alphabetic": "', value, '"}')
        elif tag.vr in _NUMERIC_VRS:
            text.write(value)
        else:
            text.write('"', value, '"')
    text.write("]}")


def _write_object(text: AnnotatedText, tags: Sequence[_Tag], indent: str) -> None:
    """Append one JSON object holding the given attributes, tags sorted."""
    text.write(indent, "{\n")
    ordered = sorted(tags, key=lambda t: t.tag)
    for position, tag in enumerate(ordered):
        _write_tag(text, tag, indent + "  ")
        text.write(",\n" if position < len(ordered) - 1 else "\n")
    text.write(indent, "}")


def sample_study(
    rng: Random,
    *,
    protocol: ImagingProtocol,
    study_date: datetime,
    accession: str,
    site: Site,
    referring_physician: str,
    performing_physician: str,
) -> ImagingStudy:
    """Invent one imaging study and its series.

    Args:
        rng: Seeded random source.
        protocol: What was scanned and with which series.
        study_date: When.
        accession: Radiology accession number.
        site: The institution.
        referring_physician: Who requested the study.
        performing_physician: Who performed or supervised it.

    Returns:
        The populated study.
    """
    manufacturer, model = rng.choice(_SCANNERS)
    series = tuple(
        ImagingSeries(
            series_uid=dicom_uid(rng),
            series_number=number,
            modality=template.modality,
            series_description=template.description,
            protocol_name=template.protocol_name,
            instance_count=rng.randrange(*template.instance_range)
            if template.instance_range[0] < template.instance_range[1]
            else template.instance_range[0],
        )
        for number, template in enumerate(protocol.series, start=1)
    )
    return ImagingStudy(
        study_uid=dicom_uid(rng),
        study_date=study_date,
        accession=accession,
        modality=protocol.modality,
        body_part=protocol.body_part,
        study_description=protocol.study_description,
        institution=site.name,
        institution_address=f"{site.address}, {site.city}",
        referring_physician=referring_physician,
        performing_physician=performing_physician,
        station_name=rng.choice(_STATIONS),
        manufacturer=manufacturer,
        manufacturer_model=model,
        device_serial_number=device_serial_number(rng),
        series=series,
    )


def _person_name(full_name: str) -> str:
    """Return a name in DICOM PN form, family and given separated by a caret.

    Args:
        full_name: A name written as ``FAMILY GIVEN``. A name with no space is
            treated as a family name alone, which PN permits.

    Returns:
        The caret-delimited PN value.
    """
    family, _, given = full_name.partition(" ")
    return f"{family}^{given}"


def render_study(
    study: ImagingStudy,
    *,
    person: Person,
    path: str,
    injector: DefectInjector,
) -> tuple[str, tuple[PhiSpan, ...]]:
    """Render a study as DICOM JSON Model metadata, injecting imaging defects.

    Args:
        study: The facts to render.
        person: The patient.
        path: Corpus-relative path, recorded on every span.
        injector: Decides and records defects.

    Returns:
        The metadata text and its identifier spans.
    """
    # --- Linkage defects: decided once per study so every series agrees. ---
    patient_id = person.mrn
    if injector.apply(
        "imaging.mrn_format_drift",
        path,
        f"PatientID written as {person.mrn.lstrip('0')} without the zero padding "
        f"used by the laboratory export ({person.mrn})",
    ):
        patient_id = person.mrn.lstrip("0")

    family, given = person.family_name, person.given_name
    if injector.apply(
        "imaging.name_mismatch",
        path,
        "PatientName re-entered at the console with an abbreviated given name",
    ):
        given = f"{person.given_name[0]}."

    study_description: Piece = study.study_description
    if injector.apply("imaging.missing_study_description", path, "StudyDescription left empty"):
        study_description = ""

    burned_in = injector.apply(
        "imaging.burned_in_annotation",
        path,
        "BurnedInAnnotation=YES: identifiers rendered into the pixel data, "
        "unreachable by header-level de-identification",
    )

    name_in_series = injector.should_apply("imaging.phi_in_series_description")
    if name_in_series:
        injector.record(
            "imaging.phi_in_series_description",
            path,
            "patient name typed into SeriesDescription (0008,103E) at the console",
        )

    phi_in_private = injector.should_apply("imaging.phi_in_private_tag")
    if phi_in_private:
        injector.record(
            "imaging.phi_in_private_tag",
            path,
            "accession number retained in vendor private tag (0029,1010)",
        )

    study_tags = [
        _Tag("00080020", "DA", Phi(study.study_date.strftime("%Y%m%d"), PhiCategory.DATE)),
        _Tag("00080030", "TM", study.study_date.strftime("%H%M%S")),
        _Tag("00080050", "SH", Phi(study.accession, PhiCategory.ACCESSION)),
        _Tag("00080060", "CS", study.modality),
        _Tag("00080070", "LO", study.manufacturer),
        _Tag("00080080", "LO", Phi(study.institution, PhiCategory.INSTITUTION)),
        _Tag("00080081", "ST", Phi(study.institution_address, PhiCategory.ADDRESS)),
        _Tag(
            "00080090",
            "PN",
            Phi(
                _person_name(study.referring_physician),
                PhiCategory.PROVIDER_NAME,
                "referring physician",
            ),
        ),
        _Tag("00081010", "SH", Phi(study.station_name, PhiCategory.DEVICE_ID)),
        _Tag("00081030", "LO", study_description),
        _Tag(
            "00081050",
            "PN",
            Phi(
                _person_name(study.performing_physician),
                PhiCategory.PROVIDER_NAME,
                "performing physician",
            ),
        ),
        _Tag("00081090", "LO", study.manufacturer_model),
        _Tag("00100010", "PN", Phi(_person_name(f"{family} {given}"), PhiCategory.PERSON_NAME)),
        _Tag("00100020", "LO", Phi(patient_id, PhiCategory.PATIENT_ID)),
        _Tag("00100030", "DA", Phi(person.birth_date.strftime("%Y%m%d"), PhiCategory.DATE)),
        _Tag("00100040", "CS", person.sex.value),
        _Tag(
            "00101010",
            "AS",
            Phi(f"{person.age_on(study.study_date.date()):03d}Y", PhiCategory.AGE),
        ),
        _Tag("00180015", "CS", study.body_part),
        _Tag("00181000", "LO", Phi(study.device_serial_number, PhiCategory.DEVICE_ID)),
        _Tag("0020000D", "UI", Phi(study.study_uid, PhiCategory.UID)),
        _Tag("00280301", "CS", "YES" if burned_in else "NO"),
    ]

    text = AnnotatedText(path)
    text.write("[\n")
    for position, series in enumerate(study.series):
        series_description: Piece = series.series_description
        if name_in_series:
            series_description = Phi(
                f"{series.series_description} {person.family_name} {person.given_name}",
                PhiCategory.PERSON_NAME,
                "patient name inside a free-text protocol field",
            )

        tags = [
            *study_tags,
            _Tag("0008103E", "LO", series_description),
            _Tag("00181030", "LO", series.protocol_name),
            _Tag("0020000E", "UI", Phi(series.series_uid, PhiCategory.UID)),
            _Tag("00200011", "IS", str(series.series_number)),
            _Tag("00201209", "IS", str(series.instance_count)),
        ]
        if phi_in_private:
            tags.append(_Tag("00290010", "LO", "SYNTH VENDOR BLOCK"))
            tags.append(
                _Tag(
                    "00291010",
                    "LO",
                    Phi(
                        f"ORDER={study.accession};MRN={person.mrn}",
                        PhiCategory.PATIENT_ID,
                        "identifiers retained in an undocumented vendor private tag",
                    ),
                )
            )

        _write_object(text, tags, "  ")
        text.write(",\n" if position < len(study.series) - 1 else "\n")
    text.write("]\n")

    return text.finish()
