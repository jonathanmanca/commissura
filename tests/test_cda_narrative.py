"""Radiology reports and discharge letters as CDA, and whether the seam held.

The laboratory reader was written with a claim attached: that it was "the seam
the radiology report and the discharge letter slot into later". A claim like
that is unverified until something slots in, which is the same class of
statement as a test that has never been watched to fail.

It held, and the measurement of that is narrow: ``HL7IT-IG_CDA2_RAD-v1.1-S``
and ``HL7IT-IG_CDA2_LDO-v1.2-S`` differ from the laboratory profile in a
document code, a title, a template identifier and a table of LOINC-coded
sections. The header is the same element for element -- the same
``recordTarget`` with the same five identifier cases under the same OIDs, the
same obligatory ``custodian`` and ``legalAuthenticator`` -- so one
:data:`commissura.generate.cda.NARRATIVE_PROFILES` table and two narrowed
helper signatures were the whole of the change on the writing side.

**What it did not absorb, and this is the finding worth the task.** A narrative
document declares an *author* as well as a signer, and both elements are
obligatory. The pipeline read only the signer, because a plain-text report
reveals its author through the signature line alone and there had never been a
second name to read. So the author's name -- declared in a defined element of
the very document being de-identified -- was never in the set the scrubber was
told to remove, and the narrative came out reading
``Refertazione a cura del dott. GALLO [PROVIDER]``: the given name matched some
other clinician's and the surname did not. A half-redaction, which is the class
recorded on 2026-11-07 and again on 2026-11-17, and **not** a limit of targeted
redaction: the document said the name and the reader discarded it.

Every identifier here is synthetic.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest

from commissura.build.writer import BuildSpec, _known_identifiers, build_dataset
from commissura.deident.keys import SecretKey
from commissura.generate.cda import NARRATIVE_PROFILES
from commissura.generate.cohort import CohortSpec
from commissura.generate.writer import write_corpus
from commissura.measure import measure
from commissura.models import ReportKind
from commissura.read.cda import (
    DISCHARGE_DOCUMENT_CODE,
    LABORATORY_DOCUMENT_CODE,
    RADIOLOGY_DOCUMENT_CODE,
    SUMMARY_DOCUMENT_CODE,
    parse_clinical_document,
)
from commissura.read.corpus import read_corpus

KEY = SecretKey(bytes(range(32)))

# Read from the specifications' own section tables, not recalled. RAD Tabella 46
# marks two of eleven sections OBBLIGATORIO; LDO Tabella 52 marks three of
# sixteen. A conformant document of each kind must carry them.
MANDATORY_SECTIONS = {
    ReportKind.RADIOLOGY: {"55111-9", "18782-3"},
    ReportKind.DISCHARGE: {"46241-6", "8648-8", "11535-2"},
    # RAP and RSA arrived on 2026-11-23 and are read from their own ART-DECOR
    # templates rather than from a PDF table; `test_cda_profiles` is where
    # their own checks live. They are listed here because this test is
    # parametrised over the whole enum, and a kind missing from this table
    # would fail with a KeyError rather than with something a reader can act
    # on.
    ReportKind.PATHOLOGY: {"29300-1", "22637-3"},
    ReportKind.OUTPATIENT: {"62387-6", "47045-0"},
}


@pytest.fixture(scope="module")
def corpus_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A CDA corpus carrying all three document profiles."""
    root = tmp_path_factory.mktemp("cda-narrative") / "raw"
    write_corpus(CohortSpec(subjects=12, seed=42, defect_rate=0.2, cda=True), root)
    return root


def _documents(root: Path) -> list[tuple[str, object]]:
    return [
        (path.name, parse_clinical_document(path.read_text(encoding="utf-8")))
        for path in sorted(root.glob("cda/*.xml"))
    ]


# --------------------------------------------------------------------------
# The profiles, against the specifications
# --------------------------------------------------------------------------


