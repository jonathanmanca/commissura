"""Acting on an objection, and proving afterwards that it was acted on.

EHDS Article 71 gives a natural person the right to object to the secondary use
of their data, and TEHDAS2 D6.1 Annex 6 A6.2 (p. 68) marks acting on it
*Mandatory* for a health data holder: "Identify and remove data of natural
persons who opted-out." ``commissura whois`` could already derive the handle an
objection points at and ``build`` then built the whole corpus anyway, so the
holder deleted files by hand and **a dataset built after an objection was
indistinguishable from one built before it**.

Two decisions are pinned here, and the arguments for both are in
:mod:`commissura.build.optout`:

**The list holds national identifiers, not subject labels.** A label is valid
for exactly one key and one permit, and nothing can check it for a typing
error — so the dangerous failure, a holder who mistypes and sees a successful
build, is unavailable to the tool. A codice fiscale carries a check character.

**Refuse what is provably wrong; report what is merely suspicious.** An
unreadable file and a malformed entry are refused before anything is written.
An empty list and an entry that matches nobody here are reported, because each
has a legitimate reading the tool cannot distinguish from a mistake.

Every identifier here is synthetic.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from commissura import layout
from commissura.build.manifest import write_manifest
from commissura.build.optout import ExclusionFileError, Exclusions, read_exclusions
from commissura.build.writer import BuildSpec, build_dataset
from commissura.cli import app
from commissura.deident.keys import SecretKey
from commissura.deident.pseudonymise import Pseudonymiser
from commissura.generate.cohort import CohortSpec
from commissura.generate.writer import write_corpus
from commissura.identifiers import codice_fiscale
from commissura.measure import excluded_record_count
from commissura.models import Sex
from commissura.read.corpus import RawCorpus, read_corpus
from commissura.read.identity import IdentityKey, KeyKind

KEY = SecretKey(bytes(range(32)))
SPEC = BuildSpec(dataset_name="d", description="d", hdab="H", publisher="P")

runner = CliRunner()

# A well-formed codice fiscale belonging to nobody in any corpus here, used
# wherever the point is an entry that matches nothing.
ABSENT = "CRSNGL57B67X596U"


@pytest.fixture(scope="module")
def corpus_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A corpus large enough to hold somebody who can be left out of it."""
    root = tmp_path_factory.mktemp("opt-out") / "raw"
    write_corpus(CohortSpec(subjects=10, seed=42, defect_rate=0.2), root)
    return root


@pytest.fixture(scope="module")
def corpus(corpus_root: Path) -> RawCorpus:
    """The linked corpus."""
    return read_corpus(corpus_root)


@pytest.fixture(scope="module")
def objectors(corpus: RawCorpus) -> tuple[str, str]:
    """Two national identifiers this corpus actually holds."""
    national = [s.key.value for s in corpus.subjects if s.key.kind is KeyKind.NATIONAL_ID]
    assert len(national) >= 2, "this corpus cannot exercise an exclusion"
    return national[0], national[1]


def _build(out: Path, corpus: RawCorpus, exclusions: Exclusions | None) -> dict[str, object]:
    """Build a dataset and return its manifest."""
    summary = build_dataset(corpus, KEY, SPEC, out, exclusions=exclusions)
    return write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=SPEC)


def _digests(root: Path) -> dict[str, str]:
    """Return a digest per file under the dataset's subject directories."""
    return {
        str(path.relative_to(root)).replace("\\", "/"): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.parts[len(root.parts)].startswith(layout.SUBJECT_PREFIX)
    }


# --------------------------------------------------------------------------
# Reading the list
# --------------------------------------------------------------------------


def test_the_list_is_read_as_identifiers_and_normalised(tmp_path: Path) -> None:
    """Comments, blank lines, lowercase and stray whitespace all behave.

    Normalisation goes through the same function the linker uses, which is what
    makes an entry and a subject agree exactly or not at all.
    """
    path = tmp_path / "list.txt"
    path.write_text(
        f"# received 2026-03-04, ticket 1198\n{ABSENT.lower()}\n\n   {ABSENT}   \n",
        encoding="utf-8",
    )

    exclusions = read_exclusions(path)

    assert len(exclusions) == 1
    assert exclusions.excludes(IdentityKey.national(ABSENT))


def test_a_repeated_objection_is_one_objection(tmp_path: Path) -> None:
    """A standing list accumulated over months will name somebody twice."""
    path = tmp_path / "list.txt"
    path.write_text(f"{ABSENT}\n{ABSENT}\n", encoding="utf-8")

    assert len(read_exclusions(path)) == 1


