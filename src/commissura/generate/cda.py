"""Render a laboratory panel as an HL7 Italia CDA R2 document.

The counterpart of :mod:`commissura.generate.labs`, which renders the same facts
as an HL7 v2 ORU^R01 message. Both read a
:class:`~commissura.models.LabPanel` and neither knows anything about the other,
so a corpus can carry one form, the other, or both — which is the state a site
part-way through migrating to the Fascicolo Sanitario Elettronico is actually
in.

**Why generating these matters more than hand-building a fixture.** This project
has now found three times that a path no corpus exercises is not covered
whatever the coverage percentage says: the institution address hiding behind a
cohort size, the linkage-issue shape that was wrong from the day it was written,
and the identity quarantine that only unit tests ever reached. A reader whose
only input is a hand-written string in a test is a reader nobody has measured.
With this module, ``commissura measure`` scores the CDA path against
ground-truth annotations exactly as it scores the other three.

**Identifiers are written through :class:`~commissura.annotate.Phi`**, so the
recorded spans are exact positions in the XML file rather than search results.
That is what lets ``verify_corpus`` re-read the document from disk and confirm
every span still quotes the characters it claims.

**Reserved characters are refused, not escaped**, which is the decision of
2026-11-06 applied to a third format. Escaping would rewrite characters after
their PHI offsets had been recorded, which silently corrupts every measurement
built on the corpus. See :func:`_literal`.

What this module does **not** do: produce an ENI, STP, TEAM or ANA patient. The
cohort generator invents Italian residents with a codice fiscale, so those four
identifier kinds are covered by hand-built fixtures in the test suite and by no
generated corpus. That gap is recorded in the decision log rather than left to
be discovered.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from commissura.annotate import AnnotatedText, Phi
from commissura.generate.defects import DefectInjector
from commissura.generate.vocabulary import Site
from commissura.models import (
    ClinicalReport,
    Enrolment,
    ForeignIdentity,
    LabObservation,
    LabPanel,
    Person,
    PhiCategory,
    PhiSpan,
    ReportKind,
)
from commissura.read.cda import (
    ADMINISTRATIVE_GENDER_SYSTEM,
    ANA_ROOT,
    CDA_NAMESPACE,
    CODICE_FISCALE_ROOT,
    CODICE_FISCALE_ROOT_MISPRINT,
    DISCHARGE_DOCUMENT_CODE,
    ENI_NATIONAL_ROOT,
    LABORATORY_DOCUMENT_CODE,
    LOINC_SYSTEM,
    RADIOLOGY_DOCUMENT_CODE,
    STP_NATIONAL_ROOT,
    SUMMARY_DOCUMENT_CODE,
    SUMMARY_TEMPLATE_EXTENSION,
    SUMMARY_TEMPLATE_ROOT,
    SUMMARY_TYPE_ID_EXTENSION,
    TEAM_CARD_ROOT,
    TEAM_PERSONAL_ROOT,
)

_RESERVED: Final[str] = '<&"'
"""Characters a value may not contain, because they would change the markup.

Only three. ``>`` and ``'`` are legal in both element text and a double-quoted
attribute value, so refusing them would reject ordinary Italian street names for
no gain — and a writer that refuses more than it must is a writer somebody
works around.
"""

_ITALIAN_DATE: Final = "%d/%m/%Y"
"""Dates in the narrative are written the way a human writes them."""

SPECIALTY_BY_PANEL: Final[dict[str, tuple[str, str]]] = {
    "CBC": ("18723-7", "EMATOLOGIA"),
    "CHEM7": ("18719-5", "CHIMICA"),
    "LFT": ("18719-5", "CHIMICA"),
    "INFL": ("26436-6", "ESAMI DI LABORATORIO"),
    "THY": ("18719-5", "CHIMICA"),
}
"""Which laboratory specialty each generated panel belongs to.

Codes and Italian descriptions transcribed from Tabella 44, "LOINC - Specialità
di Laboratorio", in §7.2.1 of the specification. Transcribed rather than
invented because a specialty section's ``code`` is the one code the
specification makes LOINC-mandatory, so a made-up value would produce a document
that is well-formed, plausible, and not conformant — the same failure as a
plausible IRI that resolves to nothing.

Several panels share a specialty, which is how laboratories work: a liver panel
and a basic metabolic panel are both chemistry.
"""

_CONFIDENTIALITY_SYSTEM: Final = "2.16.840.1.113883.5.25"
_INTERPRETATION_SYSTEM: Final = "2.16.840.1.113883.5.83"
_FLS11_ROOT: Final = "2.16.840.1.113883.2.9.4.1.1"
"""Ministero della Salute's list of health authorities, per §4.1.15."""

_SYNTHETIC_ORGANISATION_ARC: Final = "2.16.840.1.113883.2.9.2.999"
"""The organisation arc this generator's own identifiers are issued under.

``2.16.840.1.113883.2.9.2.[IdOrganizzazione]`` is HL7 Italia's arc for
organisation-assigned OIDs, and ``999`` is not an assigned organisation. Chosen
the same way every other synthetic identifier in this project is chosen: so that
the value is well formed and cannot belong to anybody. "Probably nobody" is not
good enough.
"""


def _literal(value: str) -> str:
    """Return a value unchanged, having checked it cannot alter the markup.

    Args:
        value: The text to write into element content or an attribute.

    Returns:
        The same string.

    Raises:
        ValueError: If the value holds a character that would need escaping.
            Deliberately not escaped: every identifier in this document is
            written through :class:`~commissura.annotate.Phi`, which records a
            character offset at the moment it is written, and escaping would
            move every character after it. A corpus whose recorded offsets are
            wrong scores a working de-identifier as broken, which is the one
            failure this project cannot afford in its own ground truth. A
            reader for real-world documents unescapes at parse time, before any
            offset is taken, which is where that belongs.
    """
    found = [character for character in _RESERVED if character in value]
    if found:
        raise ValueError(
            f"value {value!r} contains reserved XML character(s) {''.join(found)!r}; "
            "this writer refuses rather than escaping, so that recorded PHI offsets "
            "stay exact"
        )
    return value


def _timestamp(moment: datetime) -> str:
    """Return an HL7 v3 TS value, precise to the second with a zone offset.

    §4.1.8 requires precision at least to the second and documents the form
    ``YYYYMMDDHHMMSS±ZZZZ``. The offset is written as ``+0100`` rather than
    computed from a timezone database: these are synthetic documents from a
    notional Italian site, and a generated corpus must produce identical bytes
    on every platform, which rules out anything that consults the host's idea of
    local time.
    """
    return f"{moment:%Y%m%d%H%M%S}+0100"


