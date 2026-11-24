"""One generated site's feed sends no national identifier, and what that reaches.

The gap this closes is the sixth instance of a finding this project keeps
making, and it was recorded on 2026-11-23 after an end-to-end test for
``--exclude-subjects`` skipped: **no generated corpus established a subject on
an institution-scoped record number.** Fourteen subjects at defect rates 0.1,
0.6 and 1.0, with and without CDA, gave only ``national_id`` and
``assigned_identifier``.

That key kind is not a detail. It is the quarantine the audit of 2026-11-13
forced into existence — a subject whose national identifier is missing, a
placeholder or malformed is keyed on the record number *within the institution
that issued it*, rather than merged with every other such subject under one
flat index, which is how a patient's name leaked. So the one path a critical
defect was found on was exercised by hand-built fixtures and by nothing else,
at 99% branch coverage.

**It is a property of the site and not a defect drawn per message**, which is
the same reasoning that gave one site the deprecated PID-19 placement on
2026-11-11: an interface does not change its mind between two messages. A feed
whose source system has no national-identifier field never has one. And a
defect drawn per message would almost never give a subject whose *every*
identity-bearing record carries the placeholder, which is what it takes to
reach the key.

Every identifier here is synthetic.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from commissura.build.writer import BuildSpec, _known_identifiers, build_dataset
from commissura.deident.keys import SecretKey
from commissura.generate.cohort import CohortSpec
from commissura.generate.labs import PLACEHOLDER_NATIONAL_ID
from commissura.generate.vocabulary import SITES
from commissura.generate.writer import write_corpus
from commissura.layout import DEIDENT_DIR, MANIFEST_JSON
from commissura.measure import measure
from commissura.read.corpus import read_corpus, read_exact
from commissura.read.identity import PLACEHOLDER_IDENTIFIERS, KeyKind

KEY = SecretKey(bytes(range(32)))


@pytest.fixture(scope="module")
def plain_corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A plain corpus large enough to hold subjects from every site."""
    root = tmp_path_factory.mktemp("placeholder") / "raw"
    write_corpus(CohortSpec(subjects=14, seed=42, defect_rate=0.2), root)
    return root


