"""Identity resolution: who a record belongs to, and when we refuse to say.

These tests exist because the audit of 2026-11-13 found that this was the one
step in the pipeline with no layer, no model and no adversarial tests. Every
earlier test of ``read_corpus`` supplied a corpus in which identity was
unambiguous, so the *mechanics* of linkage were thoroughly exercised and the
*semantics* not at all. 99.11% branch coverage coexisted with a critical
finding.

The scenarios here are the ones that were missing. Each one failed before the
identity index existed, and the four marked in their docstrings are the ones
whose absence let a patient's name reach a built dataset.

Every identifier in this file is synthetic. The codice fiscali are assembled
with :func:`commissura.identifiers.codice_fiscale` from an ``X`` place code,
which no registry assigns, so they are checksum-valid and cannot belong to
anybody.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from commissura.build.writer import BuildSpec, build_dataset
from commissura.deident.keys import SecretKey
from commissura.deident.pseudonymise import Pseudonymiser
from commissura.identifiers import cf_check_character, codice_fiscale
from commissura.models import Sex
from commissura.read.corpus import read_corpus
from commissura.read.identity import (
    UNSCOPED_AUTHORITY,
    AuthorityScope,
    IdentifierStatus,
    IdentityIndex,
    IdentityKey,
    KeyKind,
    Refusal,
    RefusalReason,
    classify_national_id,
    normalise_national_id,
    normalise_record_number,
)

CR = "\r"
KEY = SecretKey(bytes(range(32)))

ROSSI = codice_fiscale("ROSSI", "MARIO", date(1980, 1, 1), Sex.MALE, "X001")
BIANCHI = codice_fiscale("BIANCHI", "LUCIA", date(1975, 6, 12), Sex.FEMALE, "X002")
VERDI = codice_fiscale("VERDI", "GIUSEPPE", date(1960, 3, 4), Sex.MALE, "X003")

HOSPITAL_A = "PRESIDIO SINTETICO VALLEDORO"
HOSPITAL_B = "POLICLINICO SINTETICO PIETRALTA"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _message(
    *,
    national_id: str,
    mrn: str,
    family: str,
    given: str,
    birth: str = "19800101",
    sex: str = "M",
    authority: str = HOSPITAL_A,
    facility: str = HOSPITAL_A,
    collected: str = "20240301090000",
    typed_authority: bool = True,
) -> str:
    """Return one HL7 ORU^R01 message, segments terminated by a bare CR."""
    scope = f"^^^{authority}^MR" if typed_authority else "^^^^MR"
    identifiers = f"{mrn}{scope}"
    if national_id:
        identifiers += f"~{national_id}^^^MINSAL^NNITA"
    return (
        CR.join(
            [
                f"MSH|^~\\&|LIS|{facility}|COMMISSURA|RESEARCH|{collected}||ORU^R01|M1|P|2.5.1",
                f"PID|1||{identifiers}||{family}^{given}||{birth}|{sex}",
                f"OBR|1|ACC1^LIS|ACC1^LAB|INFL^Indici^L|||{collected}",
                "OBX|1|NM|718-7^Emoglobina||13.0|g/dL|12.0-16.0|N|||F",
            ]
        )
        + CR
    )


def _report(*, national_id: str, mrn: str, family: str, given: str) -> str:
    """Return one free-text report header naming the patient, as the reader expects it."""
    return (
        f"{HOSPITAL_A}\nVia dei Tigli 40 - Milano\n\n"
        "REFERTO\n\n"
        f"Paziente: {given} {family}\n"
        f"Codice fiscale: {national_id}\n"
        f"Numero nosografico: {mrn}\n"
        "Data del referto: 02/03/2024\n\n"
        "QUESITO CLINICO\nControllo di routine.\n"
    )


def _imaging(*, patient_id: str, institution: str, study_date: str = "20240302") -> str:
    """Return one DICOM JSON Model sidecar as a single-series array."""
    return (
        "[{"
        f'"00100020": {{"vr": "LO", "Value": ["{patient_id}"]}},'
        f'"00100010": {{"vr": "PN", "Value": [{{"Alphabetic": "ROSSI^MARIO"}}]}},'
        f'"00080080": {{"vr": "LO", "Value": ["{institution}"]}},'
        f'"00080081": {{"vr": "ST", "Value": ["Via dei Tigli 40"]}},'
        f'"00080050": {{"vr": "SH", "Value": ["RAD1"]}},'
        f'"0020000D": {{"vr": "UI", "Value": ["2.25.1"]}},'
        f'"0020000E": {{"vr": "UI", "Value": ["2.25.2"]}},'
        f'"00080020": {{"vr": "DA", "Value": ["{study_date}"]}},'
        f'"00080060": {{"vr": "CS", "Value": ["CT"]}},'
        f'"00280301": {{"vr": "CS", "Value": ["NO"]}}'
        "}]"
    )


def _write(path: Path, text: str) -> None:
    """Write exact characters: no newline translation, because HL7 uses bare CR."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def _corpus(root: Path, **files: str) -> Path:
    """Write a corpus from ``relative/path.ext=contents`` keyword arguments."""
    for name, text in files.items():
        _write(root / name.replace("__", "/"), text)
    return root


