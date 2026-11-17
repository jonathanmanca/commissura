"""The HL7 Italia CDA R2 laboratory reader.

Every assertion here is about a rule read from
``HL7IT-IG_CDA2_RefertoMedicinaLab-v1.3-S``, and the cases that matter most are
the ones the specification itself leaves awkward: a root it misprints in its own
example, two identifier kinds whose namespace it deliberately does not fix, and
a two-level section hierarchy where the human-readable content is on whichever
level is the leaf.

The documents here are hand-built, and deliberately so for the identifier kinds:
the cohort generator invents Italian residents with a codice fiscale, so TEAM,
ENI, STP and ANA are reachable from no generated corpus. The codice fiscale path
is exercised end to end from ``generate --cda`` as well, in
``test_cda_corpus.py``, because this project has three times found that a path
no corpus exercises is not covered whatever the coverage percentage says.
"""

from __future__ import annotations

from datetime import date

import pytest

from commissura.read.cda import (
    ANA_ROOT,
    CODICE_FISCALE_ROOT,
    CODICE_FISCALE_ROOT_MISPRINT,
    ENI_NATIONAL_ROOT,
    IDENTIFIER_KIND_BY_ROOT,
    LOINC_SYSTEM,
    STP_NATIONAL_ROOT,
    TEAM_CARD_ROOT,
    TEAM_PERSONAL_ROOT,
    CdaDocument,
    CdaParseError,
    parse_clinical_document,
    parse_document_tree,
)
from commissura.read.corpus import Identity
from commissura.read.identity import (
    AuthorityScope,
    IdentifierStatus,
    IdentityIndex,
    KeyKind,
    PatientIdentifierKind,
    Refusal,
    RefusalReason,
)

VALID_CF = "DLCFRN62S44X217H"
"""The same codice fiscale the shared person fixture uses, and it validates."""

REGIONAL_OID = "2.16.840.1.113883.2.9.2.120.4.1"
"""A plausible regional OID, in HL7 Italia's organisation arc. Not assigned."""


def document(
    *,
    ids: str,
    body: str | None = None,
    effective_time: str = "20240115103000+0100",
    encounter: str = "0048812",
) -> str:
    """Return a minimal but conformant-shaped CDA laboratory report.

    Minimal in the elements this reader looks at and nothing else, so that a
    failing assertion points at the rule under test rather than at whichever of
    forty optional elements happened to be missing.

    Args:
        ids: The ``patientRole/id`` elements, as markup.
        body: The ``structuredBody`` contents, or ``None`` for a default
            single-level section.
        effective_time: ``ClinicalDocument/effectiveTime``.
        encounter: The numero nosologico.

    Returns:
        The document text.
    """
    if body is None:
        body = f"""
      <component>
        <section>
          <code code="18723-7" codeSystem="{LOINC_SYSTEM}" codeSystemName="LOINC"
                displayName="EMATOLOGIA"/>
          <text><paragraph>Prelievo nella norma.</paragraph></text>
        </section>
      </component>"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ClinicalDocument xmlns="urn:hl7-org:v3" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <id root="2.16.840.1.113883.2.9.2.999.4.6" extension="DOC1"/>
  <code code="11502-2" codeSystem="{LOINC_SYSTEM}" codeSystemName="LOINC"
        displayName="Referto di laboratorio"/>
  <title>Referto di Medicina di Laboratorio</title>
  <effectiveTime value="{effective_time}"/>
  <recordTarget>
    <patientRole>
{ids}
      <patient>
        <name><family>DE LUCA</family><given>FRANCESCA</given></name>
        <administrativeGenderCode code="F" codeSystem="2.16.840.1.113883.5.1"/>
        <birthTime value="19621104"/>
      </patient>
    </patientRole>
  </recordTarget>
  <author>
    <time value="{effective_time}"/>
    <assignedAuthor>
      <assignedPerson><name><family>ROSSI</family><given>MARIO</given></name></assignedPerson>
    </assignedAuthor>
  </author>
  <custodian>
    <assignedCustodian>
      <representedCustodianOrganization>
        <id root="2.16.840.1.113883.2.9.4.1.1" extension="999999"/>
        <name>OSPEDALE SINTETICO DI COLLEVERDE</name>
      </representedCustodianOrganization>
    </assignedCustodian>
  </custodian>
  <legalAuthenticator>
    <time value="{effective_time}"/>
    <signatureCode code="S"/>
    <assignedEntity>
      <assignedPerson><name><family>BIANCHI</family><given>ANNA</given></name></assignedPerson>
    </assignedEntity>
  </legalAuthenticator>
  <inFulfillmentOf><order><id root="X" extension="LAB1"/></order></inFulfillmentOf>
  <componentOf>
    <encompassingEncounter>
      <id root="{REGIONAL_OID}" extension="{encounter}"/>
      <effectiveTime value="{effective_time}"/>
    </encompassingEncounter>
  </componentOf>
  <component>
    <structuredBody>{body}
    </structuredBody>
  </component>
</ClinicalDocument>
"""