def _day(moment: datetime) -> str:
    """Return an HL7 v3 date value, to the day."""
    return f"{moment:%Y%m%d}"


def _number(observation: LabObservation) -> str:
    """Return a measurement at the precision the analyte is reported to."""
    if isinstance(observation.value, str):
        return observation.value
    return f"{observation.value:.{observation.decimals}f}"


def _bound(value: float | None, decimals: int) -> str:
    """Return a reference bound at matching precision, or an empty string."""
    return "" if value is None else f"{value:.{decimals}f}"


def render_lab_cda(
    panel: LabPanel,
    *,
    person: Person,
    site: Site,
    path: str,
    document_id: str,
    signed_by: str,
    injector: DefectInjector,
    previous_study_date: datetime | None = None,
    previous_site: Site | None = None,
) -> tuple[str, tuple[PhiSpan, ...]]:
    """Render one panel as a CDA R2 laboratory report.

    The structure follows §5.1: a ``structuredBody`` holding one specialty
    section, which holds one leaf section carrying the narrative and the Level 3
    entry. That nesting is deliberate rather than the simplest option — a
    specialty section with leaves MUST NOT carry ``section/text``, so a document
    shaped this way is the one that catches a reader which only looks at the top
    level and would otherwise report an empty narrative.

    Args:
        panel: The facts to render.
        person: The patient.
        site: The institution that produced and holds the document.
        path: Corpus-relative path, recorded on every span.
        document_id: The document's own identifier.
        signed_by: The clinician who legally authenticated the document.
            Supplied separately from ``panel.ordering_provider`` and
            deliberately different from it: the signer is the one name a
            plain-text report declares nowhere but its signature line, so a
            corpus where the two coincided would not show whether the reader
            found it.
        injector: Decides and records defects.
        previous_study_date: If given, the narrative may cite a comparison.
        previous_site: If given, the narrative may name where it was done.

    Returns:
        The document text and its identifier spans.
    """
    text = AnnotatedText(path)
    specialty_code, specialty_name = SPECIALTY_BY_PANEL[panel.panel_code]

    # The specification's own worked example prints the codice fiscale root with
    # an extra ".2", and an implementer who built from the example rather than
    # from the table beside it sends that root. Injecting it is what makes the
    # reader's refusal reachable from a generated corpus instead of from a
    # hand-written string in one test.
    #
    # **Not offered to a patient who has no codice fiscale.** They write no
    # codice fiscale element, so there is no root to misdeclare -- and before
    # this guard the generator *recorded* the defect for them anyway, naming two
    # documents in the manifest that did not carry it. Caught by the CDA
    # session's own `test_the_misprinted_root_is_reachable_from_a_generated_corpus`,
    # which asserts every injected defect is reported: a guard written for one
    # reason catching a different thing a day later.
    #
    # Drawn first and used second, rather than guarded by a condition that would
    # short-circuit the draw away. The draw has to happen for every document or
    # the random stream shifts with the shape of a cohort, which is the same
    # reason `lab.conflicting_identity` draws for every panel and records only
    # the draws it uses.
    misdeclare = injector.should_apply("cda.misdeclared_cf_namespace") and person.foreign is None
    if misdeclare:
        injector.record(
            "cda.misdeclared_cf_namespace",
            path,
            "recordTarget/patientRole/id/@root written as "
            f"{CODICE_FISCALE_ROOT_MISPRINT}, the root the specification's own "
            "example misprints, instead of the correct "
            f"{CODICE_FISCALE_ROOT}",
        )
    codice_fiscale_root = CODICE_FISCALE_ROOT_MISPRINT if misdeclare else CODICE_FISCALE_ROOT

    text.line('<?xml version="1.0" encoding="UTF-8"?>')
    text.line(
        f'<ClinicalDocument xmlns="{CDA_NAMESPACE}" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
    )
    text.line('  <realmCode code="IT"/>')
    text.line('  <typeId root="2.16.840.1.113883.1.3" extension="POCD_HD000040"/>')
    text.line('  <templateId root="2.16.840.1.113883.2.9.10.1.1" extension="1.3"/>')
    text.line(
        f'  <id root="{_SYNTHETIC_ORGANISATION_ARC}.4.6" extension="{_literal(document_id)}"/>'
    )
    text.line(
        f'  <code code="{LABORATORY_DOCUMENT_CODE}" codeSystem="{LOINC_SYSTEM}" '
        'codeSystemName="LOINC" displayName="Referto di laboratorio"/>'
    )
    text.line("  <title>Referto di Medicina di Laboratorio</title>")
    text.line(f'  <effectiveTime value="{_timestamp(panel.reported_at)}"/>')
    text.line(f'  <confidentialityCode code="V" codeSystem="{_CONFIDENTIALITY_SYSTEM}"/>')
    text.line('  <languageCode code="it-IT"/>')

    _record_target(text, person, codice_fiscale_root)
    _author(text, panel.reported_at, panel.ordering_provider, site)
    _custodian(text, site)
    _legal_authenticator(text, panel.reported_at, site, signed_by)

    text.line("  <inFulfillmentOf>")
    text.line("    <order>")
    text.line(
        f'      <id root="{_SYNTHETIC_ORGANISATION_ARC}.4.8" extension="',
        Phi(panel.accession, PhiCategory.ACCESSION),
        '"/>',
    )
    text.line("    </order>")
    text.line("  </inFulfillmentOf>")

    # The numero nosologico, which §4.1.23 places here. This is the element that
    # makes a CDA document linkable to a DICOM study: it is the same hospital
    # record number the imaging export carries as PatientID.
    text.line("  <componentOf>")
    text.line("    <encompassingEncounter>")
    text.line(
        f'      <id root="{_SYNTHETIC_ORGANISATION_ARC}.4.2" extension="',
        Phi(person.mrn, PhiCategory.PATIENT_ID),
        '" assigningAuthorityName="',
        _literal(site.name),
        '"/>',
    )
    text.line(f'      <effectiveTime value="{_timestamp(panel.collected_at)}"/>')
    text.line("    </encompassingEncounter>")
    text.line("  </componentOf>")

    text.line("  <component>")
    text.line("    <structuredBody>")
    text.line("      <component>")
    text.line("        <section>")
    text.line(
        f'          <code code="{specialty_code}" codeSystem="{LOINC_SYSTEM}" '
        f'codeSystemName="LOINC" displayName="{_literal(specialty_name)}"/>'
    )
    text.line(f"          <title>{_literal(specialty_name)}</title>")
    _leaf_section(
        text,
        panel,
        person=person,
        site=site,
        path=path,
        injector=injector,
        previous_study_date=previous_study_date,
        previous_site=previous_site,
    )
    text.line("        </section>")
    text.line("      </component>")
    text.line("    </structuredBody>")
    text.line("  </component>")
    text.line("</ClinicalDocument>")

    return text.finish()