def _reasons(corpus: object) -> list[str]:
    """Return the linkage-issue reasons, sorted, for order-independent assertions."""
    return sorted(issue.reason for issue in corpus.issues)  # type: ignore[attr-defined]


# --------------------------------------------------------------------------
# Classifying a value offered as a national identifier
# --------------------------------------------------------------------------


def test_the_generators_own_identifiers_all_validate() -> None:
    """The validator must accept the only corpus available to test it against.

    The synthetic codice fiscali use the unassigned ``X`` place range so they
    cannot belong to anybody, and the generator computes the check character
    correctly — a decision taken on 2026-11-06 precisely so the values would
    "exercise a real validator rather than bouncing off it". This is that
    validator, and this test is what makes the two halves of that decision meet.
    """
    for value in (ROSSI, BIANCHI, VERDI):
        assert classify_national_id(value).status is IdentifierStatus.VALID


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", IdentifierStatus.MISSING),
        ("   ", IdentifierStatus.MISSING),
        ("\t\n", IdentifierStatus.MISSING),
        ("UNKNOWN", IdentifierStatus.PLACEHOLDER),
        ("unknown", IdentifierStatus.PLACEHOLDER),
        ("  UnKnOwN  ", IdentifierStatus.PLACEHOLDER),
        ("N/A", IdentifierStatus.PLACEHOLDER),
        ("NONE", IdentifierStatus.PLACEHOLDER),
        ("NULL", IdentifierStatus.PLACEHOLDER),
        ("SCONOSCIUTO", IdentifierStatus.PLACEHOLDER),
        ("NOCF", IdentifierStatus.PLACEHOLDER),
        ("0000000000000000", IdentifierStatus.PLACEHOLDER),
        ("XXXXXXXXXXXXXXXX", IdentifierStatus.PLACEHOLDER),
        ("----", IdentifierStatus.PLACEHOLDER),
        ("RSSMRA80A01X001", IdentifierStatus.MALFORMED),
        ("RSSMRA80A01X001QQ", IdentifierStatus.MALFORMED),
        ("RSSMR080A01X001Q", IdentifierStatus.MALFORMED),
        ("RSSMRA80Z01X001Q", IdentifierStatus.MALFORMED),
        ("RSSMRA80A99X001Q", IdentifierStatus.MALFORMED),
        ("RSSMRA80A01X001!", IdentifierStatus.MALFORMED),
    ],
)
def test_unusable_values_are_diagnosed_by_name(raw: str, expected: IdentifierStatus) -> None:
    """Each class of failure gets its own verdict, because each needs a different fix.

    A checksum failure reported for ``UNKNOWN`` would send an operator looking
    for a transcription error in a field that was never filled in, so absence
    and placeholders are tested before structure and structure before the check
    character.
    """
    assert classify_national_id(raw).status is expected


def test_a_wrong_check_character_is_distinguished_from_a_wrong_shape() -> None:
    """The two mean different things: a typo, against an export using another scheme."""
    wrong = ROSSI[:15] + ("B" if ROSSI[15] != "B" else "C")

    assert classify_national_id(wrong).status is IdentifierStatus.BAD_CHECKSUM


