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

from datetime import datetime
from typing import Final

from commissura.annotate import AnnotatedText, Phi
from commissura.generate.defects import DefectInjector
from commissura.generate.vocabulary import Site
from commissura.models import (
    Enrolment,
    ForeignIdentity,
    LabObservation,
    LabPanel,
    Person,
    PhiCategory,
    PhiSpan,
)
from commissura.read.cda import (
    ADMINISTRATIVE_GENDER_SYSTEM,
    ANA_ROOT,
    CDA_NAMESPACE,
    CODICE_FISCALE_ROOT,
    CODICE_FISCALE_ROOT_MISPRINT,
    ENI_NATIONAL_ROOT,
    LOINC_SYSTEM,
    STP_NATIONAL_ROOT,
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

_LABORATORY_DOCUMENT_CODE: Final = "11502-2"
"""LOINC for a laboratory report, from the specification's own §4.1.5 example."""

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
        f'  <code code="{_LABORATORY_DOCUMENT_CODE}" codeSystem="{LOINC_SYSTEM}" '
        'codeSystemName="LOINC" displayName="Referto di laboratorio"/>'
    )
    text.line("  <title>Referto di Medicina di Laboratorio</title>")
    text.line(f'  <effectiveTime value="{_timestamp(panel.reported_at)}"/>')
    text.line(f'  <confidentialityCode code="V" codeSystem="{_CONFIDENTIALITY_SYSTEM}"/>')
    text.line('  <languageCode code="it-IT"/>')

    _record_target(text, person, codice_fiscale_root)
    _author(text, panel, site)
    _custodian(text, site)
    _legal_authenticator(text, panel, site, signed_by)

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


def _author(text: AnnotatedText, panel: LabPanel, site: Site) -> None:
    """Write the clinician who created the document."""
    text.line("  <author>")
    text.line(f'    <time value="{_timestamp(panel.reported_at)}"/>')
    text.line('    <assignedAuthor classCode="ASSIGNED">')
    text.line(f'      <id root="{_SYNTHETIC_ORGANISATION_ARC}.4.3" extension="AUT"/>')
    _clinician_elements(text, panel.ordering_provider, "      ")
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


def _legal_authenticator(text: AnnotatedText, panel: LabPanel, site: Site, signed_by: str) -> None:
    """Write the clinician who legally signed the document.

    Obligatory, and its ``assignedPerson/name`` must carry ``given`` and
    ``family`` (§4.1.17). So the signer that a plain-text report only reveals
    through a line beginning ``Dott.`` is, here, a defined element — which is the
    single clearest illustration of what reading a standard buys.
    """
    text.line("  <legalAuthenticator>")
    text.line(f'    <time value="{_timestamp(panel.reported_at)}"/>')
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
