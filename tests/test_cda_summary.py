"""The Profilo Sanitario Sintetico, and where the seam actually was.

The entry of 2026-11-18 said the three remaining profiles on the Ministry's
index were "a profile table and a section map" away, because the radiology
report and the discharge letter had been exactly that. This one is not, and
measuring how it is not is most of what this file does.

**Read from the Schematron, not from a PDF.** Every PDF the Ministry's index
offers for this profile is marked *obsoleta, da non utilizzare in nuove
implementazioni*; the normative form is an ART-DECOR package whose closed
document template is machine-readable. That is a better source than any
transcription, and it is what turned up the finding below.

**The finding: three section template OIDs in the published package carry stray
whitespace inside the attribute value**, and one of them is the vaccinations
section. Because the malformed spelling is used consistently -- in the document
template's permitted-section list *and* in the section's own rule context --
there is no spelling of that section that is both a well-formed OID and
accepted by the package. It is therefore not emitted, and these tests pin that
it stays not emitted, with the shape of the defect asserted rather than the
particular section, so a later "fix" that pastes the spaced value in fails.

Every identifier here is synthetic.
"""

from __future__ import annotations

import re
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from random import Random

import pytest

from commissura.build.writer import BuildSpec, _known_identifiers, build_dataset
from commissura.deident.keys import SecretKey
from commissura.generate.cda import SUMMARY_SECTIONS, render_summary_cda
from commissura.generate.cohort import CohortSpec, build_person
from commissura.generate.defects import DefectInjector
from commissura.generate.vocabulary import SITES
from commissura.generate.writer import write_corpus
from commissura.measure import measure
from commissura.read.cda import (
    CODICE_FISCALE_ROOT,
    CODICE_FISCALE_ROOT_MISPRINT,
    DISCHARGE_DOCUMENT_CODE,
    LABORATORY_DOCUMENT_CODE,
    RADIOLOGY_DOCUMENT_CODE,
    SUMMARY_DOCUMENT_CODE,
    SUMMARY_TEMPLATE_EXTENSION,
    SUMMARY_TEMPLATE_ROOT,
    SUMMARY_TYPE_ID_EXTENSION,
)
from commissura.read.corpus import (
    DATE_FIELD_CDA_EFFECTIVE_TIME,
    LabRecord,
    RawCorpus,
    ReportRecord,
    read_corpus,
)

KEY = SecretKey(bytes(range(32)))

REFERENCE = datetime(2024, 6, 1, tzinfo=UTC)

VACCINATION_ROOT_AS_PUBLISHED = "2.16.840.1.113883.2.9.10.1.4.2.3 "
"""The vaccinations section's templateId root, quoted exactly as the package has it.

Trailing space included. This constant exists so the assertions below can say
what they are refusing without a reader thinking the space is a typo in the
test.
"""


