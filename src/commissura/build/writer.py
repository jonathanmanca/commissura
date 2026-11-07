"""Turn a linked raw corpus into a dataset.

The pipeline, in order, because each step depends on the one before it:

1. **Link** the three exports to the same people. Done already, in
   :mod:`commissura.read.corpus`.
2. **Pseudonymise** each subject from their national identifier, so the three
   branches agree on one label.
3. **Anchor** every date to the subject's own earliest event, and express the
   rest as integer offsets from it. The calendar is gone; the intervals are
   exact.
4. **Scrub** free text, using the identifiers the structured exports declared.
5. **Write** the BIDS layout, the de-identification manifest and the
   HealthDCAT-AP description.

Two choices worth defending.

**Sessions are encounters.** A session directory is created per distinct date on
which something happened to the subject, which is what a clinician means by a
visit and what makes ``ses-01`` interpretable. The alternative, one session per
source file, would produce directories that mean nothing.

**Imaging metadata goes to ``derivatives/``, not to ``anat/``.** This project
does not convert DICOM — the brief says to orchestrate ``dcm2bids`` rather than
reimplement it — so there is no NIfTI to put in a datatype directory. Writing
pseudonymised metadata into ``derivatives/imaging-metadata/`` keeps the linkage
visible and auditable without pretending a conversion happened.
"""

from __future__ import annotations

import json
import platform
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from commissura import healthdcat, layout
from commissura.build.scrub import KnownIdentifiers, ScrubReport, scrub_text
from commissura.deident.keys import SecretKey
from commissura.deident.pseudonymise import RULE_VERSION, Pseudonymiser
from commissura.read.corpus import RawCorpus, Subject


@dataclass(frozen=True, slots=True)
class BuildSpec:
    """What the data holder has to tell the tool, because only they know it.

    Every field here is something `commissura` refuses to invent. The HealthDCAT-AP
    profile makes ``healthdcatap:hdab`` mandatory at exactly one value, and Italy
    has not designated its Health Data Access Body yet, so there is no default
    that would be true. Same for the applicable legislation and the access
    right: these are facts about a release arrangement, not about the data.
    """

    dataset_name: str
    description: str
    tier: healthdcat.Tier = healthdcat.DEFAULT_TIER
    hdab: str | None = None
    publisher: str | None = None
    health_categories: tuple[str, ...] = (healthdcat.HEALTH_CATEGORY_FOR_EHR,)
    applicable_legislation: tuple[str, ...] = ("http://data.europa.eu/eli/reg/2025/327/oj",)
    keywords: tuple[str, ...] = ("clinical", "laboratory", "imaging", "synthetic")
    dataset_type: str = healthdcat.DATASET_TYPE_FOR_SYNTHETIC
    contact_point: str | None = None
    access_url: str | None = None

    def missing_for_conformance(self) -> tuple[str, ...]:
        """Return the mandatory profile properties this spec cannot supply.

        Returned rather than raised, so `build` can produce a dataset and tell
        the user it is not yet catalogue-ready. Refusing to build without an
        HDAB would make the tool unusable in Italy until 2027.
        """
        missing: list[str] = []
        if not self.hdab:
            missing.append("healthdcatap:hdab")
        if not self.publisher:
            missing.append("dct:publisher")
        if not self.access_url:
            # DCAT-AP requires an access URL on every distribution, so the
            # profile assumes the data is reachable. A dataset on a hospital
            # disk is not, and the holder is the one who knows where a permit
            # application would go.
            missing.append("dcat:accessURL")
        if not self.contact_point:
            # Mandatory in the non-public tier, which is the default: a dataset
            # whose description is catalogued but whose data is not available
            # needs a way for somebody to ask.
            missing.append("dcat:contactPoint")
        return tuple(missing)


@dataclass(slots=True)
class BuildSummary:
    """What a build produced, and what it could not."""

    root: Path
    subject_count: int
    session_count: int
    lab_files: int = 0
    report_files: int = 0
    imaging_files: int = 0
    scrub_reports: list[ScrubReport] = field(default_factory=list)
    linkage_issues: int = 0
    missing_for_conformance: tuple[str, ...] = ()

    @property
    def file_count(self) -> int:
        """Return how many clinical files were written."""
        return self.lab_files + self.report_files + self.imaging_files

    @property
    def redaction_count(self) -> int:
        """Return how many identifier occurrences were removed from free text."""
        return sum(r.total_occurrences for r in self.scrub_reports)

    def residual_risks(self) -> tuple[str, ...]:
        """Return the distinct residual risks the scrubber reported."""
        seen: list[str] = []
        for report in self.scrub_reports:
            for risk in report.residual_risk:
                if risk not in seen:
                    seen.append(risk)
        return tuple(seen)