def test_an_empty_list_is_not_an_error(tmp_path: Path) -> None:
    """A holder keeping a standing list has one before anybody objects.

    Failing the build every day until somebody did would teach them to ignore
    the failure, which is worse than the thing it would be warning about.
    """
    path = tmp_path / "list.txt"
    path.write_text("# nobody yet\n\n", encoding="utf-8")

    assert len(read_exclusions(path)) == 0


@pytest.mark.parametrize(
    ("entry", "status"),
    [
        ("DLCFRN62S44X217A", "bad_checksum"),
        ("NOT-AN-IDENTIFIER", "malformed"),
        ("UNKNOWN", "placeholder"),
        ("a3f9c21b4e07", "malformed"),
    ],
)
def test_an_entry_that_cannot_be_a_person_is_refused(
    tmp_path: Path, entry: str, status: str
) -> None:
    """Refused before anything is written, and the message names the line.

    The fourth case is the decision this module exists to carry: twelve hex
    characters are a subject label, and a label is accepted nowhere here. It is
    valid for one key and one permit, and no check character can tell a
    mistyped one from a real one — so a holder who mistypes would see a
    successful build and would not have acted on the objection.
    """
    path = tmp_path / "list.txt"
    path.write_text(f"# header\n{ABSENT}\n{entry}\n", encoding="utf-8")

    with pytest.raises(ExclusionFileError) as caught:
        read_exclusions(path)

    assert "line 3" in str(caught.value)
    assert status in str(caught.value)


def test_a_list_that_cannot_be_read_is_refused(tmp_path: Path) -> None:
    """A mistyped path is the likeliest mistake and the easiest to catch."""
    with pytest.raises(ExclusionFileError):
        read_exclusions(tmp_path / "nothing-here.txt")


def test_unmatched_entries_are_the_ones_no_subject_claimed() -> None:
    """Sorted, so two runs over one corpus report the same thing in order."""
    other = "DLCFRN62S44X217H"
    exclusions = Exclusions(frozenset({IdentityKey.national(ABSENT), IdentityKey.national(other)}))

    assert exclusions.unmatched([IdentityKey.national(other)]) == (ABSENT,)
    assert exclusions.unmatched([]) == tuple(sorted((ABSENT, other)))


# --------------------------------------------------------------------------
# What the build leaves out
# --------------------------------------------------------------------------


def test_an_excluded_subject_is_nowhere_in_the_dataset(
    tmp_path: Path, corpus: RawCorpus, objectors: tuple[str, str]
) -> None:
    """No directory, no participant row, and no identifier anywhere in the tree.

    Asserted over every file including the manifest and the description, not
    only over the subject tree: the point of an objection is that the dataset
    says nothing about the person, and a count in a document that travels would
    still be saying something.
    """
    out = tmp_path / "ds"
    excluded, _ = objectors
    subject = next(s for s in corpus.subjects if s.key.value == excluded)
    label = Pseudonymiser(KEY).subject_label_for(subject.key)

    _build(out, corpus, Exclusions(frozenset({IdentityKey.national(excluded)})))

    assert not (out / f"{layout.SUBJECT_PREFIX}{label}").exists()
    whole = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in sorted(out.rglob("*"))
        if path.is_file()
    )
    assert label not in whole
    assert excluded not in whole
    for identity in subject.identities:
        assert identity.family_name not in whole
        assert identity.mrn not in whole


def test_everybody_else_is_untouched(
    tmp_path: Path, corpus: RawCorpus, objectors: tuple[str, str]
) -> None:
    """Byte-identical, which is the property that makes this safe to use.

    An exclusion must not move another subject's label, offsets or redactions.
    If it did, a holder acting on one person's objection would be handing a data
    user a dataset that no longer joins to the one they already have.
    """
    excluded, _ = objectors
    plain, filtered = tmp_path / "plain", tmp_path / "filtered"
    _build(plain, corpus, None)
    _build(filtered, corpus, Exclusions(frozenset({IdentityKey.national(excluded)})))

    before, after = _digests(plain), _digests(filtered)

    assert set(after) < set(before), "exclusion removed nothing"
    assert all(before[name] == after[name] for name in after)


def test_an_empty_list_builds_the_same_files_as_no_list(tmp_path: Path, corpus: RawCorpus) -> None:
    """Supplying a list that names nobody is not a different build."""
    plain, empty = tmp_path / "plain", tmp_path / "empty"
    _build(plain, corpus, None)
    _build(empty, corpus, Exclusions(frozenset()))

    assert _digests(plain) == _digests(empty)


