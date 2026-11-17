"""Build the facts of a synthetic cohort, deterministically.

The reproducibility property this module provides is stronger than "same seed,
same output", and worth stating precisely:

    Subject *n* is identical no matter how many subjects were requested.

Generating ten subjects and generating a thousand produce the same first ten
files, byte for byte. That is not what you get by drawing everything from one
stream, where asking for one more subject shifts every later random draw and
changes the whole corpus. It comes from deriving a separate stream per subject
from the master seed, which is the same trick, and the same reasoning, as the
domain-separated HMAC design the de-identification step uses.

Why it matters in practice: a bug report that says "subject 347 has a negative
haemoglobin" stays reproducible from the seed alone, without regenerating or
shipping the whole corpus. And a test can assert on subject 3 of a 5-subject
run without caring that the suite elsewhere generates 50.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from random import Random

from commissura.generate import vocabulary as vocab
from commissura.generate.imaging import sample_study
from commissura.generate.labs import sample_panel
from commissura.generate.reports import sample_discharge_report, sample_radiology_report
from commissura.identifiers import (
    accession_number,
    codice_fiscale,
    email_address,
    landline_number,
    medical_record_number,
    synthetic_place_code,
)
from commissura.models import ClinicalReport, ImagingStudy, LabPanel, Person, Sex, Subject

DEFAULT_REFERENCE_DATE = date(2024, 6, 30)
"""The notional 'today' of the corpus; all clinical activity precedes it.

