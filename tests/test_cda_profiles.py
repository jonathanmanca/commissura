"""The pathology and outpatient CDA profiles, and what reading them exposed.

RAP v1.0 and RSA v1.1 are the last two document profiles on the Ministry's
index. Unlike the Profilo Sanitario Sintetico, both *are* reports — each
requires ``componentOf``, so each carries a numero nosologico — so both fit
:data:`commissura.generate.cda.NARRATIVE_PROFILES` and the seam held this time.
What it did not already hold was two header values, and finding the second one
is what this file is mostly about.

**Both were read from ART-DECOR rather than from a PDF**, which for RSA means
the machine-readable form of a profile the Ministry publishes only as a PDF,
and which gave the cardinalities and fixed values directly instead of by
transcription.

**The finding: ``typeId/@extension`` was one value for every narrative profile
and should never have been.** The renderer wrote ``POCD_HD000040`` — the
laboratory specification's value — into radiology reports, discharge letters
and now anything else that came along. RAP and RSA both *fix*
``POCD_MT000040UV02`` in their own templates, as the PSS does, so emitting them
with the laboratory value produced two non-conformant documents. Worse, when
the four sources were checked rather than assumed, **RAD turned out to state no
value at all**: its single ``typeId`` example reads ``[POCD_HDXXXXX]``, a
placeholder the specification never instantiates.

Every identifier here is synthetic.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from random import Random

import pytest

from commissura.build.writer import BuildSpec, build_dataset
from commissura.deident.keys import SecretKey
from commissura.generate.cda import NARRATIVE_PROFILES
from commissura.generate.cohort import CohortSpec, build_person
from commissura.generate.defects import DefectInjector
from commissura.generate.reports import (
    PLAIN_TEXT_KINDS,
    render_report,
    sample_outpatient_report,
    sample_pathology_report,
)
from commissura.generate.vocabulary import SITES
from commissura.generate.writer import _REPORT_MARKER, write_corpus
from commissura.measure import measure
from commissura.models import ReportKind
from commissura.read.cda import (
    DISCHARGE_DOCUMENT_CODE,
    LABORATORY_DOCUMENT_CODE,
    OUTPATIENT_DOCUMENT_CODE,
    PATHOLOGY_DOCUMENT_CODE,
    RADIOLOGY_DOCUMENT_CODE,
    SUMMARY_DOCUMENT_CODE,
    SUMMARY_TYPE_ID_EXTENSION,
    parse_clinical_document,
)
from commissura.read.corpus import read_corpus

KEY = SecretKey(bytes(range(32)))

REFERENCE = datetime(2024, 6, 1, tzinfo=UTC)

# Read from each profile's own ART-DECOR template, where a required section is
# the component marked `1 … 1` with conformance `R`. RAP marks two of nine;
# RSA marks two of twelve. Transcribed here so a failure names the table
# somebody edited rather than a count they then have to trace.
REQUIRED_SECTIONS: dict[ReportKind, set[str]] = {
    ReportKind.PATHOLOGY: {"29300-1", "22637-3"},
    ReportKind.OUTPATIENT: {"62387-6", "47045-0"},
}

CDA_ONLY = (ReportKind.PATHOLOGY, ReportKind.OUTPATIENT)
"""The two kinds this generator writes as CDA and never as free text."""

TEMPLATE_ORDER: dict[ReportKind, tuple[str, ...]] = {
    ReportKind.PATHOLOGY: (
        "22636-5",  # Notizie Cliniche
        "29300-1",  # Procedura
        "22634-0",  # Osservazione Macroscopica
        "22635-7",  # Osservazione Microscopica
        "22639-9",  # Analisi supplementari dei campioni
        "85691-4",  # Epicrisi
        "22637-3",  # Diagnosi
        "62385-0",  # Ulteriori Accertamenti Diagnostici
    ),
    ReportKind.OUTPATIENT: (
        "29299-5",  # Quesito Diagnostico
        "62387-6",  # Prestazioni
        "47045-0",  # Referto
        "29548-5",  # Diagnosi
        "55110-1",  # Conclusioni
    ),
}
"""The order each template lists its body components in, transcribed.