def cf_id(root: str = CODICE_FISCALE_ROOT, *, authority: str = "MEF", value: str = VALID_CF) -> str:
    """Return a codice fiscale ``id`` element."""
    return f'      <id root="{root}" extension="{value}" assigningAuthorityName="{authority}"/>'


# --------------------------------------------------------------------------
# The codice fiscale, and the root the specification misprints
# --------------------------------------------------------------------------


def test_the_correct_root_yields_a_national_identity() -> None:
    """Tabella 16's root is what a conformant document carries."""
    parsed = parse_clinical_document(document(ids=cf_id()))

    assert parsed.codice_fiscale == VALID_CF
    assert not parsed.misdeclared_codice_fiscale
    assert [item.kind for item in parsed.identifiers] == [PatientIdentifierKind.CODICE_FISCALE]
    assert parsed.identifiers[0].status is IdentifierStatus.VALID


def test_the_misprinted_root_never_passes_silently() -> None:
    """The example's extra ``.2`` is always reported, however it is then read.

    The whole risk of a misprint in a specification is that an implementer
    copies it and nobody finds out. A document carrying it must therefore make
    a statement no caller can miss, which is what
    ``misdeclared_codice_fiscale`` is for.
    """
    parsed = parse_clinical_document(document(ids=cf_id(CODICE_FISCALE_ROOT_MISPRINT)))

    assert parsed.misdeclared_codice_fiscale
    # The two constants differing is proven statically: both are ``Final`` with
    # literal types, and mypy rejects comparing them as non-overlapping. That is
    # a stronger guarantee than a runtime assertion, so there is not one here.
    #
    # What a type checker cannot see is that the misprinted root must stay out
    # of the root-to-kind table. Mapping it there would make it
    # indistinguishable from the correct one, which is the whole failure this
    # constant exists to prevent.
    assert CODICE_FISCALE_ROOT_MISPRINT not in IDENTIFIER_KIND_BY_ROOT
    assert CODICE_FISCALE_ROOT in IDENTIFIER_KIND_BY_ROOT


@pytest.mark.parametrize(
    "authority", ["MEF", "Ministero Economia e Finanze", "Ministero delle Finanze", "mef"]
)
def test_the_misprinted_root_is_read_as_a_codice_fiscale_when_corroborated(
    authority: str,
) -> None:
    """All three spellings the specification itself uses, and case does not matter.

    The element names the authority as well as the namespace, so where the name
    is the MEF's and the value is a well-formed codice fiscale, the document
    agrees with itself about what the element is and only the OID's digits
    disagree. Refusing it there splits one patient into two subjects, which was
    measured before this rule existed.
    """
    parsed = parse_clinical_document(
        document(ids=cf_id(CODICE_FISCALE_ROOT_MISPRINT, authority=authority))
    )

    assert parsed.misdeclared_codice_fiscale
    assert parsed.codice_fiscale == VALID_CF


def test_the_misprinted_root_is_not_a_national_key_without_corroboration() -> None:
    """Uncorroborated, it stays inside its own namespace and never merges.

    That OID lies in HL7 Italia's regional and organisation arc, so it may be
    somebody's real local namespace. Minting a *national* key from it is the
    error that merges two people and silently breaks redaction for the second.
    """
    parsed = parse_clinical_document(
        document(ids=cf_id(CODICE_FISCALE_ROOT_MISPRINT, authority="AZIENDA LOCALE"))
    )

    assert parsed.misdeclared_codice_fiscale
    assert parsed.codice_fiscale == ""
    assert parsed.identifiers[0].kind is PatientIdentifierKind.UNRECOGNISED

    index = IdentityIndex()
    resolved = index.establish(
        parsed_identity(parsed), scope_of(parsed), assigned=parsed.identifiers
    )
    assert not isinstance(resolved, Refusal)
    key, _ = resolved
    assert key.kind is KeyKind.ASSIGNED_IDENTIFIER
    assert key.authority == CODICE_FISCALE_ROOT_MISPRINT