def test_the_document_codes_are_the_ones_the_specifications_fix() -> None:
    """And radiology's is the one that reading corrected.

    ``68604-8``, not ``18748-4``. The latter is LOINC's "Diagnostic imaging
    study" and is what recalling it produces; RAD section 4.1.5 fixes
    ``68604-8`` as a constant. Pinned here as a value rather than trusted as a
    memory, which is the `NNITA` lesson of 2026-11-11.
    """
    assert RADIOLOGY_DOCUMENT_CODE == "68604-8"
    assert DISCHARGE_DOCUMENT_CODE == "34105-7"
    assert LABORATORY_DOCUMENT_CODE == "11502-2"
    assert len({RADIOLOGY_DOCUMENT_CODE, DISCHARGE_DOCUMENT_CODE, LABORATORY_DOCUMENT_CODE}) == 3


@pytest.mark.parametrize("kind", list(ReportKind))
def test_a_profile_covers_every_mandatory_section(kind: ReportKind) -> None:
    """A document missing an OBBLIGATORIO section is not conformant.

    Asserted against the profile table rather than against a rendered document,
    so the failure names the table somebody edited.
    """
    codes = {code for code, _, _, _ in NARRATIVE_PROFILES[kind].sections}

    assert MANDATORY_SECTIONS[kind] <= codes


@pytest.mark.parametrize("kind", list(ReportKind))
def test_a_profile_draws_each_section_from_its_own_field(kind: ReportKind) -> None:
    """One section per field, so no part of a report is written twice or lost."""
    fields = [field for _, _, _, field in NARRATIVE_PROFILES[kind].sections]

    assert len(fields) == len(set(fields))
    assert set(fields) <= {"indication", "technique", "findings", "conclusion"}


# --------------------------------------------------------------------------
# What the generator writes
# --------------------------------------------------------------------------


def test_a_cda_corpus_carries_every_profile(corpus_root: Path) -> None:
    """One inventory of what a CDA corpus holds, in one place.

    A second and third document type that slot in was the point of this task;
    the fourth, the Profilo Sanitario Sintetico, did not slot in and has its own
    file. It is counted here anyway, because a reader asking "what is in a CDA
    corpus" should get the whole answer from one test rather than two.
    """
    codes = Counter(document.document_code for _, document in _documents(corpus_root))  # type: ignore[attr-defined]

    assert codes[LABORATORY_DOCUMENT_CODE] > 0
    assert codes[RADIOLOGY_DOCUMENT_CODE] > 0
    assert codes[DISCHARGE_DOCUMENT_CODE] > 0
    assert codes[SUMMARY_DOCUMENT_CODE] > 0


def test_a_cda_corpus_writes_no_plain_text_report(corpus_root: Path) -> None:
    """A site that has migrated sends everything as CDA.

    Not a tidiness point: a corpus carrying both forms would make the
    `reports/` glob and the `cda/` glob disagree about which file a narrative
    came from, and the manifest's modality ledgers would double-count it.
    """
    assert not list(corpus_root.glob("reports/*.txt"))
    assert list(corpus_root.glob("cda/*_rad_*.xml"))
    assert list(corpus_root.glob("cda/*_dim_*.xml"))


@pytest.mark.parametrize(
    ("marker", "kind"),
    [("_rad_", ReportKind.RADIOLOGY), ("_dim_", ReportKind.DISCHARGE)],
)
def test_every_mandatory_section_is_present_in_the_output(
    corpus_root: Path, marker: str, kind: ReportKind
) -> None:
    """Checked on the rendered documents, not only on the table.

    A table that lists a section and a writer that skips it when the field is
    empty would pass the table test and emit a non-conformant document, which
    is exactly the gap between a declaration and a run.
    """
    paths = sorted(corpus_root.glob(f"cda/*{marker}*.xml"))
    assert paths

    for path in paths:
        codes = set(re.findall(r'<code code="([0-9-]+)"', path.read_text(encoding="utf-8")))
        assert MANDATORY_SECTIONS[kind] <= codes, path.name


def test_a_narrative_document_carries_no_structured_results(corpus_root: Path) -> None:
    """Both specifications keep the coded entries OPZIONALE.

    A radiology report's content *is* prose, so inventing coded observations
    for it would model something a radiology department does not produce.
    """
    for name, document in _documents(corpus_root):
        if document.document_code == LABORATORY_DOCUMENT_CODE:  # type: ignore[attr-defined]
            continue
        assert not document.observations, name  # type: ignore[attr-defined]
        assert document.narrative, name  # type: ignore[attr-defined]