_FOREIGN_ROOT: Final[dict[Enrolment, str]] = {
    Enrolment.ENI: ENI_NATIONAL_ROOT,
    Enrolment.STP: STP_NATIONAL_ROOT,
    Enrolment.ANA: ANA_ROOT,
}
"""The national OID each kind is written under.

The specification allows a *regional* OID for ENI and STP instead, which is why
the reader can also recognise those two from the code's own `ENI`/`STP` prefix.
The generator writes the national form: a regional one is a local value this
project has no business inventing, and the prefix path is exercised by the
reader's own tests with a hand-built root rather than by minting a fake region.
"""


def _foreign_ids(text: AnnotatedText, foreign: ForeignIdentity) -> None:
    """Write the ``id`` elements for a patient who holds no codice fiscale.

    **TEAM writes two and the order is the specification's**: the card number
    first, then the personal identification number. Both are recorded as
    national identifiers in the ground truth, because both identify the patient
    to anybody holding them and both therefore have to be removed — the
    distinction that only the personal number may *key* a subject is the
    reader's to make, and it makes it.

    Args:
        text: The document being assembled.
        foreign: What this patient carries instead of a codice fiscale.
    """
    if foreign.enrolment is Enrolment.TEAM:
        text.line(
            f'      <id root="{TEAM_CARD_ROOT}" extension="',
            Phi(foreign.card_number, PhiCategory.NATIONAL_ID),
            '" assigningAuthorityName="Istituzione estera sintetica"/>',
        )
        text.line(
            f'      <id root="{TEAM_PERSONAL_ROOT}" extension="',
            Phi(foreign.value, PhiCategory.NATIONAL_ID),
            '" assigningAuthorityName="Istituzione estera sintetica"/>',
        )
        return
    text.line(
        f'      <id root="{_FOREIGN_ROOT[foreign.enrolment]}" extension="',
        Phi(foreign.value, PhiCategory.NATIONAL_ID),
        '"/>',
    )


@dataclass(frozen=True, slots=True)
class _NarrativeProfile:
    """What distinguishes one narrative CDA profile from another.

    Three documents, one header, and the differences confined to this: a
    document code, a title, a template identifier, and which LOINC-coded
    sections carry which part of the report. That is the whole of what the seam
    had to absorb, and it absorbed it.

    Attributes:
        document_code: ``ClinicalDocument/code/@code``, obligatory.
        display_name: The ``@displayName`` each specification gives.
        title: ``ClinicalDocument/title``.
        template_root: ``templateId/@root`` for the profile.
        template_extension: ``templateId/@extension``, empty where the
            specification states none.
        sections: ``(code, display, title, field)`` in document order, where
            ``field`` names the :class:`ClinicalReport` attribute the section
            carries.
    """

    document_code: str
    display_name: str
    title: str
    template_root: str
    template_extension: str
    sections: tuple[tuple[str, str, str, str], ...]


NARRATIVE_PROFILES: Final[dict[ReportKind, _NarrativeProfile]] = {
    ReportKind.RADIOLOGY: _NarrativeProfile(
        document_code=RADIOLOGY_DOCUMENT_CODE,
        display_name="Referto Radiologico",
        title="Referto di Radiologia",
        template_root="2.16.840.1.113883.2.9.10.1.7.1",
        template_extension="1.1",
        sections=(
            ("18785-6", "Radiology Reason for study", "Quesito diagnostico", "indication"),
            (
                "55111-9",
                "Current imaging procedure descriptions Document",
                "Esame eseguito",
                "technique",
            ),
            ("18782-3", "Radiology Study observation", "Referto", "findings"),
            ("55110-1", "Conclusions", "Conclusioni", "conclusion"),
        ),
    ),
    ReportKind.DISCHARGE: _NarrativeProfile(
        document_code=DISCHARGE_DOCUMENT_CODE,
        display_name="Lettera di dimissione ospedaliera",
        title="Lettera di Dimissione Ospedaliera",
        template_root="2.16.840.1.113883.2.9.10.1.5",
        template_extension="",
        sections=(
            ("46241-6", "Hospital Admission Dx", "Motivo del ricovero", "indication"),
            ("8648-8", "Hospital Course", "Decorso Ospedaliero", "findings"),
            ("11535-2", "Hospital Discharge Dx", "Condizioni alla dimissione", "conclusion"),
            ("18776-5", "Treatment Plan", "Istruzioni di follow-up", "technique"),
        ),
    ),
}
"""Section codes and obligations read from the two specifications, not recalled.

**RAD, Tabella 46**: of eleven sections exactly *two* are OBBLIGATORIO --
``55111-9`` "Esame eseguito" and ``18782-3`` "Referto (Refertazione)". Both are
emitted. ``18785-6`` "Quesito diagnostico" and ``55110-1`` "Conclusioni" are
OPZIONALE and are emitted because the generator has the content for them.

**LDO, Tabella 52**: of sixteen sections *three* are OBBLIGATORIO --
``46241-6`` "Motivo del ricovero", ``8648-8`` "Decorso Ospedaliero" and
``11535-2`` "Condizioni del paziente alla dimissione e diagnosi alla
dimissione". All three are emitted, plus the optional ``18776-5`` "Istruzioni di
follow-up", which is where a discharge letter's technique text belongs.

The document codes are the finding worth keeping: radiology is **68604-8** and
not ``18748-4``, which is what recalling it would produce. See
:data:`commissura.read.cda.RADIOLOGY_DOCUMENT_CODE`.
"""