def test_a_misprinted_root_with_an_invalid_value_is_not_a_codice_fiscale() -> None:
    """Corroboration is not a licence to skip the checksum."""
    parsed = parse_clinical_document(
        document(ids=cf_id(CODICE_FISCALE_ROOT_MISPRINT, value="DLCFRN62S44X217A"))
    )

    assert parsed.identifiers[0].kind is PatientIdentifierKind.CODICE_FISCALE
    assert parsed.identifiers[0].status is IdentifierStatus.BAD_CHECKSUM


# --------------------------------------------------------------------------
# The four other identifier kinds
# --------------------------------------------------------------------------


def test_a_team_document_carries_two_ids_and_only_one_of_them_keys_a_person() -> None:
    """The specification requires both, and a card is not a person.

    A TEAM card is reissued on expiry or loss. Keying on the card number would
    make one patient two subjects across a reissue, and two patients one subject
    across a recycled serial, so only the personal number may establish a
    subject — while both are still read, and therefore both still redacted.
    """
    ids = (
        f'      <id root="{TEAM_CARD_ROOT}" '
        'extension="NLD.096074309.80528070070000000001" '
        'assigningAuthorityName="ZORGINSTITUUT"/>\n'
        f'      <id root="{TEAM_PERSONAL_ROOT}" extension="NLD.4637465980125364" '
        'assigningAuthorityName="ZORGINSTITUUT"/>'
    )
    parsed = parse_clinical_document(document(ids=ids))

    kinds = [item.kind for item in parsed.identifiers]
    assert kinds == [PatientIdentifierKind.TEAM_CARD, PatientIdentifierKind.TEAM_PERSONAL]
    assert all(item.status is IdentifierStatus.VALID for item in parsed.identifiers)
    assert parsed.codice_fiscale == ""

    card, personal = parsed.identifiers
    assert not card.keys_a_person
    assert personal.keys_a_person

    index = IdentityIndex()
    resolved = index.establish(
        parsed_identity(parsed), scope_of(parsed), assigned=parsed.identifiers
    )
    assert not isinstance(resolved, Refusal)
    key, _ = resolved
    assert key.kind is KeyKind.ASSIGNED_IDENTIFIER
    assert key.authority == TEAM_PERSONAL_ROOT
    assert key.value == "NLD.4637465980125364"


def test_a_team_card_serial_may_itself_contain_dots() -> None:
    """The specification's own example splits on the first dot and no other."""
    ids = f'      <id root="{TEAM_CARD_ROOT}" extension="NLD.096074309.80528070070000000001"/>'
    parsed = parse_clinical_document(document(ids=ids))

    assert parsed.identifiers[0].status is IdentifierStatus.VALID


@pytest.mark.parametrize("prefix", ["ENI", "STP"])
def test_a_regional_code_is_recognised_by_its_own_prefix(prefix: str) -> None:
    """The root is a local OID, so the value is the only thing that can say.

    This is the case the specification creates and does not solve: an ENI or STP
    code assigned regionally carries "l'OID locale assegnato
    dall'organizzazione", which no reader can enumerate. The same table fixes
    the prefix, so the value declares its own kind — and refusing these would
    turn away exactly the population the codes exist for.
    """
    code = f"{prefix}1234567890ABC"
    parsed = parse_clinical_document(
        document(ids=f'      <id root="{REGIONAL_OID}" extension="{code}"/>')
    )

    identifier = parsed.identifiers[0]
    assert identifier.kind is PatientIdentifierKind[prefix]
    assert identifier.status is IdentifierStatus.VALID
    assert identifier.authority == REGIONAL_OID

    index = IdentityIndex()
    resolved = index.establish(
        parsed_identity(parsed), scope_of(parsed), assigned=parsed.identifiers
    )
    assert not isinstance(resolved, Refusal)
    key, _ = resolved
    # Scoped to the issuing namespace, which is what makes it honest: a
    # regionally assigned code is relinkable inside that region and nowhere
    # else, and the key says which region.
    assert key.kind is KeyKind.ASSIGNED_IDENTIFIER
    assert key.authority == REGIONAL_OID
    assert key.value == code