def test_an_omocodia_variant_is_valid() -> None:
    """A codice fiscale may legitimately carry letters where digits are expected.

    When two people would be assigned the same code the Agenzia delle Entrate
    substitutes letters for digits, from the right. A validator that does not
    know this rejects genuine identifiers — which is the difference between a
    checksum-only implementation and one that can be pointed at real data.
    """
    substitution = {
        "0": "L", "1": "M", "2": "N", "3": "P", "4": "Q",
        "5": "R", "6": "S", "7": "T", "8": "U", "9": "V",
    }  # fmt: skip
    body = list(ROSSI[:15])
    body[14] = substitution[body[14]]
    omocode = "".join(body) + cf_check_character("".join(body))

    assert omocode != ROSSI
    assert classify_national_id(omocode).status is IdentifierStatus.VALID


@pytest.mark.parametrize(
    "variant",
    [
        "{value}",
        "{value}  ",
        "  {value}",
        "{value}".lower(),
        "{value} ".replace(" ", " "),  # noqa: RUF001
    ],
)
def test_equivalent_spellings_normalise_to_one_identifier(variant: str) -> None:
    """Case, surrounding and internal whitespace, and compatibility forms.

    Only these. A cleverer normaliser would start merging identifiers that are
    not the same identifier, and in this direction a false match is far worse
    than a miss.
    """
    assert normalise_national_id(variant.format(value=ROSSI)) == ROSSI


def test_full_width_digits_normalise() -> None:
    """A copy-and-paste from a PDF or a spreadsheet is the usual source of these."""
    wide = ROSSI[:6] + "８０" + ROSSI[8:]  # noqa: RUF001

    assert normalise_national_id(wide) == ROSSI[:6] + "80" + ROSSI[8:]


def test_an_unusable_identifier_keeps_its_raw_form_for_diagnostics() -> None:
    """Retained to be reported and redacted, never trusted as a key.

    The distinction the policy rests on: a value may be worth removing from a
    report without being worth grouping records by.
    """
    classified = classify_national_id("  unknown  ")

    assert classified.raw == "  unknown  "
    assert classified.normalised == "UNKNOWN"
    assert not classified.is_usable


# --------------------------------------------------------------------------
# Identity keys
# --------------------------------------------------------------------------


def test_a_national_identifier_key_derives_from_the_identifier_alone() -> None:
    """This is what keeps every label issued from valid input unchanged.

    A subject established from a well-formed codice fiscale derives from the
    normalised identifier, and a well-formed codice fiscale normalises to
    itself, so the derivation input is byte-for-byte what it was before the
    identity index existed. ``RULE_VERSION`` 1.1.0 rests on this.
    """
    key = IdentityKey.national(ROSSI)

    assert key.kind is KeyKind.NATIONAL_ID
    assert key.derivation_input == ROSSI
    assert Pseudonymiser(KEY).subject_label_for(key) == Pseudonymiser(KEY).subject_label(ROSSI)


def test_a_record_number_key_carries_its_authority_into_the_derivation() -> None:
    """The same number at two hospitals must not produce one label."""
    pseudonymiser = Pseudonymiser(KEY)
    here = IdentityKey.scoped_record_number(HOSPITAL_A, "12345")
    there = IdentityKey.scoped_record_number(HOSPITAL_B, "12345")

    assert here.derivation_input != there.derivation_input
    assert pseudonymiser.subject_label_for(here) != pseudonymiser.subject_label_for(there)


def test_the_two_kinds_of_key_cannot_collide() -> None:
    """Separate domain separators, so a record number can never mint a CF's label."""
    pseudonymiser = Pseudonymiser(KEY)
    same_text = IdentityKey.scoped_record_number("", ROSSI)

    assert pseudonymiser.subject_label_for(same_text) != pseudonymiser.subject_label(ROSSI)


def test_an_absent_authority_becomes_the_unscoped_namespace_not_an_invented_one() -> None:
    """An authority is never fabricated: it is marked absent and the ambiguity check applies."""
    key = IdentityKey.scoped_record_number("", "12345")

    assert key.authority == UNSCOPED_AUTHORITY
    assert AuthorityScope().authority == ""


def test_the_assigning_authority_outranks_the_sending_facility() -> None:
    """PID-3.4 describes the identifier; MSH-4 describes the message."""
    scope = AuthorityScope(assigning_authority="OSPEDALE A", sending_facility="GATEWAY REGIONALE")

    assert scope.authority == "OSPEDALE A"
    assert AuthorityScope(sending_facility="GATEWAY REGIONALE").authority == "GATEWAY REGIONALE"