def test_the_participant_count_is_what_the_dataset_holds(
    tmp_path: Path, corpus: RawCorpus, objectors: tuple[str, str]
) -> None:
    """`numberOfUniqueIndividuals` derives from it, and an excluded person is not one."""
    out = tmp_path / "ds"
    excluded, _ = objectors

    manifest = _build(out, corpus, Exclusions(frozenset({IdentityKey.national(excluded)})))

    source = manifest["source"]
    assert isinstance(source, dict)
    rows = (out / layout.PARTICIPANTS_TSV).read_text(encoding="utf-8").splitlines()[1:]
    assert len(rows) == source["subjects_linked"] - 1
    output = manifest["output"]
    assert isinstance(output, dict)
    assert output["subjects"] == len(rows)


# --------------------------------------------------------------------------
# What the manifest says, and what it must not
# --------------------------------------------------------------------------


def test_a_build_with_no_list_says_so_rather_than_counting_zero(
    tmp_path: Path, corpus: RawCorpus
) -> None:
    """A reader cannot otherwise tell "excluded nobody" from "was never asked".

    The same reasoning as the modality ledger reporting a declared field at
    zero rather than dropping its row: an absent collection is not evidence
    about what would have filled it.
    """
    manifest = _build(tmp_path / "ds", corpus, None)

    source = manifest["source"]
    assert isinstance(source, dict)
    opt_out = source["opt_out"]
    assert isinstance(opt_out, dict)
    assert opt_out["applied"] is False
    assert "subjects_excluded" not in opt_out


def test_the_manifest_counts_the_exclusion_and_names_nobody(
    tmp_path: Path, corpus: RawCorpus, objectors: tuple[str, str]
) -> None:
    """The whole of R-08: the dataset is now distinguishable from one built before.

    And the leak guard that has to come with it. A list of excluded subjects is
    a list of people who exercised a right to object, which is a disclosure in
    itself, in the one document written to be sent to an access body. Neither
    the identifiers, nor the labels they resolve to, nor the paths of their
    records may appear.
    """
    out = tmp_path / "ds"
    excluded, _ = objectors
    subject = next(s for s in corpus.subjects if s.key.value == excluded)
    paths = [r.path for r in subject.labs] + [r.path for r in subject.reports]

    manifest = _build(
        out,
        corpus,
        Exclusions(frozenset({IdentityKey.national(excluded), IdentityKey.national(ABSENT)})),
    )

    source = manifest["source"]
    assert isinstance(source, dict)
    opt_out = source["opt_out"]
    assert isinstance(opt_out, dict)
    assert opt_out["applied"] is True
    assert opt_out["entries"] == 2
    assert opt_out["subjects_excluded"] == 1
    assert opt_out["records_excluded"] == len(subject.labs) + len(subject.reports) + len(
        subject.imaging
    )
    assert opt_out["entries_matching_no_subject"] == 1

    text = (out / layout.DEIDENT_DIR / layout.MANIFEST_JSON).read_text(encoding="utf-8")
    assert excluded not in text
    assert ABSENT not in text, "an entry that matched nothing is still a person"
    assert Pseudonymiser(KEY).subject_label_for(subject.key) not in text
    for path in paths:
        assert Path(path).name not in text


def test_the_absent_record_count_reconciles(
    tmp_path: Path, corpus: RawCorpus, objectors: tuple[str, str]
) -> None:
    """Three parts, each visible on its own, so the total can be checked.

    `records_not_in_dataset` widened in schema 7.0.0 and a consumer summing the
    two lists beside it no longer reaches it. The third part has to be readable
    from the same section or the number is unauditable.
    """
    out = tmp_path / "ds"
    excluded, _ = objectors

    manifest = _build(out, corpus, Exclusions(frozenset({IdentityKey.national(excluded)})))

    source = manifest["source"]
    assert isinstance(source, dict)
    dropped = source["records_dropped"]
    assert isinstance(dropped, list)
    opt_out = source["opt_out"]
    assert isinstance(opt_out, dict)
    refused = (
        source["records_not_in_dataset"]
        - sum(int(row["count"]) for row in dropped)
        - int(opt_out["records_excluded"])
    )
    assert refused >= 0
    assert source["records_not_in_dataset"] == refused + sum(
        int(row["count"]) for row in dropped
    ) + int(opt_out["records_excluded"])


