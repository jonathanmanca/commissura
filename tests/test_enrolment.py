"""Patients who hold no codice fiscale, and the four kinds that identify them.

The CDA R2 laboratory specification enumerates five cases for
``recordTarget/patientRole/id``: a codice fiscale, a TEAM card for somebody
insured abroad, an ENI code for a European not enrolled in the health service,
an STP code for a foreigner temporarily present, and an ANA code. The reader has
handled all five since the CDA work; **no generated corpus produced any but the
first**, so four of them rested on hand-built fixtures.

That is the condition this project has met three times — the shape of the
linkage issues, the institution address behind a cohort size, the identity
quarantine — and each time, the first corpus to reach the path found a real
defect. This time it found none, which is recorded in the decision log as the
outcome rather than dressed up as one. The path is covered either way, and
covered is the point.

Every identifier here is synthetic, and the constructions are in
:mod:`commissura.identifiers`: an ISO 3166-1 user-assigned country code for
TEAM, which the standard undertakes never to allocate, and a literal marker
inside the ENI, STP and ANA codes, whose internal allocation rules are not
published and are therefore not claimed to be avoided.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path
from random import Random

import pytest
from pydantic import ValidationError

from commissura.build.manifest import write_manifest
from commissura.build.writer import BuildSpec, build_dataset
from commissura.deident.keys import SecretKey
from commissura.generate.cohort import (
    ENROLMENT_PERIOD,
    NON_ENROLLED_KINDS,
    CohortSpec,
    build_person,
    plan_enrolment,
)
from commissura.generate.writer import write_corpus
from commissura.identifiers import (
    ASSIGNED_CODE_LENGTH,
    SYNTHETIC_MARKER,
    TEAM_SYNTHETIC_COUNTRY,
    synthetic_assigned_code,
    synthetic_team_number,
)
from commissura.measure import measure
from commissura.models import Enrolment, ForeignIdentity, Person, Sex
from commissura.read.cda import (
    TEAM_CARD_ROOT,
    TEAM_PERSONAL_ROOT,
    parse_clinical_document,
)
from commissura.read.corpus import read_corpus
from commissura.read.identity import KeyKind, PatientIdentifierKind

KEY = SecretKey(bytes(range(32)))
REFERENCE = date(2024, 6, 30)

_PERSON_FIELDS = {
    "family_name": "ROSSI",
    "given_name": "MARIO",
    "sex": Sex.MALE,
    "birth_date": date(1980, 1, 1),
    "mrn": "0012345",
    "street": "Via Sintetica 1",
    "city": "Collevcrde",
    "province": "RM",
    "postal_code": "00100",
    "phone": "0600000000",
    "email": "m.rossi@posta.invalid",
}


def _corpus(tmp_path: Path, *, cda: bool, subjects: int = 25, rate: float = 0.0) -> Path:
    root = tmp_path / f"raw-{cda}-{subjects}-{rate}"
    write_corpus(CohortSpec(subjects=subjects, seed=42, defect_rate=rate, cda=cda), root)
    return root


# --------------------------------------------------------------------------
# A person holds one identifier, and the model refuses anything else
# --------------------------------------------------------------------------


def test_a_person_holds_a_codice_fiscale_or_a_foreign_identity() -> None:
    """Both constructions are legitimate and each produces exactly one."""
    enrolled = Person(codice_fiscale="RSSMRA80A01X000Z", **_PERSON_FIELDS)
    visiting = Person(
        foreign=ForeignIdentity(enrolment=Enrolment.STP, value="STPSINTETIC12345"),
        **_PERSON_FIELDS,
    )

    assert enrolled.foreign is None
    assert visiting.codice_fiscale == ""


@pytest.mark.parametrize(
    ("label", "extra"),
    [
        (
            "both",
            {
                "codice_fiscale": "RSSMRA80A01X000Z",
                "foreign": ForeignIdentity(enrolment=Enrolment.ENI, value="ENISINTETIC00001"),
            },
        ),
        ("neither", {}),
        ("a codice fiscale of the wrong length", {"codice_fiscale": "RSSMRA80"}),
    ],
)
def test_a_person_with_the_wrong_identifiers_cannot_be_built(
    label: str, extra: dict[str, object]
) -> None:
    """Refused at construction, not left as a convention.

    A person with both is two people as far as identity resolution is
    concerned; one with neither cannot be identified at all and a renderer
    reaching for the empty codice fiscale would write an empty element rather
    than fail. Neither should be constructible, and the length check moved into
    the validator because the field now legitimately permits an empty value.
    """
    with pytest.raises(ValidationError):
        Person(**extra, **_PERSON_FIELDS)


# --------------------------------------------------------------------------
# The synthetic constructions
# --------------------------------------------------------------------------


@pytest.mark.parametrize("prefix", ["ENI", "STP", "ANA"])
def test_an_assigned_code_has_the_length_the_specification_states(prefix: str) -> None:
    """Sixteen characters, the prefix first, and the marker in the middle."""
    code = synthetic_assigned_code(prefix, Random(1))

    assert len(code) == ASSIGNED_CODE_LENGTH
    assert code.startswith(prefix)
    assert SYNTHETIC_MARKER in code


def test_a_team_number_names_a_country_that_cannot_exist() -> None:
    """ISO 3166-1 sets ``XAA``-``XZZ`` aside and undertakes never to allocate them.

    The same argument as the codice fiscale's ``X`` place code, applied to a
    different registry: the value is well formed, the reader accepts it, and it
    still cannot belong to any issuing state.
    """
    number = synthetic_team_number(Random(1), digits=16)

    assert number.startswith(f"{TEAM_SYNTHETIC_COUNTRY}.")
    assert TEAM_SYNTHETIC_COUNTRY.startswith("X")
    assert TEAM_SYNTHETIC_COUNTRY[1:].isalpha()
    assert SYNTHETIC_MARKER in number


# --------------------------------------------------------------------------
# Who is not enrolled, and in which corpora
# --------------------------------------------------------------------------


def test_an_hl7_corpus_has_no_non_enrolled_patient() -> None:
    """A scope decision, not a simplification.

    HL7 v2 has no sourced mapping for these four kinds -- table 0203's
    ``NNxxx`` names a *national* person identifier, which is exactly what a
    TEAM or STP patient does not have -- and inventing one would put a
    plausible code with no provenance into the generator.
    """
    assert all(plan_enrolment(index, cda=False) is None for index in range(100))


def test_all_four_kinds_appear_within_a_small_cohort() -> None:
    """Cycled rather than drawn, so coverage does not depend on luck.

    A random choice over four kinds leaves one absent from a sixteen-subject
    corpus about a third of the time, and a guarantee that holds two times in
    three is not one.
    """
    needed = ENROLMENT_PERIOD * len(NON_ENROLLED_KINDS)
    found = {plan_enrolment(index, cda=True) for index in range(needed)}

    assert found == {*NON_ENROLLED_KINDS, None}


def test_the_enrolled_random_stream_is_untouched() -> None:
    """The regression that matters, and why the README's numbers did not move.

    `build_person` with no enrolment must draw exactly what it drew before the
    parameter existed. Pinned on a person rather than on a corpus total, so the
    failure names the stream rather than a count somebody then has to trace.

    **The expected value was measured, not written down from reasoning.** The
    first version of this test carried an invented one and failed, which was
    the right outcome: the value below comes from running `build_person` under
    a worktree at `52f8ed2`, the commit before the enrolment parameter existed,
    and the same call on this tree returns it unchanged. Reasoning that "no
    extra draws happen when the parameter is None" was correct here and is not
    evidence.
    """
    person = build_person(Random(7), reference_date=REFERENCE)

    assert person.foreign is None
    assert person.codice_fiscale == "CRSNGL57B67X596U"


def test_a_non_enrolled_person_draws_their_own_identifier() -> None:
    """And it is the kind the plan asked for."""
    person = build_person(Random(7), reference_date=REFERENCE, enrolment=Enrolment.TEAM)

    assert person.codice_fiscale == ""
    assert person.foreign is not None
    assert person.foreign.enrolment is Enrolment.TEAM
    assert person.foreign.card_number
    assert person.foreign.value != person.foreign.card_number


# --------------------------------------------------------------------------
# Through a generated corpus
# --------------------------------------------------------------------------


def test_a_cda_corpus_carries_every_kind(tmp_path: Path) -> None:
    """The point of the exercise: a path a corpus reaches.

    Pinned at "some of each" rather than at counts, which depend on the cohort's
    shape and on the random stream.
    """
    kinds: Counter[PatientIdentifierKind] = Counter()
    for path in sorted(_corpus(tmp_path, cda=True).glob("cda/*.xml")):
        document = parse_clinical_document(path.read_text(encoding="utf-8"))
        kinds.update(identifier.kind for identifier in document.identifiers)

    for kind in (
        PatientIdentifierKind.CODICE_FISCALE,
        PatientIdentifierKind.ENI,
        PatientIdentifierKind.STP,
        PatientIdentifierKind.ANA,
        PatientIdentifierKind.TEAM_CARD,
        PatientIdentifierKind.TEAM_PERSONAL,
    ):
        assert kinds[kind] > 0, kind


def test_a_team_patient_carries_both_ids_under_their_own_roots(tmp_path: Path) -> None:
    """The specification requires two and they are not interchangeable."""
    found: list[tuple[str, str]] = []
    for path in sorted(_corpus(tmp_path, cda=True).glob("cda/*.xml")):
        document = parse_clinical_document(path.read_text(encoding="utf-8"))
        roots = {identifier.authority for identifier in document.identifiers}
        if TEAM_CARD_ROOT in roots:
            found.append((path.name, sorted(roots)[0]))
            assert TEAM_PERSONAL_ROOT in roots, "a card number without a personal number"

    assert found, "no TEAM patient in this corpus"


def test_a_non_enrolled_subject_is_keyed_as_an_assigned_identifier(tmp_path: Path) -> None:
    """Neither national nor institution-scoped, which is why the third kind exists.

    And the TEAM subject is keyed on the *personal* number: a card is reissued
    on expiry or loss, so keying on it would split one patient across two cards.
    """
    corpus = read_corpus(_corpus(tmp_path, cda=True))
    assigned = [s for s in corpus.subjects if s.key.kind is KeyKind.ASSIGNED_IDENTIFIER]

    assert assigned
    assert all(s.key.derivation_input.startswith("assigned_identifier|") for s in assigned)
    assert not any(TEAM_CARD_ROOT in s.key.derivation_input for s in assigned)
    assert any(TEAM_PERSONAL_ROOT in s.key.derivation_input for s in assigned)


def test_every_subject_keeps_a_distinct_key(tmp_path: Path) -> None:
    """A new kind of key must not merge anybody with anybody.

    The failure this would catch is the one the identity layer exists for: two
    people under one label leave the second person's identifiers outside the
    set the scrubber was told to remove.
    """
    corpus = read_corpus(_corpus(tmp_path, cda=True))

    assert len({s.key.derivation_input for s in corpus.subjects}) == len(corpus.subjects)


def test_a_non_enrolled_patients_report_still_links(tmp_path: Path) -> None:
    """It carries no codice fiscale line, and must link on the record number.

    Writing the foreign code under a `Codice fiscale:` label would state
    something untrue; writing it under a correct one would break linkage
    outright, because `_REPORT_LABELS` recognises four strings and
    `Codice STP` is not among them. So the line is omitted, and this asserts
    the consequence.
    """
    root = _corpus(tmp_path, cda=True)
    corpus = read_corpus(root)

    assert not [issue for issue in corpus.issues if issue.reason == "unlinked_report"]
    assigned = [s for s in corpus.subjects if s.key.kind is KeyKind.ASSIGNED_IDENTIFIER]
    assert assigned
    assert all(subject.reports for subject in assigned), "a non-enrolled subject lost its reports"


def test_no_foreign_code_survives_into_the_dataset(tmp_path: Path) -> None:
    """Text, manifest and every other produced file, against the ground truth.

    Four new kinds of identifier are four new things the scrubber has to find,
    and the only honest way to know it does is to look for the exact values the
    generator planted.
    """
    root = _corpus(tmp_path, cda=True, rate=0.3)
    out = tmp_path / "dataset"
    corpus = read_corpus(root)
    spec = BuildSpec(dataset_name="d", description="d", hdab="H", publisher="P")
    summary = build_dataset(corpus, KEY, spec, out)
    write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=spec)

    annotations = json.loads(
        (root / "_generator" / "phi_annotations.json").read_text(encoding="utf-8")
    )
    planted = {
        span["text"]
        for span in annotations["spans"]
        if span["text"].startswith(("ENI", "STP", "ANA", TEAM_SYNTHETIC_COUNTRY))
    }
    assert planted, "no foreign identifier was planted"

    produced = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(out.rglob("*"))
        if path.is_file()
    )
    assert not sorted(value for value in planted if value in produced)


def test_the_corpus_measures_clean(tmp_path: Path) -> None:
    """Recall over everything planted, with the four new kinds among it."""
    root = _corpus(tmp_path, cda=True)
    out = tmp_path / "measured"
    corpus = read_corpus(root)
    build_dataset(
        corpus, KEY, BuildSpec(dataset_name="d", description="d", hdab="H", publisher="P"), out
    )

    report = measure(root, out)

    assert report.recall == 1.0, [miss.text for miss in report.misses]


def test_the_manifest_counts_the_new_key_kind(tmp_path: Path) -> None:
    """An access body combining two holders' datasets needs to know which is which."""
    root = _corpus(tmp_path, cda=True)
    out = tmp_path / "counted"
    corpus = read_corpus(root)
    spec = BuildSpec(dataset_name="d", description="d", hdab="H", publisher="P")
    summary = build_dataset(corpus, KEY, spec, out)

    manifest = write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=spec)

    source = manifest["source"]
    assert isinstance(source, dict)
    counts = source["subject_keys"]
    assert isinstance(counts, dict)
    assert counts[KeyKind.ASSIGNED_IDENTIFIER.value] > 0
    assert sum(counts.values()) == len(corpus.subjects)