def render_narrative_cda(
    report: ClinicalReport,
    *,
    person: Person,
    site: Site,
    path: str,
    document_id: str,
    signed_by: str,
    injector: DefectInjector,
    previous_study_date: datetime | None = None,
    previous_site: Site | None = None,
) -> tuple[str, tuple[PhiSpan, ...]]:
    """Render a radiology report or a discharge letter as a CDA R2 document.

    **One function for both, because the two specifications differ in four
    values and nothing else.** ``HL7IT-IG_CDA2_RAD-v1.1-S`` and
    ``HL7IT-IG_CDA2_LDO-v1.2-S`` share the header with the laboratory profile --
    the same ``recordTarget`` with the same five identifier cases under the same
    OIDs, the same obligatory ``custodian`` and ``legalAuthenticator`` -- and
    differ in the document code, the title, the template identifier and which
    LOINC-coded sections the body carries. Those four live in
    :data:`NARRATIVE_PROFILES`; everything else is shared with
    :func:`render_lab_cda`, which is what the seam was for and is the only
    evidence that the seam was real rather than asserted.

    **No Level 3 entries.** Both specifications keep the coded entries
    OPZIONALE and say a document detailed to level two -- sections with
    narrative and no entries -- is still well formed. A radiology report's
    content *is* prose, so inventing coded observations for it would model
    something a radiology department does not produce.

    **The narrative is hostile in the same ways the plain-text reports are**,
    and that is deliberate rather than thorough. A CDA narrative that carried
    only clean clinical prose would be easier to de-identify than the free-text
    report it replaces, and the recall figure would improve for no reason but
    the corpus getting kinder. So the closing paragraph names the author and,
    where there is one to cite, the institution that performed an earlier study
    -- neither in any structured field, which is the documented limit of
    targeted redaction.

    Args:
        report: The report to render.
        person: Whose it is.
        site: The institution.
        path: Corpus-relative path, recorded with every span.
        document_id: ``ClinicalDocument/id/@extension``.
        signed_by: The clinician who legally authenticated it, deliberately
            different from the author for the reason in :func:`render_lab_cda`.
        injector: Decides and records defects.
        previous_study_date: If given, the narrative may cite a comparison.
        previous_site: If given, the narrative may name where it was done.

    Returns:
        The document text and its identifier spans.
    """
    profile = NARRATIVE_PROFILES[report.kind]
    text = AnnotatedText(path)

    # The same guard as the laboratory writer: drawn for every document so the
    # random stream does not move with the shape of a cohort, and never offered
    # to a patient who writes no codice fiscale element at all.
    misdeclare = injector.should_apply("cda.misdeclared_cf_namespace") and person.foreign is None
    if misdeclare:
        injector.record(
            "cda.misdeclared_cf_namespace",
            path,
            "recordTarget/patientRole/id/@root written as "
            f"{CODICE_FISCALE_ROOT_MISPRINT}, the root the specification's own "
            f"example misprints, instead of the correct {CODICE_FISCALE_ROOT}",
        )
    codice_fiscale_root = CODICE_FISCALE_ROOT_MISPRINT if misdeclare else CODICE_FISCALE_ROOT

    template = f'  <templateId root="{profile.template_root}"'
    if profile.template_extension:
        template += f' extension="{profile.template_extension}"'
    template += "/>"

    text.line('<?xml version="1.0" encoding="UTF-8"?>')
    text.line(
        f'<ClinicalDocument xmlns="{CDA_NAMESPACE}" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
    )
    text.line('  <realmCode code="IT"/>')
    text.line('  <typeId root="2.16.840.1.113883.1.3" extension="POCD_HD000040"/>')
    text.line(template)
    text.line(
        f'  <id root="{_SYNTHETIC_ORGANISATION_ARC}.4.6" extension="{_literal(document_id)}"/>'
    )
    text.line(
        f'  <code code="{profile.document_code}" codeSystem="{LOINC_SYSTEM}" '
        f'codeSystemName="LOINC" displayName="{profile.display_name}"/>'
    )
    text.line(f"  <title>{profile.title}</title>")
    text.line(f'  <effectiveTime value="{_timestamp(report.authored_at)}"/>')
    text.line(f'  <confidentialityCode code="V" codeSystem="{_CONFIDENTIALITY_SYSTEM}"/>')
    text.line('  <languageCode code="it-IT"/>')

    _record_target(text, person, codice_fiscale_root)
    _author(text, report.authored_at, report.author_name, site)
    _custodian(text, site)
    _legal_authenticator(text, report.authored_at, site, signed_by)

    # The numero nosologico, which is what links this document to the subject's
    # imaging. OPZIONALE for radiology and obligatory for a discharge letter
    # (CONF-LDO-80), and written for both: a document that could carry it and
    # does not is a document whose imaging attaches to nobody.
    text.line("  <componentOf>")
    text.line("    <encompassingEncounter>")
    text.line(
        f'      <id root="{_SYNTHETIC_ORGANISATION_ARC}.4.2" extension="',
        Phi(person.mrn, PhiCategory.PATIENT_ID),
        '" assigningAuthorityName="',
        _literal(site.name),
        '"/>',
    )
    text.line(f'      <effectiveTime value="{_timestamp(report.authored_at)}"/>')
    text.line("    </encompassingEncounter>")
    text.line("  </componentOf>")

    text.line("  <component>")
    text.line("    <structuredBody>")
    for code, display, title, field in profile.sections:
        value = getattr(report, field)
        lines = list(value) if field == "findings" else [value]
        if not any(lines):
            continue
        text.line("      <component>")
        text.line("        <section>")
        text.line(
            f'          <code code="{code}" codeSystem="{LOINC_SYSTEM}" '
            f'codeSystemName="LOINC" displayName="{display}"/>'
        )
        text.line(f"          <title>{title}</title>")
        text.line("          <text>")
        for line in lines:
            if line:
                text.line(f"            <paragraph>{_literal(line)}</paragraph>")
        text.line("          </text>")
        text.line("        </section>")
        text.line("      </component>")

    _narrative_attribution(
        text,
        report=report,
        previous_study_date=previous_study_date,
        previous_site=previous_site,
    )

    text.line("    </structuredBody>")
    text.line("  </component>")
    text.line("</ClinicalDocument>")

    return text.finish()


def _narrative_attribution(
    text: AnnotatedText,
    *,
    report: ClinicalReport,
    previous_study_date: datetime | None,
    previous_site: Site | None,
) -> None:
    """Write the closing section: a clinician and an institution, in prose.

    Its own section rather than appended to a coded one, because every section
    in these profiles has a prescribed LOINC code and this content belongs to
    none of them. ``55107-7`` "Addendum" is OPZIONALE in RAD's Tabella 46 and is
    what an addition like this is for; LDO has no equivalent, so a discharge
    letter carries it under ``18776-5``, which it already uses.

    Why it exists at all is in :func:`render_narrative_cda`: without prose that
    names somebody no structured field declares, a CDA narrative would be
    easier than the plain-text report it replaces and the recall figure would
    improve for no reason but a kinder corpus.
    """
    addendum = "55107-7" if report.kind is ReportKind.RADIOLOGY else "18776-5"
    text.line("      <component>")
    text.line("        <section>")
    text.line(
        f'          <code code="{addendum}" codeSystem="{LOINC_SYSTEM}" codeSystemName="LOINC"/>'
    )
    text.line("          <text>")
    text.line(
        "            <paragraph>Refertazione a cura del dott. ",
        Phi(report.author_name, PhiCategory.PROVIDER_NAME, "author named in running prose"),
        ".</paragraph>",
    )
    if previous_study_date is not None and previous_site is not None:
        text.line(
            "            <paragraph>Si confronta con l'esame del ",
            Phi(
                previous_study_date.strftime(_ITALIAN_DATE),
                PhiCategory.DATE,
                "comparison date inside running prose",
            ),
            " eseguito presso ",
            Phi(
                previous_site.name,
                PhiCategory.INSTITUTION,
                "institution named in running prose",
            ),
            ".</paragraph>",
        )
    text.line("          </text>")
    text.line("        </section>")
    text.line("      </component>")


