"""Read a raw corpus and link its three exports to the same people.

This is the problem `commissura` exists to solve, so it is worth saying plainly
what makes it hard. A hospital hands over three dumps from three systems. Each
is internally consistent. Nothing guarantees they agree with each other about
who the patient is, and nothing fails when they do not — a naive join on the
patient identifier silently drops whoever it cannot match, and the result looks
like a smaller cohort rather than a bug.

So linkage here is **explicit and accountable**. Every record either attaches to
a subject or produces a :class:`LinkageIssue` naming the file and the reason.
The count of issues is reported, written into the manifest, and is the number
somebody should look at before trusting a dataset.

Which export is authoritative matters too. The laboratory messages are, because
HL7 PID carries the national identifier and the imaging metadata does not: a
DICOM header has a ``PatientID``, which is the hospital's own number, not a
national one. Pseudonyms derive from the national identifier, so a subject
exists only if a laboratory message established it. Imaging and reports attach
to subjects already known.

Identifier normalisation is the one liberty taken, and it is taken knowingly.
The RIS and the LIS store the same medical record number with different
zero-padding — ``0007741`` against ``7741`` — which the generator models as a
defect because it is endemic. Matching on the stripped form recovers those
links, and every recovery is recorded as a normalisation rather than passed off
as a clean match.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Final

from commissura.models import Sex
from commissura.read.hl7 import Segment, parse_day, parse_message, parse_timestamp
from commissura.read.identity import (
    AuthorityScope,
    IdentifierStatus,
    IdentityIndex,
    IdentityKey,
    Refusal,
    RefusalReason,
    classify_national_id,
    identities_conflict,
)

RAW_SOURCES: Final[dict[str, str]] = {
    "lab": "lab/*.hl7",
    "reports": "reports/*.txt",
    "imaging": "imaging/*.json",
}
"""Where each modality's export lives in a raw corpus, relative to its root.

Laboratory first, because a laboratory message is what creates a subject and
the other two can only attach to one that exists. The dictionary order carries
that, and :func:`read_corpus` depends on it.

Declared here rather than written at each call site because two modules now walk
the same corpus -- this one to link it, :mod:`commissura.build.observe` to
account for its fields -- and a glob that disagreed between them would make the
manifest describe files the dataset was not built from.
"""


NATIONAL_ID_TYPE_CODES: Final[frozenset[str]] = frozenset({"NNITA", "NI"})
"""PID-3 identifier type codes that mark a value as the national identifier.

HL7 v2 table 0203 has **no concrete code for Italy**, which is the first thing
to know here. What it has is a documented pattern: ``NNxxx``, "National Person
Identifier where the xxx is the ISO table 3166 3-character (alphabetic) country
code". So ``NNITA`` is that pattern instantiated for Italy rather than a listed
concept, and it is what Italian profiles send. ``NI``, "National unique
individual identifier", *is* a listed concept and some systems use it instead.

