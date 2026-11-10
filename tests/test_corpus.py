"""End-to-end corpus generation: reproducibility, ground truth, and file integrity."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from commissura.generate.cohort import CohortSpec, build_cohort, child_seed
from commissura.generate.defects import BY_ID
from commissura.generate.writer import read_exact, verify_corpus, write_corpus
from commissura.read.corpus import read_corpus


def _corpus(tmp_path: Path, name: str, **kwargs: object) -> Path:
    spec = CohortSpec(**kwargs)  # type: ignore[arg-type]
    root = tmp_path / name
    summary = write_corpus(spec, root)
    verify_corpus(summary)
    return root


def _file_bytes(root: Path) -> dict[str, bytes]:
    """Return every clinical file, keyed by path relative to the corpus root."""
    return {
        str(path.relative_to(root)).replace("\\", "/"): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and "_generator" not in path.parts
    }


def test_same_seed_produces_identical_bytes(tmp_path: Path) -> None:
    first = _corpus(tmp_path, "a", subjects=5, seed=7)
    second = _corpus(tmp_path, "b", subjects=5, seed=7)
    assert _file_bytes(first) == _file_bytes(second)


def test_different_seeds_produce_different_corpora(tmp_path: Path) -> None:
    first = _corpus(tmp_path, "a", subjects=5, seed=7)
    second = _corpus(tmp_path, "b", subjects=5, seed=8)
    assert _file_bytes(first) != _file_bytes(second)


def test_a_subject_does_not_depend_on_how_many_were_requested(tmp_path: Path) -> None:
    """The strong reproducibility claim: asking for more must not change the first.

    A single shared random stream would fail this, because one extra subject
    shifts every later draw.
    """
    small = _file_bytes(_corpus(tmp_path, "small", subjects=3, seed=11))
    large = _file_bytes(_corpus(tmp_path, "large", subjects=30, seed=11))

    assert small, "the small corpus should not be empty"
    for relative, content in small.items():
        assert relative in large, f"{relative} disappeared when the cohort grew"
        assert large[relative] == content, f"{relative} changed when the cohort grew"


def test_cohort_facts_are_independent_of_cohort_size() -> None:
    small = build_cohort(CohortSpec(subjects=2, seed=3))
    large = build_cohort(CohortSpec(subjects=9, seed=3))
    assert [p.subject for p in small] == [p.subject for p in large][:2]


def test_child_seeds_are_stable_and_domain_separated() -> None:
    assert child_seed(1, "subject|0") == child_seed(1, "subject|0")
    assert child_seed(1, "subject|0") != child_seed(1, "subject|1")
    assert child_seed(1, "subject|0") != child_seed(2, "subject|0")
    assert child_seed(1, "subject|0") != child_seed(1, "defects|0")


def test_hl7_files_contain_no_line_feed(tmp_path: Path) -> None:
    """Guards against newline translation, which would shift every PHI offset."""
    root = _corpus(tmp_path, "c", subjects=6, seed=5)
    messages = list((root / "lab").glob("*.hl7"))
    assert messages
    for path in messages:
        raw = path.read_bytes()
        assert b"\n" not in raw, f"{path.name} contains a line feed"
        assert b"\r" in raw


def test_imaging_sidecars_are_valid_dicom_json(tmp_path: Path) -> None:
    root = _corpus(tmp_path, "d", subjects=8, seed=5)
    sidecars = list((root / "imaging").glob("*.json"))
    assert sidecars
    for path in sidecars:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(payload, list)
        for series in payload:
            assert "0020000D" in series, "StudyInstanceUID missing"
            assert "0020000E" in series, "SeriesInstanceUID missing"
            assert series["00100010"]["Value"][0]["Alphabetic"]  # PatientName


def test_manifest_counts_match_the_files_on_disk(tmp_path: Path) -> None:
    spec = CohortSpec(subjects=7, seed=13)
    root = tmp_path / "e"
    summary = write_corpus(spec, root)

    counts = summary.manifest.files
    assert counts.lab == len(list((root / "lab").glob("*.hl7")))
    assert counts.reports == len(list((root / "reports").glob("*.txt")))
    assert counts.imaging == len(list((root / "imaging").glob("*.json")))


def test_ground_truth_offsets_match_the_files(tmp_path: Path) -> None:
    """Re-read from disk rather than trusting the in-memory text."""
    spec = CohortSpec(subjects=6, seed=21)
    root = tmp_path / "f"
    summary = write_corpus(spec, root)
    verify_corpus(summary)

    annotations = json.loads(
        (root / "_generator" / "phi_annotations.json").read_text(encoding="utf-8")
    )
    assert annotations["spans"]
    assert len(annotations["spans"]) == summary.manifest.phi_span_count

    for span in annotations["spans"]:
        content = read_exact(root / span["path"])
        assert content[span["start"] : span["end"]] == span["text"]


def test_zero_defect_rate_produces_a_clean_corpus(tmp_path: Path) -> None:
    spec = CohortSpec(subjects=10, seed=4, defect_rate=0.0)
    summary = write_corpus(spec, tmp_path / "g")
    assert summary.manifest.defects == ()


def test_a_clean_corpus_is_still_hard_to_de_identify(tmp_path: Path) -> None:
    """Clean means undamaged, not easy.

    Identifiers in running prose are how reports are written, not a defect, so
    they survive ``defect_rate=0``. Were that not so, anyone generating a clean
    corpus, scrubbing the header fields and scoring perfectly would walk away
    with a false result.
    """
    spec = CohortSpec(subjects=15, seed=4, defect_rate=0.0)
    root = tmp_path / "clean"
    summary = write_corpus(spec, root)

    assert summary.manifest.defects == ()

    bodies = [read_exact(path) for path in (root / "reports").glob("*.txt")]
    assert any("Si confronta con il precedente esame del" in body for body in bodies)

    prose_spans = [span for span in summary.spans if span.note and "running prose" in span.note]
    assert prose_spans, "a clean corpus should still carry identifiers outside header fields"


def test_full_defect_rate_exercises_the_whole_catalogue(tmp_path: Path) -> None:
    """Every catalogued defect must be reachable, or it is dead documentation."""
    spec = CohortSpec(subjects=40, seed=4, defect_rate=1.0)
    summary = write_corpus(spec, tmp_path / "h")
    seen = {defect.defect_id for defect in summary.manifest.defects}
    assert seen == set(BY_ID), f"never injected: {sorted(set(BY_ID) - seen)}"


def test_every_injected_defect_names_a_file_that_exists(tmp_path: Path) -> None:
    spec = CohortSpec(subjects=12, seed=6, defect_rate=0.8)
    root = tmp_path / "i"
    summary = write_corpus(spec, root)
    assert summary.manifest.defects
    for defect in summary.manifest.defects:
        assert (root / defect.path).is_file(), defect.path


def test_duplicate_message_defect_writes_a_byte_identical_copy(tmp_path: Path) -> None:
    spec = CohortSpec(subjects=25, seed=2, defect_rate=1.0)
    root = tmp_path / "j"
    summary = write_corpus(spec, root)

    duplicates = [d for d in summary.manifest.defects if d.defect_id == "lab.duplicate_message"]
    assert duplicates
    for defect in duplicates:
        copy = root / defect.path
        original = Path(str(copy).replace("_2.hl7", ".hl7"))
        assert copy.read_bytes() == original.read_bytes()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"subjects": 0}, "subjects must be at least 1"),
        ({"defect_rate": 1.5}, "defect_rate must be between 0 and 1"),
        ({"defect_rate": -0.1}, "defect_rate must be between 0 and 1"),
        ({"max_encounters": 0}, "max_encounters must be at least 1"),
    ],
)
def test_invalid_specifications_are_rejected(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        CohortSpec(**kwargs)  # type: ignore[arg-type]


def _pid_segments(root: Path) -> list[str]:
    """Return every lab message's PID segment, split on HL7's bare carriage return."""
    segments = []
    for path in sorted((root / "lab").glob("*.hl7")):
        text = read_exact(path)
        segments.append(next(s for s in text.split("\r") if s.startswith("PID")))
    return segments


def test_a_corpus_carries_the_codice_fiscale_in_both_positions(tmp_path: Path) -> None:
    """One site still sends PID-19, the rest send the PID-3 list.

    Without this the reader's PID-19 fallback would be dead code that only a
    unit test ever reached, and a corpus in which every interface is modern
    would be modelling a world where the old ones were all switched off.
    """
    root = _corpus(tmp_path, "both", subjects=20, seed=5, defect_rate=0.0)
    segments = _pid_segments(root)

    modern = [s for s in segments if "NNITA" in s]
    legacy = [s for s in segments if "NNITA" not in s]

    assert modern, "no message carries the codice fiscale in the PID-3 list"
    assert legacy, "no message carries it in PID-19, so the fallback is untested here"
    # The legacy interface sends it in PID-19 and nowhere else; the modern one
    # sends it in PID-3 and leaves the deprecated field empty.
    assert all(s.count("^MR") == 1 for s in segments)


def test_every_subject_is_read_whichever_position_was_used(tmp_path: Path) -> None:
    """The point of the fallback: no subject is lost to its interface's age."""
    root = _corpus(tmp_path, "linked", subjects=20, seed=5, defect_rate=0.0)
    corpus = read_corpus(root)

    assert len(corpus.subjects) == 20
    assert not [issue for issue in corpus.issues if issue.reason == "unreadable_lab_message"]