@pytest.mark.parametrize(
    ("root", "prefix"), [(ENI_NATIONAL_ROOT, "ENI"), (STP_NATIONAL_ROOT, "STP")]
)
def test_a_nationally_assigned_code_is_recognised_by_its_root(root: str, prefix: str) -> None:
    """Where the specification does fix the OID, the OID is enough."""
    parsed = parse_clinical_document(
        document(ids=f'      <id root="{root}" extension="{prefix}1234567890ABC"/>')
    )

    assert parsed.identifiers[0].kind is PatientIdentifierKind[prefix]
    assert parsed.identifiers[0].status is IdentifierStatus.VALID


@pytest.mark.parametrize("code", ["ENI123", "ENI1234567890ABCD", "XYZ1234567890ABC"])
def test_a_malformed_regional_code_is_not_rescued_by_looking_like_one(code: str) -> None:
    """Sixteen characters and the right three letters, or it is not that kind.

    Too short, too long, and the right length with the wrong prefix. The third
    is the interesting one: under an unknown root with no recognisable prefix
    there is nothing to validate against, so it stays unrecognised rather than
    being scored against a rule it never claimed to follow.
    """
    parsed = parse_clinical_document(
        document(ids=f'      <id root="{REGIONAL_OID}" extension="{code}"/>')
    )

    identifier = parsed.identifiers[0]
    if identifier.kind is PatientIdentifierKind.UNRECOGNISED:
        assert identifier.status is IdentifierStatus.VALID
    else:
        assert identifier.status is IdentifierStatus.MALFORMED


def test_an_ana_code_is_keyed_on_its_fixed_root_and_validated_no_further() -> None:
    """ANA is implementable: the root is a ``DEVE`` and only details are deferred.

    The specification's footnote defers "maggiori dettagli" to a later release,
    which reads like deferring the whole case; Tabella 21 already fixes the
    root. What is genuinely absent is any rule about the value, so nothing is
    invented about it.
    """
    parsed = parse_clinical_document(
        document(ids=f'      <id root="{ANA_ROOT}" extension="ANA-0000-1"/>')
    )

    identifier = parsed.identifiers[0]
    assert identifier.kind is PatientIdentifierKind.ANA
    assert identifier.status is IdentifierStatus.VALID


def test_a_placeholder_is_refused_whatever_kind_it_is_offered_as() -> None:
    """The module's central rule survives the new kinds.

    Missing identity is not shared identity. An export writing ``UNKNOWN`` into
    an ENI field has said nothing about the patient, and two documents that both
    said nothing have nothing in common — the defect that leaked a name in the
    audit of 2026-11-13.
    """
    parsed = parse_clinical_document(
        document(ids=f'      <id root="{ENI_NATIONAL_ROOT}" extension="UNKNOWN"/>', encounter="")
    )

    assert parsed.identifiers[0].status is IdentifierStatus.PLACEHOLDER

    index = IdentityIndex()
    resolved = index.establish(
        parsed_identity(parsed), scope_of(parsed), assigned=parsed.identifiers
    )
    assert isinstance(resolved, Refusal)
    assert resolved.reason is RefusalReason.NO_USABLE_IDENTIFIER


def test_a_document_with_no_usable_identifier_falls_back_to_its_record_number() -> None:
    """Unusable is a diagnosis, not a dead end.

    The numero nosologico still identifies the patient within the institution
    that issued it, so the subject exists and is reported as not relinkable
    across institutions rather than discarded.
    """
    parsed = parse_clinical_document(
        document(ids=f'      <id root="{ENI_NATIONAL_ROOT}" extension="NULL"/>')
    )

    index = IdentityIndex()
    resolved = index.establish(
        parsed_identity(parsed), scope_of(parsed), assigned=parsed.identifiers
    )
    assert not isinstance(resolved, Refusal)
    key, _ = resolved
    assert key.kind is KeyKind.SCOPED_RECORD_NUMBER
    assert key.value == "48812"


def test_an_id_with_no_extension_is_not_an_identifier() -> None:
    """An empty ``id`` contributes nothing and must not be counted as a kind."""
    parsed = parse_clinical_document(
        document(ids=f'      <id root="{CODICE_FISCALE_ROOT}"/>\n{cf_id()}')
    )

    assert len(parsed.identifiers) == 1
    assert parsed.codice_fiscale == VALID_CF