SUMMARY_SECTIONS: Final[tuple[tuple[str, str, str, str], ...]] = (
    (
        "2.16.840.1.113883.3.1937.777.63.10.415",
        "48765-2",
        "Allergie e Intolleranze",
        "allergies",
    ),
    (
        "2.16.840.1.113883.2.9.10.1.4.2.2",
        "10160-0",
        "Terapie Farmacologiche",
        "therapies",
    ),
)
"""The PSS sections this generator emits: ``(templateId root, LOINC code, title, field)``.

Read from the v1.5 Schematron, where each section's own rule file states its
code -- ``48765-2`` in "Allergie e Intolleranze PSS", ``10160-0`` in "Terapie
Farmacologiche (PSS)". Both roots are spelled identically in the document
template's permitted-section list and in the section's own context, which is the
condition the next paragraph is about.

**The vaccinations section is deliberately absent, and that is a finding rather
than a shortcut.** The package describes one -- "Vaccinazioni (PSS)", LOINC
``11369-6`` -- but every root it offers for it reads
``'2.16.840.1.113883.2.9.10.1.4.2.3 '``, with a trailing space **inside the
attribute value**, in the document template's permitted list and in the
section's own context alike. Two more, ``.2.13`` and ``.2.14``, carry a leading
space the same way, and so does ``.3.10.5``.

Because the malformed string is used consistently, there is no spelling that is
both a well-formed OID and accepted by the package: a document carrying
``…4.2.3`` is rejected by the closed document template as an unpermitted section
*and* never matched by the section's own rules. Emitting the untrimmed value
would put a malformed OID into a document this project generates; emitting the
trimmed one would claim conformance to a rule the package does not contain. The
section is OPZIONALE -- no section is mandatory in this profile -- so leaving it
out costs nothing and states something true.

This is the misprinted codice fiscale root of 2026-11-17 one turn worse. There,
a correct spelling appeared elsewhere in the same document and could corroborate
a reading; here the malformed value is the only form there is.
"""