def test_a_record_number_is_normalised_within_its_authority() -> None:
    """Leading zeros and case fold, which is what recovers the padding-drift defect."""
    assert normalise_record_number(" 0012345 ") == normalise_record_number("12345")
    assert normalise_record_number("") == ""


# --------------------------------------------------------------------------
# The index: establishing and refusing
# --------------------------------------------------------------------------


class _Facts:
    """The four fields identity resolution needs, as a record would supply them."""

    def __init__(
        self,
        national_id: str = "",
        mrn: str = "",
        family_name: str = "ROSSI",
        birth_date: date | None = date(1980, 1, 1),
    ) -> None:
        self.national_id = national_id
        self.mrn = mrn
        self.family_name = family_name
        self.birth_date = birth_date


def test_a_record_with_no_usable_identifier_of_any_kind_is_refused() -> None:
    """Nothing to be: no national identifier and no record number."""
    index = IdentityIndex()

    refusal = index.establish(_Facts(national_id="UNKNOWN"), AuthorityScope())

    assert isinstance(refusal, Refusal)
    assert refusal.reason is RefusalReason.NO_USABLE_IDENTIFIER


def test_a_placeholder_identifier_falls_back_to_the_scoped_record_number() -> None:
    """The record number still identifies the patient within the issuing institution.

    So the record is kept and the subject exists — it is simply not relinkable
    to another institution's export, which the caller reports.
    """
    index = IdentityIndex()

    resolved = index.establish(
        _Facts(national_id="UNKNOWN", mrn="0012345"),
        AuthorityScope(assigning_authority=HOSPITAL_A),
    )

    assert not isinstance(resolved, Refusal)
    key, classified = resolved
    assert key.kind is KeyKind.SCOPED_RECORD_NUMBER
    assert key.authority == HOSPITAL_A
    assert classified.status is IdentifierStatus.PLACEHOLDER


def test_two_placeholder_identifiers_at_one_site_do_not_become_one_person() -> None:
    """The audit's critical finding, at the unit level.

    Missing identity information is not evidence of shared identity. Two
    records that both failed to say who they belong to have told you nothing in
    common, and keying a subject on the raw string made every patient whose
    identifier was unavailable into the same patient.
    """
    index = IdentityIndex()

    first = index.establish(
        _Facts(national_id="UNKNOWN", mrn="111"), AuthorityScope(assigning_authority=HOSPITAL_A)
    )
    second = index.establish(
        _Facts(national_id="UNKNOWN", mrn="222"), AuthorityScope(assigning_authority=HOSPITAL_A)
    )

    assert not isinstance(first, Refusal)
    assert not isinstance(second, Refusal)
    assert first[0] != second[0]


def test_one_record_number_claimed_by_two_people_becomes_ambiguous() -> None:
    """Refused, not resolved. Not the first, not the last, not the one that sorted higher."""
    index = IdentityIndex()
    scope = AuthorityScope(assigning_authority=HOSPITAL_A)
    index.establish(_Facts(national_id=ROSSI, mrn="12345"), scope)
    index.establish(_Facts(national_id=BIANCHI, mrn="12345"), scope)

    found = index.resolve_record_number("12345", scope)

    assert isinstance(found, Refusal)
    assert found.reason is RefusalReason.AMBIGUOUS_RECORD_NUMBER
    assert (HOSPITAL_A, "12345") in index.ambiguous_record_numbers()


def test_ambiguity_does_not_depend_on_the_order_records_were_read() -> None:
    """The result is a property of the set of inputs, which the old code's was not."""
    scope = AuthorityScope(assigning_authority=HOSPITAL_A)
    forwards, backwards = IdentityIndex(), IdentityIndex()
    for index, order in ((forwards, (ROSSI, BIANCHI)), (backwards, (BIANCHI, ROSSI))):
        for value in order:
            index.establish(_Facts(national_id=value, mrn="12345"), scope)

    assert forwards.ambiguous_record_numbers() == backwards.ambiguous_record_numbers()


def test_the_same_record_number_at_two_authorities_is_two_people() -> None:
    """A record number is a hospital's own number and both number from one."""
    index = IdentityIndex()
    index.establish(
        _Facts(national_id=ROSSI, mrn="12345"), AuthorityScope(assigning_authority=HOSPITAL_A)
    )
    index.establish(
        _Facts(national_id=BIANCHI, mrn="12345"), AuthorityScope(assigning_authority=HOSPITAL_B)
    )

    at_a = index.resolve_record_number("12345", AuthorityScope(assigning_authority=HOSPITAL_A))
    at_b = index.resolve_record_number("12345", AuthorityScope(assigning_authority=HOSPITAL_B))

    assert at_a == IdentityKey.national(ROSSI)
    assert at_b == IdentityKey.national(BIANCHI)