Both are accepted because this is a reader, and a reader that insisted on one
spelling would reject half of the real messages for a difference that carries
no information. Checked against the table rather than recalled -- see the
decision log entry of 2026-11-11 for why that mattered.
"""

MEDICAL_RECORD_TYPE_CODE: Final = "MR"
"""The listed code for a medical record number, per table 0203."""


def _identifier_of_type(pid: Segment, wanted: frozenset[str]) -> str:
    """Return the first PID-3 identifier whose type code is one of ``wanted``.

    Args:
        pid: The PID segment.
        wanted: Identifier type codes to accept, from table 0203.

    Returns:
        The identifier, or an empty string if no repetition carries one of
        those type codes.
    """
    for components in pid.repetition_components(3):
        value = components[0].strip() if components else ""
        type_code = components[4].strip().upper() if len(components) > 4 else ""
        if value and type_code in wanted:
            return value
    return ""


def _assigning_authority(pid: Segment) -> str:
    """Return the authority that issued the medical record number, if stated.

    PID-3 component 4. A record number is a hospital's own number, so the
    authority is what makes it comparable: two hospitals both number their
    patients from 1, and an index that ignored this attributed one hospital's
    imaging study to another hospital's patient. The value was always parsed
    into the message and discarded at exactly the point it mattered.

    Read **only** from the repetition carrying the record-number type code.
    There is deliberately no fallback to "whichever repetition names an
    authority", which was the first version of this function and was wrong: the
    national identifier's repetition names MINSAL, the ministry that issues
    codice fiscali, and taking that as the authority for a record number would
    scope every hospital's numbering under one national namespace — which is
    the flat index this change exists to remove, reintroduced under a
    plausible-looking name. A test pins it.

    When the record-number repetition names no authority, the caller falls back
    to MSH-4, which at least names the institution that sent the message.

    Args:
        pid: The PID segment.

    Returns:
        The authority, or an empty string. Never invented.
    """
    for components in pid.repetition_components(3):
        type_code = components[4].strip().upper() if len(components) > 4 else ""
        if (
            type_code == MEDICAL_RECORD_TYPE_CODE
            and len(components) > 3
            and (authority := components[3].strip())
        ):
            return authority
    return ""


def _untyped_identifier(pid: Segment) -> str:
    """Return PID-3's first identifier when the segment declares no type codes.

    An interface that sends a bare ``PID|1||0012345`` means the medical record
    number, because that is the only identifier it has room to mean. The test is
    that *no* repetition carries a type code: once one does, an untyped value is
    something the sender chose not to label, and guessing what it is would be
    how a codice fiscale ends up filed as a record number.

    Args:
        pid: The PID segment.

    Returns:
        The identifier, or an empty string.
    """
    repetitions = pid.repetition_components(3)
    if any(len(components) > 4 and components[4].strip() for components in repetitions):
        return ""
    return repetitions[0][0].strip() if repetitions and repetitions[0] else ""


def read_exact(path: Path) -> str:
    """Read a file's text with no newline translation, on every supported Python.

    ``Path.read_text`` grew a ``newline`` parameter only in Python 3.13, and this
    project supports 3.11. Going through :meth:`Path.open`, which has accepted it
    all along, keeps the behaviour identical across the whole supported range.

    Without this, reading a corpus file on Windows would translate the bare
    carriage returns that terminate HL7 segments, and every character offset
    after the first one would be wrong.

    This is the project's only copy. It lived in three modules — here, in the
    corpus writer and in the validator's context — and three copies of a
    byte-exactness primitive is three places for one of them to drift.

    Args:
        path: File to read.

    Returns:
        The exact characters on disk, decoded as UTF-8.
    """
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


@dataclass(frozen=True, slots=True)
class LinkageIssue:
    """One record that could not be attached to a subject, and why.

    ``reason`` is drawn from :class:`~commissura.read.identity.RefusalReason`
    and reaches the manifest, so it is an interface rather than a message.
    ``detail`` is for a terminal only: an unlinked report's detail names the
    identifier it could not match, and that identifier is patient data.

    Attributes:
        path: The corpus file, relative to the corpus root.
        reason: Why the record could not be attached.
        detail: What a human needs in order to go and fix it.
    """

    path: str
    reason: str
    detail: str


@dataclass(frozen=True, slots=True)
class Identity:
    """Who a laboratory message says the patient is.

    The national identifier is what pseudonyms derive from; everything else is
    what has to be removed or replaced on the way into a dataset.
    """

    national_id: str
    mrn: str
    family_name: str
    given_name: str
    sex: Sex | None
    birth_date: date | None

    @property
    def full_name(self) -> str:
        """Return the name as prose would write it."""
        return f"{self.given_name} {self.family_name}".strip()


@dataclass(frozen=True, slots=True)
class Observation:
    """One analyte result read back from an OBX segment."""

    loinc_code: str
    display: str
    value: str
    unit: str
    reference_range: str
    abnormal_flag: str
    observed_at: datetime | None


@dataclass(frozen=True, slots=True)
class LabRecord:
    """One laboratory message, parsed."""

    path: str
    identity: Identity
    accession: str
    panel_code: str
    panel_name: str
    collected_at: datetime | None
    ordering_provider: str
    sending_facility: str
    assigning_authority: str
    observations: tuple[Observation, ...]

    @property
    def scope(self) -> AuthorityScope:
        """Return the institution whose record numbers this message speaks for.

        PID-3 component 4 describes the *identifier*, MSH-4 describes the
        *message*, so the first is preferred where both are present.
        """
        return AuthorityScope(
            assigning_authority=self.assigning_authority,
            sending_facility=self.sending_facility,
        )


@dataclass(frozen=True, slots=True)
class ReportRecord:
    """One free-text report, with the identifiers its header declares.

    ``text`` is the whole document, unmodified. De-identifying it is a later
    step, and it needs the original: a scrubber that received pre-trimmed text
    could not report what it removed.
    """

    path: str
    mrn: str
    national_id: str
    full_name: str
    signed_by: str
    authored_on: date | None
    text: str


@dataclass(frozen=True, slots=True)
class ImagingRecord:
    """One imaging study's metadata, parsed from DICOM JSON.

    ``patient_id`` is the DICOM ``PatientID`` as found, which may disagree with
    the laboratory export's medical record number. That disagreement is the
    point of keeping it verbatim.
    """

    path: str
    patient_id: str
    patient_name: str
    institution_name: str
    institution_address: str
    accession: str
    study_uid: str
    series_uids: tuple[str, ...]
    study_date: date | None
    modality: str
    burned_in_annotation: bool

    @property
    def scope(self) -> AuthorityScope:
        """Return the institution this study came from, for scoping its PatientID.

        ``InstitutionName`` (0008,0080) is the only institutional identifier a
        DICOM header reliably carries, and it is what makes one hospital's
        record number distinguishable from another's. A study that names none
        falls back to the unscoped namespace, where the ambiguity check applies.
        """
        return AuthorityScope(sending_facility=self.institution_name)


@dataclass(slots=True)
class Subject:
    """One person, with everything the three exports say about them.

    **Every identity is kept, not just the first.** A subject assembled from
    several laboratory messages has one identity per message, and they can
    differ: a second institution spells the given name differently, uses its own
    record number, or sends a middle name. The old model kept whichever arrived
    first and discarded the rest, which is what let the audit of 2026-11-13 leak
    a patient's name — targeted redaction removes the identifiers the structured
    exports declared for a subject, so an identity that was discarded is a name
    nothing looks for.

    :attr:`identity` remains the primary one, used where a single value is
    required: the participant row's age and sex. :attr:`identities` is what
    redaction is built from.

    Attributes:
        key: What established this subject, and on whose authority.
        identities: Every identity observed for this subject, first one first.
        labs: Laboratory messages.
        reports: Free-text reports.
        imaging: Imaging metadata.
    """

    key: IdentityKey
    identities: list[Identity]
    labs: list[LabRecord] = field(default_factory=list)
    reports: list[ReportRecord] = field(default_factory=list)
    imaging: list[ImagingRecord] = field(default_factory=list)

    @property
    def identity(self) -> Identity:
        """Return the primary identity: the first one observed for this subject."""
        return self.identities[0]

    def observe(self, identity: Identity) -> bool:
        """Record another identity for this subject.

        Args:
            identity: What a further record said about the same person.

        Returns:
            Whether the new identity materially disagrees with the primary one,
            which the caller reports rather than resolving.
        """
        conflicts = identities_conflict(self.identities[0], identity)
        if identity not in self.identities:
            self.identities.append(identity)
        return conflicts

    @property
    def baseline(self) -> date | None:
        """Return the subject's earliest dated event, which anchors every offset.

        Drawn from whatever is dated across all three exports, so a subject
        whose first contact was an imaging study is anchored there rather than
        at their first blood test. Returns ``None`` only when nothing in the
        subject's records carries a readable date, which makes offsets
        impossible and is a condition the caller has to handle.
        """
        moments: list[date] = []
        moments += [r.collected_at.date() for r in self.labs if r.collected_at]
        moments += [r.authored_on for r in self.reports if r.authored_on]
        moments += [r.study_date for r in self.imaging if r.study_date]
        return min(moments) if moments else None


@dataclass(frozen=True, slots=True)
class RawCorpus:
    """A linked corpus, plus an account of what could not be linked."""

    root: Path
    subjects: tuple[Subject, ...]
    issues: tuple[LinkageIssue, ...]

    @property
    def record_count(self) -> int:
        """Return how many source records were linked to a subject."""
        return sum(len(s.labs) + len(s.reports) + len(s.imaging) for s in self.subjects)


# --------------------------------------------------------------------------
# Per-modality readers
# --------------------------------------------------------------------------


def read_lab(path: Path, relative: str) -> LabRecord:
    """Parse one HL7 laboratory message.

    **Parses, and does not judge the identity.** This used to raise when the
    national identifier was absent, which conflated two different failures: a
    message this reader cannot parse, and a message that parses perfectly and
    says nothing usable about who the patient is. The second is not an
    unreadable message — it is a record whose identity has to be resolved some
    other way or reported, and that decision belongs to
    :class:`~commissura.read.identity.IdentityIndex`. So an unusable national
    identifier now travels in the record and is classified there.

    Raises:
        ValueError: If the message carries no PID segment at all, which is the
            one case where there is nothing to parse.
    """
    message = parse_message(read_exact(path))
    pid = message.require("PID")

    # PID-3 first, PID-19 only as a fallback. PID-19 was deprecated in HL7
    # v2.3.1 and Italian installations carry the codice fiscale in the PID-3
    # identifier list with a type code; the fallback stays because deprecated is
    # not the same as absent and plenty of interfaces still send it there.
    national_id = _identifier_of_type(pid, NATIONAL_ID_TYPE_CODES) or pid.field(19).strip()

    sex_value = pid.field(8).strip().upper()
    identity = Identity(
        national_id=national_id,
        mrn=_identifier_of_type(pid, frozenset({MEDICAL_RECORD_TYPE_CODE}))
        or _untyped_identifier(pid),
        family_name=pid.component(5, 1).strip(),
        given_name=pid.component(5, 2).strip(),
        sex=Sex(sex_value) if sex_value in {"M", "F"} else None,
        birth_date=parse_day(pid.field(7)),
    )

    msh = message.first("MSH")
    obr = message.first("OBR")
    observations = tuple(
        Observation(
            loinc_code=obx.component(3, 1).strip(),
            display=obx.component(3, 2).strip(),
            value=obx.field(5).strip(),
            unit=obx.component(6, 1).strip(),
            reference_range=obx.field(7).strip(),
            abnormal_flag=obx.field(8).strip(),
            observed_at=parse_timestamp(obx.field(14)),
        )
        for obx in message.all("OBX")
    )

    return LabRecord(
        path=relative,
        identity=identity,
        accession=obr.component(2, 1).strip() if obr else "",
        panel_code=obr.component(4, 1).strip() if obr else "",
        panel_name=obr.component(4, 2).strip() if obr else "",
        collected_at=parse_timestamp(obr.field(7)) if obr else None,
        sending_facility=msh.component(4, 1).strip() if msh else "",
        assigning_authority=_assigning_authority(pid),
        ordering_provider=" ".join(
            part for part in (obr.component(16, 2), obr.component(16, 3)) if part
        ).strip()
        if obr
        else "",
        observations=observations,
    )


_REPORT_LABELS: dict[str, str] = {
    "Paziente": "full_name",
    "Codice fiscale": "national_id",
    "Numero nosografico": "mrn",
    "Data del referto": "authored_on",
}
"""Header labels the generated reports use, mapped to the field they carry.