@pytest.fixture(scope="module")
def cda_corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The same cohort as CDA documents."""
    root = tmp_path_factory.mktemp("placeholder-cda") / "raw"
    write_corpus(CohortSpec(subjects=14, seed=42, defect_rate=0.2, cda=True), root)
    return root


def _spec() -> BuildSpec:
    return BuildSpec(dataset_name="d", description="d", hdab="H", publisher="P")


def _kinds(corpus_root: Path) -> Counter[str]:
    return Counter(s.key.kind.value for s in read_corpus(corpus_root).subjects)


# --------------------------------------------------------------------------
# The two sides have to agree on the value
# --------------------------------------------------------------------------


def test_the_placeholder_is_one_the_reader_recognises() -> None:
    """Otherwise the diagnosis would be *malformed*, which is a different thing.

    A value the reader does not have in its own set is classified malformed
    instead of a placeholder — a different status, a different linkage reason,
    and a different row in ``REASON_KEEPS_RECORD``. The generator would still
    reach the record-number key, so every other test here would pass, and the
    corpus would be exercising the wrong diagnosis. That is why the value is a
    named constant and why this asserts the agreement rather than the spelling.
    """
    assert PLACEHOLDER_NATIONAL_ID in PLACEHOLDER_IDENTIFIERS


def test_exactly_one_site_sends_no_national_identifier() -> None:
    """A coverage guarantee, and the same shape as the PID-19 one.

    All five would make a corpus in which no subject is keyed nationally, which
    is not a hospital anybody has. None would put this file back to testing
    nothing. One is the smallest number that makes the path reachable, and
    pinning it means a later edit that flips a second site has to say so here.
    """
    sending = [site for site in SITES if site.national_id_is_placeholder]

    assert len(sending) == 1
    # And not the same site as the other interface quirk, so a corpus exercises
    # the two independently rather than only in combination.
    assert not sending[0].national_id_in_pid_19


# --------------------------------------------------------------------------
# What a generated corpus now reaches
# --------------------------------------------------------------------------


def test_a_plain_corpus_establishes_a_subject_on_a_record_number(
    plain_corpus: Path,
) -> None:
    """The gap, closed, and the whole reason for the change."""
    kinds = _kinds(plain_corpus)

    assert kinds[KeyKind.SCOPED_RECORD_NUMBER.value] > 0
    assert kinds[KeyKind.NATIONAL_ID.value] > 0


def test_every_kind_of_subject_key_is_reachable_from_a_generated_corpus(
    plain_corpus: Path, cda_corpus: Path
) -> None:
    """Between the two modalities, with nothing left to a fixture.

    The completeness claim, asserted over the enum rather than over a list
    written here, so a fourth kind added later fails this until a corpus
    produces it.
    """
    reachable = set(_kinds(plain_corpus)) | set(_kinds(cda_corpus))

    assert {kind.value for kind in KeyKind} <= reachable


def test_a_cda_corpus_carries_no_placeholder_identifier(cda_corpus: Path) -> None:
    """And that is the specification rather than an omission.

    The CDA laboratory profile marks the codice fiscale OBBLIGATORIO for a
    patient enrolled in the health service, so a conformant document cannot
    carry a placeholder in its place; HL7 v2 imposes no such obligation. A
    non-enrolled CDA patient is a different case with its own identifier kinds,
    which is why that corpus reaches ``assigned_identifier`` instead.
    """
    for path in cda_corpus.glob("cda/*.xml"):
        assert PLACEHOLDER_NATIONAL_ID not in path.read_text(encoding="utf-8")

    assert _kinds(cda_corpus)[KeyKind.SCOPED_RECORD_NUMBER.value] == 0


def test_the_placeholder_is_not_planted_as_ground_truth(plain_corpus: Path) -> None:
    """Because it is not an identifier, and counting it as one would flatter the score.

    A span recorded here could never leak — nothing downstream carries
    ``UNKNOWN`` anywhere — so it would count as removed for free, which is
    scoring better by planting easier targets. The same decision as the
    unfilled date placeholder of 2026-11-12.
    """
    annotations = json.loads(
        (plain_corpus / "_generator" / "phi_annotations.json").read_text(encoding="utf-8")
    )
    values = {span["text"] for span in annotations["spans"]}

    assert PLACEHOLDER_NATIONAL_ID not in values
    # It is in the corpus, which is what makes the absence above meaningful.
    assert any(
        PLACEHOLDER_NATIONAL_ID in read_exact(path) for path in plain_corpus.glob("lab/*.hl7")
    )


def test_the_record_is_kept_and_the_attribution_flagged(plain_corpus: Path, tmp_path: Path) -> None:
    """A placeholder is a diagnosis, not a dead end — the audit's own words.

    The record number still identifies the patient within the institution that
    issued it, so the subject exists and the record reaches the dataset; what
    the manifest says is that something about the attribution is worth a second
    look. Asserted on the two counts an auditor reads together, because the
    failure that matters is a record counted absent while it is present — which
    is the defect of 2026-11-16.
    """
    out = tmp_path / "ds"
    corpus = read_corpus(plain_corpus)
    summary = build_dataset(corpus, KEY, _spec(), out)
    from commissura.build.manifest import write_manifest

    write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=_spec())
    source = json.loads((out / DEIDENT_DIR / MANIFEST_JSON).read_text(encoding="utf-8"))["source"]
    reasons = {entry["reason"]: entry["count"] for entry in source["linkage_issues"]}

    assert reasons.get("invalid_national_identifier", 0) > 0
    assert source["records_flagged_in_dataset"] >= reasons["invalid_national_identifier"]


# --------------------------------------------------------------------------
# The finding: the codice fiscale is still removed
# --------------------------------------------------------------------------


def test_the_codice_fiscale_is_still_redacted_for_such_a_subject(
    plain_corpus: Path, tmp_path: Path
) -> None:
    """The question this change could have got wrong, and it did not.

    The *person* still has a codice fiscale — the feed simply does not send it
    — and the report header at that site prints it. So the value is in the
    dataset's input and in **no laboratory record**, which is the shape of the
    leak of 2026-11-18: a declared identifier the pipeline never read.

    It is removed, and the mechanism is ``KnownIdentifiers.declared``, which
    carries what each of a subject's reports declared in its own header. That
    is what reaches redaction here, because the laboratory messages — the
    authoritative source for identity everywhere else in this project — carry
    a placeholder for this subject and have no codice fiscale to contribute.
    A subject keyed on a record number while a report of theirs states their
    national identifier is a combination nothing exercised before this corpus
    existed, which is the argument for building it.

    **The values are taken from the reports and the identities, with
    placeholders filtered out, and that is not fussiness.** The first version
    of this test read ``identity.national_id`` alone, which for these subjects
    is the string ``UNKNOWN`` — so it asserted that the placeholder was absent
    from the dataset, counted that as a check, and passed while never looking
    at a codice fiscale at all. A sabotage that built redaction from the
    primary identity only did not fail it, which is how the vacuity was found.
    """
    out = tmp_path / "ds"
    corpus = read_corpus(plain_corpus)
    build_dataset(corpus, KEY, _spec(), out)
    scoped = [s for s in corpus.subjects if s.key.kind is KeyKind.SCOPED_RECORD_NUMBER]

    assert scoped, "this corpus cannot exercise the finding"

    whole = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in out.rglob("*")
        if path.is_file()
    )
    checked = 0
    for subject in scoped:
        stated = {identity.national_id for identity in subject.identities}
        stated |= {report.declared().national_id for report in subject.reports}
        for value in stated:
            if not value or value.upper() in PLACEHOLDER_IDENTIFIERS:
                continue
            assert value not in whole, value
            checked += 1

    assert checked > 0, "no codice fiscale was declared for a record-number subject"


def test_redaction_is_built_from_every_identity_and_not_the_first(
    plain_corpus: Path,
) -> None:
    """The consumer of the audit's central fix, which nothing was guarding.

    `KnownIdentifiers.identities` is plural because of the critical defect of
    2026-11-13: a subject assembled from several laboratory messages has one
    identity per message, they can disagree, and carrying only the first made
    every name in the others a name redaction never looked for. That is
    guarded where the identities are *resolved*, in ``read/identity.py``.

    **It was not guarded where they are consumed.** A sabotage of this session
    replaced ``tuple(subject.identities)`` with ``tuple(subject.identities[:1])``
    in ``build.writer._known_identifiers`` and the whole suite passed. The
    reason is worth keeping, because it is the project's own recurring
    finding: those names reach the dataset through no path a *generated*
    corpus produces. A later identity's family name is declared in an HL7
    PID-5, the laboratory branch writes no patient name into ``lab/*.tsv``,
    and where a report names somebody other than its subject the name is in
    that report's own header, which ``declared`` covers. So dropping them
    produces no leak here while leaving a real one open for a hospital whose
    reports name a patient in prose that only a laboratory message spells.

    Which makes this an assertion on the plan rather than on the output: the
    only honest place to catch it. Measured rather than assumed — this corpus
    has seven subjects carrying more than one identity.
    """
    corpus = read_corpus(plain_corpus)
    multiple = [subject for subject in corpus.subjects if len(subject.identities) > 1]

    assert multiple, "this corpus cannot exercise the fix"

    for subject in multiple:
        known = _known_identifiers(corpus, subject)
        assert known.identities == tuple(subject.identities)


def test_the_corpus_still_measures_clean(plain_corpus: Path, tmp_path: Path) -> None:
    """End to end, because a new shape of input is what moves this number."""
    out = tmp_path / "ds"
    build_dataset(read_corpus(plain_corpus), KEY, _spec(), out)
    report = measure(plain_corpus, out)

    assert report.survived == 0
    assert report.measurable > 0
