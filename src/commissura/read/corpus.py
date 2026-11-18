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
from commissura.read.cda import (
    CODICE_FISCALE_ROOT,
    CODICE_FISCALE_ROOT_MISPRINT,
    LABORATORY_DOCUMENT_CODE,
    CdaParseError,
    parse_clinical_document,
)
from commissura.read.hl7 import Segment, parse_day, parse_message, parse_timestamp
from commissura.read.identity import (
    AuthorityScope,
    IdentifierStatus,
    IdentityIndex,
    IdentityKey,
    KeyKind,
    PatientIdentifier,
    Refusal,
    RefusalReason,
    classify_national_id,
    identities_conflict,
    report_name_conflicts,
)

RAW_SOURCES: Final[dict[str, str]] = {
    "lab": "lab/*.hl7",
    "cda": "cda/*.xml",
    "reports": "reports/*.txt",
    "imaging": "imaging/*.json",
}
"""Where each modality's export lives in a raw corpus, relative to its root.

Laboratory first, because a laboratory message is what creates a subject and
the other two can only attach to one that exists. The dictionary order carries
that, and :func:`read_corpus` depends on it.

**``cda`` is second because it also creates subjects**, and it is a source
rather than a modality: one HL7 Italia CDA R2 laboratory report is both a set of
structured results and a human-readable document, so it yields a laboratory
record *and* a report record from the same file. A holder may hand over either
form or both — a site part-way through migrating to the Fascicolo Sanitario
Elettronico has both — and nothing here requires a corpus to carry any
particular subset of the four.

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


DATE_FIELD_OBR_7: Final = "OBR-7 collection time"
"""Where an HL7 laboratory message states the time its specimen was collected.

Carried on the record rather than written at the point a date turns out to be
missing, because that message tells an operator which field of which document to
go and look at — and the answer is different for a CDA document, which has no
OBR segment at all. A hardcoded field name is a true sentence about one input
format printed over every other.
"""

DATE_FIELD_REPORT_HEADER: Final = "the 'Data del referto' header"
"""Where a plain-text report states its date, in this project's own template."""

DATE_FIELD_CDA_EFFECTIVE_TIME: Final = "ClinicalDocument/effectiveTime"
"""Where a CDA document states when it was created.

Obligatory in the specification and precise at least to the second, so a CDA
document with no readable date here is a malformed document rather than an
ordinary gap.
"""


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
    date_field: str = DATE_FIELD_OBR_7

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

    **Two clinician names and not one, which a plain-text report did not need.**
    A free-text report reveals its author only through the signature line, so
    ``signed_by`` was the whole of what there was to know. A CDA document
    declares both: ``author/assignedAuthor`` is obligatory and so is
    ``legalAuthenticator``, and the two are routinely different people -- the
    radiologist who dictated the report and the one who signed it off.
    ``author_name`` exists because leaving it unread threw away a declared
    identifier and produced a half-redaction: ``Refertazione a cura del dott.
    GALLO [PROVIDER]``, where the given name matched some other clinician's and
    the surname, declared in this document's own header, did not.
    """

    path: str
    mrn: str
    national_id: str
    full_name: str
    signed_by: str
    authored_on: date | None
    text: str
    author_name: str = ""
    date_field: str = DATE_FIELD_REPORT_HEADER

    def declared(self) -> DeclaredIdentity:
        """Return what this report's header says about who it is about."""
        return DeclaredIdentity(
            full_name=self.full_name,
            national_id=self.national_id,
            mrn=self.mrn,
        )


