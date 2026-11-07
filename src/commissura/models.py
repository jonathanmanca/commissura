"""Domain models: the ground truth of a synthetic cohort.

The central design choice of this module is the separation between *facts* and
*artifacts*.

A :class:`Subject` holds facts: this person exists, has this name, this codice
fiscale, had blood drawn on this day, had a chest CT reported by this
radiologist. Nothing here is an HL7 message or a report; nothing here is text.

Rendering those facts into HL7 v2, free-text reports and DICOM metadata happens
in :mod:`commissura.generate`. Keeping the two apart buys three things:

1. **Cross-modal consistency is free.** All three renderers read the same facts,
   so the same person cannot accidentally have two birth dates.
2. **Inconsistency becomes deliberate.** When the lab export and the imaging
   export disagree about a name, that is a defect the generator chose to inject
   and recorded in the manifest, not an accident in the code.
3. **The models stay testable.** Facts can be asserted on without parsing text.

Every model is frozen. Ground truth that mutates after construction is a bug
waiting to happen, and immutability lets the type checker enforce that.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    """Base for every model here: immutable and strict about unknown fields.

    ``extra="forbid"`` turns a typo in a keyword argument into an error at
    construction time instead of a silently dropped value.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class Sex(StrEnum):
    """Administrative sex as it appears in HL7 v2 field PID-8.

    HL7 table 0001 also defines ``O`` (other), ``U`` (unknown) and ``A``
    (ambiguous). The generator emits only M and F for now; the enum is the place
    to widen that when the dataset schema is ready to carry it.
    """

    MALE = "M"
    FEMALE = "F"


class PhiCategory(StrEnum):
    """Categories of protected health information the generator can place.

    The scheme is adapted from Philter (UCSF), broadened where Italian and GDPR
    practice differs from HIPAA Safe Harbor. Two deliberate departures:

    - ``NATIONAL_ID`` is its own category rather than a generic identifier. The
      codice fiscale encodes birth date, sex and place of birth, so a single
      leaked value re-identifies directly; it deserves separate accounting.
    - ``AGE`` exists even though an age is not an identifier on its own, because
      ages above 89 are re-identifying in small populations.
    """

    PERSON_NAME = "person_name"
    PATIENT_ID = "patient_id"
    NATIONAL_ID = "national_id"
    DATE = "date"
    ADDRESS = "address"
    CONTACT = "contact"
    PROVIDER_NAME = "provider_name"
    INSTITUTION = "institution"
    AGE = "age"
    DEVICE_ID = "device_id"
    ACCESSION = "accession"
    UID = "uid"


class ReportKind(StrEnum):
    """The kind of free-text document being generated."""

    RADIOLOGY = "radiology"
    DISCHARGE = "discharge"


class AbnormalFlag(StrEnum):
    """HL7 v2 table 0078 interpretation codes, restricted to what we emit."""

    NORMAL = "N"
    LOW = "L"
    HIGH = "H"


class Person(_Frozen):
    """A synthetic person. Every field is fabricated.

    ``mrn`` is the hospital's own medical record number and ``codice_fiscale``
    the Italian national identifier. Both appear in the generated material and
    both are things a de-identifier has to find.
    """

    family_name: str
    given_name: str
    sex: Sex
    birth_date: date
    codice_fiscale: str = Field(min_length=16, max_length=16)
    mrn: str
    street: str
    city: str
    province: str = Field(min_length=2, max_length=2)
    postal_code: str = Field(min_length=5, max_length=5)
    phone: str
    email: str

    @property
    def full_name(self) -> str:
        """Return the name as a clinician would write it in prose."""
        return f"{self.given_name} {self.family_name}"

    def age_on(self, reference: date) -> int:
        """Return the age in whole years on ``reference``.

        Computed from the birth date rather than stored, because a stored age is
        a second source of truth and it drifts.
        """
        had_birthday = (reference.month, reference.day) >= (
            self.birth_date.month,
            self.birth_date.day,
        )
        return reference.year - self.birth_date.year - (0 if had_birthday else 1)


class LabObservation(_Frozen):
    """A single analyte result, rendered later as one HL7 OBX segment."""

    loinc_code: str
    display: str
    value: float | str
    unit: str
    reference_low: float | None = None
    reference_high: float | None = None
    abnormal_flag: AbnormalFlag = AbnormalFlag.NORMAL
    observed_at: datetime
    decimals: int = Field(default=1, ge=0)
    """How many decimal places this analyte is reported to.

    Part of the result, not a display preference: a platelet count is reported
    as ``535`` and a creatinine as ``0.94``, and a laboratory that printed
    ``535.0`` would be telling you it measured a precision it does not have.
    """


