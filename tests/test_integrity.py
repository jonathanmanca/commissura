"""Whether a dataset is still the one its manifest describes.

The counterpart to ``verify_corpus``, which checks the input corpus's recorded
PHI offsets against the bytes on disk. Same principle at the other end: a claim
about bytes is checked against the bytes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from commissura import layout
from commissura.build.integrity import (
    DIGEST_ALGORITHM,
    HMAC_FIELD,
    canonical_payload,
    digest_file,
    tag_manifest,
    verify_dataset,
)
from commissura.build.manifest import write_healthdcat_description, write_manifest
from commissura.build.risk import write_risk_report
from commissura.build.writer import BuildSpec, build_dataset
from commissura.deident.keys import SecretKey
from commissura.generate.cohort import CohortSpec
from commissura.generate.writer import write_corpus
from commissura.read.corpus import read_corpus

KEY = SecretKey(bytes(range(32)))
OTHER_KEY = SecretKey(bytes(range(32, 64)))


def built(tmp_path: Path) -> Path:
    """Build a dataset the way the command line does, including the write order."""
    raw, out = tmp_path / "raw", tmp_path / "dataset"
    write_corpus(CohortSpec(subjects=3, seed=17, defect_rate=0.0), raw)
    corpus = read_corpus(raw)
    spec = BuildSpec(
        dataset_name="Synthetic dataset",
        description="For checking integrity.",
        hdab="Agenzia Nazionale Sintetica per i Dati Sanitari",
        publisher="IRCCS SINTETICO MAREBIANCO",
        contact_point="dati@irccs-sintetico.invalid",
        access_url="https://portale-hdab-sintetico.invalid/permessi",
    )
    summary = build_dataset(corpus, KEY, spec, out)
    # The manifest goes last, because it digests everything else.
    write_healthdcat_description(out, spec=spec, summary=summary)
    write_risk_report(out)
    write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=spec)
    return out


def manifest_of(out: Path) -> Path:
    """Return the manifest's path."""
    return out / layout.DEIDENT_DIR / layout.MANIFEST_JSON


def test_a_freshly_built_dataset_is_intact(tmp_path: Path) -> None:
    """And the manifest authenticates against the key that built it."""
    out = built(tmp_path)

    report = verify_dataset(out, key=KEY)

    assert report.is_intact
    assert report.checked > 0
    assert report.authenticated is True


def test_every_file_the_build_produced_is_recorded(tmp_path: Path) -> None:
    """Except the manifest, which cannot carry its own digest.

    Written last for this reason: the two documents that used to follow it would
    otherwise show up as additions on a dataset nobody had touched.
    """
    out = built(tmp_path)
    recorded = json.loads(manifest_of(out).read_text(encoding="utf-8"))["integrity"]["files"]

    on_disk = {path.relative_to(out).as_posix() for path in out.rglob("*") if path.is_file()}
    manifest_relative = manifest_of(out).relative_to(out).as_posix()

    assert set(recorded) == on_disk - {manifest_relative}
    assert manifest_relative not in recorded
    assert layout.HEALTHDCAT_DESCRIPTION in recorded
    assert f"{layout.DEIDENT_DIR}/{layout.RISK_REPORT_JSON}" in recorded


def test_an_altered_file_is_reported(tmp_path: Path) -> None:
    """The case the whole thing exists for: a name pasted back into a report."""
    out = built(tmp_path)
    report_file = sorted(out.rglob(f"*{layout.REPORT_TEXT_EXTENSION}"))[0]
    report_file.write_text(
        report_file.read_text(encoding="utf-8") + "Firmato: MARIO ROSSI\n", encoding="utf-8"
    )

    result = verify_dataset(out)

    assert not result.is_intact
    assert result.altered == (report_file.relative_to(out).as_posix(),)
    assert result.missing == ()
    assert result.added == ()


def test_a_missing_file_is_reported(tmp_path: Path) -> None:
    """An incomplete copy is the commonest way a dataset stops being itself."""
    out = built(tmp_path)
    (out / layout.PARTICIPANTS_JSON).unlink()

    result = verify_dataset(out)

    assert result.missing == (layout.PARTICIPANTS_JSON,)
    assert not result.is_intact


def test_an_added_file_is_reported(tmp_path: Path) -> None:
    """A stray export dropped into the tree is not part of what was described."""
    out = built(tmp_path)
    (out / "stray.txt").write_text("not part of this dataset\n", encoding="utf-8")

    result = verify_dataset(out)

    assert result.added == ("stray.txt",)
    assert not result.is_intact