**Transcribed and not derived from the profile table**, which is the whole
point: the first version of the order test compared the emitted order against
:data:`NARRATIVE_PROFILES`, so reordering that table moved both sides of the
assertion and it passed. The sabotage that swapped two RSA sections went
unnoticed, which is what a guard nobody has watched fail is worth.

RAP's "Stato del margine" is left out because its template fixes no ``code``;
it sits between the microscopic observation and the supplementary analyses, and
this generator emits neither of its neighbours' gap, so its absence here cannot
hide a reordering of anything that is emitted.
"""

PATIENT = build_person(Random(7), reference_date=REFERENCE)
"""One synthetic patient, for the renderer that is going to refuse anyway."""


@pytest.fixture(scope="module")
def corpus_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A CDA corpus carrying all five document kinds."""
    root = tmp_path_factory.mktemp("cda-profiles") / "raw"
    write_corpus(CohortSpec(subjects=14, seed=42, defect_rate=0.2, cda=True), root)
    return root


def _documents(root: Path, marker: str) -> list[str]:
    return [path.read_text(encoding="utf-8") for path in sorted(root.glob(f"cda/*_{marker}_*.xml"))]


def _in_order(codes: list[str], order: tuple[str, ...]) -> bool:
    """Whether ``codes`` appears in ``order``, skipping what is not emitted."""
    positions = [order.index(code) for code in codes]
    return positions == sorted(positions)


def _spec() -> BuildSpec:
    """The catalogue fields a build will not invent."""
    return BuildSpec(
        dataset_name="profile corpus",
        description="A synthetic corpus carrying four narrative CDA profiles.",
        hdab="HDAB SINTETICO",
        publisher="ENTE SINTETICO PUBBLICATORE",
    )


# --------------------------------------------------------------------------
# The profiles, against their templates
# --------------------------------------------------------------------------


def test_the_document_codes_are_the_ones_the_templates_fix() -> None:
    """Pinned as values, because recalling a code is how this has gone wrong twice.

    ``11526-1`` for RAP and ``11488-4`` for RSA, each fixed (``F``) on
    ``code/@code`` in its own ART-DECOR template against LOINC. The two lessons
    behind asserting rather than trusting are `NNITA` on 2026-11-11 and the
    radiology code on 2026-11-18, where ``18748-4`` looked exactly as plausible
    as the right answer.
    """
    assert PATHOLOGY_DOCUMENT_CODE == "11526-1"
    assert OUTPATIENT_DOCUMENT_CODE == "11488-4"

    codes = {
        LABORATORY_DOCUMENT_CODE,
        RADIOLOGY_DOCUMENT_CODE,
        DISCHARGE_DOCUMENT_CODE,
        SUMMARY_DOCUMENT_CODE,
        PATHOLOGY_DOCUMENT_CODE,
        OUTPATIENT_DOCUMENT_CODE,
    }
    assert len(codes) == 6


@pytest.mark.parametrize("kind", CDA_ONLY)
def test_a_profile_covers_every_required_section(kind: ReportKind) -> None:
    """A document missing a required section is not conformant.

    Asserted against the profile table, so the failure names the table. The
    rendered documents are checked separately below, because a table that lists
    a section and a writer that skips it when its field is empty would pass
    this and emit a non-conformant document.
    """
    codes = {code for code, _, _, _ in NARRATIVE_PROFILES[kind].sections}

    assert REQUIRED_SECTIONS[kind] <= codes


@pytest.mark.parametrize("kind", CDA_ONLY)
def test_every_required_section_is_present_in_the_output(
    corpus_root: Path, kind: ReportKind
) -> None:
    """The other half: on the documents, not only on the table."""
    marker = _REPORT_MARKER[kind]
    documents = _documents(corpus_root, marker)

    assert documents, marker
    for document in documents:
        for code in REQUIRED_SECTIONS[kind]:
            assert f'<code code="{code}"' in document, (marker, code)