def _write_text(path: Path, content: str) -> None:
    """Write text with no newline translation, creating parents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="")


def _write_json(path: Path, payload: object) -> None:
    """Write pretty-printed UTF-8 JSON with no newline translation."""
    _write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def _write_tsv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    """Write a tab-separated file with a header row."""
    lines = ["\t".join(header), *("\t".join(row) for row in rows)]
    _write_text(path, "\n".join(lines) + "\n")


def _split_reference_range(value: str) -> tuple[str, str]:
    """Split a printed reference interval into its two bounds.

    Laboratories print ``12.0-15.5``. A one-sided interval, an empty field or
    anything else yields ``n/a`` for both, because a half-parsed range is worse
    than an absent one: it reads as authoritative.
    """
    if value.count("-") != 1:
        return layout.NOT_APPLICABLE, layout.NOT_APPLICABLE
    low, _, high = value.partition("-")
    low, high = low.strip(), high.strip()
    if not low or not high:
        return layout.NOT_APPLICABLE, layout.NOT_APPLICABLE
    return low, high


def _age_band(birth_date: date | None, reference: date | None) -> str:
    """Return the participant's age, truncated at the ceiling.

    Returns ``n/a`` when either date is unreadable: a dataset that guessed an
    age would be stating something it does not know.
    """
    if birth_date is None or reference is None:
        return layout.NOT_APPLICABLE
    had_birthday = (reference.month, reference.day) >= (birth_date.month, birth_date.day)
    age = reference.year - birth_date.year - (0 if had_birthday else 1)
    if age > layout.AGE_CEILING:
        return layout.AGE_ABOVE_CEILING
    return str(age)


def _report_kind(text: str) -> str:
    """Infer a report's kind from its heading.

    Read from the document rather than the filename, because a filename
    convention is ours and a heading is the hospital's.
    """
    if "DIAGNOSTICA PER IMMAGINI" in text or "REFERTO" in text:
        return "radiology"
    if "DIMISSIONE" in text:
        return "discharge"
    return "unspecified"


def _session_dates(subject: Subject) -> list[date]:
    """Return the distinct dates on which something happened, in order."""
    moments: set[date] = set()
    moments |= {r.collected_at.date() for r in subject.labs if r.collected_at}
    moments |= {r.authored_on for r in subject.reports if r.authored_on}
    moments |= {r.study_date for r in subject.imaging if r.study_date}
    return sorted(moments)


def _known_identifiers(corpus: RawCorpus, subject: Subject) -> KnownIdentifiers:
    """Collect everything the structured exports declared about this subject.

    Providers and institutions are gathered across the whole corpus, not just
    this subject: a clinician who signed one report signs others, and removing
    their name everywhere is both safer and cheaper than deciding per document.
    """
    providers: set[str] = set()
    institutions: set[str] = set()
    for other in corpus.subjects:
        for lab in other.labs:
            if lab.ordering_provider:
                providers.add(lab.ordering_provider)
                providers.update(part for part in lab.ordering_provider.split() if len(part) >= 4)
            if lab.sending_facility:
                institutions.add(lab.sending_facility)
                # Individual words too: an institution named in running prose is
                # usually shortened, while HL7 MSH-4 carries the official form.
                institutions.update(part for part in lab.sending_facility.split() if len(part) >= 4)
    # The clinician who signed a report appears in no laboratory message, so
    # the signature line is the only structured source for that name.
    for report in subject.reports:
        if report.signed_by:
            providers.add(report.signed_by)
            providers.update(part for part in report.signed_by.split() if len(part) >= 4)
    # Imaging metadata carries the institution's street address, which no
    # laboratory message does. A street plus a city is a quasi-identifier even
    # with the patient's own address gone.
    addresses: set[str] = set()
    for other in corpus.subjects:
        for study in other.imaging:
            for part in study.institution_address.split(","):
                cleaned = part.strip()
                if len(cleaned) >= 4:
                    addresses.add(cleaned)
    return KnownIdentifiers(
        identity=subject.identity,
        providers=frozenset(providers),
        institutions=frozenset(institutions),
        addresses=frozenset(addresses),
    )


def build_dataset(corpus: RawCorpus, key: SecretKey, spec: BuildSpec, out: Path) -> BuildSummary:
    """Write a de-identified dataset from a linked raw corpus.

    Args:
        corpus: The linked corpus.
        key: The secret every pseudonym derives from.
        spec: What the data holder had to supply.
        out: Dataset root. Created if absent.

    Returns:
        A summary of what was written and what remains unsatisfied.
    """
    out = out.resolve()
    pseudonymiser = Pseudonymiser(key)
    summary = BuildSummary(
        root=out,
        subject_count=len(corpus.subjects),
        session_count=0,
        linkage_issues=len(corpus.issues),
        missing_for_conformance=spec.missing_for_conformance(),
    )

    participant_rows: list[list[str]] = []

    for subject in corpus.subjects:
        label = pseudonymiser.subject_label(subject.identity.national_id)
        directory = f"{layout.SUBJECT_PREFIX}{label}"
        baseline = subject.baseline
        known = _known_identifiers(corpus, subject)

        participant_rows.append(
            [
                directory,
                _age_band(subject.identity.birth_date, baseline),
                subject.identity.sex.value if subject.identity.sex else layout.NOT_APPLICABLE,
            ]
        )

        sessions = _session_dates(subject)
        session_of: dict[date, str] = {
            moment: f"{layout.SESSION_PREFIX}{index:02d}"
            for index, moment in enumerate(sessions, start=1)
        }
        summary.session_count += len(sessions)

        _write_subject_labs(subject, out, directory, session_of, baseline, pseudonymiser, summary)
        _write_subject_reports(
            subject, out, directory, session_of, baseline, pseudonymiser, label, known, summary
        )
        _write_subject_imaging(subject, out, directory, baseline, pseudonymiser, summary)

    _write_tsv(
        out / layout.PARTICIPANTS_TSV,
        [layout.PARTICIPANT_ID_COLUMN, "age", "sex"],
        participant_rows,
    )
    _write_participants_sidecar(out)
    _write_bids_description(out, spec)
    return summary


def _write_subject_labs(
    subject: Subject,
    out: Path,
    directory: str,
    session_of: dict[date, str],
    baseline: date | None,
    pseudonymiser: Pseudonymiser,
    summary: BuildSummary,
) -> None:
    """Write one subject's laboratory tables, one per session."""
    by_session: dict[str, list[list[str]]] = {}
    for lab in subject.labs:
        if lab.collected_at is None or baseline is None:
            continue
        session = session_of[lab.collected_at.date()]
        offset = pseudonymiser.day_offset(baseline, lab.collected_at.date())
        for observation in lab.observations:
            low, high = _split_reference_range(observation.reference_range)
            by_session.setdefault(session, []).append(
                [
                    str(offset),
                    observation.loinc_code or layout.NOT_APPLICABLE,
                    observation.value or layout.NOT_APPLICABLE,
                    observation.unit or layout.NOT_APPLICABLE,
                    observation.display or layout.NOT_APPLICABLE,
                    low,
                    high,
                    observation.abnormal_flag or layout.NOT_APPLICABLE,
                    lab.panel_code or layout.NOT_APPLICABLE,
                ]
            )

    for session, rows in sorted(by_session.items()):
        stem = f"{directory}_{session}"
        base = out / directory / session / "lab"
        _write_tsv(
            base / f"{stem}_{layout.LAB_SUFFIX}.tsv",
            [*layout.LAB_REQUIRED_COLUMNS, *layout.LAB_RECOMMENDED_COLUMNS],
            rows,
        )
        _write_json(
            base / f"{stem}_{layout.LAB_SUFFIX}.json",
            {
                "day_offset": {
                    "Description": "Whole days from the subject's own earliest recorded "
                    "event. Negative values precede it.",
                    "Units": "days",
                },
                "loinc_code": {"Description": "LOINC code identifying the analyte."},
                "value": {"Description": "Measured value as the laboratory reported it."},
                "unit": {"Description": "Unit of measure, as sent in HL7 OBX-6."},
            },
        )
        summary.lab_files += 2


