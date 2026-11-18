"""Parse an HL7 Italia CDA R2 laboratory report into format-shaped objects.

**Why this module is the input roadmap and not one more reader.** Every other
format this project reads is a standard: HL7 v2 field positions are HL7's, DICOM
tags are DICOM's, the dataset layout is BIDS, the catalogue description is
HealthDCAT-AP. One part was ours — the labels a free-text report's header uses,
in :data:`commissura.read.corpus._REPORT_LABELS`. A real hospital template
writes something else, every report lands in ``unlinked_report``, and the build
*succeeds* with no reports in the dataset. That is the obstacle recorded in the
brief on 2026-11-13, and template matching is work that never finishes.

In a CDA document the patient's identity is in the structured header, in defined
elements, with the issuing authority stated as an OID. So there is nothing to
guess. This module is the analogue of :mod:`commissura.read.hl7`: it knows CDA
and knows nothing about this project's record shapes, and
:func:`commissura.read.corpus.read_cda` maps what it returns onto the same
``LabRecord`` and ``ReportRecord`` the other readers produce. That is what keeps
``build`` free of a branch per document type, and it is the seam the radiology
report and the discharge letter slot into later.

**What CDA does not do, because it is easy to oversell.** It does not remove the
free text. Chapter 5.1 of the specification is titled "Livello 2: human-readable
body" and requires a ``structuredBody`` whose sections carry the document's
human-readable content, written by a human. So the scrubber, the residual-risk
detector and ``commissura measure`` all stay and all still earn their keep.
What disappears is template guessing, which was the whole of the obstacle.

**Source.** ``Specifiche HL7 CDA R2 del Referto di Medicina di Laboratorio
v.1.3`` (``HL7IT-IG_CDA2_RefertoMedicinaLab-v1.3-S``, © HL7 Italia 2022), linked
from the Ministry's index of national document standards at
https://www.fascicolosanitario.gov.it/portale/standard-documentali. Every rule
cited below was read from that PDF rather than recalled, and the places where it
differs from what this project previously believed are in the decision log entry
of 2026-11-17.

**Two tolerances, both deliberate, both following the reader/writer asymmetry
decided on 2026-11-07.** Observations are found by *descending* from a section
rather than by walking one exact path, because the specification permits a
``BATTERY`` organizer, a ``CLUSTER`` organizer and a direct ``observation``, and
a reader keyed to one nesting would silently drop the others. And a document
that satisfies none of the optional elements still parses: only the absence of a
``patientRole`` is fatal, because that is the one case where there is nothing to
attribute the document to.

**One strictness, and it is about untrusted input rather than about CDA.** See
:func:`parse_clinical_document`.

**A limit worth stating rather than discovering.** The patient's own address and
telephone number are in the header, which does not reach the dataset — only the
narrative does. If a narrative spelled out the patient's street, nothing here
would remove it: the scrubber's address set is built from institutional
addresses. The plain-text reader has exactly the same gap, so this is a standing
limitation of the pipeline and not a regression introduced here.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final

from commissura.read.hl7 import parse_day, parse_timestamp
from commissura.read.identity import (
    PatientIdentifier,
    PatientIdentifierKind,
    classify_patient_identifier,
    kind_from_assigned_code,
)

CDA_NAMESPACE: Final = "urn:hl7-org:v3"
"""The HL7 v3 namespace every CDA element lives in.

Not optional and not negotiable: an element matched without it would match
nothing in a real document, and a document written without it is not CDA.
"""

_NS: Final[dict[str, str]] = {"v3": CDA_NAMESPACE}

CODICE_FISCALE_ROOT: Final = "2.16.840.1.113883.2.9.4.3.2"
"""The OID of the Ministero dell'Economia e delle Finanze: a codice fiscale.

**The specification contradicts itself here, and this constant is the correct
form.** Table 16 of §4.1.12.3 gives this root, and it appears in that form
throughout the document. The worked example printed three lines below that table
writes ``2.16.840.1.113883.2.9.2.4.3.2`` — an extra ``.2`` after ``2.9``. A grep
over the whole specification returns the form above on thirteen lines and the
example's form on exactly one, and a later example writes it correctly, so the
example is the typo.