@pytest.mark.parametrize("kind", CDA_ONLY)
def test_the_sections_are_emitted_in_the_templates_own_order(
    corpus_root: Path, kind: ReportKind
) -> None:
    """``structuredBody`` is a sequence, so order is conformance and not taste.

    A body whose sections are each correct and in the wrong order does not
    validate, and nothing downstream in this project would notice — the reader
    walks by descent and does not care.
    """
    order = TEMPLATE_ORDER[kind]
    addendum = NARRATIVE_PROFILES[kind].addendum_code

    declared = [code for code, _, _, _ in NARRATIVE_PROFILES[kind].sections]
    assert _in_order(declared, order), declared

    for document in _documents(corpus_root, _REPORT_MARKER[kind]):
        emitted = re.findall(
            r'<code code="([^"]+)" codeSystem="2\.16\.840\.1\.113883\.6\.1"', document
        )
        body = [code for code in emitted if code in order]
        assert _in_order(body, order), body
        assert emitted[-1] == addendum


def test_the_type_id_is_per_profile_and_the_lab_value_is_the_odd_one(
    corpus_root: Path,
) -> None:
    """One corpus legitimately carries both spellings, which is the finding.

    RAP and RSA fix ``POCD_MT000040UV02``; the laboratory report and the
    discharge letter carry ``POCD_HD000040``. A renderer that wrote one value
    for all of them — which is what it did until these two profiles were
    read — made two of the four non-conformant, and nothing in this project
    could have seen it: the reader does not check ``typeId`` and the
    de-identification does not depend on it.
    """
    for kind in CDA_ONLY:
        for document in _documents(corpus_root, _REPORT_MARKER[kind]):
            assert f'extension="{SUMMARY_TYPE_ID_EXTENSION}"' in document
            assert "POCD_HD000040" not in document

    for marker in ("rad", "dim"):
        for document in _documents(corpus_root, marker):
            assert 'extension="POCD_HD000040"' in document
            assert SUMMARY_TYPE_ID_EXTENSION not in document


def test_only_the_outpatient_report_declares_itself_versioned(corpus_root: Path) -> None:
    """RSA requires ``setId`` at 1..1 where the other three do not.

    A cardinality difference rather than a preference, and the one header value
    the four-row table could not express before. RAP leaves ``setId``
    conditional at 0..1, so it is not written: emitting an optional identifier
    would imply a revision history this generator does not model.
    """
    for document in _documents(corpus_root, "rsa"):
        assert "<setId " in document
        assert "<versionNumber value=" in document

    for marker in ("rad", "dim", "rap"):
        for document in _documents(corpus_root, marker):
            assert "<setId " not in document, marker


def test_every_narrative_profile_declares_a_numero_nosologico(corpus_root: Path) -> None:
    """Which is what links a report to the subject's imaging.

    All four narrative templates require ``componentOf``, which is exactly the
    difference from the patient summary — and it means a pathology or
    outpatient document can establish a subject on an institution-scoped record
    number, where a summary cannot.
    """
    for kind in CDA_ONLY:
        for document in _documents(corpus_root, _REPORT_MARKER[kind]):
            parsed = parse_clinical_document(document)
            assert parsed.record_number, kind


# --------------------------------------------------------------------------
# What a corpus contains, and what it must not
# --------------------------------------------------------------------------


def test_a_cda_corpus_carries_both_new_profiles(corpus_root: Path) -> None:
    """The point of the task: two more document types a hospital really sends."""
    codes = Counter(
        parse_clinical_document(path.read_text(encoding="utf-8")).document_code
        for path in sorted(corpus_root.glob("cda/*.xml"))
    )

    assert codes[PATHOLOGY_DOCUMENT_CODE] > 0
    assert codes[OUTPATIENT_DOCUMENT_CODE] > 0
    # Six: the laboratory report, the four narrative profiles and the patient
    # summary. Asserted as a total rather than one code at a time, so a
    # seventh profile added without a line here fails and gets counted.
    assert len(codes) == 6


