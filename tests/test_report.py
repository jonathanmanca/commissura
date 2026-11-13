"""The HTML build report: the one output that must not be released.

Most of these tests are about *where* the file may go and *what it says about
itself*, not about how it looks. The page holds unredacted clinical reports by
design, so the interesting properties are the ones that stop it travelling.
"""

from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path

import pytest

from commissura import layout
from commissura.build.manifest import write_healthdcat_description, write_manifest
from commissura.build.report import (
    DEFAULT_COMPARISONS,
    gather_comparisons,
    render,
    write_report,
)
from commissura.build.risk import write_risk_report
from commissura.build.writer import BuildSpec, BuildSummary, build_dataset
from commissura.deident.keys import SecretKey
from commissura.generate.cohort import CohortSpec
from commissura.generate.writer import write_corpus
from commissura.read.corpus import RawCorpus, read_corpus

KEY = SecretKey(bytes(range(32)))

HOSTILE = 'removed" onmouseover="alert(1)'
"""A disposition that closes its own attribute, if nothing escapes it."""

VOID_ELEMENTS = frozenset(
    {"meta", "br", "hr", "img", "input", "link", "area", "base", "col", "embed"}
)


class _Balanced(HTMLParser):
    """Check that every element is closed, in order."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.problems: list[str] = []

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag not in VOID_ELEMENTS:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack:
            self.problems.append(f"stray </{tag}>")
        elif self.stack[-1] != tag:
            self.problems.append(f"expected </{self.stack[-1]}>, got </{tag}>")
        else:
            self.stack.pop()


def built(tmp_path: Path) -> tuple[RawCorpus, BuildSummary, dict, dict]:  # type: ignore[type-arg]
    """Build a dataset and return everything the report needs."""
    raw, out = tmp_path / "raw", tmp_path / "dataset"
    write_corpus(CohortSpec(subjects=6, seed=42, defect_rate=0.2), raw)
    corpus = read_corpus(raw)
    spec = BuildSpec(
        dataset_name="Synthetic dataset",
        description="For reporting on.",
        hdab="Agenzia Nazionale Sintetica per i Dati Sanitari",
        publisher="IRCCS SINTETICO MAREBIANCO",
        contact_point="dati@irccs-sintetico.invalid",
        access_url="https://portale-hdab-sintetico.invalid/permessi",
    )
    summary = build_dataset(corpus, KEY, spec, out)
    write_healthdcat_description(out, spec=spec, summary=summary)
    risk = write_risk_report(out)
    manifest = write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=spec)
    return corpus, summary, manifest, risk


def test_it_refuses_to_be_written_inside_the_dataset(tmp_path: Path) -> None:
    """The mistake the option invites, and the one that would ship patient data.

    A file inside the dataset is digested into the manifest's integrity list and
    released with it. Refused rather than warned about: a warning on a build
    that otherwise succeeded is a warning nobody reads.
    """
    corpus, summary, manifest, risk = built(tmp_path)

    with pytest.raises(ValueError, match="refusing to write"):
        write_report(
            summary.root / "report.html",
            corpus=corpus,
            summary=summary,
            manifest=manifest,
            risk=risk,
        )


def test_it_refuses_a_path_nested_deeper_in_the_dataset(tmp_path: Path) -> None:
    """Not only the dataset root: anywhere under it travels just the same."""
    corpus, summary, manifest, risk = built(tmp_path)

    with pytest.raises(ValueError, match="refusing to write"):
        write_report(
            summary.root / layout.DEIDENT_DIR / "deep" / "report.html",
            corpus=corpus,
            summary=summary,
            manifest=manifest,
            risk=risk,
        )


def test_it_writes_beside_the_dataset(tmp_path: Path) -> None:
    """A sibling directory is fine; only inside is refused."""
    corpus, summary, manifest, risk = built(tmp_path)

    written = write_report(
        tmp_path / "review" / "report.html",
        corpus=corpus,
        summary=summary,
        manifest=manifest,
        risk=risk,
    )

    assert written.is_file()
    assert summary.root not in written.parents


def test_the_page_says_it_holds_patient_data(tmp_path: Path) -> None:
    """In the first screenful, not a footnote.

    Everything else about this file depends on whoever opens it knowing what it
    is, and the only reason they would know is that it tells them.
    """
    corpus, summary, manifest, risk = built(tmp_path)
    document = render(
        corpus=corpus,
        summary=summary,
        manifest=manifest,
        risk=risk,
        comparisons=gather_comparisons(corpus, summary),
    )

    warning = document.index("contains patient data")
    assert warning < document.index("<h2>"), "the warning comes before the first section"
    assert "Do not release it" in document


def test_the_page_is_self_contained(tmp_path: Path) -> None:
    """One file, offline, no server and no network.

    An artefact that stops rendering when a CDN moves is not an artefact.
    """
    corpus, summary, manifest, risk = built(tmp_path)
    document = render(
        corpus=corpus,
        summary=summary,
        manifest=manifest,
        risk=risk,
        comparisons=gather_comparisons(corpus, summary),
    )

    assert "<script" not in document
    assert "@import" not in document
    assert "http://" not in document.replace("http://www.w3.org", "")
    assert 'src="' not in document


def test_the_page_is_balanced_html(tmp_path: Path) -> None:
    """Assembled by string concatenation, so this is the check that earns it."""
    corpus, summary, manifest, risk = built(tmp_path)
    document = render(
        corpus=corpus,
        summary=summary,
        manifest=manifest,
        risk=risk,
        comparisons=gather_comparisons(corpus, summary),
    )

    parser = _Balanced()
    parser.feed(document)

    assert parser.problems == []
    assert parser.stack == []


def test_report_text_is_escaped_not_interpreted(tmp_path: Path) -> None:
    """A clinical report is arbitrary text and must not become markup.

    Not a hypothetical in a tool whose whole input is other people's documents:
    a report containing `<b>` would silently restyle the page, and one
    containing a stray `</pre>` would break the comparison it sits in.
    """
    corpus, summary, manifest, risk = built(tmp_path)
    comparisons = gather_comparisons(corpus, summary)
    assert comparisons, "this corpus should produce comparisons"
    hostile = type(comparisons[0])(
        source=comparisons[0].source,
        output=comparisons[0].output,
        before="<script>alert(1)</script></pre><b>",
        after="clean",
    )

    document = render(
        corpus=corpus,
        summary=summary,
        manifest=manifest,
        risk=risk,
        comparisons=[hostile],
    )

    assert "<script>alert(1)</script>" not in document
    assert "&lt;script&gt;" in document
    parser = _Balanced()
    parser.feed(document)
    assert parser.problems == []


def test_it_shows_both_halves_of_a_real_report(tmp_path: Path) -> None:
    """The before/after is the point; a page with only the after is a listing."""
    corpus, summary, _, _ = built(tmp_path)
    comparisons = gather_comparisons(corpus, summary)

    assert comparisons
    for item in comparisons:
        assert item.before != item.after
        # The original names the patient; the output does not.
        assert "Paziente:" in item.before
        assert "[NAME]" in item.after


def test_the_number_of_comparisons_is_capped(tmp_path: Path) -> None:
    """Thirty unredacted reports make a file nobody scrolls and a bigger hazard."""
    corpus, summary, _, _ = built(tmp_path)

    assert len(gather_comparisons(corpus, summary)) <= DEFAULT_COMPARISONS
    assert gather_comparisons(corpus, summary, limit=2) == gather_comparisons(
        corpus, summary, limit=2
    )
    assert len(gather_comparisons(corpus, summary, limit=1)) == 1
    assert gather_comparisons(corpus, summary, limit=0) == []


def test_a_missing_source_file_is_skipped_not_raised(tmp_path: Path) -> None:
    """A picture of a build must not be able to fail the build."""
    corpus, summary, _, _ = built(tmp_path)
    first = corpus.root / summary.report_pairs[0].source
    first.unlink()

    comparisons = gather_comparisons(corpus, summary)

    assert all(item.source != summary.report_pairs[0].source for item in comparisons)


def test_it_carries_the_tables_the_manifest_holds(tmp_path: Path) -> None:
    """The page exists to show what is already recorded, not to recompute it."""
    corpus, summary, manifest, risk = built(tmp_path)
    document = render(
        corpus=corpus,
        summary=summary,
        manifest=manifest,
        risk=risk,
        comparisons=gather_comparisons(corpus, summary),
    )

    assert "PID-19" in document or "PID-3" in document
    assert "day_offset" in document
    assert str(manifest["key_fingerprint"]) in document
    assert "pseudonymises and does not anonymise" in document


def test_it_survives_a_manifest_without_a_field_table(tmp_path: Path) -> None:
    """A manifest from an older build still deserves a readable page."""
    corpus, summary, _, risk = built(tmp_path)

    document = render(
        corpus=corpus,
        summary=summary,
        manifest={"schema_version": "1.0.0"},
        risk=risk,
        comparisons=[],
    )

    assert "records no field table" in document
    parser = _Balanced()
    parser.feed(document)
    assert parser.problems == []


def test_the_dataset_never_contains_the_report(tmp_path: Path) -> None:
    """Belt and braces: the manifest's own digest list must not list it."""
    corpus, summary, manifest, risk = built(tmp_path)
    write_report(
        tmp_path / "review.html",
        corpus=corpus,
        summary=summary,
        manifest=manifest,
        risk=risk,
    )

    recorded = json.loads(
        (summary.root / layout.DEIDENT_DIR / layout.MANIFEST_JSON).read_text(encoding="utf-8")
    )["integrity"]["files"]

    assert not [name for name in recorded if name.endswith(".html")]
    assert not list(summary.root.rglob("*.html"))