Do not "fix" this to match the example. A reader written from the example would
match no document written from the table, and the failure would present as "this
hospital sends something non-standard". The typo'd form has its own constant,
:data:`CODICE_FISCALE_ROOT_MISPRINT`, so that a document written from the
example is recognised and reported rather than silently mis-read.
"""

CODICE_FISCALE_ROOT_MISPRINT: Final = "2.16.840.1.113883.2.9.2.4.3.2"
"""The root the specification's own worked example prints, which is wrong.

Always reported, and accepted as a codice fiscale **only when the document
corroborates it**. The reasoning took three passes and the first two were worse,
so it is written out here.

**It is not a harmless misprint.** It falls inside HL7 Italia's regional and
organisation arc ``2.16.840.1.113883.2.9.2.*`` — the same arc the specification
uses for organisation-scoped identifiers, as in
``2.16.840.1.113883.2.9.2.[IdOrganizzazione].4.8``. So it could be some
organisation's real local namespace, and reading it as the national one would
flatten a regional namespace into the national one. That is precisely the error
that forced :mod:`commissura.read.identity` into existence: a key minted on an
unverified namespace merges two people, and a merge corrupts redaction, because
targeted redaction only looks for the identifiers of the subject it knows.

**But refusing it outright splits patients, which running it showed and reading
it did not.** On a generated corpus where some of a patient's documents carry
the misprint and some do not, refusing gave one person two subjects, and the two
then claimed the same numero nosologico — so the ambiguity check correctly
refused that number and the patient's imaging studies attached to nobody. Every
step of that is reported, and it is still a worse answer than necessary: a
six-subject corpus became ten subjects with no imaging.

**The way out is that the document states the authority twice.** An ``id``
element carries both ``@root`` and ``@assigningAuthorityName``, and the
specification fixes the latter to the Ministero dell'Economia e delle Finanze
(see :data:`MEF_AUTHORITY_NAMES`). When a value under this root also names the
MEF *and* classifies as a well-formed codice fiscale, three independent facts
about the element agree on what it is and only the OID's digits disagree. That
is corroboration from the document rather than a decision taken on its behalf,
which is the standard the rest of this pipeline holds itself to.

So: named by the MEF and valid, it is a codice fiscale and the patient links
normally. Otherwise it stays unrecognised and is keyed within this namespace
alone, never merged into the national one. Either way the document produces
:attr:`~commissura.read.identity.RefusalReason.MISDECLARED_IDENTIFIER_NAMESPACE`
naming the correct root, because an export that sends this should be fixed.
"""

MEF_AUTHORITY_NAMES: Final[frozenset[str]] = frozenset(
    {"ministero economia e finanze", "ministero delle finanze", "mef"}
)
"""Every spelling the specification uses for the authority that issues a CF.

Three, in one document. Tabella 16 fixes
``assigningAuthorityName="Ministero Economia e Finanze"`` as the normative
value; the worked examples write ``MEF`` seven times and
``Ministero delle Finanze`` once. So a reader that compared against the
normative string alone would reject the form the specification's own examples
use most, and an implementer following those examples sends ``MEF``.

This matters beyond tolerance, because it is what lets the misprinted root be
resolved from the document rather than from a judgement — see
:data:`CODICE_FISCALE_ROOT_MISPRINT`. Compared folded and case-insensitively;
nothing is inferred beyond these three.
"""

TEAM_CARD_ROOT: Final = "2.16.840.1.113883.2.9.4.3.7"
"""Card number of a European Health Insurance Card issued abroad (Tabella 17)."""

TEAM_PERSONAL_ROOT: Final = "2.16.840.1.113883.2.9.4.3.3"
"""Personal identification number of a TEAM holder (Tabella 18)."""

ENI_NATIONAL_ROOT: Final = "2.16.840.1.113883.2.9.4.3.18"
"""ENI, when the code was assigned nationally (Tabella 19).

Only when assigned nationally. The specification is explicit that a regionally
assigned ENI code carries "l'OID locale assegnato dall'organizzazione che ha
rilasciato il codice identificativo", so this root identifies some ENI codes and
not all of them. The rest are recognised by the prefix their own value must
carry — see :data:`commissura.read.identity.ASSIGNED_CODE_PREFIX`.
"""

STP_NATIONAL_ROOT: Final = "2.16.840.1.113883.2.9.4.3.17"
"""STP, when the code was assigned nationally (Tabella 20). Same caveat as ENI."""

LABORATORY_DOCUMENT_CODE: Final = "11502-2"
"""``ClinicalDocument/code``, obligatory, for a laboratory medicine report."""

RADIOLOGY_DOCUMENT_CODE: Final = "68604-8"
"""``ClinicalDocument/code``, obligatory, for a radiology report.