Fixed rather than taken from the system clock, because a corpus whose content
depends on when it was generated is not reproducible, and the first symptom is a
test that passes until midnight on New Year's Eve.
"""


def child_seed(seed: int, label: str) -> int:
    """Derive an independent seed from a master seed and a label.

    Uses SHA-256 over ``seed|label`` rather than arithmetic on the seed, so that
    adjacent labels give unrelated streams. ``hash()`` would be the obvious
    choice and the wrong one: it is salted per process for strings, so it would
    make output depend on the environment.

    Args:
        seed: The master seed.
        label: A domain-separating label, for example ``"subject|7"``.

    Returns:
        A 64-bit seed.
    """
    digest = hashlib.sha256(f"{seed}|{label}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


@dataclass(frozen=True, slots=True)
class CohortSpec:
    """What to generate.

    Attributes:
        subjects: How many subjects.
        seed: Master seed. The reproducibility contract rests on this.
        defect_rate: Per-opportunity probability that a defect is injected.
            ``0.0`` gives a clean corpus; ``1.0`` gives one that is maximally
            hostile to a validator.
        reference_date: The notional present. All activity precedes it.
        max_encounters: Upper bound on encounters per subject.
        cda: Emit each laboratory panel as an HL7 Italia CDA R2 document under
            ``cda/`` instead of an HL7 v2 message under ``lab/``.

            **Off by default, and that is deliberate rather than cautious.** A
            CDA document carries its own narrative, so turning this on changes
            which files a corpus holds and therefore every captured number in
            the README's worked example. Defaulting to off keeps a corpus
            generated from a given seed byte-identical to one generated before
            this flag existed, which is the reproducibility contract the seed
            is for. Turning it on produces the corpus a site that has migrated
            to the Fascicolo Sanitario Elettronico would hand over: structured
            laboratory data as CDA, with the radiology reports and discharge
            letters still arriving as plain text, because those have their own
            CDA profiles that this project does not read yet.
    """

    subjects: int = 10
    seed: int = 0
    defect_rate: float = 0.15
    reference_date: date = DEFAULT_REFERENCE_DATE
    max_encounters: int = 3
    cda: bool = False

    def __post_init__(self) -> None:
        """Validate the specification.

        Raises:
            ValueError: If any value is out of range.
        """
        if self.subjects < 1:
            raise ValueError(f"subjects must be at least 1, got {self.subjects}")
        if not 0.0 <= self.defect_rate <= 1.0:
            raise ValueError(f"defect_rate must be between 0 and 1, got {self.defect_rate}")
        if self.max_encounters < 1:
            raise ValueError(f"max_encounters must be at least 1, got {self.max_encounters}")


@dataclass(frozen=True, slots=True)
class PlannedSubject:
    """A subject together with the context needed to render their files.

    ``site`` is the institution whose exports the subject appears in, and
    ``previous_study_dates`` lets a report refer in prose to an earlier study,
    which is where the hardest de-identification cases live.
    """

    index: int
    subject: Subject
    site: vocab.Site
    previous_site: vocab.Site | None = None
    control_ids: tuple[str, ...] = field(default_factory=tuple)


def build_person(rng: Random, *, reference_date: date) -> Person:
    """Invent one synthetic person.

    Ages are drawn from a triangular distribution peaking at 68. A uniform draw
    over adult ages would produce a cohort unlike any real clinical population,
    and the resulting corpus would not exercise the age handling that matters —
    the tail above 89, which is re-identifying in small groups.

    Args:
        rng: Seeded random source.
        reference_date: The notional present, used to place the birth date.

    Returns:
        The person. Every field is fabricated and, where the format allows it,
        provably not real.
    """
    sex = rng.choice((Sex.MALE, Sex.FEMALE))
    given_name = rng.choice(vocab.GIVEN_NAMES_MALE if sex is Sex.MALE else vocab.GIVEN_NAMES_FEMALE)
    family_name = rng.choice(vocab.FAMILY_NAMES)

    age = int(rng.triangular(18, 94, 68))
    # Day capped at 28 so no month-length special cases are needed.
    birth_date = date(
        reference_date.year - age,
        rng.randrange(1, 13),
        rng.randrange(1, 29),
    )

    city, province, postal_code, area_code = rng.choice(vocab.CITIES)
    street = f"{rng.choice(vocab.STREETS)} {rng.randrange(1, 180)}"

    return Person(
        family_name=family_name,
        given_name=given_name,
        sex=sex,
        birth_date=birth_date,
        codice_fiscale=codice_fiscale(
            family_name, given_name, birth_date, sex, synthetic_place_code(rng)
        ),
        mrn=medical_record_number(rng),
        street=street,
        city=city,
        province=province,
        postal_code=postal_code,
        phone=landline_number(rng, area_code),
        email=email_address(given_name, family_name, rng),
    )


def _clinician(rng: Random) -> str:
    """Return a clinician name as ``FAMILY GIVEN``."""
    family = rng.choice(vocab.FAMILY_NAMES)
    given = rng.choice(vocab.GIVEN_NAMES_MALE + vocab.GIVEN_NAMES_FEMALE)
    return f"{family} {given}"


def build_subject(rng: Random, *, index: int, spec: CohortSpec) -> PlannedSubject:
    """Build one subject's complete clinical history.

    Args:
        rng: Seeded random source, derived for this subject alone.
        index: Position in the cohort, used only for message control numbers.
        spec: The cohort specification.

    Returns:
        The subject and the context needed to render their files.
    """
    person = build_person(rng, reference_date=spec.reference_date)
    site = rng.choice(vocab.SITES)
    previous_site = rng.choice(vocab.SITES)

    baseline_date = spec.reference_date - timedelta(days=rng.randrange(30, 900))
    encounters = rng.randrange(1, spec.max_encounters + 1)

    panels: list[LabPanel] = []
    studies: list[ImagingStudy] = []
    reports: list[ClinicalReport] = []

    for encounter in range(encounters):
        when = datetime.combine(
            baseline_date + timedelta(days=encounter * rng.randrange(20, 160)),
            datetime.min.time(),
        ) + timedelta(hours=rng.randrange(7, 17), minutes=rng.randrange(0, 60))

        for panel_template in rng.sample(vocab.PANELS, rng.randrange(1, 4)):
            panels.append(
                sample_panel(
                    rng,
                    person=person,
                    panel=panel_template,
                    collected_at=when,
                    accession=accession_number(rng, "LAB"),
                    ordering_provider=_clinician(rng),
                    performing_lab=rng.choice(vocab.LABORATORIES),
                )
            )

        # Not every encounter involves imaging; a laboratory-only visit is the
        # common case and the corpus should reflect that.
        if rng.random() < 0.55:
            study = sample_study(
                rng,
                protocol=rng.choice(vocab.PROTOCOLS),
                study_date=when + timedelta(hours=rng.randrange(1, 6)),
                accession=accession_number(rng, "RAD"),
                site=site,
                referring_physician=_clinician(rng),
                performing_physician=_clinician(rng),
            )
            studies.append(study)
            reports.append(
                sample_radiology_report(
                    rng,
                    study=study,
                    author_name=_clinician(rng),
                    author_role=rng.choice(vocab.RADIOLOGIST_ROLES),
                    site=site,
                )
            )

        if rng.random() < 0.35:
            reports.append(
                sample_discharge_report(
                    rng,
                    admitted_at=when,
                    author_name=_clinician(rng),
                    specialty=rng.choice(vocab.CLINICAL_SPECIALTIES),
                    site=site,
                )
            )

    subject = Subject(
        person=person,
        baseline_date=baseline_date,
        panels=tuple(panels),
        reports=tuple(reports),
        studies=tuple(studies),
    )
    control_ids = tuple(f"MSG{index:05d}{n:04d}" for n in range(len(panels)))
    return PlannedSubject(
        index=index,
        subject=subject,
        site=site,
        previous_site=previous_site,
        control_ids=control_ids,
    )


def build_cohort(spec: CohortSpec) -> tuple[PlannedSubject, ...]:
    """Build every subject in the cohort.

    Each subject is generated from its own derived stream, so the result for
    subject *n* does not depend on ``spec.subjects``.

    Args:
        spec: The cohort specification.

    Returns:
        The planned subjects, in order.
    """
    return tuple(
        build_subject(
            Random(child_seed(spec.seed, f"subject|{index}")),
            index=index,
            spec=spec,
        )
        for index in range(spec.subjects)
    )