# --------------------------------------------------------------------------
# The header's other PHI, which a plain-text reader has to guess at
# --------------------------------------------------------------------------


def test_the_header_states_the_things_a_template_would_have_to_be_guessed() -> None:
    """Name, sex, birth date, signer and custodian, each in a defined element."""
    parsed = parse_clinical_document(document(ids=cf_id()))

    assert parsed.family_name == "DE LUCA"
    assert parsed.given_name == "FRANCESCA"
    assert parsed.sex == "F"
    assert parsed.birth_date == date(1962, 11, 4)
    assert parsed.record_number == "0048812"
    assert parsed.custodian_name == "OSPEDALE SINTETICO DI COLLEVERDE"
    assert parsed.author_name == "MARIO ROSSI"
    # The one name a plain-text report declares nowhere but a line beginning
    # "Dott.", which here is an obligatory element with obligatory children.
    assert parsed.signed_by == "ANNA BIANCHI"


def test_a_document_with_no_patient_element_still_parses() -> None:
    """Tolerant where it can be: only ``patientRole`` is load-bearing.

    ``patient`` is obligatory in the specification, but a reader that raised on
    its absence could not be used to measure how a dataset copes with an export
    that omits it — the asymmetry decided on 2026-11-07.
    """
    text = document(ids=cf_id()).replace(
        """      <patient>
        <name><family>DE LUCA</family><given>FRANCESCA</given></name>
        <administrativeGenderCode code="F" codeSystem="2.16.840.1.113883.5.1"/>
        <birthTime value="19621104"/>
      </patient>
""",
        "",
    )
    parsed = parse_clinical_document(text)

    assert parsed.codice_fiscale == VALID_CF
    assert parsed.family_name == ""
    assert parsed.sex == ""
    assert parsed.birth_date is None


# --------------------------------------------------------------------------
# The body: two levels, and the narrative on whichever one is the leaf
# --------------------------------------------------------------------------


NESTED_BODY = f"""
      <component>
        <section>
          <code code="18723-7" codeSystem="{LOINC_SYSTEM}" codeSystemName="LOINC"
                displayName="EMATOLOGIA"/>
          <title>EMATOLOGIA</title>
          <component>
            <section>
              <code code="CBC" codeSystem="2.16.840.1.113883.2.9.2.999.5.1"
                    codeSystemName="Codifica locale" displayName="Emocromo completo"/>
              <text>
                <paragraph>Prelievo eseguito in data 15/01/2024.</paragraph>
                <table><tbody>
                  <tr><td>Emoglobina</td><td>13.2 g/dL</td><td>12.0-15.5</td></tr>
                </tbody></table>
              </text>
              <entry typeCode="DRIV">
                <act classCode="ACT" moodCode="EVN">
                  <entryRelationship typeCode="COMP">
                    <organizer classCode="BATTERY" moodCode="EVN">
                      <component>
                        <observation classCode="OBS" moodCode="EVN">
                          <code code="718-7" codeSystem="{LOINC_SYSTEM}"
                                displayName="Emoglobina"/>
                          <effectiveTime value="20240115090000+0100"/>
                          <value xsi:type="PQ" value="13.2" unit="g/dL"/>
                          <interpretationCode code="N"/>
                          <referenceRange><observationRange>
                            <value xsi:type="IVL_PQ">
                              <low value="12.0" unit="g/dL"/>
                              <high value="15.5" unit="g/dL"/>
                            </value>
                          </observationRange></referenceRange>
                        </observation>
                      </component>
                    </organizer>
                  </entryRelationship>
                </act>
              </entry>
            </section>
          </component>
        </section>
      </component>"""


def test_the_narrative_is_read_from_the_leaf_section() -> None:
    """A specialty section with leaves must not carry ``section/text``.

    So the human-readable content of a nested document is entirely on the
    leaves, and a reader that only looked at the top level would report an empty
    narrative — the worst available outcome, because the scrubber would then
    report nothing to remove and the build would succeed.
    """
    parsed = parse_clinical_document(document(ids=cf_id(), body=NESTED_BODY))

    assert "Prelievo eseguito in data 15/01/2024." in parsed.narrative
    assert "Emoglobina" in parsed.narrative
    assert "EMATOLOGIA" in parsed.narrative