def test_a_narrative_document_declares_the_numero_nosologico(corpus_root: Path) -> None:
    """Which is what links it to the subject's imaging.

    OPZIONALE for radiology and obligatory for a discharge letter (CONF-LDO-80),
    and written for both: a document that could carry it and does not is a
    document whose imaging attaches to nobody.

    **The patient summary is excluded, and not as a convenience.** Its profile
    does not permit ``componentOf`` at all, so a PSS has no encounter and no
    numero nosologico to declare -- which means a subject established only by a
    summary is keyed on their codice fiscale or on nothing. This assertion read
    "every CDA document" because every CDA document could carry one, and that
    stopped being true when a fourth profile arrived.
    """
    for name, document in _documents(corpus_root):
        if document.document_code == SUMMARY_DOCUMENT_CODE:  # type: ignore[attr-defined]
            assert not document.record_number, name  # type: ignore[attr-defined]
            continue
        assert document.record_number, name  # type: ignore[attr-defined]


# --------------------------------------------------------------------------
# Through the pipeline
# --------------------------------------------------------------------------


def test_a_narrative_document_yields_a_report_and_no_lab(corpus_root: Path) -> None:
    """Giving it an empty laboratory record would claim the modality carried one."""
    corpus = read_corpus(corpus_root)
    lab_paths = {record.path for s in corpus.subjects for record in s.labs}
    narrative_paths = {
        record.path
        for s in corpus.subjects
        for record in s.reports
        if record.path.startswith("cda/") and ("_rad_" in record.path or "_dim_" in record.path)
    }

    assert narrative_paths
    assert not narrative_paths & lab_paths


def test_both_clinician_names_reach_the_scrubber(corpus_root: Path) -> None:
    """The finding this task produced, pinned so it cannot come back.

    A CDA document declares an obligatory author *and* an obligatory legal
    authenticator, and they are different people here on purpose. Reading only
    the signer left the author's name out of the set the scrubber removes, and
    the narrative came out half-redacted.
    """
    corpus = read_corpus(corpus_root)
    subject = next(s for s in corpus.subjects if s.reports)
    known = _known_identifiers(corpus, subject)

    authors = {r.author_name for r in subject.reports if r.author_name}
    signers = {r.signed_by for r in subject.reports if r.signed_by}
    assert authors, "no CDA document declared an author"
    assert authors - signers, "the author and the signer are never different in this corpus"
    assert authors <= known.providers
    assert signers <= known.providers


def test_no_clinician_name_is_left_half_redacted(corpus_root: Path, tmp_path: Path) -> None:
    """The shape of the defect, asserted rather than the particular name.

    `[PROVIDER]` beside a surviving capitalised word is what a half-redaction
    looks like in the output, and it reads as a success to anybody skimming.
    """
    out = tmp_path / "ds"
    corpus = read_corpus(corpus_root)
    build_dataset(
        corpus, KEY, BuildSpec(dataset_name="d", description="d", hdab="H", publisher="P"), out
    )
    stranded = re.compile(r"\[PROVIDER\]\s+[A-ZÀ-Ü]{4,}|[A-ZÀ-Ü]{4,}\s+\[PROVIDER\]")

    offences = [
        f"{path.name}: {match.group(0)!r}"
        for path in sorted(out.rglob("*_report.txt"))
        for match in stranded.finditer(path.read_text(encoding="utf-8"))
    ]

    assert not offences, "a clinician name survived beside its own placeholder:\n" + "\n".join(
        offences[:10]
    )


def test_the_three_profile_corpus_measures_clean(corpus_root: Path, tmp_path: Path) -> None:
    """Recall over everything planted, across all three document types."""
    out = tmp_path / "measured"
    corpus = read_corpus(corpus_root)
    build_dataset(
        corpus, KEY, BuildSpec(dataset_name="d", description="d", hdab="H", publisher="P"), out
    )

    report = measure(corpus_root, out)

    assert report.recall == 1.0, Counter(miss.text for miss in report.misses).most_common(8)
