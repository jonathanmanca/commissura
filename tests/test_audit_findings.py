"""The three findings the audit of 2026-11-13 left open, and their guards.

All three were filed as informational: two were "one docstring sentence" and
the third was mitigated but not closed. Closing them before publication rather
than after is the whole argument for doing it now — one of the three moves
derived values, and a derivation that moves after a release is a migration for
everybody who has built a dataset.

* **Finding 13**, the accession collision check. `subject_label` refuses a
  collision and `accession` does not, which is correct and was undocumented.
  Closed with the reasoning in the docstring; nothing here to assert about
  behaviour, so this file asserts that the asymmetry is still the way round
  that the reasoning describes.
* **Finding 14**, the ``2.25`` arc. It is defined as a UUID rendered as a
  single integer and was carrying a 112-bit value that is not one. Closed by
  emitting a conformant UUID.
* **Finding 10**, symlinks. `digest_tree` read *through* a link, so a link to a
  file outside the dataset was digested as though its bytes belonged to it.
  Closed by reporting links and never digesting them.

Every identifier here is synthetic.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from commissura.build.integrity import digest_tree, symlinks_under, verify_dataset
from commissura.deident.keys import SecretKey
from commissura.deident.pseudonymise import RULE_VERSION, UID_ROOT, Pseudonymiser

KEY = SecretKey(bytes(range(32)))

OTHER = SecretKey(bytes(range(1, 33)))

DICOM_UID_LIMIT = 64
"""The maximum length of a DICOM UID, from PS3.5. Not a choice of ours."""


def _uuid_of(dicom_uid: str) -> uuid.UUID:
    """Decode a ``2.25`` OID the way the arc says it should be decodable."""
    prefix, _, integer = dicom_uid.partition(f"{UID_ROOT}.")
    assert prefix == "", dicom_uid
    return uuid.UUID(int=int(integer))


# --------------------------------------------------------------------------
# Finding 14: the 2.25 arc carries a UUID
# --------------------------------------------------------------------------


def test_a_pseudonymous_uid_decodes_to_a_conformant_uuid() -> None:
    """Which is the one thing the ``2.25`` arc promises a consumer.

    ITU-T X.667 defines the arc as a UUID rendered as a single integer. The
    previous form took fourteen digest bytes, so the integer was 112 bits: well
    formed as a DICOM UID, unique in practice, and not a UUID. Anybody decoding
    it got a wrong answer, silently, which is the shape of defect this project
    treats as worse than a loud one.
    """
    derived = Pseudonymiser(KEY).uid("1.2.840.113619.2.55.3.604688654")
    decoded = _uuid_of(derived)

    assert decoded.version == 8
    assert decoded.variant == uuid.RFC_4122


def test_a_pseudonymous_uid_fits_the_standard_s_own_limit() -> None:
    """A 128-bit integer is at most 39 digits, so the arc plus it is at most 44.

    Asserted against the limit rather than against 44, because the limit is the
    constraint and the length is a consequence. Checked over many inputs, since
    a short integer would hide a long one.
    """
    pseudonymiser = Pseudonymiser(KEY)

    for index in range(500):
        derived = pseudonymiser.uid(f"1.2.840.10008.5.1.4.1.1.{index}")
        assert len(derived) <= DICOM_UID_LIMIT
        assert derived.startswith(f"{UID_ROOT}.")
        assert derived.split(".", 2)[2].isdigit()


def test_a_pseudonymous_uid_is_deterministic_and_keyed() -> None:
    """The two properties the whole scheme rests on, on the changed function.

    Determinism is what makes a multimodal dataset linkable at all; the key is
    what makes the pseudonym useless without it. A change to the derivation is
    exactly where either could be lost without any test noticing.
    """
    original = "1.2.392.200036.9116.2.5.1.37"

    assert Pseudonymiser(KEY).uid(original) == Pseudonymiser(KEY).uid(original)
    assert Pseudonymiser(KEY).uid(original) != Pseudonymiser(OTHER).uid(original)
    assert Pseudonymiser(KEY).uid(original) != Pseudonymiser(KEY).uid(original + "0")


def test_the_rule_version_moved_with_the_derivation() -> None:
    """Because a holder has no other way to tell that a rebuild moves values.

    This is the lesson of 2026-11-10, recorded by this project and then walked
    past four times: the version is part of the change and not a chore
    afterwards. Imaging UIDs move between 1.1.0 and 1.2.0 and subject labels do
    not, which is what the constant's own docstring has to say for the number
    to be worth anything.
    """
    assert RULE_VERSION == "1.2.0"

    explanation = Pseudonymiser.uid.__doc__ or ""
    assert "version 8" in explanation
    assert "migration" in explanation


# --------------------------------------------------------------------------
# Finding 13: the asymmetry is documented, and is the right way round
# --------------------------------------------------------------------------


def test_a_subject_label_refuses_a_collision_and_an_accession_does_not() -> None:
    """The asymmetry, asserted so the docstring cannot drift away from it.

    A merged subject label is a redaction failure, because targeted redaction
    removes what the exports declared *for a subject*. A shared accession is a
    cosmetic oddity in one column that nothing is keyed on. So the guard
    belongs on one and not the other, and this pins which.
    """
    pseudonymiser = Pseudonymiser(KEY)

    assert pseudonymiser.issued_subject_count() == 0
    pseudonymiser.subject_label("RSSMRA80A01X000Y")
    assert pseudonymiser.issued_subject_count() == 1

    # An accession is derived without being witnessed at all, which is the
    # observable half of "no collision check".
    pseudonymiser.accession("LAB0000001")
    assert pseudonymiser.issued_subject_count() == 1

    reasoning = Pseudonymiser.accession.__doc__ or ""
    assert "collision check" in reasoning
    assert "48 bits" in reasoning
    assert "64 bits" in reasoning


# --------------------------------------------------------------------------
# Finding 10: a symlink is reported, never digested
# --------------------------------------------------------------------------


def _link(target: Path, link: Path) -> bool:
    """Create a symlink, or report that this platform will not allow it."""
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        return False
    return True


def test_a_symlink_is_reported_and_its_bytes_are_not_digested(tmp_path: Path) -> None:
    """`is_file()` reads through a link, which is what made this a defect.

    A link to a file outside the dataset was digested as though its bytes were
    part of the dataset, so the manifest authenticated content the dataset does
    not contain -- and a copy made without following links would then verify as
    altered through no fault of whoever copied it.
    """
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("not part of any dataset\n", encoding="utf-8")
    root = tmp_path / "dataset"
    root.mkdir()
    (root / "real.txt").write_text("part of it\n", encoding="utf-8")

    if not _link(outside, root / "link.txt"):
        pytest.skip("symlink creation needs elevation on Windows")

    digests = digest_tree(root)

    assert set(digests) == {"real.txt"}
    assert symlinks_under(root) == ("link.txt",)


def test_a_dataset_with_no_symlink_reports_none(tmp_path: Path) -> None:
    """The other half, which needs no privileges and so runs everywhere.

    A guard that only ever fires is as uninformative as one that never does,
    and this is the half that says the ordinary dataset is unaffected.
    """
    root = tmp_path / "dataset"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "a.txt").write_text("a\n", encoding="utf-8")

    assert symlinks_under(root) == ()
    assert set(digest_tree(root)) == {"sub/a.txt"}


def test_a_symlink_does_not_make_a_dataset_fail_verification(tmp_path: Path) -> None:
    """A judgement rather than an oversight, so it is pinned.

    Every byte the manifest records can still be exactly where it was, so the
    dataset does match its manifest. Whether it should be archived with a link
    in it is a different question, and `verify` answers both separately.

    **Everything up to the link runs on every platform, and the first version
    of this test is why.** It built a dataset and called `verify_dataset`
    straight away, which raises: `build_dataset` writes the dataset and
    `write_manifest` writes the document that describes it, and verification
    needs the second. On Windows the symlink skip fired *before* that line was
    ever reached, so the setup defect could only surface on Ubuntu -- which is
    where CI found it, two pushes later. So the dataset is now verified before
    the privilege gate: a platform that cannot make a link still exercises
    everything a platform that can would exercise first. **A skip hides the
    setup, not only the assertion.**
    """
    from commissura.build.manifest import write_manifest
    from commissura.build.writer import BuildSpec, build_dataset
    from commissura.generate.cohort import CohortSpec
    from commissura.generate.writer import write_corpus
    from commissura.read.corpus import read_corpus

    spec = BuildSpec(dataset_name="d", description="d", hdab="H", publisher="P")
    raw = tmp_path / "raw"
    write_corpus(CohortSpec(subjects=3, seed=11), raw)
    out = tmp_path / "ds"
    corpus = read_corpus(raw)
    summary = build_dataset(corpus, KEY, spec, out)
    write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=spec)

    before = verify_dataset(out)
    assert before.is_intact
    assert before.symlinks == ()

    outside = tmp_path / "stray.txt"
    outside.write_text("stray\n", encoding="utf-8")
    if not _link(outside, out / "stray.txt"):
        pytest.skip("symlink creation needs elevation on Windows")

    report = verify_dataset(out)

    assert report.symlinks == ("stray.txt",)
    assert report.is_intact
    assert not report.added