def test_narrative_table_cells_do_not_run_together() -> None:
    """Two values joined into one token are a token no redaction can find.

    The CDA Narrative Block is its own markup, so flattening it without
    separators is not merely ugly: it manufactures strings that exact-match
    scrubbing cannot see.
    """
    parsed = parse_clinical_document(document(ids=cf_id(), body=NESTED_BODY))

    assert "13.2 g/dL" in parsed.narrative
    assert "dL12.0" not in parsed.narrative


def test_results_are_found_through_the_organizer_nesting() -> None:
    """Descent, not one expected path.

    The specification permits a ``BATTERY`` organizer, a ``CLUSTER`` organizer
    or a direct observation. A reader keyed to one of those returns nothing for
    a document using another, silently.
    """
    parsed = parse_clinical_document(document(ids=cf_id(), body=NESTED_BODY))

    assert len(parsed.observations) == 1
    observation = parsed.observations[0]
    assert observation.code == "718-7"
    assert observation.code_system == LOINC_SYSTEM
    assert observation.value == "13.2"
    assert observation.unit == "g/dL"
    assert observation.reference_low == "12.0"
    assert observation.reference_high == "15.5"
    assert observation.interpretation == "N"


def test_a_result_is_counted_once_and_not_once_per_level() -> None:
    """Descending from the specialty section too would double every result.

    The specialty section's subtree contains its leaves', so gathering results
    at both levels reports every measurement twice — in the document an auditor
    reads, as a count of what the dataset holds.
    """
    parsed = parse_clinical_document(document(ids=cf_id(), body=NESTED_BODY))

    assert len(parsed.sections) == 2
    assert parsed.sections[0].observations == ()
    assert len(parsed.sections[1].observations) == 1
    assert len(parsed.observations) == 1


def test_a_leaf_section_code_need_not_be_loinc() -> None:
    """LOINC is mandatory for the specialty code and optional for the leaf's.

    §5.1.1.1 fixes the specialty section's ``codeSystem`` to the LOINC OID;
    §5.1.2.1 permits "sia una codifica locale che la codifica LOINC" for a leaf.
    "CDA requires LOINC for section/code" is true of one level only.
    """
    parsed = parse_clinical_document(document(ids=cf_id(), body=NESTED_BODY))

    specialty, leaf = parsed.sections
    assert specialty.code_system == LOINC_SYSTEM
    assert leaf.code_system != LOINC_SYSTEM
    assert leaf.code == "CBC"


def test_a_non_quantitative_result_keeps_its_text() -> None:
    """A direct Coombs test reports NEGATIVO, not a number."""
    body = f"""
      <component>
        <section>
          <code code="18727-8" codeSystem="{LOINC_SYSTEM}" displayName="SEROLOGIA"/>
          <text><paragraph>Esito.</paragraph></text>
          <entry typeCode="DRIV">
            <observation classCode="OBS" moodCode="EVN">
              <code code="1006-1" codeSystem="{LOINC_SYSTEM}" displayName="Coombs diretto"/>
              <value xsi:type="ST">NEGATIVO</value>
            </observation>
          </entry>
        </section>
      </component>"""
    parsed = parse_clinical_document(document(ids=cf_id(), body=body))

    assert parsed.observations[0].value == "NEGATIVO"
    assert parsed.observations[0].unit == ""


def test_an_observation_with_no_value_is_not_a_result() -> None:
    """A structural or narrative-only observation must not become an empty row."""
    body = f"""
      <component>
        <section>
          <code code="18727-8" codeSystem="{LOINC_SYSTEM}" displayName="SEROLOGIA"/>
          <text><paragraph>Esito.</paragraph></text>
          <entry typeCode="DRIV">
            <observation classCode="OBS" moodCode="EVN">
              <code code="1006-1" codeSystem="{LOINC_SYSTEM}" displayName="Coombs diretto"/>
            </observation>
            <observation classCode="OBS" moodCode="EVN">
              <value xsi:type="ST">orfano</value>
            </observation>
          </entry>
        </section>
      </component>"""
    parsed = parse_clinical_document(document(ids=cf_id(), body=body))

    assert parsed.observations == ()


def test_a_document_with_no_body_has_no_narrative_and_no_report() -> None:
    """An empty narrative must be an absence, not an empty string pretending."""
    parsed = parse_clinical_document(document(ids=cf_id(), body=""))

    assert parsed.sections == ()
    assert parsed.narrative == ""
    assert parsed.specialty is None