def _write_subject_reports(
    subject: Subject,
    out: Path,
    directory: str,
    session_of: dict[date, str],
    baseline: date | None,
    pseudonymiser: Pseudonymiser,
    label: str,
    known: KnownIdentifiers,
    summary: BuildSummary,
) -> None:
    """Scrub and write one subject's reports, with a sidecar each."""
    counters: dict[str, int] = {}
    for report in subject.reports:
        if report.authored_on is None or baseline is None:
            continue
        session = session_of[report.authored_on]
        counters[session] = counters.get(session, 0) + 1
        run = counters[session]
        stem = f"{directory}_{session}_run-{run:02d}_{layout.REPORT_SUFFIX}"
        base = out / directory / session / "reports"

        scrubbed, scrub_report = scrub_text(
            report.text,
            path=f"{directory}/{session}/reports/{stem}{layout.REPORT_TEXT_EXTENSION}",
            known=known,
            pseudonymiser=pseudonymiser,
            subject_label=label,
            baseline=baseline,
        )
        summary.scrub_reports.append(scrub_report)

        _write_text(base / f"{stem}{layout.REPORT_TEXT_EXTENSION}", scrubbed)
        _write_json(
            base / f"{stem}{layout.REPORT_SIDECAR_EXTENSION}",
            {
                "kind": _report_kind(report.text),
                "day_offset": pseudonymiser.day_offset(baseline, report.authored_on),
                "RedactedCategories": scrub_report.categories(),
            },
        )
        summary.report_files += 2