A real corpus would need its own mapping, which is why this is a table rather
than a chain of conditionals: adapting to another hospital's template is an edit
here, not a rewrite of the reader.
"""


def read_report(path: Path, relative: str) -> ReportRecord:
    """Parse one free-text report's labelled header, keeping the body intact."""
    text = read_exact(path)
    found: dict[str, str] = {}
    for line in text.splitlines():
        label, separator, value = line.partition(":")
        if not separator:
            continue
        key = _REPORT_LABELS.get(label.strip())
        if key is not None and key not in found:
            found[key] = value.strip()

    authored = found.get("authored_on", "")
    moment = parse_timestamp(authored) if authored else None

    return ReportRecord(
        path=relative,
        mrn=found.get("mrn", ""),
        national_id=found.get("national_id", ""),
        full_name=found.get("full_name", ""),
        signed_by=_signing_clinician(text),
        authored_on=moment.date() if moment else None,
        text=text,
    )


_SIGNATURE_PATTERN = re.compile(r"^\s*Dott\.?\s+(?P<name>.+?)\s*$", re.MULTILINE)
"""The signature line a report ends with.

Extracting the signer is what closes the last gap targeted redaction left: the
report's author appears in no laboratory message, so until this was read the
only name the scrubber could not reach was the one printed at the bottom of
every document. It is still structure rather than guesswork — the report
declares who signed it, in a fixed position, with a title in front.
"""