# --------------------------------------------------------------------------
# Untrusted input
# --------------------------------------------------------------------------


BILLION_LAUGHS = """<?xml version="1.0"?>
<!DOCTYPE lolz [
 <!ENTITY lol "lol">
 <!ENTITY lol1 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
 <!ENTITY lol2 "&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;">
]>
<ClinicalDocument xmlns="urn:hl7-org:v3"><title>&lol2;</title></ClinicalDocument>"""


def test_a_document_declaring_a_dtd_is_refused() -> None:
    """Entity expansion is a denial of service, checked rather than recalled.

    ``xml.etree.ElementTree`` refuses *external* entities on this interpreter —
    verified — but expands internal ones, so a billion-laughs document is a real
    attack on a tool somebody points at a directory of hospital exports. CDA R2
    is schema-defined and has no use for a DTD, so refusing one costs nothing.
    """
    with pytest.raises(CdaParseError, match="DTD"):
        parse_clinical_document(BILLION_LAUGHS)


def test_an_external_entity_cannot_reach_the_filesystem() -> None:
    """The parser's own refusal, pinned so a change in it would be noticed."""
    external = (
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE r [<!ENTITY ext SYSTEM "file:///etc/passwd">]>\n'
        '<ClinicalDocument xmlns="urn:hl7-org:v3"><title>&ext;</title></ClinicalDocument>'
    )
    with pytest.raises(CdaParseError):
        parse_clinical_document(external)


def test_a_doctype_inside_the_narrative_does_not_refuse_the_document() -> None:
    """Only the prolog is scanned, because a comment is not a declaration.

    A plain substring search would refuse a perfectly good report that happened
    to quote ``<!DOCTYPE`` in its narrative, and a reader that refuses valid
    clinical documents is one somebody works around.
    """
    body = f"""
      <component>
        <section>
          <code code="18723-7" codeSystem="{LOINC_SYSTEM}" displayName="EMATOLOGIA"/>
          <text><paragraph>Il referto citava &lt;!DOCTYPE html&gt; nel testo.</paragraph></text>
        </section>
      </component>"""
    parsed = parse_clinical_document(document(ids=cf_id(), body=body))

    assert "<!DOCTYPE html>" in parsed.narrative


def test_a_comment_in_the_prolog_does_not_hide_a_doctype() -> None:
    """The scanner steps over a prolog comment and keeps looking."""
    text = BILLION_LAUGHS.replace('<?xml version="1.0"?>', "<!-- un commento -->")
    with pytest.raises(CdaParseError, match="DTD"):
        parse_clinical_document(text)


def test_an_unterminated_prolog_comment_is_left_to_the_parser() -> None:
    """Not well-formed either way, and the parser's message is the better one."""
    with pytest.raises(CdaParseError, match="not well-formed"):
        parse_clinical_document('<!-- mai chiuso <ClinicalDocument xmlns="urn:hl7-org:v3"/>')


def test_malformed_xml_is_a_value_error_so_the_corpus_reader_survives_it() -> None:
    """One bad file must cost one linkage issue, not the whole corpus."""
    assert issubclass(CdaParseError, ValueError)
    with pytest.raises(CdaParseError, match="not well-formed"):
        parse_clinical_document("<ClinicalDocument><unclosed>")


def test_a_document_that_is_not_a_clinical_document_is_refused() -> None:
    """Including one in no namespace, which is the commonest mistake."""
    with pytest.raises(CdaParseError, match="ClinicalDocument"):
        parse_clinical_document('<?xml version="1.0"?><ClinicalDocument><id/></ClinicalDocument>')
    with pytest.raises(CdaParseError, match="ClinicalDocument"):
        parse_clinical_document('<Bundle xmlns="urn:hl7-org:v3"/>')


def test_a_document_with_no_patient_role_is_refused() -> None:
    """The one element whose absence leaves nothing to attribute the file to."""
    with pytest.raises(CdaParseError, match="patientRole"):
        parse_clinical_document(
            '<?xml version="1.0"?>'
            '<ClinicalDocument xmlns="urn:hl7-org:v3"><title>x</title></ClinicalDocument>'
        )