class _Attributes(HTMLParser):
    """Collect every attribute name the parser actually sees."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.names: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, _ in attrs:
            self.names.add(name)


def _hostile_dispositions(manifest: dict) -> dict:  # type: ignore[type-arg]
    """Return the manifest with every disposition replaced by markup."""
    poisoned = dict(manifest)
    modalities = []
    for entry in manifest["modalities"]:
        copy = dict(entry)
        for table in ("fields", "body"):
            rows = copy.get(table)
            if isinstance(rows, list):
                copy[table] = [{**row, "disposition": HOSTILE} for row in rows]
        modalities.append(copy)
    poisoned["modalities"] = modalities
    return poisoned


def test_a_disposition_cannot_break_out_of_its_class_attribute(tmp_path: Path) -> None:
    """Every interpolation goes through the escaper, attributes included.

    The three dispositions are written by this tool, so a value carrying a
    quote "cannot" happen — but the manifest is read back from disk, and
    somebody with write access to a share is the threat ``manifest_hmac``
    exists for. Unescaped, this closed the attribute and attached an event
    handler to the page, and balanced-HTML checking cannot see it because the
    result is still balanced.
    """
    corpus, summary, manifest, risk = built(tmp_path)

    document = render(
        corpus=corpus,
        summary=summary,
        manifest=_hostile_dispositions(manifest),
        risk=risk,
        comparisons=[],
    )

    parser = _Attributes()
    parser.feed(document)
    assert "onmouseover" not in parser.names
    assert parser.names <= {"charset", "class", "lang", "name", "content"}
    assert HOSTILE not in document