def test_a_number_two_authorities_share_is_ambiguous_when_looked_up_unscoped() -> None:
    """A report header names no facility, so it can only ask unscoped.

    The scoped lookups still succeed for whoever can name their institution.
    What fails is the lookup that cannot tell the two apart, which is the
    refusal we want rather than a guess.
    """
    index = IdentityIndex()
    index.establish(
        _Facts(national_id=ROSSI, mrn="12345"), AuthorityScope(assigning_authority=HOSPITAL_A)
    )
    index.establish(
        _Facts(national_id=BIANCHI, mrn="12345"), AuthorityScope(assigning_authority=HOSPITAL_B)
    )

    unscoped = index.resolve_record_number("12345", AuthorityScope())

    assert isinstance(unscoped, Refusal)
    assert unscoped.reason is RefusalReason.AMBIGUOUS_RECORD_NUMBER


def test_an_unscoped_number_still_resolves_in_a_single_site_corpus() -> None:
    """The common case must keep working: one hospital, reports with no facility."""
    index = IdentityIndex()
    index.establish(
        _Facts(national_id=ROSSI, mrn="0012345"), AuthorityScope(assigning_authority=HOSPITAL_A)
    )

    assert index.resolve_record_number("12345", AuthorityScope()) == IdentityKey.national(ROSSI)


def test_a_lookup_with_no_record_number_is_refused_rather_than_matched() -> None:
    index = IdentityIndex()

    found = index.resolve_record_number("", AuthorityScope())

    assert isinstance(found, Refusal)
    assert found.reason is RefusalReason.NO_USABLE_IDENTIFIER


def test_an_unknown_record_number_is_refused_by_name() -> None:
    index = IdentityIndex()

    found = index.resolve_record_number("99999", AuthorityScope(assigning_authority=HOSPITAL_A))

    assert isinstance(found, Refusal)
    assert found.reason is RefusalReason.NO_USABLE_IDENTIFIER


# --------------------------------------------------------------------------
# Through the corpus reader
# --------------------------------------------------------------------------


def test_two_patients_sharing_a_placeholder_stay_two_subjects(tmp_path: Path) -> None:
    """The audit scenario, exactly as reported.

    Two distinct patients, both messages carrying ``UNKNOWN`` as the national
    identifier, different names. Before: one subject, zero linkage issues, and
    the second patient's identity discarded. The expected result is two
    identities, no silent merge, and an explicit finding for each unusable
    identifier.
    """
    root = _corpus(
        tmp_path / "raw",
        lab__a=_message(national_id="UNKNOWN", mrn="111", family="BIANCHI", given="LUCIA"),
        lab__b=_message(national_id="UNKNOWN", mrn="222", family="FONTANA", given="FRANCESCA"),
    )
    _write(root / "lab" / "a.hl7", (root / "lab" / "a").read_text(encoding="utf-8"))
    _write(root / "lab" / "b.hl7", (root / "lab" / "b").read_text(encoding="utf-8"))
    (root / "lab" / "a").unlink()
    (root / "lab" / "b").unlink()

    corpus = read_corpus(root)

    assert len(corpus.subjects) == 2
    assert {s.identity.family_name for s in corpus.subjects} == {"BIANCHI", "FONTANA"}
    assert _reasons(corpus) == [
        "invalid_national_identifier",
        "invalid_national_identifier",
    ]
    assert all("placeholder" in issue.detail for issue in corpus.issues)