@dataclass(frozen=True, slots=True)
class DeclaredIdentity:
    """What a free-text report's header says about who the document is about.

    Separate from :class:`Identity`, and the difference is the point. A
    laboratory message states the family name and the given name in their own
    PID-5 components, so :class:`Identity` can hold them apart. A report writes
    one line — ``Paziente: GIOVANNA ESPOSITO`` — and whether that is
    *given family* or *family given* depends on the template. **The name is
    therefore carried as one opaque string and never split**, because splitting
    it would be a guess, and a guess here would put a surname in the given-name
    field of the document an auditor reads.

    This exists because what a report declared never reached redaction. Only
    laboratory messages produced an :class:`Identity`, so a report whose header
    named a different person — a mis-filed document, which happens in any real
    export — had that name published in the dataset. The subject's *own* name
    was removed correctly, which is what made it hard to see.

    Attributes:
        full_name: The name as the header wrote it, unsplit.
        national_id: The national identifier the header declared.
        mrn: The record number the header declared.
    """

    full_name: str
    national_id: str
    mrn: str

    def words(self) -> frozenset[str]:
        """Return the redactable words of the declared name.

        The whole string and its words both have to go: a header writes
        ``GIOVANNA ESPOSITO`` while the prose below it writes just
        ``ESPOSITO``, and replacing only the whole string leaves the second
        one. The same treatment institution names already get.

        Returns:
            The words of length four or more. Shorter ones are left to the
            scrubber, which refuses to replace below that length anyway — a
            two-letter particle like ``DE`` matches inside ordinary words.
        """
        return frozenset(word for word in self.full_name.split() if len(word) >= 4)


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


@dataclass(frozen=True, slots=True)
class CdaRecords:
    """What one CDA R2 laboratory report yields: two records from one file.

    **Two records and not one, because the document genuinely is two things.**
    A CDA laboratory report carries LOINC-coded results in its Level 3 entries
    and a human-written narrative in its Level 2 sections, and this project
    already has a shape for each. Mapping it onto both means ``build`` needs no
    branch for a new document type: the results go down the laboratory branch
    and the narrative down the scrubbing branch, exactly as they do for a
    hospital that sends HL7 messages and text files separately.

    Both records carry the same corpus-relative path. That is correct rather
    than a collision — one input file contributing two records — and it is what
    lets the manifest say that a CDA document was read once while two records
    came out of it.

    Attributes:
        identity: Who the document is about, read from its header. Held here
            rather than reached for through ``lab``, because a radiology report
            and a discharge letter have no structured results and so no
            laboratory record to reach through -- and identity resolution needs
            it for every document type.
        scope: The institution whose record numbers this document speaks for,
            for the same reason.
        lab: The structured results, or ``None`` for a document type that has
            none. A radiology report and a discharge letter are narrative:
            giving them an empty laboratory record would write an empty table
            into the dataset and claim the modality carried something.
        report: The narrative, as a report record, or ``None`` when the
            document carried no human-readable text at all.
        identifiers: Every classified ``patientRole/id``, so that identity
            resolution can consider the ones that are not a codice fiscale.
        misdeclared_codice_fiscale: Whether the document declared its codice
            fiscale under the root the specification's own example misprints.
    """

    identity: Identity
    scope: AuthorityScope
    lab: LabRecord | None
    report: ReportRecord | None
    identifiers: tuple[PatientIdentifier, ...]
    misdeclared_codice_fiscale: bool