def _signing_clinician(text: str) -> str:
    """Return the clinician named in the signature block, or an empty string.

    Takes the last match rather than the first: a report may mention a title
    mid-sentence, and the signature is at the end.
    """
    matches = _SIGNATURE_PATTERN.findall(text)
    return matches[-1].strip() if matches else ""


_TAG_PATIENT_ID = "00100020"
_TAG_PATIENT_NAME = "00100010"
_TAG_ACCESSION = "00080050"
_TAG_INSTITUTION_NAME = "00080080"
_TAG_INSTITUTION_ADDRESS = "00080081"
_TAG_STUDY_UID = "0020000D"
_TAG_SERIES_UID = "0020000E"
_TAG_STUDY_DATE = "00080020"
_TAG_MODALITY = "00080060"
_TAG_BURNED_IN = "00280301"


def _tag_value(series: dict[str, object], tag: str) -> str:
    """Return a DICOM JSON tag's first value as text, or an empty string."""
    entry = series.get(tag)
    if not isinstance(entry, dict):
        return ""
    values = entry.get("Value")
    if not isinstance(values, list) or not values:
        return ""
    first = values[0]
    if isinstance(first, dict):  # PersonName: {"Alphabetic": "FAMILY^GIVEN"}
        alphabetic = first.get("Alphabetic", "")
        return str(alphabetic)
    return str(first)