def render_summary_cda(
    person: Person,
    *,
    site: Site,
    path: str,
    document_id: str,
    set_id: str,
    version: int,
    authored_at: datetime,
    author_name: str,
    signed_by: str,
    allergies: tuple[str, ...],
    therapies: tuple[str, ...],
    injector: DefectInjector,
) -> tuple[str, tuple[PhiSpan, ...]]:
    """Render a Profilo Sanitario Sintetico as a CDA R2 document, v1.5.

    **A third renderer rather than a fourth row in :data:`NARRATIVE_PROFILES`,
    and finding that out relocated the seam.** The entry of 2026-11-18 claimed
    the remaining profiles were "a profile table and a section map" away, which
    held for the radiology report and the discharge letter and does not hold
    here. Five differences, every one read from the v1.5 Schematron rather than
    from a PDF, because every PDF on the Ministry's index for this profile is
    marked obsolete:

    * ``typeId/@extension`` is ``POCD_MT000040UV02``, asserted at min 1 and
      max 1, where the laboratory specification writes ``POCD_HD000040`` on page
      18 and this generator writes that for the other three profiles. **Two
      specifications from one affiliate disagreeing on a fixed attribute** --
      see :data:`commissura.read.cda.SUMMARY_TYPE_ID_EXTENSION`.
    * ``componentOf`` is **not among the permitted elements at all**, so there
      is no ``encompassingEncounter`` and no numero nosologico.
      :func:`render_narrative_cda` writes one unconditionally, because a report
      belongs to an encounter. A patient summary does not.
    * ``documentationOf[serviceEvent]`` is required at exactly one and takes its
      place.
    * ``setId`` and ``versionNumber`` are permitted, with up to two
      ``relatedDocument`` -- because a summary is **maintained and versioned**
      and supersedes its own previous version. A report is authored once.
    * **No section is mandatory.** Only ``component[structuredBody]`` is, where
      RAD requires two sections of eleven and LDO three of sixteen. A summary
      records what is known, so a patient with nothing to record in a section
      has no such section rather than an empty one.

    What *did* transfer, unchanged, is the identity header:
    :func:`_record_target` with its five identifier cases, :func:`_author`,
    :func:`_custodian` and :func:`_legal_authenticator`. **That is the real
    seam, and the 2026-11-18 entry located it one level too high** -- it is the
    header helpers, not the profile table. Here it also absorbed a cardinality
    difference for free: ``legalAuthenticator`` is max 1 and **not** required in
    this profile, where LDO requires it, and its ``signatureCode code="S"`` is
    what the PSS asserts when one is present.

    Level 2 and not Level 3, deliberately. The package ships nine entry-level
    templates -- acts, substanceAdministrations, observations, procedures -- so
    a real PSS is normally coded, and distinct templates exist for *Presenza
    Terapia* and *Assenza Terapia*. Neither section emitted here requires an
    ``entry``, so a narrative-only document is conformant, and the identifiers
    this project exists to remove live in the narrative in either case.

    Args:
        person: Whose summary it is.
        site: The institution holding it.
        path: Corpus-relative path, recorded with every span.
        document_id: ``ClinicalDocument/id/@extension``.
        set_id: ``setId/@extension``, stable across versions of one summary,
            which is what lets a recipient tell a newer version of this
            document from a different document about the same person.
        version: ``versionNumber/@value``.
        authored_at: When this version was compiled.
        author_name: The clinician who compiled it.
        signed_by: The clinician who legally authenticated it, deliberately
            different from the author for the reason in :func:`render_lab_cda`.
        allergies: Narrative lines for the allergies section, omitted when
            empty.
        therapies: Narrative lines for the medication section, omitted when
            empty. The caller is expected to supply at least one -- "nessuna
            terapia in corso" is a statement a summary makes, which is why the
            specification has a template for it -- because the closing
            attribution is written into the last section emitted.
        injector: Decides and records defects.

    Returns:
        The document text and its identifier spans.
    """
    text = AnnotatedText(path)
    content = {"allergies": allergies, "therapies": therapies}

    # The same guard as every other profile: drawn for every document so the
    # random stream does not move with the shape of a cohort, and never offered
    # to a patient who writes no codice fiscale element at all.
    misdeclare = injector.should_apply("cda.misdeclared_cf_namespace") and person.foreign is None
    if misdeclare:
        injector.record(
            "cda.misdeclared_cf_namespace",
            path,
            "recordTarget/patientRole/id/@root written as "
            f"{CODICE_FISCALE_ROOT_MISPRINT}, the root the specification's own "
            f"example misprints, instead of the correct {CODICE_FISCALE_ROOT}",
        )
    codice_fiscale_root = CODICE_FISCALE_ROOT_MISPRINT if misdeclare else CODICE_FISCALE_ROOT

    text.line('<?xml version="1.0" encoding="UTF-8"?>')
    text.line(
        f'<ClinicalDocument xmlns="{CDA_NAMESPACE}" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
    )
    text.line('  <realmCode code="IT"/>')
    # Not POCD_HD000040, which is what the other three profiles here write. The
    # element order below is the template's own, because CDA's header is a
    # sequence: a reordered document is invalid however correct each element is.
    text.line(f'  <typeId root="2.16.840.1.113883.1.3" extension="{SUMMARY_TYPE_ID_EXTENSION}"/>')
    text.line(
        f'  <templateId root="{SUMMARY_TEMPLATE_ROOT}" extension="{SUMMARY_TEMPLATE_EXTENSION}"/>'
    )
    text.line(
        f'  <id root="{_SYNTHETIC_ORGANISATION_ARC}.4.6" extension="{_literal(document_id)}"/>'
    )
    text.line(
        f'  <code code="{SUMMARY_DOCUMENT_CODE}" codeSystem="{LOINC_SYSTEM}" '
        'codeSystemName="LOINC" displayName="Patient Summary"/>'
    )
    text.line("  <title>Profilo Sanitario Sintetico</title>")
    text.line(f'  <effectiveTime value="{_timestamp(authored_at)}"/>')
    text.line(f'  <confidentialityCode code="V" codeSystem="{_CONFIDENTIALITY_SYSTEM}"/>')
    text.line('  <languageCode code="it-IT"/>')
    # What makes this a maintained document rather than a record of an event:
    # the set identifier is stable across versions and the version number moves.
    text.line(f'  <setId root="{_SYNTHETIC_ORGANISATION_ARC}.4.9" extension="{_literal(set_id)}"/>')
    text.line(f'  <versionNumber value="{version}"/>')

    _record_target(text, person, codice_fiscale_root)
    _author(text, authored_at, author_name, site)
    _custodian(text, site)
    _legal_authenticator(text, authored_at, site, signed_by)

    # Where a report carries componentOf/encompassingEncounter, which this
    # profile does not permit. A summary documents the act of compiling it,
    # which has no encounter -- so a subject established only by a PSS has no
    # institution-scoped record number to fall back on, and is keyed on the
    # codice fiscale or on nothing.
    text.line("  <documentationOf>")
    text.line('    <serviceEvent classCode="PCPR">')
    text.line(f'      <effectiveTime><low value="{_timestamp(authored_at)}"/></effectiveTime>')
    text.line("    </serviceEvent>")
    text.line("  </documentationOf>")

    text.line("  <component>")
    text.line("    <structuredBody>")
    for template_root, code, title, field in SUMMARY_SECTIONS:
        lines = content[field]
        if not any(lines):
            continue
        text.line("      <component>")
        text.line("        <section>")
        # A templateId per section, which the narrative profiles do not write:
        # the PSS document template is closed and keys its permitted sections on
        # exactly this attribute, so a section without one is not merely
        # unidentified but not allowed.
        text.line(f'          <templateId root="{template_root}"/>')
        text.line(
            f'          <code code="{code}" codeSystem="{LOINC_SYSTEM}" '
            f'codeSystemName="LOINC" displayName="{title}"/>'
        )
        text.line(f"          <title>{title}</title>")
        text.line("          <text>")
        for line in lines:
            if line:
                text.line(f"            <paragraph>{_literal(line)}</paragraph>")
        if field == SUMMARY_SECTIONS[-1][3]:
            _summary_attribution(text, author_name=author_name, site=site, moment=authored_at)
        text.line("          </text>")
        text.line("        </section>")
        text.line("      </component>")

    text.line("    </structuredBody>")
    text.line("  </component>")
    text.line("</ClinicalDocument>")

    return text.finish()


def _summary_attribution(
    text: AnnotatedText, *, author_name: str, site: Site, moment: datetime
) -> None:
    """Write the closing paragraphs: who compiled the summary, where, and when.

    **Paragraphs inside a section this document already carries, not a section
    of its own**, which is the one place this differs from
    :func:`_narrative_attribution`. RAD has ``55107-7`` "Addendum" for an
    addition like this and LDO reuses ``18776-5``; the PSS document template is
    closed and every section it permits has its own prescribed code, so there is
    no section here that means "a note about the document". Inventing one would
    mean writing a templateId and a code that the package does not pair, which
    is the failure mode of a plausible IRI that resolves to nothing.

    Hostile on purpose, the same decision as the narrative profiles of
    2026-11-18: a summary carrying only clean clinical prose would be *easier*
    to de-identify than the documents it sits beside, and the recall figure
    would improve for no reason but the corpus getting kinder. So this names the
    compiler, the institution and a date in running prose, where no structured
    field of this document declares them.
    """
    text.line(
        "            <paragraph>Profilo compilato dal dott. ",
        Phi(author_name, PhiCategory.PROVIDER_NAME, "compiler named in running prose"),
        " presso ",
        Phi(site.name, PhiCategory.INSTITUTION, "institution named in running prose"),
        ".</paragraph>",
    )
    text.line(
        "            <paragraph>Dati aggiornati al ",
        Phi(
            moment.strftime(_ITALIAN_DATE),
            PhiCategory.DATE,
            "update date inside running prose",
        ),
        ".</paragraph>",
    )