def read_cda(path: Path, relative: str) -> CdaRecords:
    """Parse one CDA R2 laboratory report into the records this pipeline reads.

    **The scope a record number is read in is the custodian's name, not the
    encounter identifier's OID**, and that choice is the one worth defending.
    ``componentOf/encompassingEncounter/id`` carries the numero nosologico and
    its ``@root`` would be a far better identifier for the issuing authority
    than any name — but the other two modalities do not have it. HL7 states the
    authority as a facility name in MSH-4 and DICOM as ``InstitutionName``, and
    a record number is only comparable across modalities if all three name the
    authority the same way. Scoping by the OID would make every CDA-established
    subject invisible to its own imaging studies, silently, with every count
    still looking right.

    Raises:
        commissura.read.cda.CdaParseError: If the document cannot be parsed or
            carries no ``patientRole``.
    """
    document = parse_clinical_document(read_exact(path))
    specialty = document.specialty

    sex = document.sex
    identity = Identity(
        national_id=document.codice_fiscale,
        mrn=document.record_number,
        family_name=document.family_name,
        given_name=document.given_name,
        sex=Sex(sex) if sex in {"M", "F"} else None,
        birth_date=document.birth_date,
    )

    # A laboratory record only for a laboratory report, decided by what the
    # document declares about itself rather than by whether it happens to carry
    # observations. A laboratory report with no results is still one, and an
    # export that was truncated should not change what kind of document it is.
    lab = (
        LabRecord(
            path=relative,
            identity=identity,
            accession=document.order_id or document.document_id,
            panel_code=specialty.code if specialty else "",
            panel_name=specialty.display or specialty.title if specialty else "",
            collected_at=document.effective_time,
            ordering_provider=document.author_name,
            sending_facility=document.custodian_name,
            # Deliberately empty: see this function's docstring. The custodian's
            # name reaches the scope through ``sending_facility``.
            assigning_authority="",
            observations=tuple(
                Observation(
                    loinc_code=item.code,
                    display=item.display,
                    value=item.value,
                    unit=item.unit,
                    reference_range=f"{item.reference_low}-{item.reference_high}"
                    if item.reference_low and item.reference_high
                    else "",
                    abnormal_flag=item.interpretation,
                    observed_at=item.observed_at,
                )
                for item in document.observations
            ),
            date_field=DATE_FIELD_CDA_EFFECTIVE_TIME,
        )
        if document.document_code == LABORATORY_DOCUMENT_CODE
        else None
    )

    narrative = document.narrative
    report = (
        ReportRecord(
            path=relative,
            mrn=document.record_number,
            national_id=document.codice_fiscale,
            full_name=identity.full_name,
            signed_by=document.signed_by,
            author_name=document.author_name,
            authored_on=document.effective_time.date() if document.effective_time else None,
            text=narrative,
            date_field=DATE_FIELD_CDA_EFFECTIVE_TIME,
        )
        if narrative
        else None
    )

    return CdaRecords(
        identity=identity,
        scope=AuthorityScope(sending_facility=document.custodian_name),
        lab=lab,
        report=report,
        identifiers=document.identifiers,
        misdeclared_codice_fiscale=document.misdeclared_codice_fiscale,
    )


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


_CONFLICTING_IDENTITY: Final[tuple[str, str]] = (
    RefusalReason.CONFLICTING_IDENTITY.value,
    "this record shares an identifier with a record naming a different "
    "person; both identities are kept so that both names are redacted",
)
"""The reason and detail for a record whose identity disagrees with a sibling's.

A constant because two sources can now establish a subject — an HL7 message and
a CDA document — and the sentence an auditor reads must not depend on which one
found the disagreement. The condition is the same condition.
"""


def _attach(subjects: dict[IdentityKey, Subject], key: IdentityKey, identity: Identity) -> bool:
    """Create the subject this key names, or add another identity to it.

    Args:
        subjects: Subjects established so far, mutated in place.
        key: What established this subject.
        identity: What the record said about the person.

    Returns:
        Whether the new identity materially disagrees with the subject's
        primary one, which the caller reports rather than resolving.
    """
    subject = subjects.get(key)
    if subject is None:
        subjects[key] = Subject(key=key, identities=[identity])
        return False
    return subject.observe(identity)