def read_imaging(path: Path, relative: str) -> ImagingRecord:
    """Parse one DICOM JSON Model metadata sidecar.

    Raises:
        ValueError: If the file is not a non-empty JSON array of series objects.
    """
    payload = json.loads(read_exact(path))
    if not isinstance(payload, list) or not payload:
        raise ValueError("expected a non-empty JSON array of series objects")

    series_objects = [s for s in payload if isinstance(s, dict)]
    if not series_objects:
        raise ValueError("no series objects found")
    first = series_objects[0]

    return ImagingRecord(
        path=relative,
        patient_id=_tag_value(first, _TAG_PATIENT_ID),
        patient_name=_tag_value(first, _TAG_PATIENT_NAME),
        institution_name=_tag_value(first, _TAG_INSTITUTION_NAME),
        institution_address=_tag_value(first, _TAG_INSTITUTION_ADDRESS),
        accession=_tag_value(first, _TAG_ACCESSION),
        study_uid=_tag_value(first, _TAG_STUDY_UID),
        series_uids=tuple(_tag_value(s, _TAG_SERIES_UID) for s in series_objects),
        study_date=parse_day(_tag_value(first, _TAG_STUDY_DATE)),
        modality=_tag_value(first, _TAG_MODALITY),
        burned_in_annotation=_tag_value(first, _TAG_BURNED_IN).upper() == "YES",
    )


# --------------------------------------------------------------------------
# Linkage
# --------------------------------------------------------------------------