@pytest.fixture(scope="module")
def corpus_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A CDA corpus, which now carries a patient summary per subject."""
    root = tmp_path_factory.mktemp("cda-summary") / "raw"
    write_corpus(CohortSpec(subjects=10, seed=7, defect_rate=0.2, cda=True), root)
    return root


def _spec() -> BuildSpec:
    """The catalogue fields a build will not invent."""
    return BuildSpec(
        dataset_name="summary corpus",
        description="A synthetic corpus carrying patient summaries.",
        hdab="HDAB SINTETICO",
        publisher="IRCCS SINTETICO MAREBIANCO",
    )


def _is_summary(path: str) -> bool:
    """Whether a corpus-relative path names a patient summary."""
    return path.endswith("_pss_1.xml")


def _reports(corpus: RawCorpus) -> list[ReportRecord]:
    return [record for subject in corpus.subjects for record in subject.reports]


def _labs(corpus: RawCorpus) -> list[LabRecord]:
    return [record for subject in corpus.subjects for record in subject.labs]


def _summaries(root: Path) -> list[str]:
    return [path.read_text(encoding="utf-8") for path in sorted(root.glob("cda/*_pss_*.xml"))]


def _render_one(*, rate: float) -> tuple[str, DefectInjector]:
    """Render one summary directly, so a defect can be forced rather than drawn."""
    injector = DefectInjector(Random(1), rate)
    person = build_person(Random(7), reference_date=REFERENCE)
    document, _ = render_summary_cda(
        person,
        site=SITES[0],
        path="cda/x_pss_1.xml",
        document_id="PSS000010001",
        set_id="PSS00001",
        version=1,
        authored_at=REFERENCE,
        author_name="ROSSI MARIO",
        signed_by="BIANCHI ANNA",
        allergies=("Nessuna allergia nota",),
        therapies=("Nessuna terapia farmacologica in corso",),
        injector=injector,
    )
    return document, injector


# --------------------------------------------------------------------------
# The profile, against the Schematron
# --------------------------------------------------------------------------


def test_the_document_constants_are_the_ones_the_schematron_fixes() -> None:
    """Pinned as values, because recalling an identifier is how this goes wrong.

    ``60591-5`` is asserted at min 1 and max 1 on the document's own ``code``,
    and the template is ``2.16.840.1.113883.2.9.10.1.4.1.1`` at extension
    ``1.5``. The lesson is `NNITA` of 2026-11-11 and the radiology code of
    2026-11-18: a plausible value written without checking is the same failure
    as a plausible IRI that resolves to nothing.
    """
    assert SUMMARY_DOCUMENT_CODE == "60591-5"
    assert SUMMARY_TEMPLATE_ROOT == "2.16.840.1.113883.2.9.10.1.4.1.1"
    assert SUMMARY_TEMPLATE_EXTENSION == "1.5"
    codes = {
        SUMMARY_DOCUMENT_CODE,
        LABORATORY_DOCUMENT_CODE,
        RADIOLOGY_DOCUMENT_CODE,
        DISCHARGE_DOCUMENT_CODE,
    }
    assert len(codes) == 4


def test_two_hl7_italia_profiles_disagree_about_the_type_id(corpus_root: Path) -> None:
    """The divergence is the finding, so it is asserted rather than smoothed over.

    The PSS Schematron requires ``typeId/@extension`` to be
    ``POCD_MT000040UV02`` at min 1 and max 1. The laboratory specification
    writes ``POCD_HD000040`` on page 18, and this generator writes that for its
    other three profiles. Both documents come from HL7 Italia, so one corpus
    legitimately contains both spellings -- and a test that quietly made them
    agree would be choosing between two specifications on their behalf.

    Asserted across two documents of one corpus rather than on the constants,
    because the constants alone are a tautology: what matters is that the two
    renderers write different values and each writes its own profile's.
    """
    assert SUMMARY_TYPE_ID_EXTENSION == "POCD_MT000040UV02"

    radiology = next(iter(sorted(corpus_root.glob("cda/*_rad_*.xml")))).read_text(encoding="utf-8")
    summary = _summaries(corpus_root)[0]

    assert f'extension="{SUMMARY_TYPE_ID_EXTENSION}"' in summary
    assert SUMMARY_TYPE_ID_EXTENSION not in radiology
    assert "POCD_HD000040" in radiology
    assert "POCD_HD000040" not in summary


def test_every_emitted_section_root_is_a_well_formed_oid() -> None:
    """The guard on the whitespace finding, asserted as a shape.

    Not "the vaccinations section is absent", which a later edit could satisfy
    by renaming something. A templateId root is digits and dots; any emitted
    root carrying a space is the published package's defect copied into a
    document this project generates, whichever section it belongs to.
    """
    for root, _, _, _ in SUMMARY_SECTIONS:
        assert re.fullmatch(r"[0-9]+(\.[0-9]+)+", root), root
        assert root == root.strip()


def test_the_vaccinations_section_is_not_emitted_in_either_spelling() -> None:
    """Neither spelling, and both halves of that matter.

    The untrimmed value would put a malformed OID into a generated document.
    The trimmed value would claim conformance to a rule the package does not
    contain: a document carrying it is rejected by the closed document template
    as an unpermitted section *and* never matched by the vaccination rules,
    whose own context names the spaced form too.
    """
    roots = {root for root, _, _, _ in SUMMARY_SECTIONS}

    assert VACCINATION_ROOT_AS_PUBLISHED not in roots
    assert VACCINATION_ROOT_AS_PUBLISHED.strip() not in roots

    summary, _ = _render_one(rate=0.0)

    assert VACCINATION_ROOT_AS_PUBLISHED not in summary
    assert VACCINATION_ROOT_AS_PUBLISHED.strip() not in summary
    # And the section's LOINC code is not emitted under some other root either,
    # which is the way an "improvement" would most plausibly arrive.
    assert "11369-6" not in summary


def test_each_emitted_section_pairs_the_root_the_package_pairs_with_its_code() -> None:
    """Root and code together, because either alone is satisfiable by accident.

    Both pairs are read from the section's own rule file, where the
    ``<title>`` names the section: ``48765-2`` in "Allergie e Intolleranze
    PSS" under ``…63.10.415``, and ``10160-0`` in "Terapie Farmacologiche
    (PSS)" under ``…4.2.2``.
    """
    pairs = {(root, code) for root, code, _, _ in SUMMARY_SECTIONS}

    assert pairs == {
        ("2.16.840.1.113883.3.1937.777.63.10.415", "48765-2"),
        ("2.16.840.1.113883.2.9.10.1.4.2.2", "10160-0"),
    }


# --------------------------------------------------------------------------
# What the generator writes
# --------------------------------------------------------------------------


def test_a_cda_corpus_carries_one_summary_per_subject(corpus_root: Path) -> None:
    """One per person, not one per encounter, which is the structural point.

    A summary is a maintained document about a patient. Writing one per
    encounter would model a thing the Fascicolo Sanitario Elettronico does not
    hold, and would also have made this profile a fourth row in a table of
    report profiles, which is the conclusion this task set out to test.
    """
    summaries = sorted(corpus_root.glob("cda/*_pss_*.xml"))
    mrns = {path.name.split("_")[0] for path in summaries}
    subjects = {path.name.split("_")[0] for path in corpus_root.glob("cda/*.xml")}

    assert len(summaries) == len(mrns) == len(subjects) == 10


def test_a_summary_carries_no_encompassing_encounter(corpus_root: Path) -> None:
    """``componentOf`` is not among the elements this profile permits.

    So there is no numero nosologico in a patient summary, where every other
    CDA document this generator writes carries one. A renderer that reused the
    narrative header would emit it, the document would be non-conformant, and
    nothing downstream would notice -- the record number would simply link.
    """
    for summary in _summaries(corpus_root):
        assert "<componentOf>" not in summary
        assert "encompassingEncounter" not in summary


def test_a_summary_declares_itself_a_maintained_document(corpus_root: Path) -> None:
    """``setId`` stable, ``versionNumber`` present, ``documentationOf`` required.

    The three together are what distinguish a document that is kept up to date
    from a record of one event, and ``documentationOf[serviceEvent]`` is
    required at exactly one where the narrative profiles do not use it at all.
    """
    for summary in _summaries(corpus_root):
        assert "<setId " in summary
        assert "<versionNumber value=" in summary
        assert "<documentationOf>" in summary
        assert 'classCode="PCPR"' in summary


def test_a_summary_names_its_compiler_in_prose(corpus_root: Path) -> None:
    """Hostile on purpose, the same decision as the narrative profiles.

    A summary carrying only clean clinical prose would be easier to
    de-identify than the documents it sits beside, and the recall figure would
    improve for no reason but a kinder corpus.
    """
    for summary in _summaries(corpus_root):
        assert "Profilo compilato dal dott. " in summary
        assert "Dati aggiornati al " in summary


def test_the_closing_prose_sits_inside_a_section_the_profile_permits(
    corpus_root: Path,
) -> None:
    """Paragraphs in an existing section, not a section of this project's own.

    RAD has ``55107-7`` "Addendum" for an addition like this and LDO reuses
    ``18776-5``. The PSS document template is closed and every section it
    permits carries a prescribed code, so there is no section here meaning "a
    note about the document" -- and inventing a templateId-and-code pair the
    package does not pair is the failure this whole file is about.
    """
    permitted = {code for _, code, _, _ in SUMMARY_SECTIONS}

    for summary in _summaries(corpus_root):
        codes = set(
            re.findall(r'<code code="([^"]+)" codeSystem="2\.16\.840\.1\.113883\.6\.1"', summary)
        )
        assert codes <= permitted | {SUMMARY_DOCUMENT_CODE}


def test_the_misprinted_codice_fiscale_root_reaches_the_summary_path() -> None:
    """The defect of 2026-11-17 is drawn here too, and is recorded when used.

    Forced rather than drawn, because whether a particular seed applies it to a
    particular document is not the property under test. What is under test is
    that the summary renderer takes part in the defect at all: a renderer that
    silently wrote the correct root would make the misprint unreachable from a
    corpus that contains summaries, which is the condition this project has
    four times found to mean "not covered".
    """
    summary, injector = _render_one(rate=1.0)

    assert f'root="{CODICE_FISCALE_ROOT_MISPRINT}"' in summary
    assert f'root="{CODICE_FISCALE_ROOT}" ' not in summary
    assert [applied.defect_id for applied in injector.applied()] == ["cda.misdeclared_cf_namespace"]


def test_a_clean_summary_declares_the_correct_root() -> None:
    """The other half, so the test above cannot pass by always misdeclaring."""
    summary, injector = _render_one(rate=0.0)

    assert f'root="{CODICE_FISCALE_ROOT}"' in summary
    assert CODICE_FISCALE_ROOT_MISPRINT not in summary
    assert not list(injector.applied())


# --------------------------------------------------------------------------
# Through the reader and the build
# --------------------------------------------------------------------------


def test_a_summary_yields_a_report_record_and_no_lab_record(corpus_root: Path) -> None:
    """No reader change was needed, and this is the evidence.

    ``read_cda`` routes a document whose code is not the laboratory one to a
    report-only record, so a fourth profile arrives through the path the second
    and third already used. The claim is cheap to make and was worth checking.
    """
    corpus = read_corpus(corpus_root)
    summaries = [record for record in _reports(corpus) if _is_summary(record.path)]

    assert len(summaries) == 10
    assert not [record for record in _labs(corpus) if _is_summary(record.path)]
    for record in summaries:
        assert record.date_field == DATE_FIELD_CDA_EFFECTIVE_TIME
        assert record.author_name
        assert record.signed_by
        assert record.author_name != record.signed_by


def test_a_summary_opens_no_session_of_its_own(corpus_root: Path, tmp_path: Path) -> None:
    """The reason the summary is dated as of the subject's last recorded event.

    Sessions are dated encounters. A summary dated later than everything it
    summarises would add a session to every subject in the dataset, holding a
    document and no clinical event -- a statement about care that did not
    happen, in a dataset built to be believed.

    **Asserted on the sessions rather than on the dates**, which is the second
    attempt. The first compared the summary's date against the subject's other
    records and got the comparison backwards: it asserted the summary was not
    *earlier*, which a summary dated a day late satisfies happily. The
    sabotage that moved the date forward passed, which is what a guard nobody
    has watched fail is worth. The two date sets are not even directly
    comparable -- the writer reads a panel's `reported_at` where the reader
    reports its collection time -- so the dates were the wrong thing to assert
    on. Whether a session holds anything besides the summary is the property.
    """
    out = tmp_path / "ds"
    build_dataset(read_corpus(corpus_root), KEY, _spec(), out)
    lonely = []

    for session in sorted(out.glob("sub-*/ses-*")):
        files = [path for path in session.rglob("*") if path.is_file()]
        texts = [path for path in files if path.suffix == ".txt"]
        summaries = [
            path
            for path in texts
            if "Profilo compilato dal dott." in path.read_text(encoding="utf-8")
        ]
        if summaries and len(files) == 2 * len(summaries):
            lonely.append(session.relative_to(out).as_posix())

    assert not lonely, lonely


def test_both_clinician_names_in_a_summary_reach_the_scrubber(corpus_root: Path) -> None:
    """The 2026-11-18 finding, on the new path.

    A narrative CDA document declares an author *and* a signer, and reading
    only the signer left the author's surname in no set the scrubber was told
    to remove -- a half-redaction that reads as a success. The summary carries
    both elements, so it has to be checked on this path too rather than
    inherited.
    """
    corpus = read_corpus(corpus_root)
    checked = 0

    for subject in corpus.subjects:
        known = _known_identifiers(corpus, subject)
        declared = {value.upper() for value in known.providers}
        for record in subject.reports:
            if not _is_summary(record.path):
                continue
            assert record.author_name.upper() in declared
            assert record.signed_by.upper() in declared
            checked += 1

    assert checked == 10


def test_a_summary_corpus_measures_clean(corpus_root: Path, tmp_path: Path) -> None:
    """End to end: build, then ask whether any planted identifier survived.

    The number that matters is the one the instrument reports, and a fourth
    document profile is exactly the kind of change that moves it without
    anybody noticing.
    """
    out = tmp_path / "ds"
    build_dataset(read_corpus(corpus_root), KEY, _spec(), out)
    report = measure(corpus_root, out)

    assert report.survived == 0
    assert report.measurable > 0


def test_the_clinical_content_of_a_summary_survives(corpus_root: Path, tmp_path: Path) -> None:
    """The other side of the same coin, and the reason the tool exists.

    A de-identification that removed the allergy and the medication would
    score perfectly on recall and deliver nothing a researcher asked for. So
    the sections' titles and at least one clinical line have to come out the
    far end.
    """
    out = tmp_path / "ds"
    build_dataset(read_corpus(corpus_root), KEY, _spec(), out)

    texts = [path.read_text(encoding="utf-8") for path in out.glob("sub-*/ses-*/reports/*.txt")]
    summaries = [text for text in texts if "Profilo compilato dal dott." in text]

    assert summaries
    titles: Counter[str] = Counter()
    for text in summaries:
        for _, _, title, _ in SUMMARY_SECTIONS:
            if title in text:
                titles[title] += 1
    assert set(titles) == {title for _, _, title, _ in SUMMARY_SECTIONS}
    assert any("[PROVIDER]" in text and "[INSTITUTION]" in text for text in summaries)


# --------------------------------------------------------------------------
# What must not have moved
# --------------------------------------------------------------------------


def test_a_plain_corpus_draws_exactly_what_it_drew_before() -> None:
    """The guard that keeps the README's captured numbers honest.

    Summaries are drawn from ``render_rng`` only inside the ``spec.cda``
    branch, and only after every draw that already existed, so a corpus
    without CDA cannot see them. **The expected values were measured, not
    reasoned about**: they come from running ``write_corpus`` under a worktree
    at ``45fbae5``, the commit before this profile existed. The precedent is
    the enrolment stream pin of 2026-11-18, where reasoning was right and was
    not evidence.

    **The span count moved once, on 2026-11-24, from 1307 to 1301, and the two
    numbers beside it are what say why.** One generated site's feed now sends a
    placeholder where the codice fiscale belongs, so six of its messages carry
    no national-identifier span -- a change to what is *written*, not to what
    is *drawn*. The defect count and the file count are identical across that
    change, which is the evidence: a shifted stream moves the defects too, and
    these did not move. So this pin still guards what it was written to guard.
    """
    with tempfile.TemporaryDirectory() as directory:
        summary = write_corpus(
            CohortSpec(subjects=8, seed=42, defect_rate=0.2, cda=False),
            Path(directory) / "raw",
        )

        assert len(summary.spans) == 1301
        assert len(summary.manifest.defects) == 123
        assert summary.file_count == 67
        assert summary.manifest.files.cda == 0