def _record_target(text: AnnotatedText, person: Person, codice_fiscale_root: str) -> None:
    """Write the patient's identity, which CDA states in defined elements.

    Every value here is an identifier and every one is recorded. This is the
    block that makes CDA worth reading: the codice fiscale, the name, the birth
    date and the address are each in their own element with their own meaning,
    where a free-text report has a line of prose and a label somebody chose.
    """
    text.line("  <recordTarget>")
    text.line("    <patientRole>")
    if person.foreign is None:
        text.line(
            f'      <id root="{codice_fiscale_root}" extension="',
            Phi(person.codice_fiscale, PhiCategory.NATIONAL_ID),
            '" assigningAuthorityName="Ministero Economia e Finanze"/>',
        )
    else:
        _foreign_ids(text, person.foreign)
    text.line('      <addr use="H">')
    text.line("        <country>100</country>")
    text.line("        <city>", Phi(person.city, PhiCategory.ADDRESS), "</city>")
    text.line(f"        <county>{_literal(person.province)}</county>")
    text.line("        <postalCode>", Phi(person.postal_code, PhiCategory.ADDRESS), "</postalCode>")
    text.line(
        "        <streetAddressLine>",
        Phi(person.street, PhiCategory.ADDRESS),
        "</streetAddressLine>",
    )
    text.line("      </addr>")
    text.line('      <telecom use="HP" value="tel:', Phi(person.phone, PhiCategory.CONTACT), '"/>')
    text.line(
        '      <telecom use="HP" value="mailto:', Phi(person.email, PhiCategory.CONTACT), '"/>'
    )
    text.line("      <patient>")
    text.line("        <name>")
    text.line("          <family>", Phi(person.family_name, PhiCategory.PERSON_NAME), "</family>")
    text.line("          <given>", Phi(person.given_name, PhiCategory.PERSON_NAME), "</given>")
    text.line("        </name>")
    text.line(
        f'        <administrativeGenderCode code="{person.sex.value}" '
        f'codeSystem="{ADMINISTRATIVE_GENDER_SYSTEM}" '
        'codeSystemName="HL7 AdministrativeGender"/>'
    )
    text.line(
        '        <birthTime value="',
        Phi(
            _day(datetime.combine(person.birth_date, datetime.min.time())),
            PhiCategory.DATE,
            "date of birth",
        ),
        '"/>',
    )
    text.line("      </patient>")
    text.line("    </patientRole>")
    text.line("  </recordTarget>")


def _clinician_elements(text: AnnotatedText, provider: str, indent: str) -> None:
    """Write a clinician's name as CDA states it: family and given, separately.

    Args:
        text: The builder.
        provider: A name written ``FAMILY GIVEN``, as this project's vocabulary
            holds it.
        indent: Leading spaces, so the document stays readable to a human.
    """
    family, _, given = provider.partition(" ")
    text.line(f"{indent}<assignedPerson>")
    text.line(f"{indent}  <name>")
    text.line(f"{indent}    <family>", Phi(family, PhiCategory.PROVIDER_NAME), "</family>")
    if given:
        text.line(f"{indent}    <given>", Phi(given, PhiCategory.PROVIDER_NAME), "</given>")
    text.line(f"{indent}  </name>")
    text.line(f"{indent}</assignedPerson>")


def _author(text: AnnotatedText, moment: datetime, clinician: str, site: Site) -> None:
    """Write the clinician who created the document.

    Takes the moment and the name rather than a ``LabPanel``, because a
    radiology report and a discharge letter carry the same element and have no
    panel. Narrowing the parameters is what let the three document types share
    one header without a branch per type.
    """
    text.line("  <author>")
    text.line(f'    <time value="{_timestamp(moment)}"/>')
    text.line('    <assignedAuthor classCode="ASSIGNED">')
    text.line(f'      <id root="{_SYNTHETIC_ORGANISATION_ARC}.4.3" extension="AUT"/>')
    _clinician_elements(text, clinician, "      ")
    text.line("      <representedOrganization>")
    text.line("        <name>", Phi(site.name, PhiCategory.INSTITUTION), "</name>")
    text.line("      </representedOrganization>")
    text.line("    </assignedAuthor>")
    text.line("  </author>")


def _custodian(text: AnnotatedText, site: Site) -> None:
    """Write the organisation responsible for the document.

    Obligatory, with its ``id`` and ``name`` both obligatory (§4.1.15), which is
    what makes it the element a record number can be scoped by: it is the one
    institutional name a conformant CDA document always carries.
    """
    text.line("  <custodian>")
    text.line("    <assignedCustodian>")
    text.line("      <representedCustodianOrganization>")
    text.line(
        f'        <id root="{_FLS11_ROOT}" extension="999999" '
        'assigningAuthorityName="Ministero della Salute"/>'
    )
    text.line("        <name>", Phi(site.name, PhiCategory.INSTITUTION), "</name>")
    text.line("        <addr>")
    text.line(
        "          <streetAddressLine>",
        Phi(site.address, PhiCategory.ADDRESS),
        "</streetAddressLine>",
    )
    text.line("          <city>", Phi(site.city, PhiCategory.ADDRESS), "</city>")
    text.line("        </addr>")
    text.line("      </representedCustodianOrganization>")
    text.line("    </assignedCustodian>")
    text.line("  </custodian>")


def _legal_authenticator(text: AnnotatedText, moment: datetime, site: Site, signed_by: str) -> None:
    """Write the clinician who legally signed the document.

    Obligatory, and its ``assignedPerson/name`` must carry ``given`` and
    ``family`` (§4.1.17). So the signer that a plain-text report only reveals
    through a line beginning ``Dott.`` is, here, a defined element — which is the
    single clearest illustration of what reading a standard buys.
    """
    text.line("  <legalAuthenticator>")
    text.line(f'    <time value="{_timestamp(moment)}"/>')
    text.line('    <signatureCode code="S"/>')
    text.line("    <assignedEntity>")
    text.line(f'      <id root="{_SYNTHETIC_ORGANISATION_ARC}.4.4" extension="FIR"/>')
    _clinician_elements(text, signed_by, "      ")
    text.line("      <representedOrganization>")
    text.line("        <name>", Phi(site.name, PhiCategory.INSTITUTION), "</name>")
    text.line("      </representedOrganization>")
    text.line("    </assignedEntity>")
    text.line("  </legalAuthenticator>")


def _leaf_section(
    text: AnnotatedText,
    panel: LabPanel,
    *,
    person: Person,
    site: Site,
    path: str,
    injector: DefectInjector,
    previous_study_date: datetime | None,
    previous_site: Site | None,
) -> None:
    """Write the leaf section: the narrative block and the Level 3 entry."""
    text.line("          <component>")
    text.line("            <section>")
    text.line(
        f'              <code code="{panel.panel_code}" '
        f'codeSystem="{_SYNTHETIC_ORGANISATION_ARC}.5.1" '
        f'codeSystemName="Codifica locale" displayName="{_literal(panel.panel_name)}"/>'
    )
    text.line(f"              <title>{_literal(panel.panel_name)}</title>")
    _narrative(
        text,
        panel,
        person=person,
        site=site,
        path=path,
        injector=injector,
        previous_study_date=previous_study_date,
        previous_site=previous_site,
    )
    _entry(text, panel)
    text.line("            </section>")
    text.line("          </component>")