def read_corpus(root: Path) -> RawCorpus:
    """Read every export under ``root`` and link the records to subjects.

    Four passes, in an order that is load-bearing. The two sources that carry a
    national identifier go first, because they are the only ones that may
    *create* a subject: HL7 laboratory messages, then CDA R2 laboratory
    reports, which state identity in a defined header element and so also
    contribute their own narrative directly. Then plain-text reports, which
    state the national identifier in their header and so prefer it. Then
    imaging, which has no national identifier at all and must resolve on a
    record number scoped to the institution that issued it.

    Every decision goes through :class:`~commissura.read.identity.IdentityIndex`
    and every refusal becomes a :class:`LinkageIssue`. Nothing is resolved by
    guessing, and nothing is merged because two records were equally silent
    about who they belonged to.

    Args:
        root: The corpus root, holding any of ``lab/``, ``cda/``, ``reports/``
            and ``imaging/``. None of them is required: a holder hands over
            what they have, and a directory that is absent contributes nothing
            rather than failing.

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

        if _attach(subjects, key, record.identity):
            issues.append(LinkageIssue(relative, *_CONFLICTING_IDENTITY))
        subjects[key].labs.append(record)

    # --- CDA: one document, two records, and it establishes subjects too. ---
    #
    # Processed here rather than with the reports, because a CDA laboratory
    # report carries a national identifier in a defined element and may
    # therefore *create* a subject. Its narrative attaches directly to the key
    # that the same document established: going back through `_resolve_report`
    # would re-derive an answer this document already gave, and would fail for
    # a patient keyed on an ENI code or a record number, whose narrative would
    # then be dropped from a dataset built out of its own structured half.
    for path in sorted(root.glob(RAW_SOURCES["cda"])):
        relative = path.relative_to(root).as_posix()
        try:
            records = read_cda(path, relative)
        except (OSError, CdaParseError, UnicodeDecodeError) as exc:
            issues.append(
                LinkageIssue(relative, RefusalReason.UNREADABLE_CDA_DOCUMENT.value, str(exc))
            )
            continue

        if records.misdeclared_codice_fiscale:
            issues.append(
                LinkageIssue(
                    relative,
                    RefusalReason.MISDECLARED_IDENTIFIER_NAMESPACE.value,
                    "this document declares a codice fiscale under "
                    f"{CODICE_FISCALE_ROOT_MISPRINT}, which is the root the "
                    "specification's own worked example misprints; the correct root is "
                    f"{CODICE_FISCALE_ROOT}. Fix the export: that OID lies in the "
                    "regional and organisation arc, so it is only read as a codice "
                    "fiscale where the same element names the Ministero dell'Economia "
                    "e delle Finanze as its assigning authority",
                )
            )

        resolved = index.establish(records.identity, records.scope, assigned=records.identifiers)
        if isinstance(resolved, Refusal):
            refuse(relative, resolved)
            continue
        key, classified = resolved

        # Reported only when nothing identified the *person*. An ENI, STP, TEAM
        # or ANA code is a legitimate identity for a patient who has no codice
        # fiscale, and reporting it as an invalid national identifier would
        # file a whole class of lawful patients as a data-quality problem.
        # `source.subject_keys` is where the kind of key is accounted for.
        if key.kind is KeyKind.SCOPED_RECORD_NUMBER:
            issues.append(
                LinkageIssue(
                    relative,
                    RefusalReason.INVALID_NATIONAL_IDENTIFIER.value,
                    f"the national identifier is {classified.status.value} and no other "
                    "declared identifier could key a person; this document was attached "
                    f"by its record number within {key.authority}",
                )
            )

        if _attach(subjects, key, records.identity):
            issues.append(LinkageIssue(relative, *_CONFLICTING_IDENTITY))
        # Only a laboratory report has results. A radiology report or a
        # discharge letter contributes its narrative and nothing else.
        if records.lab is not None:
            subjects[key].labs.append(records.lab)
        if records.report is not None:
            subjects[key].reports.append(records.report)

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
        subject_for_report = subjects[owner_of_report]
        if report.full_name and report_name_conflicts(
            report.full_name, [identity.full_name for identity in subject_for_report.identities]
        ):
            issues.append(
                LinkageIssue(
                    relative,
                    RefusalReason.CONFLICTING_REPORT_NAME.value,
                    f"this report's header names {report.full_name!r}, which shares no "
                    "name with the subject its identifiers resolve to. The document may "
                    "belong to somebody else; the name is redacted either way",
                )
            )
        subject_for_report.reports.append(report)

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