def test_a_plain_corpus_carries_neither(tmp_path: Path) -> None:
    """The scope decision, asserted rather than left to a comment.

    Both are published CDA profiles, and a free-text template for either would
    be a layout this project invented — which measures nothing the published
    form does not. The consequence that matters is in
    `test_cda_summary`: a plain corpus draws nothing here, so every number the
    README captures still stands.
    """
    root = tmp_path / "raw"
    summary = write_corpus(CohortSpec(subjects=8, seed=42, defect_rate=0.4), root)

    assert summary.manifest.files.cda == 0
    assert not list(root.glob("reports/*_rap_*"))
    assert not list(root.glob("reports/*_rsa_*"))


@pytest.mark.parametrize("kind", CDA_ONLY)
def test_the_free_text_renderer_refuses_a_kind_it_cannot_write(kind: ReportKind) -> None:
    """Refused loudly, because the alternative is a silent wrong document.

    Every branch in the free-text renderer treats "not radiology" as
    "discharge letter", so a pathology report would come out with a discharge
    letter's headings and its contact sentence, and nothing would say so. The
    path is unreachable from any generated corpus, and this project has
    recorded four times that unreachable is not the same as safe.
    """
    report = (
        sample_pathology_report(
            Random(1), collected_at=REFERENCE, author_name="ROSSI MARIO", site=SITES[0]
        )
        if kind is ReportKind.PATHOLOGY
        else sample_outpatient_report(
            Random(1),
            seen_at=REFERENCE,
            author_name="ROSSI MARIO",
            specialty="Cardiologia",
            site=SITES[0],
        )
    )
    assert report.kind is kind
    assert kind not in PLAIN_TEXT_KINDS

    with pytest.raises(ValueError, match="no free-text template"):
        render_report(
            report,
            person=PATIENT,
            site=SITES[0],
            path="reports/x.txt",
            rng=Random(1),
            injector=DefectInjector(Random(1), 0.0),
        )


def test_every_report_kind_is_renderable_by_one_path_or_the_other() -> None:
    """Between the free-text templates and the CDA profiles, nothing is orphaned.

    A kind in neither set would be a kind the cohort could plan and no renderer
    could write, which fails at generation time with a `KeyError` — late, and
    in a message about a dictionary.
    """
    assert PLAIN_TEXT_KINDS | set(NARRATIVE_PROFILES) == set(ReportKind)


def test_every_report_kind_has_a_filename_marker() -> None:
    """Looked up without a default, so a new kind cannot be filed as a discharge.

    The expression this table replaced read ``"rad" if RADIOLOGY else "dim"``,
    which would have given both new kinds a discharge letter's filename.
    """
    assert set(_REPORT_MARKER) == set(ReportKind)
    assert len(set(_REPORT_MARKER.values())) == len(ReportKind)


# --------------------------------------------------------------------------
# Through the build
# --------------------------------------------------------------------------


def test_a_four_profile_corpus_measures_clean(corpus_root: Path, tmp_path: Path) -> None:
    """End to end, because a new document type is exactly what moves this number."""
    out = tmp_path / "ds"
    build_dataset(read_corpus(corpus_root), KEY, _spec(), out)
    report = measure(corpus_root, out)

    assert report.survived == 0
    assert report.measurable > 0


def test_the_clinical_content_of_both_profiles_survives(corpus_root: Path, tmp_path: Path) -> None:
    """The other side of recall, and the reason the tool exists.

    A scrubber that removed the medicine would score perfectly and deliver
    nothing. The section titles are the cheapest evidence that the narrative came
    through, and they are this project's own words for neither profile — they
    are the titles the two templates give.
    """
    out = tmp_path / "ds"
    build_dataset(read_corpus(corpus_root), KEY, _spec(), out)
    texts = [path.read_text(encoding="utf-8") for path in out.glob("sub-*/ses-*/reports/*.txt")]

    assert any("Osservazione Microscopica" in text for text in texts)
    assert any("Prestazioni" in text for text in texts)
    assert any("[PROVIDER]" in text and "[INSTITUTION]" in text for text in texts)