def test_the_audit_scenario_no_longer_leaks_a_patients_name(tmp_path: Path) -> None:
    """The end-to-end form, and the one that matters most.

    The leak was never about attribution. Targeted redaction removes the
    identifiers the structured exports declared *for that subject*, so a merge
    left only the first person's identity in the known set and the second
    person's name was never looked for. The built dataset contained
    ``Paziente: FRANCESCA FONTANA`` in plain text, in the one field the
    scrubber exists to redact.
    """
    root = tmp_path / "raw"
    _write(
        root / "lab" / "a.hl7",
        _message(national_id="UNKNOWN", mrn="111", family="BIANCHI", given="LUCIA"),
    )
    _write(
        root / "lab" / "b.hl7",
        _message(national_id="UNKNOWN", mrn="222", family="FONTANA", given="FRANCESCA"),
    )
    # The second patient's own report, which is what used to carry her name out.
    _write(
        root / "reports" / "b.txt",
        _report(national_id="UNKNOWN", mrn="222", family="FONTANA", given="FRANCESCA"),
    )

    corpus = read_corpus(root)
    summary = build_dataset(
        corpus,
        KEY,
        BuildSpec(dataset_name="d", description="d", hdab="H", publisher="P"),
        tmp_path / "dataset",
    )

    assert summary.subject_count == 2
    written = [p for p in summary.root.rglob("*") if p.is_file()]
    assert written, "the build produced nothing to check"
    for path in written:
        text = path.read_text(encoding="utf-8")
        for leaked in ("FONTANA", "FRANCESCA", "BIANCHI", "LUCIA"):
            assert leaked not in text, f"{leaked} survived in {path.name}"


def test_one_person_written_in_two_cases_is_one_subject(tmp_path: Path) -> None:
    """The split, which an opt-out would have missed.

    Two subjects meant two baselines, so the ``day_offset`` values stopped
    describing one timeline — and ``commissura whois`` returns one label, so
    half that person's records would have survived an objection.
    """
    root = tmp_path / "raw"
    _write(
        root / "lab" / "upper.hl7",
        _message(national_id=ROSSI, mrn="111", family="ROSSI", given="MARIO"),
    )
    _write(
        root / "lab" / "lower.hl7",
        _message(
            national_id=ROSSI.lower(),
            mrn="111",
            family="ROSSI",
            given="MARIO",
            collected="20240401090000",
        ),
    )

    corpus = read_corpus(root)

    assert len(corpus.subjects) == 1
    assert len(corpus.subjects[0].labs) == 2
    assert corpus.issues == ()


def test_an_imaging_study_goes_to_the_patient_at_the_issuing_institution(
    tmp_path: Path,
) -> None:
    """**The audit's second finding.** The study used to go to whoever sorted last."""
    root = tmp_path / "raw"
    _write(
        root / "lab" / "a.hl7",
        _message(
            national_id=ROSSI,
            mrn="12345",
            family="ROSSI",
            given="MARIO",
            authority=HOSPITAL_A,
            facility=HOSPITAL_A,
        ),
    )
    _write(
        root / "lab" / "b.hl7",
        _message(
            national_id=BIANCHI,
            mrn="12345",
            family="BIANCHI",
            given="LUCIA",
            authority=HOSPITAL_B,
            facility=HOSPITAL_B,
        ),
    )
    _write(root / "imaging" / "s.json", _imaging(patient_id="12345", institution=HOSPITAL_B))

    corpus = read_corpus(root)
    owners = {s.identity.family_name: len(s.imaging) for s in corpus.subjects}

    assert owners == {"ROSSI": 0, "BIANCHI": 1}
    assert corpus.issues == ()


def test_an_imaging_study_naming_no_institution_is_refused_when_the_number_is_shared(
    tmp_path: Path,
) -> None:
    """Fail closed: a study that cannot say where it came from is not guessed at."""
    root = tmp_path / "raw"
    _write(
        root / "lab" / "a.hl7",
        _message(
            national_id=ROSSI, mrn="12345", family="ROSSI", given="MARIO", authority=HOSPITAL_A
        ),
    )
    _write(
        root / "lab" / "b.hl7",
        _message(
            national_id=BIANCHI, mrn="12345", family="BIANCHI", given="LUCIA", authority=HOSPITAL_B
        ),
    )
    _write(root / "imaging" / "s.json", _imaging(patient_id="12345", institution=""))

    corpus = read_corpus(root)

    assert _reasons(corpus) == ["ambiguous_record_number"]
    assert all(not s.imaging for s in corpus.subjects)