class LabPanel(_Frozen):
    """An ordered group of observations, rendered later as one ORU^R01 message."""

    accession: str
    panel_code: str
    panel_name: str
    ordered_at: datetime
    collected_at: datetime
    reported_at: datetime
    ordering_provider: str
    performing_lab: str
    observations: tuple[LabObservation, ...] = Field(min_length=1)


class ClinicalReport(_Frozen):
    """A free-text document, held as structured sections rather than as text.

    The renderer assembles prose from these fields and records where it placed
    each identifier. Storing finished prose here instead would make the
    ground-truth PHI offsets impossible to produce without re-parsing our own
    output.
    """

    kind: ReportKind
    authored_at: datetime
    author_name: str
    author_role: str
    institution: str
    indication: str
    technique: str
    findings: tuple[str, ...]
    conclusion: str
    linked_study_uid: str | None = None


class ImagingSeries(_Frozen):
    """One series within a study, as DICOM would describe it."""

    series_uid: str
    series_number: int
    modality: str
    series_description: str
    protocol_name: str
    instance_count: int = Field(gt=0)


class ImagingStudy(_Frozen):
    """An imaging study, modelled on the DICOM header fields that carry identity.

    The fields below are not an arbitrary selection: each one is a place where
    identifiers are known to hide in real exports. ``station_name`` and
    ``device_serial_number`` narrow a study to one machine in one department;
    ``burned_in_annotation`` marks pixel data that no header-level scrubber can
    reach; ``private_tags`` stands in for vendor blocks, which are the single
    most commonly missed hiding place.
    """

    study_uid: str
    study_date: datetime
    accession: str
    modality: str
    body_part: str
    study_description: str
    institution: str
    institution_address: str
    referring_physician: str
    performing_physician: str
    station_name: str
    manufacturer: str
    manufacturer_model: str
    device_serial_number: str
    burned_in_annotation: bool = False
    private_tags: tuple[tuple[str, str], ...] = ()
    series: tuple[ImagingSeries, ...] = Field(min_length=1)


class Subject(_Frozen):
    """One synthetic person together with everything generated about them.

    ``baseline_date`` is the anchor the de-identification step will later shift
    dates against. It is kept here in the clear because this is raw material:
    the whole point is that ``commissura build`` has something real to remove.
    """

    person: Person
    baseline_date: date
    panels: tuple[LabPanel, ...]
    reports: tuple[ClinicalReport, ...]
    studies: tuple[ImagingStudy, ...]


class PhiSpan(_Frozen):
    """Ground truth: one identifier, and exactly where it was written.

    ``start`` and ``end`` are character offsets into the file named by ``path``,
    as decoded UTF-8, over a half-open interval. So ``text`` must always equal
    ``content[start:end]``, and the test suite checks that against the files on
    disk rather than trusting the generator.

    Character offsets rather than byte offsets is a real trade-off. Characters
    are what a Python scrubber works in, so comparison needs no conversion; but
    HL7 v2 is historically a byte protocol, and a tool reading bytes will have
    to convert. Recording the choice here makes it a decision rather than an
    accident of implementation.
    """

    path: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str
    category: PhiCategory
    note: str | None = None


class AppliedDefect(_Frozen):
    """Record of one defect the generator deliberately introduced.

    This is the second measurement loop in the project. Because every injected
    defect is recorded against the file it landed in, ``commissura validate`` can
    be scored against known ground truth instead of eyeballed.
    """

    defect_id: str
    path: str
    detail: str


class ModalityCounts(_Frozen):
    """How many files were written per modality."""

    lab: int = 0
    reports: int = 0
    imaging: int = 0


class GenerationManifest(_Frozen):
    """Everything needed to reproduce a corpus, and to audit what it contains.

    ``seed`` together with ``tool_version`` is the reproducibility contract: the
    same pair must always produce identical output. The test suite asserts it.
    """

    manifest_schema_version: str = "1.0.0"
    tool_version: str
    python_version: str
    generated_at: datetime
    seed: int
    subject_count: int
    files: ModalityCounts
    phi_span_count: int
    defects: tuple[AppliedDefect, ...]