def _narrative(
    text: AnnotatedText,
    panel: LabPanel,
    *,
    person: Person,
    site: Site,
    path: str,
    injector: DefectInjector,
    previous_study_date: datetime | None,
    previous_site: Site | None,
) -> None:
    """Write ``section/text``: the human-readable half, written by a human.

    **This is the half CDA does not solve**, and the narrative here is built to
    be hostile in the same ways the free-text reports are. The results appear in
    a table, which is how a laboratory presents them and which is also why the
    reader has to insert a break between cells rather than running them
    together. The prose around the table carries a collection date and, where
    there is one to cite, the institution that performed an earlier study —
    neither of them in any structured field, neither reachable by a scrubber
    that only reads the header.
    """
    text.line("              <text>")
    text.line(
        "                <paragraph>Prelievo eseguito in data ",
        Phi(
            panel.collected_at.strftime(_ITALIAN_DATE),
            PhiCategory.DATE,
            "collection date inside running prose",
        ),
        " presso ",
        Phi(site.name, PhiCategory.INSTITUTION, "institution named in running prose"),
        ".</paragraph>",
    )
    text.line("                <table>")
    text.line("                  <tbody>")
    for observation in panel.observations:
        low = _bound(observation.reference_low, observation.decimals)
        high = _bound(observation.reference_high, observation.decimals)
        interval = f"{low}-{high}" if low and high else ""
        text.line(
            "                    <tr><td>",
            _literal(observation.display),
            "</td><td>",
            _literal(_number(observation)),
            " ",
            _literal(observation.unit),
            "</td><td>",
            _literal(interval),
            "</td></tr>",
        )
    text.line("                  </tbody>")
    text.line("                </table>")

    if previous_study_date is not None and previous_site is not None:
        text.line(
            "                <paragraph>Si confronta con il precedente controllo del ",
            Phi(
                previous_study_date.strftime(_ITALIAN_DATE),
                PhiCategory.DATE,
                "comparison date inside running prose",
            ),
            " eseguito presso ",
            Phi(
                previous_site.name,
                PhiCategory.INSTITUTION,
                "institution named in running prose, not in a header field",
            ),
            ".</paragraph>",
        )

    if injector.apply(
        "reports.identifier_in_prose",
        path,
        "ordering clinician named mid-sentence in the CDA narrative block, with no preceding label",
    ):
        text.line(
            "                <paragraph>Referto discusso con il collega ",
            Phi(
                panel.ordering_provider,
                PhiCategory.PROVIDER_NAME,
                "clinician named mid-sentence in a narrative block",
            ),
            ".</paragraph>",
        )

    # The patient named in the narrative as well as in the header. Ordinary
    # clinical writing -- a laboratory comment addresses the patient by name --
    # and therefore not a defect, but it is the case that makes the difference
    # between reading the header and scrubbing the body visible in a number.
    text.line(
        "                <paragraph>Esito comunicato a ",
        Phi(person.full_name, PhiCategory.PERSON_NAME, "patient named in a narrative block"),
        ".</paragraph>",
    )
    text.line("              </text>")


def _entry(text: AnnotatedText, panel: LabPanel) -> None:
    """Write the Level 3 entry: the same results, machine-readable.

    One ``entry`` with ``@typeCode="DRIV"``, holding one ``act``, holding a
    ``BATTERY`` organizer — which is §5.1.1.4's shape and is deliberately not
    the flattest one available. A reader that walked a single expected path
    would return no observations for a document shaped this way, and would do it
    silently, so generating the nested form is what proves the reader descends
    rather than walks.
    """
    text.line('              <entry typeCode="DRIV">')
    text.line('                <act classCode="ACT" moodCode="EVN">')
    text.line(
        f'                  <code code="{panel.panel_code}" '
        f'codeSystem="{_SYNTHETIC_ORGANISATION_ARC}.5.1" '
        f'displayName="{_literal(panel.panel_name)}"/>'
    )
    text.line('                  <statusCode code="completed"/>')
    text.line('                  <entryRelationship typeCode="COMP">')
    text.line('                    <organizer classCode="BATTERY" moodCode="EVN">')
    text.line('                      <statusCode code="completed"/>')
    for observation in panel.observations:
        _observation_element(text, observation)
    text.line("                    </organizer>")
    text.line("                  </entryRelationship>")
    text.line("                </act>")
    text.line("              </entry>")


def _observation_element(text: AnnotatedText, observation: LabObservation) -> None:
    """Write one analyte result as a Level 3 ``observation``."""
    low = _bound(observation.reference_low, observation.decimals)
    high = _bound(observation.reference_high, observation.decimals)
    quantitative = not isinstance(observation.value, str)

    text.line("                      <component>")
    text.line('                        <observation classCode="OBS" moodCode="EVN">')
    text.line(
        f'                          <code code="{_literal(observation.loinc_code)}" '
        f'codeSystem="{LOINC_SYSTEM}" codeSystemName="LOINC" '
        f'displayName="{_literal(observation.display)}"/>'
    )
    text.line('                          <statusCode code="completed"/>')
    text.line(
        f'                          <effectiveTime value="{_timestamp(observation.observed_at)}"/>'
    )
    if quantitative:
        text.line(
            f'                          <value xsi:type="PQ" '
            f'value="{_literal(_number(observation))}" '
            f'unit="{_literal(observation.unit)}"/>'
        )
    else:
        text.line(
            '                          <value xsi:type="ST">',
            _literal(_number(observation)),
            "</value>",
        )
    text.line(
        f"                          <interpretationCode "
        f'code="{observation.abnormal_flag.value}" '
        f'codeSystem="{_INTERPRETATION_SYSTEM}"/>'
    )
    if low and high:
        text.line("                          <referenceRange>")
        text.line("                            <observationRange>")
        text.line('                              <value xsi:type="IVL_PQ">')
        text.line(
            f'                                <low value="{low}" '
            f'unit="{_literal(observation.unit)}"/>'
        )
        text.line(
            f'                                <high value="{high}" '
            f'unit="{_literal(observation.unit)}"/>'
        )
        text.line("                              </value>")
        text.line("                            </observationRange>")
        text.line("                          </referenceRange>")
    text.line("                        </observation>")
    text.line("                      </component>")
