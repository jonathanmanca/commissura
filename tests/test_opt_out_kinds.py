"""An objection can now reach a subject who holds no codice fiscale.

The gap this closes was recorded as a limit on 2026-11-19, in the module
docstring and in the manifest's own note: ``--exclude-subjects`` matched on
national identifiers, so a subject this corpus established from an
institution's own record number, or from an ENI, STP or ANA code, could not be
reached by any entry at all. For those people the holder had no way to act on
an objection except by deleting files by hand -- which is the failure the flag
exists to remove.

**The mechanism needed nothing.** ``Exclusions`` already held
:class:`commissura.read.identity.IdentityKey`, and a key already carried its
kind and its authority, so the match was general from the day it was written.
What was narrow was the *parser*: it read every line as a codice fiscale. That
is worth knowing before reading the diff, because it is why closing a
capability gap touched no arithmetic -- the record counts, the flagged count
and the three-part reconciliation of ``records_not_in_dataset`` are all
unchanged.

**A line declares its kind; nothing is inferred from the shape of a value.**
That distinction is what keeps this consistent with the 2026-11-19 decision
against accepting both identifiers and subject labels: that design would have
*guessed* from the shape of a value, and guessing is how a file is read in the
wrong mode and nobody is excluded.

The tests that matter most here are the end-to-end ones. A parser that builds a
key the readers would never produce would pass every unit test and exclude
nobody, silently, which is this project's worst failure shape -- so the keys
these tests exclude on are taken from a corpus that really produced them.

Every identifier here is synthetic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from commissura.build.manifest import write_manifest
from commissura.build.optout import (
    FIELD_SEPARATOR,
    ExclusionFileError,
    read_exclusions,
)
from commissura.build.writer import BuildSpec, build_dataset
from commissura.cli import app
from commissura.deident.keys import SecretKey
from commissura.generate.cohort import CohortSpec
from commissura.generate.writer import write_corpus
from commissura.layout import DEIDENT_DIR, MANIFEST_JSON
from commissura.read.corpus import read_corpus
from commissura.read.identity import IdentityKey, KeyKind

KEY = SecretKey(bytes(range(32)))

VALID_CODICE_FISCALE = "CRSNGL57B67X596U"
"""One synthetic codice fiscale, used where the value itself does not matter."""

runner = CliRunner()


@pytest.fixture(scope="module")
def cda_corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A CDA corpus, where one subject in four holds no codice fiscale."""
    root = tmp_path_factory.mktemp("opt-out-kinds") / "raw"
    write_corpus(CohortSpec(subjects=14, seed=42, defect_rate=0.1, cda=True), root)
    return root


def _entry(key: IdentityKey) -> str:
    """Return the line a holder would write to exclude this subject."""
    if key.kind is KeyKind.NATIONAL_ID:
        return key.value
    return FIELD_SEPARATOR.join((key.kind.value, key.authority, key.value))


UNUSABLE_MESSAGE = """MSH|^~\\&|LIS|OSPEDALE SINTETICO DI PROVA|||20230512101500\
||ORU^R01|MSG0001|P|2.5
PID|1||{mrn}^^^OSPEDALE SINTETICO DI PROVA^MR~UNKNOWN^^^MINSAL^NNITA||\
{family}^{given}||19500506|F|||VIA SINTETICA 1^^MILANO^MI^20100^100
OBR|1|ACC{mrn}|ACC{mrn}|CBC^Emocromo^L|||20230512101500
OBX|1|NM|718-7^Haemoglobin^LN||13.2|g/dL|12.0-16.0|N|||F
"""
"""A laboratory message whose national identifier is the string ``UNKNOWN``.

**The audit's own reproduction, from 2026-11-13**, and what establishes a
subject on an institution-scoped record number: the national identifier is a
placeholder, so it is never a key, and the record number identifies the patient
within the institution that issued it.

A fixture and not a generator defect, for a reason worth knowing: **no
generated corpus produces a subject of this kind.** Measured rather than
assumed -- fourteen subjects at defect rates 0.1, 0.6 and 1.0, with and without
CDA, give only ``national_id`` and ``assigned_identifier``. Closing that means
a new defect, which shifts the random stream and moves every number the README
captures; this project does that deliberately rather than in passing, so it is
queued in the brief instead of done here.
"""


