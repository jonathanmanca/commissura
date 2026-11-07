"""Writing the corpus to disk: encoding, newlines, and whether verification verifies."""

from __future__ import annotations

from pathlib import Path

import pytest

from commissura.generate.cohort import CohortSpec
from commissura.generate.writer import (
    ANNOTATION_SCHEMA_VERSION,
    _write_json,
    _write_text,
    read_exact,
    verify_corpus,
    write_corpus,
)


def test_read_exact_preserves_a_bare_carriage_return(tmp_path: Path) -> None:
    r"""The unit-level guard against newline translation.

    HL7 segments end with a bare ``\r``. Python's text mode would turn a written
    ``\n`` into ``\r\n`` on Windows and, on reading, collapse terminators back —
    either way every character offset past the first line would be wrong.
    """
    path = tmp_path / "message.hl7"
    content = "MSH|^~\\&|LIS\rPID|1\rOBX|1\r"
    _write_text(path, content)

    assert path.read_bytes() == content.encode("utf-8")
    assert read_exact(path) == content
    assert len(read_exact(path)) == len(content)


def test_read_exact_preserves_mixed_terminators(tmp_path: Path) -> None:
    path = tmp_path / "mixed.txt"
    content = "line one\nsegment\rboth\r\nend"
    _write_text(path, content)
    assert read_exact(path) == content


def test_write_text_creates_missing_parents(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "deeper" / "file.txt"
    _write_text(path, "x")
    assert path.read_text(encoding="utf-8") == "x"


def test_write_json_keeps_accented_characters_unescaped(tmp_path: Path) -> None:
    """Offsets elsewhere are character positions, so escaping would shift them."""
    path = tmp_path / "payload.json"
    _write_json(path, {"city": "Forlì", "note": "però"})
    raw = path.read_bytes().decode("utf-8")
    assert "Forlì" in raw
    assert "\\u00ec" not in raw


def test_summary_file_count_excludes_metadata(tmp_path: Path) -> None:
    summary = write_corpus(CohortSpec(subjects=4, seed=1), tmp_path / "raw")
    counts = summary.manifest.files
    assert summary.file_count == counts.lab + counts.reports + counts.imaging

    on_disk = [
        path
        for path in (tmp_path / "raw").rglob("*")
        if path.is_file() and "_generator" not in path.parts
    ]
    assert summary.file_count == len(on_disk)


def test_annotation_file_declares_its_schema_and_offset_convention(tmp_path: Path) -> None:
    import json

    root = tmp_path / "raw"
    write_corpus(CohortSpec(subjects=3, seed=1), root)
    payload = json.loads((root / "_generator" / "phi_annotations.json").read_text(encoding="utf-8"))

    assert payload["schema_version"] == ANNOTATION_SCHEMA_VERSION
    assert "content[start:end]" in payload["note"]
    assert payload["spans"]


def test_manifest_records_what_is_needed_to_reproduce_the_run(tmp_path: Path) -> None:
    summary = write_corpus(CohortSpec(subjects=3, seed=99), tmp_path / "raw")
    manifest = summary.manifest
    assert manifest.seed == 99
    assert manifest.subject_count == 3
    assert manifest.tool_version
    assert "3." in manifest.python_version
    assert manifest.generated_at.tzinfo is not None, "a naive timestamp is ambiguous"


def test_verification_fails_when_a_file_is_altered(tmp_path: Path) -> None:
    """Proves the verification is load-bearing rather than decorative.

    Without this test, ``verify_corpus`` could silently pass on everything and
    nobody would notice that the guarantee printed by the CLI means nothing.
    """
    root = tmp_path / "raw"
    summary = write_corpus(CohortSpec(subjects=3, seed=7), root)
    verify_corpus(summary)

    target = summary.spans[0].path
    original = read_exact(root / target)
    _write_text(root / target, "X" + original)

    with pytest.raises(AssertionError, match="span mismatch"):
        verify_corpus(summary)


def test_verification_fails_on_newline_translation(tmp_path: Path) -> None:
    """Simulates the exact platform bug the writer exists to prevent."""
    root = tmp_path / "raw"
    summary = write_corpus(CohortSpec(subjects=4, seed=8), root)

    report = next(span.path for span in summary.spans if span.path.startswith("reports/"))
    content = read_exact(root / report)
    _write_text(root / report, content.replace("\n", "\r\n"))

    with pytest.raises(AssertionError, match="span mismatch"):
        verify_corpus(summary)


def test_writing_into_an_existing_directory_is_allowed(tmp_path: Path) -> None:
    root = tmp_path / "raw"
    root.mkdir()
    (root / "pre-existing.txt").write_text("untouched", encoding="utf-8")

    summary = write_corpus(CohortSpec(subjects=2, seed=1), root)
    verify_corpus(summary)
    assert (root / "pre-existing.txt").read_text(encoding="utf-8") == "untouched"


def test_corpus_root_is_resolved_to_an_absolute_path(tmp_path: Path) -> None:
    summary = write_corpus(CohortSpec(subjects=2, seed=1), tmp_path / "raw")
    assert summary.root.is_absolute()