def test_a_record_number_reused_at_one_site_refuses_the_imaging_linkage(
    tmp_path: Path,
) -> None:
    """Same institution, same number, two people: a renumbering or a typo.

    The laboratory records are unaffected, because their own national
    identifiers established them. Only the lookup that cannot tell the two
    apart fails, which is safe partial processing rather than an aborted run.
    """
    root = tmp_path / "raw"
    for name, cf, family in (("a", ROSSI, "ROSSI"), ("b", BIANCHI, "BIANCHI")):
        _write(
            root / "lab" / f"{name}.hl7",
            _message(national_id=cf, mrn="777", family=family, given="X", authority=HOSPITAL_A),
        )
    _write(root / "imaging" / "s.json", _imaging(patient_id="777", institution=HOSPITAL_A))

    corpus = read_corpus(root)

    assert len(corpus.subjects) == 2
    assert sum(len(s.labs) for s in corpus.subjects) == 2
    assert _reasons(corpus) == ["ambiguous_record_number"]


def test_several_messages_for_one_patient_keep_every_identity(tmp_path: Path) -> None:
    """§2.5: combining records must never discard a known identifier.

    Two institutions, one person, two spellings of the given name. Both have to
    reach redaction, because the one that was discarded used to be a name
    nothing looked for.
    """
    root = tmp_path / "raw"
    _write(
        root / "lab" / "a.hl7",
        _message(national_id=ROSSI, mrn="111", family="ROSSI", given="MARIO", authority=HOSPITAL_A),
    )
    _write(
        root / "lab" / "b.hl7",
        _message(
            national_id=ROSSI,
            mrn="222",
            family="ROSSI",
            given="MARIOLINO",
            authority=HOSPITAL_B,
            collected="20240401090000",
        ),
    )

    corpus = read_corpus(root)

    assert len(corpus.subjects) == 1
    subject = corpus.subjects[0]
    assert {i.given_name for i in subject.identities} == {"MARIO", "MARIOLINO"}
    assert {i.mrn for i in subject.identities} == {"111", "222"}
    # And the primary identity is still the first one observed.
    assert subject.identity.given_name == "MARIO"


def test_a_second_identity_naming_a_different_person_is_reported(tmp_path: Path) -> None:
    """A valid codice fiscale encodes the surname and birth date, so a clash is a finding.

    Not a reason to split: the identifier is checksum-valid and authoritative,
    so identity is established. Both identities are kept so that both names are
    redacted, and the disagreement is reported rather than resolved.
    """
    root = tmp_path / "raw"
    _write(
        root / "lab" / "a.hl7",
        _message(national_id=ROSSI, mrn="111", family="ROSSI", given="MARIO"),
    )
    _write(
        root / "lab" / "b.hl7",
        _message(
            national_id=ROSSI,
            mrn="111",
            family="ESPOSITO",
            given="CARLA",
            birth="19551212",
            collected="20240401090000",
        ),
    )

    corpus = read_corpus(root)

    assert len(corpus.subjects) == 1
    assert _reasons(corpus) == ["conflicting_identity"]
    assert {i.family_name for i in corpus.subjects[0].identities} == {"ROSSI", "ESPOSITO"}


def test_a_report_naming_a_placeholder_does_not_attach_to_a_placeholder_subject(
    tmp_path: Path,
) -> None:
    """A header reading ``Codice fiscale: UNKNOWN`` has named nobody.

    It used to attach to whichever subject the same placeholder created. Now no
    such subject exists, and the record number is scoped, so the report
    resolves on the number or is reported unlinked.
    """
    root = tmp_path / "raw"
    _write(
        root / "lab" / "a.hl7",
        _message(national_id=ROSSI, mrn="111", family="ROSSI", given="MARIO"),
    )
    _write(
        root / "reports" / "orphan.txt",
        _report(national_id="UNKNOWN", mrn="999", family="ESPOSITO", given="CARLA"),
    )

    corpus = read_corpus(root)

    assert _reasons(corpus) == ["unlinked_report"]
    assert not corpus.subjects[0].reports


def test_a_report_still_links_by_its_national_identifier(tmp_path: Path) -> None:
    """The positive case: nothing above may break ordinary linkage."""
    root = tmp_path / "raw"
    _write(
        root / "lab" / "a.hl7",
        _message(national_id=ROSSI, mrn="111", family="ROSSI", given="MARIO"),
    )
    _write(
        root / "reports" / "r.txt",
        _report(national_id=ROSSI.lower(), mrn="999", family="ROSSI", given="MARIO"),
    )

    corpus = read_corpus(root)

    assert corpus.issues == ()
    assert len(corpus.subjects[0].reports) == 1