def _unusable_corpus(root: Path) -> None:
    """Write a corpus whose subjects are keyed on an institution's record number."""
    (root / "lab").mkdir(parents=True)
    for index, (mrn, family, given) in enumerate(
        (("0012345", "FONTANA", "FRANCESCA"), ("0067890", "GRECO", "LUCA")), start=1
    ):
        (root / "lab" / f"{mrn}_{index}.hl7").write_text(
            UNUSABLE_MESSAGE.format(mrn=mrn, family=family, given=given),
            encoding="utf-8",
            newline="",
        )


@pytest.fixture(scope="module")
def scoped_corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A corpus whose subjects hold no usable national identifier."""
    root = tmp_path_factory.mktemp("opt-out-scoped") / "raw"
    _unusable_corpus(root)
    return root


def _corpus_for(kind: KeyKind, cda: Path, scoped: Path) -> Path:
    """Return whichever corpus establishes subjects of this kind."""
    return scoped if kind is KeyKind.SCOPED_RECORD_NUMBER else cda


def _a_subject_keyed_on(corpus_root: Path, kind: KeyKind) -> IdentityKey:
    """Return one subject key of the given kind, or skip if the corpus has none."""
    corpus = read_corpus(corpus_root)
    for subject in corpus.subjects:
        if subject.key.kind is kind:
            return subject.key
    pytest.skip(f"this corpus established no subject on a {kind.value}")


def _spec() -> BuildSpec:
    return BuildSpec(dataset_name="d", description="d", hdab="H", publisher="P")


def _build(corpus_root: Path, out: Path, listing: Path) -> dict[str, object]:
    """Build with an exclusion list and return the manifest's opt-out section.

    `build_dataset` writes the dataset and `write_manifest` writes the document
    that describes it. The command calls both, so a test that wants the
    manifest has to as well.
    """
    corpus = read_corpus(corpus_root)
    summary = build_dataset(corpus, KEY, _spec(), out, exclusions=read_exclusions(listing))
    assert summary.opt_out is not None
    write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=_spec())
    payload = json.loads((out / DEIDENT_DIR / MANIFEST_JSON).read_text(encoding="utf-8"))
    section: dict[str, object] = payload["source"]["opt_out"]
    return section


# --------------------------------------------------------------------------
# End to end: the two kinds that could not be reached
# --------------------------------------------------------------------------


@pytest.mark.parametrize("kind", [KeyKind.SCOPED_RECORD_NUMBER, KeyKind.ASSIGNED_IDENTIFIER])
def test_an_objection_reaches_a_subject_who_holds_no_codice_fiscale(
    cda_corpus: Path, scoped_corpus: Path, tmp_path: Path, kind: KeyKind
) -> None:
    """The gap, closed, and asserted on a key the corpus really produced.

    Taking the key from the corpus rather than writing one here is the whole
    point: a parser that assembled a key the readers would never produce would
    satisfy any unit test and exclude nobody.
    """
    root = _corpus_for(kind, cda_corpus, scoped_corpus)
    key = _a_subject_keyed_on(root, kind)
    listing = tmp_path / "list.txt"
    listing.write_text(f"{_entry(key)}\n", encoding="utf-8")

    section = _build(root, tmp_path / "ds", listing)

    assert section["subjects_excluded"] == 1
    assert section["entries_matching_no_subject"] == 0
    assert isinstance(section["records_excluded"], int)
    assert section["records_excluded"] > 0


@pytest.mark.parametrize("kind", [KeyKind.SCOPED_RECORD_NUMBER, KeyKind.ASSIGNED_IDENTIFIER])
def test_the_excluded_subject_is_absent_from_the_dataset(
    cda_corpus: Path, scoped_corpus: Path, tmp_path: Path, kind: KeyKind
) -> None:
    """Excluded means absent, not flagged — checked on the participants table.

    A count in the manifest saying a subject was excluded, over a dataset that
    still holds them, would be the withdrawal that did not withdraw
    (2026-11-13) with a number attached.
    """
    root = _corpus_for(kind, cda_corpus, scoped_corpus)
    key = _a_subject_keyed_on(root, kind)
    listing = tmp_path / "list.txt"
    listing.write_text(f"{_entry(key)}\n", encoding="utf-8")

    whole = tmp_path / "whole"
    build_dataset(read_corpus(root), KEY, _spec(), whole)
    reduced = tmp_path / "reduced"
    build_dataset(read_corpus(root), KEY, _spec(), reduced, exclusions=read_exclusions(listing))

    def participants(root: Path) -> set[str]:
        lines = (root / "participants.tsv").read_text(encoding="utf-8").splitlines()
        return {line.split("\t")[0] for line in lines[1:]}

    missing = participants(whole) - participants(reduced)

    assert len(missing) == 1
    assert participants(reduced) < participants(whole)


def test_everybody_else_is_byte_identical(cda_corpus: Path, tmp_path: Path) -> None:
    """An exclusion must not move another subject's labels or offsets.

    The property pinned for the national form on 2026-11-19, asserted again for
    a new one: a data user holding the earlier dataset must still be able to
    join it to this one on everybody who remains.
    """
    key = _a_subject_keyed_on(cda_corpus, KeyKind.ASSIGNED_IDENTIFIER)
    listing = tmp_path / "list.txt"
    listing.write_text(f"{_entry(key)}\n", encoding="utf-8")

    whole = tmp_path / "whole"
    build_dataset(read_corpus(cda_corpus), KEY, _spec(), whole)
    reduced = tmp_path / "reduced"
    build_dataset(
        read_corpus(cda_corpus),
        KEY,
        _spec(),
        reduced,
        exclusions=read_exclusions(listing),
    )

    shared = 0
    for path in reduced.rglob("*"):
        relative = path.relative_to(reduced)
        other = whole / relative
        if not path.is_file() or not other.is_file():
            continue
        if relative.parts[0] == DEIDENT_DIR or not relative.parts[0].startswith("sub-"):
            continue
        assert path.read_bytes() == other.read_bytes(), relative.as_posix()
        shared += 1

    assert shared > 0


# --------------------------------------------------------------------------
# What the file may say
# --------------------------------------------------------------------------


def test_a_bare_line_is_still_a_codice_fiscale(tmp_path: Path) -> None:
    """A standing list must not need rewriting because the tool grew.

    This is the form every exclusion list held before the two new ones existed,
    and it means exactly what it meant.
    """
    listing = tmp_path / "list.txt"
    listing.write_text(f"# an objection\n{VALID_CODICE_FISCALE}\n\n", encoding="utf-8")

    exclusions = read_exclusions(listing)

    assert len(exclusions) == 1
    assert exclusions.excludes(IdentityKey.national(VALID_CODICE_FISCALE))
    assert exclusions.by_kind()[KeyKind.NATIONAL_ID.value] == 1


def test_the_prefixed_national_form_means_the_same_thing(tmp_path: Path) -> None:
    """Offered so a holder can make every line explicit, at no cost in meaning."""
    bare = tmp_path / "bare.txt"
    bare.write_text(f"{VALID_CODICE_FISCALE}\n", encoding="utf-8")
    declared = tmp_path / "declared.txt"
    declared.write_text(
        f"{KeyKind.NATIONAL_ID.value}{FIELD_SEPARATOR}{VALID_CODICE_FISCALE}\n",
        encoding="utf-8",
    )

    assert read_exclusions(bare).keys == read_exclusions(declared).keys


def test_spacing_case_and_leading_zeros_do_not_decide_whether_an_objection_acts(
    tmp_path: Path,
) -> None:
    """Because the holder is transcribing from their own system, by hand.

    The readers compare a record number with leading zeros stripped and case
    folded -- which is what recovers the same patient across two exports -- so
    an entry has to be normalised the same way or the objection silently
    reaches nobody. Asserted as an equality between two spellings rather than
    against one expected key, so it cannot pass by both being wrong in the same
    way.
    """
    tidy = tmp_path / "tidy.txt"
    tidy.write_text(
        f"{KeyKind.SCOPED_RECORD_NUMBER.value}{FIELD_SEPARATOR}"
        f"OSPEDALE SINTETICO{FIELD_SEPARATOR}12345\n",
        encoding="utf-8",
    )
    untidy = tmp_path / "untidy.txt"
    untidy.write_text(
        f"  {KeyKind.SCOPED_RECORD_NUMBER.value} {FIELD_SEPARATOR} "
        f"ospedale   sintetico {FIELD_SEPARATOR} 0012345 \n",
        encoding="utf-8",
    )

    assert read_exclusions(tidy).keys == read_exclusions(untidy).keys


def test_the_authority_is_part_of_the_key(tmp_path: Path) -> None:
    """Two hospitals' record numbers are deliberately not one namespace.

    The audit of 2026-11-13 forced that separation into existence; an exclusion
    list that ignored the authority would flatten it again, and would exclude
    somebody at the wrong hospital.
    """
    listing = tmp_path / "list.txt"
    listing.write_text(
        f"{KeyKind.SCOPED_RECORD_NUMBER.value}{FIELD_SEPARATOR}OSPEDALE A{FIELD_SEPARATOR}12345\n",
        encoding="utf-8",
    )

    exclusions = read_exclusions(listing)

    assert exclusions.excludes(IdentityKey.scoped_record_number("OSPEDALE A", "12345"))
    assert not exclusions.excludes(IdentityKey.scoped_record_number("OSPEDALE B", "12345"))


def test_an_assigned_entry_normalises_its_value_and_not_its_namespace(
    tmp_path: Path,
) -> None:
    """The value is folded the way the reader folds it; the namespace is not.

    **Only the first half of that is assertable, and saying so is the point.**
    An issuing namespace is an OID -- digits and dots -- and
    `normalise_authority` upper-cases and collapses whitespace, so folding a
    real OID is indistinguishable from leaving it alone. A sabotage that
    case-folded it passed every test here, which proved nothing about the guard
    and everything about the example: the two code paths cannot differ for the
    values this kind actually carries.

    What does pin the agreement with the reader is
    `test_an_objection_reaches_a_subject_who_holds_no_codice_fiscale`, which
    excludes on a key a corpus really produced rather than on one written here.
    """
    oid = "2.16.840.1.113883.2.9.4.3.4"
    listing = tmp_path / "list.txt"
    listing.write_text(
        f"{KeyKind.ASSIGNED_IDENTIFIER.value}{FIELD_SEPARATOR}{oid}"
        f"{FIELD_SEPARATOR}stp0000000sintetic\n",
        encoding="utf-8",
    )

    exclusions = read_exclusions(listing)
    (key,) = exclusions.keys

    assert key.authority == oid
    assert key.value == "STP0000000SINTETIC"
    assert key.kind is KeyKind.ASSIGNED_IDENTIFIER


# --------------------------------------------------------------------------
# What the file may not say
# --------------------------------------------------------------------------


def test_a_kind_this_tool_does_not_know_is_refused(tmp_path: Path) -> None:
    """And the message lists the kinds there are, because the holder has to fix it."""
    listing = tmp_path / "list.txt"
    listing.write_text(f"subject_label{FIELD_SEPARATOR}a3f9c21b4e07\n", encoding="utf-8")

    with pytest.raises(ExclusionFileError, match="is not a kind of subject key"):
        read_exclusions(listing)


@pytest.mark.parametrize(
    "line",
    [
        f"{KeyKind.SCOPED_RECORD_NUMBER.value}{FIELD_SEPARATOR}12345",
        f"{KeyKind.SCOPED_RECORD_NUMBER.value}{FIELD_SEPARATOR}A{FIELD_SEPARATOR}1{FIELD_SEPARATOR}2",
        f"{KeyKind.SCOPED_RECORD_NUMBER.value}{FIELD_SEPARATOR}{FIELD_SEPARATOR}12345",
        f"{KeyKind.ASSIGNED_IDENTIFIER.value}{FIELD_SEPARATOR}STP0000000SINTETIC",
    ],
)
def test_an_authority_is_never_guessed(tmp_path: Path, line: str) -> None:
    """A scoped identifier is meaningless without the namespace that scopes it.

    So a line that omits it, leaves it blank, or carries one field too many is
    refused rather than read with a default. A default authority is the flat
    index the audit of 2026-11-13 removed.
    """
    listing = tmp_path / "list.txt"
    listing.write_text(f"{line}\n", encoding="utf-8")

    with pytest.raises(ExclusionFileError, match="field"):
        read_exclusions(listing)


def test_a_record_number_that_normalises_to_nothing_is_refused(tmp_path: Path) -> None:
    """``000`` strips to the empty string, which names nobody.

    Refused rather than kept as an empty key, which would match every subject
    whose authority happened to agree -- the one failure worse than excluding
    nobody.
    """
    listing = tmp_path / "list.txt"
    listing.write_text(
        f"{KeyKind.SCOPED_RECORD_NUMBER.value}{FIELD_SEPARATOR}OSPEDALE{FIELD_SEPARATOR}000\n",
        encoding="utf-8",
    )

    with pytest.raises(ExclusionFileError, match="normalises to nothing"):
        read_exclusions(listing)


def test_a_mistyped_codice_fiscale_is_still_refused_by_name(tmp_path: Path) -> None:
    """The property the whole identifier form exists for, in both spellings.

    A check character is what makes a transcription error loud instead of
    silent, and the prefixed form must not be a way around it.
    """
    wrong = VALID_CODICE_FISCALE[:-1] + ("A" if VALID_CODICE_FISCALE[-1] != "A" else "B")

    for line in (wrong, f"{KeyKind.NATIONAL_ID.value}{FIELD_SEPARATOR}{wrong}"):
        listing = tmp_path / "list.txt"
        listing.write_text(f"{line}\n", encoding="utf-8")
        with pytest.raises(ExclusionFileError, match="not a usable national identifier"):
            read_exclusions(listing)


# --------------------------------------------------------------------------
# What the documents say about it
# --------------------------------------------------------------------------


def test_the_manifest_says_what_kinds_the_list_named(scoped_corpus: Path, tmp_path: Path) -> None:
    """The one thing about a list an auditor cannot learn any other way.

    Counts and never values, for the reason the section's own note gives: a
    list of excluded subjects is a list of people who exercised a right.
    """
    key = _a_subject_keyed_on(scoped_corpus, KeyKind.SCOPED_RECORD_NUMBER)
    listing = tmp_path / "list.txt"
    listing.write_text(f"{_entry(key)}\n{VALID_CODICE_FISCALE}\n", encoding="utf-8")

    section = _build(scoped_corpus, tmp_path / "ds", listing)
    counts = section["entries_by_kind"]

    assert isinstance(counts, dict)
    assert counts[KeyKind.SCOPED_RECORD_NUMBER.value] == 1
    assert counts[KeyKind.NATIONAL_ID.value] == 1
    # A kind nobody listed is reported at zero rather than omitted.
    assert counts[KeyKind.ASSIGNED_IDENTIFIER.value] == 0


def test_the_manifest_carries_no_value_from_the_list(scoped_corpus: Path, tmp_path: Path) -> None:
    """Values never travel, authority included.

    An institution name is not a patient identifier, but beside a record number
    it narrows who the person is. The guard the manifest has needed four
    times: counts travel, values do not.
    """
    key = _a_subject_keyed_on(scoped_corpus, KeyKind.SCOPED_RECORD_NUMBER)
    listing = tmp_path / "list.txt"
    listing.write_text(f"{_entry(key)}\n", encoding="utf-8")
    out = tmp_path / "ds"

    _build(scoped_corpus, out, listing)
    manifest = (out / DEIDENT_DIR / MANIFEST_JSON).read_text(encoding="utf-8")

    assert key.value not in manifest
    assert _entry(key) not in manifest


def test_an_unmatched_scoped_entry_is_reported_with_its_authority(
    tmp_path: Path,
) -> None:
    """Because a bare record number is not the line the holder has to go and fix.

    The same number can belong to two people at two institutions, which is the
    whole reason the authority is part of the key, so printing the number alone
    would send a holder looking through the wrong list.
    """
    raw = tmp_path / "raw"
    write_corpus(CohortSpec(subjects=4, seed=11), raw)
    listing = tmp_path / "list.txt"
    entry = (
        f"{KeyKind.SCOPED_RECORD_NUMBER.value}{FIELD_SEPARATOR}"
        f"OSPEDALE CHE NON ESISTE{FIELD_SEPARATOR}999999"
    )
    listing.write_text(f"{entry}\n", encoding="utf-8")
    key_file = tmp_path / "k.key"
    key_file.write_text(KEY.material.hex(), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "build",
            str(raw),
            "--out",
            str(tmp_path / "ds"),
            "--key-file",
            str(key_file),
            "--hdab",
            "H",
            "--publisher",
            "P",
            "--exclude-subjects",
            str(listing),
        ],
    )

    assert result.exit_code == 0
    assert entry in result.stdout