def test_a_flagged_record_of_an_excluded_subject_is_not_counted_as_present(
    tmp_path: Path, corpus: RawCorpus
) -> None:
    """It is not in the dataset, whatever its attribution was flagged for.

    This is the 2026-11-16 defect in a new coat: `records_flagged_in_dataset`
    counts linkage issues whose reason keeps the record, and exclusion is a
    fourth way for a kept record to be absent. Driven by excluding exactly the
    subjects whose records carry such an issue, so the count must fall.
    """
    plain, filtered = tmp_path / "plain", tmp_path / "filtered"
    before = _build(plain, corpus, None)
    source_before = before["source"]
    assert isinstance(source_before, dict)
    flagged = int(source_before["records_flagged_in_dataset"])
    assert flagged, "this corpus has no flagged record to exercise the count"

    flagged_paths = {issue.path for issue in corpus.issues}
    owner = next(
        (
            s.key
            for s in corpus.subjects
            if flagged_paths
            & ({r.path for r in s.labs} | {r.path for r in s.reports} | {r.path for r in s.imaging})
        ),
        None,
    )
    assert owner is not None, "no subject here owns a flagged record"

    after = _build(filtered, corpus, Exclusions(frozenset({owner})))

    source_after = after["source"]
    assert isinstance(source_after, dict)
    assert int(source_after["records_flagged_in_dataset"]) < flagged


def test_measure_counts_an_excluded_record_as_absent(
    tmp_path: Path, corpus: RawCorpus, objectors: tuple[str, str]
) -> None:
    """A record that was never written removes its identifiers by not existing.

    In the degenerate case a build that excluded everybody would score a perfect
    recall for producing nothing, so the caveat `measure` prints beside the
    recall has to grow with the exclusion. It reads
    `source.records_not_in_dataset`, which is why that field had to widen rather
    than gain a sibling.
    """
    plain, filtered = tmp_path / "plain", tmp_path / "filtered"
    excluded, _ = objectors
    _build(plain, corpus, None)
    _build(filtered, corpus, Exclusions(frozenset({IdentityKey.national(excluded)})))

    assert excluded_record_count(filtered) > excluded_record_count(plain)


# --------------------------------------------------------------------------
# Through the command
# --------------------------------------------------------------------------


def _key_file(tmp_path: Path) -> Path:
    path = tmp_path / "k.key"
    path.write_text(KEY.material.hex(), encoding="utf-8")
    return path


def test_the_command_refuses_a_bad_list_before_writing_anything(
    tmp_path: Path, corpus_root: Path
) -> None:
    """A holder with a typo learns in a second, not after a dataset is staged."""
    listing = tmp_path / "list.txt"
    listing.write_text("DLCFRN62S44X217A\n", encoding="utf-8")
    out = tmp_path / "ds"

    result = runner.invoke(
        app,
        [
            "build",
            str(corpus_root),
            "--out",
            str(out),
            "--key-file",
            str(_key_file(tmp_path)),
            "--exclude-subjects",
            str(listing),
        ],
    )

    assert result.exit_code == 2
    assert not out.exists()


def test_the_command_reports_what_it_excluded_and_what_it_could_not(
    tmp_path: Path, corpus_root: Path, objectors: tuple[str, str]
) -> None:
    """Counts on the terminal, plus the entries that matched nothing by name.

    Named here and in no document: the operator already holds this file, and
    these are the lines they have to go and check. An entry matching nothing is
    reported rather than fatal, so the build still succeeds.
    """
    excluded, _ = objectors
    listing = tmp_path / "list.txt"
    listing.write_text(f"{excluded}\n{ABSENT}\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "build",
            str(corpus_root),
            "--out",
            str(tmp_path / "ds"),
            "--key-file",
            str(_key_file(tmp_path)),
            "--exclude-subjects",
            str(listing),
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["opt_out"]["subjects_excluded"] == 1
    assert payload["opt_out"]["entries_matching_no_subject"] == 1
    # Counts, not values, on the machine-readable branch: `--json` exists so
    # this command composes into somebody else's pipeline, and a pipeline's
    # stdout outlives the run in a log file far more often than a terminal does.
    assert ABSENT not in result.stdout
    assert excluded not in result.stdout


def test_the_text_output_names_the_entries_that_matched_nothing(
    tmp_path: Path, corpus_root: Path
) -> None:
    """Without the value a holder cannot tell which line to go and look at."""
    listing = tmp_path / "list.txt"
    listing.write_text(f"{ABSENT}\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "build",
            str(corpus_root),
            "--out",
            str(tmp_path / "ds"),
            "--key-file",
            str(_key_file(tmp_path)),
            "--exclude-subjects",
            str(listing),
        ],
    )

    assert result.exit_code == 0
    assert "Opt-out exclusions" in result.stdout
    assert ABSENT in result.stdout
    assert "cannot tell which" in result.stdout