def test_the_digest_list_alone_cannot_catch_a_tamperer(tmp_path: Path) -> None:
    """The honest limit, demonstrated rather than asserted in a comment.

    Somebody who edits a report and then recomputes the whole digest list passes
    this check completely. That is not a defect in the digests; it is what a
    digest list stored beside the data can do.
    """
    out = built(tmp_path)
    report_file = sorted(out.rglob(f"*{layout.REPORT_TEXT_EXTENSION}"))[0]
    report_file.write_text(
        report_file.read_text(encoding="utf-8") + "Firmato: MARIO ROSSI\n", encoding="utf-8"
    )

    path = manifest_of(out)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["integrity"]["files"] = {
        file.relative_to(out).as_posix(): digest_file(file)
        for file in sorted(out.rglob("*"))
        if file.is_file() and file != path
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    assert verify_dataset(out).is_intact, "a recomputed list passes, which is the point"


def test_the_key_catches_what_the_digest_list_cannot(tmp_path: Path) -> None:
    """Same tampered dataset, and the tag fails with zero files differing.

    Zero differences and a failed tag is the signature of somebody adjusting the
    manifest to cover their tracks, which is why the two are reported apart.
    """
    out = built(tmp_path)
    report_file = sorted(out.rglob(f"*{layout.REPORT_TEXT_EXTENSION}"))[0]
    report_file.write_text(
        report_file.read_text(encoding="utf-8") + "Firmato: MARIO ROSSI\n", encoding="utf-8"
    )

    path = manifest_of(out)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["integrity"]["files"] = {
        file.relative_to(out).as_posix(): digest_file(file)
        for file in sorted(out.rglob("*"))
        if file.is_file() and file != path
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    result = verify_dataset(out, key=KEY)

    assert result.difference_count == 0
    assert result.authenticated is False
    assert not result.is_intact


def test_the_wrong_key_does_not_authenticate(tmp_path: Path) -> None:
    """Otherwise the tag would prove only that somebody had some key."""
    out = built(tmp_path)

    assert verify_dataset(out, key=OTHER_KEY).authenticated is False


def test_reformatting_the_manifest_does_not_break_its_tag(tmp_path: Path) -> None:
    """The tag covers content, not whitespace.

    A tag that failed on a pretty-printed file would teach people to ignore it,
    and ignoring it is worse than not having it.
    """
    out = built(tmp_path)
    path = manifest_of(out)
    payload = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(payload, indent=8, sort_keys=True), encoding="utf-8")

    assert verify_dataset(out, key=KEY).authenticated is True


def test_the_tag_excludes_only_itself(tmp_path: Path) -> None:
    """Every other field is covered, including the digest list."""
    out = built(tmp_path)
    payload = json.loads(manifest_of(out).read_text(encoding="utf-8"))

    # Parsed, not matched as a substring: the integrity note names the field in
    # its own prose, which a substring check would find and call a failure.
    assert HMAC_FIELD not in json.loads(canonical_payload(payload))
    assert payload[HMAC_FIELD] == tag_manifest(payload, KEY)

    tampered = dict(payload)
    tampered["key_fingerprint"] = "0000000000000000"
    assert tag_manifest(tampered, KEY) != payload[HMAC_FIELD]


def test_the_algorithm_is_named_in_the_manifest(tmp_path: Path) -> None:
    """A bare hex string says nothing about how it was produced."""
    out = built(tmp_path)
    integrity = json.loads(manifest_of(out).read_text(encoding="utf-8"))["integrity"]

    assert integrity["algorithm"] == DIGEST_ALGORITHM


def test_a_digest_is_taken_over_bytes_not_decoded_text(tmp_path: Path) -> None:
    """A text-mode read would translate newlines and digest something else.

    This project exists to put exact bytes on disk, and HL7 terminates segments
    with a bare carriage return.
    """
    path = tmp_path / "crlf.txt"
    path.write_bytes(b"a\r\nb\r\n")

    assert digest_file(path) == hashlib.sha256(b"a\r\nb\r\n").hexdigest()


def test_verifying_a_dataset_with_no_manifest_says_so(tmp_path: Path) -> None:
    """Rather than reporting an empty dataset as intact."""
    with pytest.raises(FileNotFoundError, match="no manifest"):
        verify_dataset(tmp_path)


def test_verifying_against_a_manifest_without_digests_says_so(tmp_path: Path) -> None:
    """A manifest from before this existed cannot be verified, and must not look fine."""
    path = tmp_path / layout.DEIDENT_DIR / layout.MANIFEST_JSON
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"schema_version": "1.0.0"}), encoding="utf-8")

    with pytest.raises(ValueError, match="no per-file digests"):
        verify_dataset(tmp_path)