Read from `Specifiche HL7 CDA R2 del Referto di Radiologia (RAD) v.1.1`
(`HL7IT-IG_CDA2_RAD-v1.1-S`, HL7 Italia 2022) section 4.1.5, which fixes it as
a constant: "DEVE essere presente ed assumere il valore costante 68604-8".

**Not ``18748-4``, which is what recalling it would produce.** That is LOINC's
"Diagnostic imaging study" and is the obvious guess; the profile uses
``68604-8``, "Radiology Imaging study [Impression] (narrative)". The difference
was found by reading the specification rather than by remembering it, which is
the same lesson as `NNITA` on 2026-11-11 and the misprinted codice fiscale root
two entries below.
"""

DISCHARGE_DOCUMENT_CODE: Final = "34105-7"
"""``ClinicalDocument/code``, obligatory, for a hospital discharge letter.

`Specifiche HL7 CDA R2 della Lettera di Dimissione Ospedaliera (LDO) v.1.2`
(`HL7IT-IG_CDA2_LDO-v1.2-S`, HL7 Italia 2022), CONF-LDO-9.
"""

ANA_ROOT: Final = "2.16.840.1.113883.2.9.4.3.15"
"""Anagrafe Nazionale degli Assistiti (Tabella 21).

Fixed, and usable now. The specification's footnote defers "maggiori dettagli
relativi al Codice ANA" to a later release, which is easy to read as deferring
the whole case; the table already states this root as a ``DEVE``. What is
genuinely absent is any rule about the *value*, which is why
:func:`commissura.read.identity.classify_patient_identifier` checks an ANA code
for presence and for not being a placeholder and invents nothing further.
"""

IDENTIFIER_KIND_BY_ROOT: Final[dict[str, PatientIdentifierKind]] = {
    CODICE_FISCALE_ROOT: PatientIdentifierKind.CODICE_FISCALE,
    TEAM_CARD_ROOT: PatientIdentifierKind.TEAM_CARD,
    TEAM_PERSONAL_ROOT: PatientIdentifierKind.TEAM_PERSONAL,
    ENI_NATIONAL_ROOT: PatientIdentifierKind.ENI,
    STP_NATIONAL_ROOT: PatientIdentifierKind.STP,
    ANA_ROOT: PatientIdentifierKind.ANA,
}
"""How CDA spells each kind of patient identifier: the OID in ``id/@root``.

This table is the only CDA-specific part of identity classification, and it is
here rather than in :mod:`commissura.read.identity` on purpose. FHIR expresses
the same five kinds through ``identifier.system`` URIs, so a FHIR reader will
need its own table against the same
:class:`~commissura.read.identity.PatientIdentifierKind` values and the same
structural rules. The kinds are identity policy; the spelling belongs to the
format that spells it.

The misprinted root is deliberately **not** in this table. It is handled apart,
because mapping it here would make it indistinguishable from the correct one.
"""

ADMINISTRATIVE_GENDER_SYSTEM: Final = "2.16.840.1.113883.5.1"
"""The HL7 AdministrativeGender code system, fixed by §4.1.12.3.3."""

LOINC_SYSTEM: Final = "2.16.840.1.113883.6.1"
"""LOINC.