def read_corpus(root: Path) -> RawCorpus:
    """Read every export under ``root`` and link the records to subjects.

    Three passes, in an order that is load-bearing. Laboratory messages first,
    because they are the only source carrying a national identifier and
    therefore the only source that may *create* a subject. Then reports, which
    state the national identifier in their header and so prefer it. Then
    imaging, which has no national identifier at all and must resolve on a
    record number scoped to the institution that issued it.

    Every decision goes through :class:`~commissura.read.identity.IdentityIndex`
    and every refusal becomes a :class:`LinkageIssue`. Nothing is resolved by
    guessing, and nothing is merged because two records were equally silent
    about who they belonged to.

    Args:
        root: The corpus root, holding ``lab/``, ``reports/`` and ``imaging/``.

    Returns:
        The linked corpus, with an issue recorded for every record that could
        not be attached and for every identity that could not be trusted.
    """
    root = root.resolve()
    subjects: dict[IdentityKey, Subject] = {}
    index = IdentityIndex()
    issues: list[LinkageIssue] = []

    def refuse(relative: str, refusal: Refusal) -> None:
        issues.append(LinkageIssue(relative, refusal.reason.value, refusal.detail))

    # --- Laboratory first: it is what establishes a subject. ---
    for path in sorted(root.glob(RAW_SOURCES["lab"])):
        relative = path.relative_to(root).as_posix()
        try:
            record = read_lab(path, relative)
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            issues.append(
                LinkageIssue(relative, RefusalReason.UNREADABLE_LAB_MESSAGE.value, str(exc))
            )
            continue

        resolved = index.establish(record.identity, record.scope)
        if isinstance(resolved, Refusal):
            refuse(relative, resolved)
            continue
        key, classified = resolved

        # An unusable national identifier is reported even when the record
        # number rescued the linkage. The subject exists, but it is not
        # relinkable to another institution's export, and whoever reads the
        # manifest has to know which subjects those are.
        if classified.status is not IdentifierStatus.VALID:
            issues.append(
                LinkageIssue(
                    relative,
                    RefusalReason.INVALID_NATIONAL_IDENTIFIER.value,
                    f"the national identifier is {classified.status.value}; this record "
                    f"was attached by its record number within {key.authority}",
                )
            )

        subject = subjects.get(key)
        if subject is None:
            subjects[key] = Subject(key=key, identities=[record.identity])
        elif subject.observe(record.identity):
            issues.append(
                LinkageIssue(
                    relative,
                    RefusalReason.CONFLICTING_IDENTITY.value,
                    "this record shares an identifier with a record naming a different "
                    "person; both identities are kept so that both names are redacted",
                )
            )
        subjects[key].labs.append(record)

    # --- Reports: the national identifier is in the header, so prefer it. ---
    for path in sorted(root.glob(RAW_SOURCES["reports"])):
        relative = path.relative_to(root).as_posix()
        try:
            report = read_report(path, relative)
        except (OSError, UnicodeDecodeError) as exc:
            issues.append(LinkageIssue(relative, RefusalReason.UNREADABLE_REPORT.value, str(exc)))
            continue

        owner_of_report = _resolve_report(report, index, subjects)
        if owner_of_report is None:
            issues.append(
                LinkageIssue(
                    relative,
                    RefusalReason.UNLINKED_REPORT.value,
                    f"no subject for national id {report.national_id!r} "
                    f"or record number {report.mrn!r}",
                )
            )
            continue
        subjects[owner_of_report].reports.append(report)

    # --- Imaging: no national identifier in a DICOM header, so match on a
    # --- record number scoped to the institution that issued it.
    for path in sorted(root.glob(RAW_SOURCES["imaging"])):
        relative = path.relative_to(root).as_posix()
        try:
            study = read_imaging(path, relative)
        except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            issues.append(
                LinkageIssue(relative, RefusalReason.UNREADABLE_IMAGING_METADATA.value, str(exc))
            )
            continue

        owner = index.resolve_record_number(study.patient_id, study.scope)
        if isinstance(owner, Refusal):
            reason = (
                owner.reason
                if owner.reason is RefusalReason.AMBIGUOUS_RECORD_NUMBER
                else RefusalReason.UNLINKED_IMAGING
            )
            issues.append(LinkageIssue(relative, reason.value, owner.detail))
            continue
        subjects[owner].imaging.append(study)

    ordered = tuple(subjects[key] for key in sorted(subjects))
    return RawCorpus(root=root, subjects=ordered, issues=tuple(issues))


def _resolve_report(
    report: ReportRecord,
    index: IdentityIndex,
    subjects: dict[IdentityKey, Subject],
) -> IdentityKey | None:
    """Return the subject a report belongs to, or None if nothing can place it.

    A report header states the national identifier, so that is tried first and
    is subject to the same validation as a laboratory message's: a header
    reading ``Codice fiscale: UNKNOWN`` must not attach the report to whichever
    subject was created from the same placeholder, because under the current
    policy no such subject exists.

    The record-number fallback has no institution to scope by — a report header
    carries no facility — so it resolves in the unscoped namespace, where
    :class:`~commissura.read.identity.IdentityIndex` registered every record
    number alongside its scoped form. A number that two institutions share is
    ambiguous there and resolves to nothing, which is the intended refusal.

    Args:
        report: The parsed report.
        index: The corpus's identity index.
        subjects: Subjects established so far.

    Returns:
        The key, or None.
    """
    classified = classify_national_id(report.national_id)
    if classified.is_usable:
        key = IdentityKey.national(classified.normalised)
        if key in subjects:
            return key
    found = index.resolve_record_number(report.mrn, AuthorityScope())
    if isinstance(found, Refusal) or found not in subjects:
        return None
    return found