def test_a_long_list_of_unmatched_entries_is_truncated(tmp_path: Path, corpus_root: Path) -> None:
    """A standing list matching nothing must not bury the rest of the output.

    The identifiers are built here rather than borrowed from another corpus, so
    they are impossible by construction: the place code is in the ``X`` range,
    which no municipality and no foreign state holds. The assertion that all
    eleven went unmatched is also what would fail, loudly, if one of them ever
    collided with a generated subject.
    """
    absent = [
        codice_fiscale("ROSSI", "MARIO", date(1970, 1, day), Sex.MALE, "X001")
        for day in range(1, 12)
    ]
    listing = tmp_path / "list.txt"
    listing.write_text("\n".join(absent) + "\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "build",
            str(corpus_root),
            "--out",
            str(tmp_path / "ds"),
            "--key-file",
            str(_key_file(tmp_path)),
            "--exclude-subjects",
            str(listing),
        ],
    )

    assert result.exit_code == 0
    assert "... and 1 more" in result.stdout


def test_excluded_records_are_counted_in_records_and_not_in_files(tmp_path: Path) -> None:
    """A CDA laboratory document is two records at one path, and both are absent.

    `records_not_in_dataset` has to reconcile against `records_linked` and
    `records_dropped`, which are both counted in records. Counting files instead
    would agree with this on every HL7 corpus and undercount on every CDA one --
    a unit error that no corpus in the rest of this file could see.
    """
    raw, out = tmp_path / "raw", tmp_path / "ds"
    write_corpus(CohortSpec(subjects=8, seed=42, defect_rate=0.0, cda=True), raw)
    cda_corpus = read_corpus(raw)
    subject = next(s for s in cda_corpus.subjects if s.labs and s.reports)
    records = len(subject.labs) + len(subject.reports) + len(subject.imaging)
    paths = (
        {r.path for r in subject.labs}
        | {r.path for r in subject.reports}
        | {r.path for r in subject.imaging}
    )
    assert records > len(paths), "no document here yields two records"

    manifest = _build(out, cda_corpus, Exclusions(frozenset({subject.key})))

    source = manifest["source"]
    assert isinstance(source, dict)
    opt_out = source["opt_out"]
    assert isinstance(opt_out, dict)
    assert opt_out["records_excluded"] == records


def test_a_subject_holding_no_codice_fiscale_is_reported_as_out_of_reach(
    tmp_path: Path,
) -> None:
    """The limit of this whole feature, said out loud where the operator is.

    A list of codici fiscali cannot reach a subject the corpus established from
    an institution's own record number or from an ENI, STP or ANA code, because
    no codice fiscale was ever stated for them. A holder who reads "1 subject
    excluded" and nothing else would not know the list was never even offered
    the chance on the others.

    Driven from a CDA corpus, where one subject in four is enrolled under one of
    those codes, so the path is reached by a generated corpus rather than by a
    fixture.
    """
    raw = tmp_path / "raw"
    write_corpus(CohortSpec(subjects=12, seed=42, defect_rate=0.1, cda=True), raw)
    listing = tmp_path / "list.txt"
    listing.write_text(f"{ABSENT}\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "build",
            str(raw),
            "--out",
            str(tmp_path / "ds"),
            "--key-file",
            str(_key_file(tmp_path)),
            "--exclude-subjects",
            str(listing),
        ],
    )

    assert result.exit_code == 0
    # The sentence this used to assert -- "no entry on the list could reach
    # them" -- was true until the list learnt to name a kind, and asserting it
    # now would pin the limit rather than the report. What it always meant is
    # that the holder is told these subjects exist and told what to write, and
    # that is what it checks.
    assert "ENI, STP or ANA code" in result.stdout
    assert "No bare codice fiscale reaches them" in result.stdout
    assert "scoped_record_number|authority|number" in result.stdout
    # And the list's own composition beside the corpus's, because a holder
    # comparing "12 subjects of a kind" against "0 entries of that kind" is the
    # one who catches a list aimed at the wrong population before a build goes
    # out.
    assert "This list names 0 of the first and 0 of the second." in result.stdout