def test_text_with_no_markup_declares_no_doctype() -> None:
    """The scanner has to terminate on text that never opens an element."""
    with pytest.raises(CdaParseError, match="not well-formed"):
        parse_clinical_document("nessun markup qui")


@pytest.mark.parametrize(
    "removed",
    [
        '  <author>\n    <time value="20240115103000+0100"/>\n'
        "    <assignedAuthor>\n"
        "      <assignedPerson><name><family>ROSSI</family><given>MARIO</given></name>"
        "</assignedPerson>\n"
        "    </assignedAuthor>\n  </author>\n",
        '  <legalAuthenticator>\n    <time value="20240115103000+0100"/>\n'
        '    <signatureCode code="S"/>\n'
        "    <assignedEntity>\n"
        "      <assignedPerson><name><family>BIANCHI</family><given>ANNA</given></name>"
        "</assignedPerson>\n"
        "    </assignedEntity>\n  </legalAuthenticator>\n",
    ],
    ids=["no-author", "no-legal-authenticator"],
)
def test_a_missing_clinician_element_is_an_empty_name_not_a_crash(removed: str) -> None:
    """Both are obligatory and a reader that raised could not measure a corpus.

    An export that omits one is exactly the kind of damage this project
    generates on purpose elsewhere, so the reader reports an empty name and lets
    the pipeline record what it could not find.
    """
    text = document(ids=cf_id()).replace(removed, "")
    assert removed not in text

    parsed = parse_clinical_document(text)

    assert parsed.codice_fiscale == VALID_CF
    assert "" in {parsed.author_name, parsed.signed_by}


def test_an_assigned_person_with_no_name_element_yields_an_empty_name() -> None:
    """Present but empty is a different shape from absent, and both occur."""
    text = document(ids=cf_id()).replace(
        "<assignedPerson><name><family>BIANCHI</family><given>ANNA</given></name></assignedPerson>",
        "<assignedPerson/>",
    )
    parsed = parse_clinical_document(text)

    assert parsed.signed_by == ""


def test_an_observation_whose_value_carries_nothing_is_not_a_result() -> None:
    """An empty ``value`` element is not a measurement of zero."""
    body = f"""
      <component>
        <section>
          <code code="18727-8" codeSystem="{LOINC_SYSTEM}" displayName="SEROLOGIA"/>
          <text><paragraph>Esito.</paragraph></text>
          <entry typeCode="DRIV">
            <observation classCode="OBS" moodCode="EVN">
              <code code="1006-1" codeSystem="{LOINC_SYSTEM}" displayName="Coombs"/>
              <value xsi:type="ST"></value>
            </observation>
          </entry>
        </section>
      </component>"""
    parsed = parse_clinical_document(document(ids=cf_id(), body=body))

    assert parsed.observations == ()


def test_a_section_with_neither_heading_nor_narrative_contributes_nothing() -> None:
    """An empty section must not pad the narrative with blank blocks.

    A narrative made of separators is one the scrubber reports as having had
    nothing to remove, which reads exactly like a clean document.
    """
    body = """
      <component>
        <section>
          <code code=""/>
        </section>
      </component>"""
    parsed = parse_clinical_document(document(ids=cf_id(), body=body))

    assert len(parsed.sections) == 1
    assert parsed.narrative == ""


def test_the_tree_parser_is_the_same_gate() -> None:
    """``observe`` walks the document too, and must not reach around the refusal."""
    with pytest.raises(CdaParseError, match="DTD"):
        parse_document_tree(BILLION_LAUGHS)
    assert parse_document_tree(document(ids=cf_id())).tag.endswith("ClinicalDocument")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def parsed_identity(parsed: CdaDocument) -> Identity:
    """Return the identity a parsed document implies."""
    return Identity(
        national_id=parsed.codice_fiscale,
        mrn=parsed.record_number,
        family_name=parsed.family_name,
        given_name=parsed.given_name,
        sex=None,
        birth_date=parsed.birth_date,
    )


def scope_of(parsed: CdaDocument) -> AuthorityScope:
    """Return the authority scope the corpus reader would use for a document.

    The custodian's *name*, not the encounter identifier's OID, which is the
    choice :func:`commissura.read.corpus.read_cda` makes and defends: a record
    number only joins across modalities if HL7, DICOM and CDA name the authority
    the same way, and only CDA has an OID for it.
    """
    return AuthorityScope(sending_facility=parsed.custodian_name)