Mandatory for a **specialty** section's ``code`` (§5.1.1.1, "DEVE assumere il
valore costante"). A *leaf* section's code may use a local coding instead
(§5.1.2.1, "è possibile utilizzare sia una codifica locale che la codifica
LOINC"), which is why nothing here requires a leaf code to be LOINC. "CDA
requires LOINC for section/code" is true of one level and not the other.
"""


class CdaParseError(ValueError):
    """A document this reader cannot parse at all.

    A ``ValueError``, so that the corpus reader's existing ``except`` clauses
    treat it the way they treat an unreadable HL7 message or an unparseable
    DICOM sidecar: one linkage issue naming the file, and the rest of the corpus
    still read.
    """


@dataclass(frozen=True, slots=True)
class CdaObservation:
    """One laboratory result, as CDA Level 3 encodes it.

    Attributes:
        code: The analyte's code, normally LOINC.
        code_system: The OID of the system ``code`` is drawn from, so a caller
            can tell a LOINC code from a local one rather than assuming.
        display: The analyte's display name.
        value: The measured value, as text.
        unit: The unit of measure, empty for a non-quantitative result.
        reference_low: Lower reference bound, as text.
        reference_high: Upper reference bound, as text.
        interpretation: The interpretation code, HL7 table 0078 style.
        observed_at: When the observation was made, if stated.
    """

    code: str
    code_system: str
    display: str
    value: str
    unit: str
    reference_low: str
    reference_high: str
    interpretation: str
    observed_at: datetime | None


@dataclass(frozen=True, slots=True)
class CdaSection:
    """One section of the body, with its narrative and its results.

    Attributes:
        code: ``section/code/@code``.
        code_system: ``section/code/@codeSystem``.
        display: ``section/code/@displayName``.
        title: ``section/title``, if the document carries one.
        narrative: The human-readable text of ``section/text``, flattened.
        observations: The Level 3 results found beneath this section.
    """

    code: str
    code_system: str
    display: str
    title: str
    narrative: str
    observations: tuple[CdaObservation, ...]


@dataclass(frozen=True, slots=True)
class CdaDocument:
    """An HL7 Italia CDA R2 laboratory report, parsed.

    Format-shaped rather than project-shaped, exactly as
    :class:`commissura.read.hl7.Message` is: this is what the document says, and
    mapping it onto a ``LabRecord`` and a ``ReportRecord`` is the corpus
    reader's job.

    Attributes:
        document_code: ``ClinicalDocument/code/@code``, obligatory in all three
            profiles, which is how the document says what kind it is. Read
            rather than inferred from the body: a laboratory report that
            happened to carry no results is still a laboratory report, and
            guessing from the sections present would make the answer depend on
            how complete an export was.
        document_id: ``ClinicalDocument/id/@extension``.
        order_id: ``inFulfillmentOf/order/id/@extension``, the request this
            report answers. The nearest thing CDA has to a laboratory accession.
        title: ``ClinicalDocument/title``.
        effective_time: ``ClinicalDocument/effectiveTime``, obligatory, which is
            when the document was created.
        identifiers: Every ``patientRole/id``, classified, in document order.
        misdeclared_codice_fiscale: Whether some ``id`` carried
            :data:`CODICE_FISCALE_ROOT_MISPRINT`.
        family_name: ``patient/name/family``.
        given_name: ``patient/name/given``.
        sex: ``patient/administrativeGenderCode/@code``.
        birth_date: ``patient/birthTime``.
        record_number: ``componentOf/encompassingEncounter/id/@extension``, the
            numero nosologico.
        custodian_name: The organisation responsible for the document.
        author_name: The clinician who created it.
        signed_by: The clinician who legally authenticated it.
        sections: The body's sections, specialty sections first.
    """

    document_code: str
    document_id: str
    order_id: str
    title: str
    effective_time: datetime | None
    identifiers: tuple[PatientIdentifier, ...]
    misdeclared_codice_fiscale: bool
    family_name: str
    given_name: str
    sex: str
    birth_date: date | None
    record_number: str
    custodian_name: str
    author_name: str
    signed_by: str
    sections: tuple[CdaSection, ...]

    @property
    def codice_fiscale(self) -> str:
        """Return the codice fiscale this document declared, or an empty string.

        Only from :data:`CODICE_FISCALE_ROOT`. A value under the misprinted root
        is deliberately not returned here, so that it cannot become a national
        identity key; ``misdeclared_codice_fiscale`` is how a caller learns it
        was there.
        """
        for identifier in self.identifiers:
            if identifier.kind is PatientIdentifierKind.CODICE_FISCALE:
                return identifier.raw
        return ""

    @property
    def narrative(self) -> str:
        """Return the document's human-readable text, sections in order.

        **The offsets of this string are its own and are not offsets into the
        file.** Flattening markup has to insert separators that are not in the
        document, so a position here does not index the XML. Nothing downstream
        mixes the two: the ground-truth annotations index the file on disk, the
        scrubber reports categories and counts rather than positions, and
        ``commissura measure`` matches strings rather than offsets. Stated here
        because the opposite is the natural assumption.
        """
        blocks: list[str] = []
        for section in self.sections:
            heading = section.title or section.display
            if heading:
                blocks.append(heading)
            if section.narrative:
                blocks.append(section.narrative)
        return "\n\n".join(blocks)

    @property
    def observations(self) -> tuple[CdaObservation, ...]:
        """Return every result in the document, across all its sections."""
        return tuple(
            observation for section in self.sections for observation in section.observations
        )

    @property
    def specialty(self) -> CdaSection | None:
        """Return the first specialty section, which names what was examined."""
        return self.sections[0] if self.sections else None


def _text(element: ElementTree.Element | None) -> str:
    """Return an element's text content, collapsed, or an empty string."""
    if element is None:
        return ""
    return _collapse(" ".join(element.itertext()))


def _collapse(value: str) -> str:
    """Return a string with runs of whitespace reduced to single spaces."""
    return re.sub(r"\s+", " ", value).strip()


def _attribute(element: ElementTree.Element | None, name: str) -> str:
    """Return an attribute of an element that may be absent, or an empty string."""
    if element is None:
        return ""
    return (element.get(name) or "").strip()


_NARRATIVE_BLOCK_BREAK: Final[frozenset[str]] = frozenset(
    {"paragraph", "td", "th", "tr", "item", "caption", "title", "list", "table", "br"}
)
"""Narrative-block elements after which the flattened text needs a break.

The CDA Narrative Block is its own small markup language, defined by
``NarrativeBlock.xsd`` rather than by XHTML, and a reader that joined its text
nodes without separators would run the end of one table cell into the start of
the next. That matters beyond readability: two values joined into one token are
a token no exact-match redaction can find, so the separator is a correctness
property of the scrubbing that follows and not a cosmetic one.
"""


def _flatten_narrative(element: ElementTree.Element) -> str:
    """Return the readable text of a narrative block, structure as line breaks.

    Args:
        element: A ``section/text`` element.

    **Iterative, and that is about untrusted input rather than about style.** The
    obvious version of this walker recurses once per nesting level, and a
    narrative nested deeper than the interpreter's recursion limit — a thousand
    levels, by default — then raises ``RecursionError``. That is not a
    ``ValueError``, so it is caught by neither
    :func:`commissura.read.corpus.read_cda` nor
    :func:`commissura.build.observe.observe_corpus`, both of which catch
    ``ValueError`` precisely so that :class:`CdaParseError` behaves like any
    other unreadable file: one issue naming it, and the rest of the corpus still
    read. A recursive walker therefore let one pathological document kill a whole
    build with a traceback, which is the one thing the refusal design exists to
    prevent. Found by attacking this function rather than by reading it: at depth
    5000 it raised, uncaught, while three genuinely hostile documents in the same
    corpus were reported correctly.

    An explicit stack removes the limit instead of handling the error, so there
    is no new failure mode to report and no except clause whose branch nothing
    reaches. The closing marker is what preserves the order: a block break and a
    tail belong *after* that element's children, which recursion got for free.

    Returns:
        The text, with a newline wherever the markup implied one and runs of
        blank lines collapsed.
    """
    pieces: list[str] = []
    stack: list[tuple[ElementTree.Element, bool]] = [(element, False)]

    while stack:
        node, closing = stack.pop()
        if closing:
            if node.tag.rsplit("}", 1)[-1] in _NARRATIVE_BLOCK_BREAK:
                pieces.append("\n")
            if node.tail:
                pieces.append(node.tail)
            continue
        if node.text:
            pieces.append(node.text)
        stack.append((node, True))
        stack.extend((child, False) for child in reversed(node))

    joined = "".join(pieces)
    lines = [_collapse(line) for line in joined.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _classify_identifiers(
    patient_role: ElementTree.Element,
) -> tuple[tuple[PatientIdentifier, ...], bool]:
    """Classify every ``patientRole/id``, and report a misdeclared namespace.

    Three ways a kind is decided, in this order, and the order is the whole
    policy. A known root names the kind outright. The misprinted codice fiscale
    root is reported always, and read as a codice fiscale only where the
    element's own ``@assigningAuthorityName`` corroborates it — the reasoning is
    on :data:`CODICE_FISCALE_ROOT_MISPRINT` and is the part of this module most
    worth reading before changing it. Otherwise the value's own prefix is
    consulted, which is what makes a regionally assigned ENI or STP code usable
    at all: the specification fixes the prefix in the same table where it leaves
    the root open.

    Args:
        patient_role: The ``recordTarget/patientRole`` element.

    Returns:
        The classified identifiers in document order, and whether any of them
        declared the codice fiscale under the misprinted root.
    """
    identifiers: list[PatientIdentifier] = []
    misdeclared = False
    for element in patient_role.findall("v3:id", _NS):
        root = _attribute(element, "root")
        extension = _attribute(element, "extension")
        if not extension:
            continue
        if root == CODICE_FISCALE_ROOT_MISPRINT:
            misdeclared = True
            authority_name = _attribute(element, "assigningAuthorityName").casefold()
            kind = (
                PatientIdentifierKind.CODICE_FISCALE
                if authority_name in MEF_AUTHORITY_NAMES
                else PatientIdentifierKind.UNRECOGNISED
            )
        else:
            kind = (
                IDENTIFIER_KIND_BY_ROOT.get(root)
                or kind_from_assigned_code(extension)
                or PatientIdentifierKind.UNRECOGNISED
            )
        identifiers.append(classify_patient_identifier(kind, root, extension))
    return tuple(identifiers), misdeclared


def _person_name(element: ElementTree.Element | None) -> str:
    """Return a ``name`` element's given and family parts, in that order.

    Written ``given family``, which is how Italian clinical prose writes a name
    and therefore the form most likely to appear in the narrative this value is
    used to scrub. Unlike a free-text report's header, CDA states the two parts
    separately and both are obligatory, so nothing here has to guess which is
    which — the guess the plain-text reader cannot avoid.
    """
    if element is None:
        return ""
    name = element.find("v3:name", _NS)
    if name is None:
        return ""
    given = " ".join(_text(part) for part in name.findall("v3:given", _NS))
    family = " ".join(_text(part) for part in name.findall("v3:family", _NS))
    return _collapse(f"{given} {family}")


def _observation(element: ElementTree.Element) -> CdaObservation | None:
    """Read one ``observation`` element, or return None if it carries no result.

    Args:
        element: An ``observation`` element.

    Returns:
        The observation, or ``None`` when it has no code or no value — a
        narrative-only or structural observation, which is not a result.
    """
    code = element.find("v3:code", _NS)
    value = element.find("v3:value", _NS)
    if code is None or value is None:
        return None

    # A result is a physical quantity (@value plus @unit), a coded value
    # (@code), or free text. Taking them in that order means a quantity is read
    # as a number rather than as the text of an empty element.
    measured = _attribute(value, "value") or _attribute(value, "code") or _text(value)
    if not measured:
        return None

    low = high = ""
    reference = element.find("v3:referenceRange/v3:observationRange/v3:value", _NS)
    if reference is not None:
        low = _attribute(reference.find("v3:low", _NS), "value")
        high = _attribute(reference.find("v3:high", _NS), "value")

    return CdaObservation(
        code=_attribute(code, "code"),
        code_system=_attribute(code, "codeSystem"),
        display=_attribute(code, "displayName") or _text(code.find("v3:originalText", _NS)),
        value=measured,
        unit=_attribute(value, "unit"),
        reference_low=low,
        reference_high=high,
        interpretation=_attribute(element.find("v3:interpretationCode", _NS), "code"),
        observed_at=parse_timestamp(_attribute(element.find("v3:effectiveTime", _NS), "value")),
    )


def _section(element: ElementTree.Element, *, with_results: bool) -> CdaSection:
    """Read one ``section`` element, with the results anywhere beneath it.

    Results are gathered by descent rather than along one exact path. The
    specification allows a leaf section's single ``entry/act`` to nest its
    observations under a ``BATTERY`` organizer, under a ``CLUSTER`` organizer,
    or directly, and permits ``entryRelationship`` chains between them. A reader
    that walked one of those shapes would silently return nothing for a document
    using another, which is the failure mode this project has learned to fear:
    not an error, just an empty result that reads like clean data.

    Args:
        element: The ``section`` element.
        with_results: False for a specialty section that holds leaf sections.
            Descent would otherwise reach its leaves' observations and report
            every result twice, once here and once on the leaf that owns it.
    """
    code = element.find("v3:code", _NS)
    narrative_element = element.find("v3:text", _NS)
    found = (
        (_observation(node) for node in element.iter(f"{{{CDA_NAMESPACE}}}observation"))
        if with_results
        else ()
    )
    return CdaSection(
        code=_attribute(code, "code"),
        code_system=_attribute(code, "codeSystem"),
        display=_attribute(code, "displayName"),
        title=_text(element.find("v3:title", _NS)),
        narrative=_flatten_narrative(narrative_element) if narrative_element is not None else "",
        observations=tuple(item for item in found if item is not None),
    )


def _sections(root: ElementTree.Element) -> tuple[CdaSection, ...]:
    """Return the body's sections, each specialty section followed by its leaves.

    **The two-level hierarchy is why this is not one findall.** §5.1 allows at
    most two levels, and §5.1.1.3 makes them exclusive: a specialty section that
    holds leaf sections MUST NOT carry ``section/text``, and one that holds none
    MUST carry a non-empty ``section/text``. So the human-readable content of a
    document with leaves lives entirely on the leaves, and reading only the top
    level — which is what the obvious ``findall`` does — would return a document
    whose narrative is empty. Empty narrative on a document that has one is the
    worst available outcome here: the scrubber would report nothing to remove
    and the build would succeed.

    Flattened into one sequence rather than nested, because every consumer wants
    either the headings in order or all the results, and neither needs the tree.
    """
    found: list[CdaSection] = []
    for specialty in root.findall("v3:component/v3:structuredBody/v3:component/v3:section", _NS):
        leaves = specialty.findall("v3:component/v3:section", _NS)
        found.append(_section(specialty, with_results=not leaves))
        found.extend(_section(leaf, with_results=True) for leaf in leaves)
    return tuple(found)


def _declares_a_doctype(text: str) -> bool:
    """Return whether the document's prolog declares a document type.

    Scans only the prolog, understanding the three things that may legally
    precede the root element — a processing instruction, a comment, and the
    doctype declaration itself. A plain substring search over the whole document
    would also match ``<!DOCTYPE`` written inside a comment or a CDATA section
    in the narrative and refuse a perfectly good report.

    An unterminated comment or processing instruction returns ``False`` and
    leaves the refusal to the parser, which will reject the document anyway with
    a better message than this function could produce.
    """
    index = 0
    while (start := text.find("<", index)) >= 0:
        if text.startswith("<!DOCTYPE", start):
            return True
        if text.startswith("<!--", start):
            end = text.find("-->", start + 4)
        elif text.startswith("<?", start):
            end = text.find("?>", start + 2)
        else:
            return False  # The root element starts here; the prolog is over.
        if end < 0:
            return False
        index = end + 2
    return False


def parse_document_tree(text: str) -> ElementTree.Element:
    """Parse a CDA document's XML, refusing what must not be parsed.

    Separate from :func:`parse_clinical_document` because two callers need the
    tree and only one of them wants the laboratory report's meaning:
    :mod:`commissura.build.observe` walks the same document to account for every
    element it carried, including elements this reader does not understand, and
    it must do that behind the same refusal rather than reaching for
    ``ElementTree`` itself. Two parse sites with one safety rule between them is
    one parse site too many.

    **On untrusted input, checked rather than recalled.** This is other people's
    XML, so the two classic attacks were tried against
    :mod:`xml.etree.ElementTree` on this interpreter before anything was written.
    External entities are *refused*: an ``<!ENTITY ext SYSTEM "file:///...">``
    reference raises ``ParseError: undefined entity``, so there is no file
    disclosure and no network retrieval. Internal entity expansion is *not*
    refused: a billion-laughs document expands, which is a denial of service on
    a tool somebody points at a directory of hospital exports.

    So a document whose prolog declares a document type is refused outright.
    That closes both entity-expansion attacks at the source without a
    dependency — ``defusedxml`` would be the obvious alternative and
    ``pip install commissura`` has to stay light — and it costs nothing real:
    CDA R2 is defined by an XML Schema, the specification's examples carry no
    doctype, and a DTD in a clinical document has no legitimate purpose. This is
    the one place this reader is strict rather than tolerant, and the reason is
    not CDA but the fact that refusing service is not a defect a hospital can
    stop sending.

    Args:
        text: The document's exact characters.

    Returns:
        The root element.

    Raises:
        CdaParseError: If the text declares a document type or is not
            well-formed XML.
    """
    if _declares_a_doctype(text):
        raise CdaParseError(
            "the document declares a DTD, which CDA R2 does not use and which "
            "this reader refuses because entity expansion is a denial of service"
        )
    try:
        return ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise CdaParseError(f"not well-formed XML: {exc}") from exc


def parse_clinical_document(text: str) -> CdaDocument:
    """Parse a CDA R2 laboratory report.

    **On untrusted input, checked rather than recalled.** This is other people's
    XML, so the two classic attacks were tried against
    :mod:`xml.etree.ElementTree` on this interpreter before anything was written.
    External entities are *refused*: an ``<!ENTITY ext SYSTEM "file:///...">``
    reference raises ``ParseError: undefined entity``, so there is no file
    disclosure and no network retrieval. Internal entity expansion is *not*
    refused: a billion-laughs document expands, which is a denial of service on
    a tool somebody points at a directory of hospital exports.

    So a document whose prolog declares a document type is refused outright.
    That closes both entity-expansion attacks at the source without a
    dependency — ``defusedxml`` would be the obvious alternative and
    ``pip install commissura`` has to stay light — and it costs nothing real:
    CDA R2 is defined by an XML Schema, the specification's examples carry no
    doctype, and a DTD in a clinical document has no legitimate purpose. This is
    the one place this reader is strict rather than tolerant, and the reason is
    not CDA but the fact that refusing service is not a defect a hospital can
    stop sending.

    Args:
        text: The document's exact characters, as read without newline
            translation.

    Returns:
        The parsed document.

    Raises:
        CdaParseError: If the text is not well-formed XML, is not a
            ``ClinicalDocument``, declares a document type, or carries no
            ``recordTarget/patientRole`` — the one element whose absence leaves
            nothing to attribute the document to.
    """
    root = parse_document_tree(text)

    if root.tag != f"{{{CDA_NAMESPACE}}}ClinicalDocument":
        raise CdaParseError(
            f"expected a ClinicalDocument in the {CDA_NAMESPACE} namespace, got {root.tag!r}"
        )

    patient_role = root.find("v3:recordTarget/v3:patientRole", _NS)
    if patient_role is None:
        raise CdaParseError(
            "no recordTarget/patientRole, which the specification makes mandatory "
            "at exactly one, so there is nothing to attribute this document to"
        )

    identifiers, misdeclared = _classify_identifiers(patient_role)
    patient = patient_role.find("v3:patient", _NS)
    name = patient.find("v3:name", _NS) if patient is not None else None

    return CdaDocument(
        document_code=_attribute(root.find("v3:code", _NS), "code"),
        document_id=_attribute(root.find("v3:id", _NS), "extension"),
        order_id=_attribute(root.find("v3:inFulfillmentOf/v3:order/v3:id", _NS), "extension"),
        title=_text(root.find("v3:title", _NS)),
        effective_time=parse_timestamp(_attribute(root.find("v3:effectiveTime", _NS), "value")),
        identifiers=identifiers,
        misdeclared_codice_fiscale=misdeclared,
        family_name=" ".join(_text(part) for part in name.findall("v3:family", _NS))
        if name is not None
        else "",
        given_name=" ".join(_text(part) for part in name.findall("v3:given", _NS))
        if name is not None
        else "",
        sex=_attribute(
            patient.find("v3:administrativeGenderCode", _NS) if patient is not None else None,
            "code",
        ).upper(),
        birth_date=parse_day(
            _attribute(patient.find("v3:birthTime", _NS) if patient is not None else None, "value")
        ),
        record_number=_attribute(
            root.find("v3:componentOf/v3:encompassingEncounter/v3:id", _NS), "extension"
        ),
        custodian_name=_text(
            root.find(
                "v3:custodian/v3:assignedCustodian/v3:representedCustodianOrganization/v3:name",
                _NS,
            )
        ),
        author_name=_person_name(root.find("v3:author/v3:assignedAuthor/v3:assignedPerson", _NS)),
        signed_by=_person_name(
            root.find("v3:legalAuthenticator/v3:assignedEntity/v3:assignedPerson", _NS)
        ),
        sections=_sections(root),
    )