def _write_subject_imaging(
    subject: Subject,
    out: Path,
    directory: str,
    baseline: date | None,
    pseudonymiser: Pseudonymiser,
    summary: BuildSummary,
) -> None:
    """Write pseudonymised imaging metadata under ``derivatives/``.

    Not under ``anat/`` or ``pet/``, because no conversion happened: this
    project orchestrates ``dcm2bids`` rather than reimplementing it, so there is
    no image to accompany. Keeping the metadata makes the linkage auditable.
    """
    for study in subject.imaging:
        if study.study_date is None or baseline is None:
            continue
        payload = {
            "study_uid": pseudonymiser.uid(study.study_uid),
            "series_uids": [pseudonymiser.uid(uid) for uid in study.series_uids],
            "accession": pseudonymiser.accession(study.accession),
            "day_offset": pseudonymiser.day_offset(baseline, study.study_date),
            "modality": study.modality,
            "burned_in_annotation": study.burned_in_annotation,
            "source_patient_id_matched_by": "normalised medical record number",
        }
        name = f"{directory}_{pseudonymiser.accession(study.accession)}_imaging.json"
        _write_json(out / layout.DERIVATIVES_DIR / "imaging-metadata" / name, payload)
        summary.imaging_files += 1


def _write_participants_sidecar(out: Path) -> None:
    """Describe the participants table's columns, as BIDS recommends."""
    _write_json(
        out / layout.PARTICIPANTS_JSON,
        {
            "age": {
                "Description": "Age in whole years at the subject's earliest recorded "
                f"event, truncated at {layout.AGE_CEILING}.",
                "Units": "years",
                "Levels": {layout.AGE_ABOVE_CEILING: f"Older than {layout.AGE_CEILING} years."},
            },
            "sex": {
                "Description": "Administrative sex as recorded in the source HL7 PID-8.",
                "Levels": {"M": "male", "F": "female"},
            },
        },
    )


def _write_bids_description(out: Path, spec: BuildSpec) -> None:
    """Write ``dataset_description.json``, the BIDS half of the provenance."""
    from commissura import __version__

    _write_json(
        out / layout.DATASET_DESCRIPTION,
        {
            "Name": spec.dataset_name,
            "BIDSVersion": layout.BIDS_VERSION,
            "DatasetType": "raw",
            "License": "CC0-1.0",
            "Authors": [spec.publisher] if spec.publisher else [],
            "GeneratedBy": [
                {
                    "Name": "commissura",
                    "Version": __version__,
                    "Description": "De-identified from a raw clinical corpus.",
                }
            ],
            "CommissuraSchemaVersion": layout.SCHEMA_VERSION,
            "HowToAcknowledge": (
                "Dates are expressed only as day_offset from each subject's own "
                "earliest recorded event. No absolute date appears in this dataset."
            ),
        },
    )


def tool_versions() -> dict[str, str]:
    """Return the versions a manifest has to record to be reproducible."""
    from commissura import __version__

    return {
        "commissura": __version__,
        "python": f"{platform.python_implementation()} {sys.version.split()[0]}",
        "deidentification_rules": RULE_VERSION,
        "healthdcat_ap_release": healthdcat.RELEASE,
        "layout_schema": layout.SCHEMA_VERSION,
    }


def utc_now() -> datetime:
    """Return the current moment, timezone-aware.

    A naive timestamp in an audit record is ambiguous by exactly one offset,
    and an audit record that cannot be placed in time is not much of a record.
    """
    return datetime.now(UTC)