def test_a_report_links_by_record_number_when_the_header_omits_the_identifier(
    tmp_path: Path,
) -> None:
    """The other positive case, and the one the unscoped namespace exists for."""
    root = tmp_path / "raw"
    _write(
        root / "lab" / "a.hl7",
        _message(national_id=ROSSI, mrn="0012345", family="ROSSI", given="MARIO"),
    )
    _write(
        root / "reports" / "r.txt",
        _report(national_id="", mrn="12345", family="ROSSI", given="MARIO"),
    )

    corpus = read_corpus(root)

    assert corpus.issues == ()
    assert len(corpus.subjects[0].reports) == 1


def test_a_message_with_no_typed_authority_still_scopes_on_the_sending_facility(
    tmp_path: Path,
) -> None:
    """MSH-4 is the fallback when PID-3 component 4 is empty."""
    root = tmp_path / "raw"
    _write(
        root / "lab" / "a.hl7",
        _message(
            national_id="UNKNOWN",
            mrn="111",
            family="ROSSI",
            given="MARIO",
            facility=HOSPITAL_A,
            typed_authority=False,
        ),
    )

    corpus = read_corpus(root)

    assert len(corpus.subjects) == 1
    assert corpus.subjects[0].key.authority == HOSPITAL_A


def test_subjects_are_emitted_in_a_stable_order(tmp_path: Path) -> None:
    """Determinism: the dataset's session numbering and participant order depend on it."""
    root = tmp_path / "raw"
    for name, cf, family in (
        ("a", ROSSI, "ROSSI"),
        ("b", BIANCHI, "BIANCHI"),
        ("c", VERDI, "VERDI"),
    ):
        _write(
            root / "lab" / f"{name}.hl7",
            _message(national_id=cf, mrn=f"{name}1", family=family, given="X"),
        )

    first = [s.key for s in read_corpus(root).subjects]
    second = [s.key for s in read_corpus(root).subjects]

    assert first == second == sorted(first)


def test_a_letter_that_is_no_substitution_in_a_digit_position_is_malformed() -> None:
    """Only the ten official substitution letters may stand in for a digit.

    An export using a different scheme in the same sixteen characters is
    malformed, not a codice fiscale with a transcription error, and the
    distinction decides whether an operator goes looking for a typo.
    """
    # Position seven must be a digit or one of LMNPQRSTUV. "Z" is neither.
    broken = ROSSI[:6] + "Z" + ROSSI[7:]

    assert classify_national_id(broken).status is IdentifierStatus.MALFORMED


def test_a_digit_where_the_place_code_letter_belongs_is_malformed() -> None:
    """The place code is a letter followed by three digits, and the letter is checked."""
    broken = ROSSI[:11] + "9" + ROSSI[12:]

    assert classify_national_id(broken).status is IdentifierStatus.MALFORMED


def test_a_subject_with_no_record_number_registers_none() -> None:
    """A valid national identifier is enough on its own; nothing is indexed by number."""
    index = IdentityIndex()

    resolved = index.establish(_Facts(national_id=ROSSI, mrn=""), AuthorityScope())

    assert not isinstance(resolved, Refusal)
    assert index.ambiguous_record_numbers() == ()
    assert isinstance(index.resolve_record_number("", AuthorityScope()), Refusal)


def test_an_imaging_study_with_no_date_is_dropped_and_reported(tmp_path: Path) -> None:
    """Sessions are dated encounters, so a study with no StudyDate has nowhere to go.

    Linkage succeeded, so this is a dropped record rather than a linkage issue —
    the distinction recorded on 2026-11-12, re-pinned here because the imaging
    branch reaches it through the new scoped lookup.
    """
    root = tmp_path / "raw"
    _write(
        root / "lab" / "a.hl7",
        _message(national_id=ROSSI, mrn="12345", family="ROSSI", given="MARIO"),
    )
    _write(
        root / "imaging" / "s.json",
        _imaging(patient_id="12345", institution=HOSPITAL_A, study_date=""),
    )

    corpus = read_corpus(root)
    summary = build_dataset(
        corpus,
        KEY,
        BuildSpec(dataset_name="d", description="d", hdab="H", publisher="P"),
        tmp_path / "dataset",
    )

    assert corpus.issues == ()
    assert [record.reason for record in summary.dropped] == ["undated_record"]
    assert "StudyDate" in summary.dropped[0].detail
