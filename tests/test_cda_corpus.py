"""CDA documents inside a corpus: linkage, the build, and the measurement.

Where ``test_cda.py`` is about the specification's rules, this is about the
claim that matters: ``commissura build`` takes real hospital documents and the
pipeline behind it needs no branch per document type. So these tests go through
``generate --cda`` and ``read_corpus`` rather than through hand-built strings,
because this project has three times found that a path no corpus exercises is
not covered whatever the coverage percentage says.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from commissura.annotate import check_spans
from commissura.build.manifest import write_manifest
from commissura.build.observe import CARRIED_FIELDS, cda_fields, observe_corpus
from commissura.build.writer import BuildSpec, build_dataset
from commissura.deident.keys import SecretKey
from commissura.generate.cohort import CohortSpec
from commissura.generate.writer import CorpusSummary, verify_corpus, write_corpus
from commissura.measure import measure
from commissura.read.cda import CODICE_FISCALE_ROOT, CODICE_FISCALE_ROOT_MISPRINT
from commissura.read.corpus import (
    DATE_FIELD_CDA_EFFECTIVE_TIME,
    RAW_SOURCES,
    read_corpus,
    read_exact,
)
from commissura.read.identity import KeyKind, RefusalReason

KEY = SecretKey(bytes(range(32)))
"""The published test vector the rest of the suite uses."""


@pytest.fixture(scope="module")
def cda_corpus(tmp_path_factory: pytest.TempPathFactory) -> CorpusSummary:
    """Generate one CDA corpus for the whole module.

    Module-scoped because generating and reading it is the expensive part and
    none of these tests mutate it. The defect rate is non-zero so that the
    misprinted-root path is reached, which is the entire reason that defect
    exists.
    """
    root = tmp_path_factory.mktemp("cda") / "raw"
    spec = CohortSpec(subjects=8, seed=11, defect_rate=0.4, cda=True)
    return write_corpus(spec, root)


# --------------------------------------------------------------------------
# The corpus layout
# --------------------------------------------------------------------------


def test_cda_is_discovered_through_the_one_declaration_of_the_globs() -> None:
    """Two modules walk a corpus and must not disagree about what it holds.

    ``RAW_SOURCES`` exists because a glob written twice makes the manifest
    describe files the dataset was not built from. A new source has to go there
    and nowhere else, so every consumer picks it up — including
    :func:`commissura.build.observe.observe_corpus`, which raises ``KeyError``
    on a source it has no ledger for.
    """
    assert RAW_SOURCES["cda"] == "cda/*.xml"
    # Laboratory sources first: they are the ones that may create a subject.
    assert list(RAW_SOURCES)[:2] == ["lab", "cda"]
    assert set(CARRIED_FIELDS) <= set(RAW_SOURCES)


def test_the_generator_writes_cda_instead_of_hl7(cda_corpus: CorpusSummary) -> None:
    """One or the other, because a CDA report *is* the laboratory message."""
    assert cda_corpus.manifest.files.cda > 0
    assert cda_corpus.manifest.files.lab == 0
    assert not (cda_corpus.root / "lab").exists()
    assert sorted(p.suffix for p in (cda_corpus.root / "cda").iterdir()) == [".xml"] * (
        cda_corpus.manifest.files.cda
    )


def test_the_default_corpus_is_unchanged(tmp_path: Path) -> None:
    """``--cda`` is off by default, and that is the reproducibility contract.

    The same seed must produce the same corpus it produced before this flag
    existed, or every captured number in the README's worked example is a lie
    about the current tool.
    """
    summary = write_corpus(CohortSpec(subjects=4, seed=2, defect_rate=0.3), tmp_path / "raw")

    assert summary.manifest.files.cda == 0
    assert summary.manifest.files.lab > 0
    assert not (summary.root / "cda").exists()


# --------------------------------------------------------------------------
# The offsets, which everything else rests on
# --------------------------------------------------------------------------


def test_every_planted_span_still_quotes_the_xml_on_disk(cda_corpus: CorpusSummary) -> None:
    """The invariant the whole measurement story rests on, re-checked from disk.

    Not against the in-memory text: the point is to catch newline translation
    and encoding mistakes between rendering and disk, which would silently
    invalidate every measurement taken on this corpus.
    """
    verify_corpus(cda_corpus)

    spans = [span for span in cda_corpus.spans if span.path.startswith("cda/")]
    assert spans
    by_path: dict[str, list[object]] = {}
    for span in spans:
        by_path.setdefault(span.path, []).append(span)
    for relative, found in by_path.items():
        check_spans(read_exact(cda_corpus.root / relative), tuple(found))  # type: ignore[arg-type]


def test_a_generated_document_is_lf_terminated(cda_corpus: CorpusSummary) -> None:
    """``newline=""`` is load-bearing, and Windows is where it would break."""
    document = next((cda_corpus.root / "cda").iterdir())
    assert "\r\n" not in document.read_bytes().decode("utf-8")


# --------------------------------------------------------------------------
# Linkage: one file, two records, one subject
# --------------------------------------------------------------------------


def test_one_document_yields_a_lab_record_and_a_report_record(
    cda_corpus: CorpusSummary,
) -> None:
    """Both halves of the document reach the pipeline, attached to one person.

    A CDA laboratory report is structured results *and* a human-written
    narrative, and the existing pipeline has a shape for each. Mapping it onto
    both is what keeps ``build`` free of a branch per document type.

    **Of a laboratory report.** This asserted that every CDA document in the
    corpus contributed a laboratory record, which held only while the laboratory
    report was the one profile the generator wrote. Radiology reports and
    discharge letters arrived on 2026-11-18 and are narrative: they contribute a
    report record and no laboratory record, because giving them an empty one
    would write an empty table into the dataset and claim the modality carried
    something. The claim this test is about is unchanged for the profile it is
    about: a laboratory document yields exactly one of each, naming the same
    file -- one input contributing two records, not a collision.
    """
    corpus = read_corpus(cda_corpus.root)

    assert corpus.subjects
    for subject in corpus.subjects:
        lab_paths = Counter(record.path for record in subject.labs)
        # Keyed on the paths the laboratory records claim, because the narrative
        # profiles share the directory and not the shape.
        report_paths = Counter(
            record.path
            for record in subject.reports
            if record.path.startswith("cda/") and record.path in lab_paths
        )
        assert set(report_paths) == set(lab_paths)
        assert all(count == 1 for count in lab_paths.values())

    cda_labs = [r for s in corpus.subjects for r in s.labs if r.path.startswith("cda/")]
    assert cda_labs
    assert all(record.observations for record in cda_labs)
    assert all(record.date_field == DATE_FIELD_CDA_EFFECTIVE_TIME for record in cda_labs)


def test_the_narrative_reaches_the_report_record_intact(cda_corpus: CorpusSummary) -> None:
    """CDA does not remove the free text, so the scrubber still has work to do.

    The narrative must arrive unmodified: a scrubber handed pre-trimmed text
    could not report what it removed.
    """
    corpus = read_corpus(cda_corpus.root)
    # Laboratory documents only: the sentence asserted below is the laboratory
    # narrative's, and a radiology report or a discharge letter has its own.
    # Those are covered by `tests/test_cda_narrative.py`.
    lab_paths = {record.path for s in corpus.subjects for record in s.labs}
    reports = [
        r
        for s in corpus.subjects
        for r in s.reports
        if r.path.startswith("cda/") and r.path in lab_paths
    ]

    assert reports
    for report in reports:
        assert "Prelievo eseguito in data" in report.text
        assert report.signed_by
        assert report.authored_on is not None
        # The narrative is the readable text, not the markup it came wrapped in.
        assert "<paragraph>" not in report.text
        assert "xmlns" not in report.text


def test_a_cda_subject_is_keyed_on_its_codice_fiscale(cda_corpus: CorpusSummary) -> None:
    """The same key an HL7 message would have produced, so labels are stable.

    **Of the subjects that have one.** This asserted that *every* CDA subject
    was keyed nationally, which held only because no generated corpus produced
    a patient without a codice fiscale -- the gap closed on 2026-11-18. A
    non-enrolled patient is keyed as an assigned identifier by design, and
    `tests/test_enrolment.py` is where that is asserted. What this test is
    about is unchanged: a codice fiscale read from CDA must key exactly as one
    read from HL7, or the same person gets two labels depending on the format
    their hospital sends.
    """
    corpus = read_corpus(cda_corpus.root)

    enrolled = [s for s in corpus.subjects if s.key.kind is not KeyKind.ASSIGNED_IDENTIFIER]
    assert enrolled
    assert {subject.key.kind for subject in enrolled} == {KeyKind.NATIONAL_ID}
    assert all(subject.key.derivation_input == subject.key.value for subject in enrolled)


def test_imaging_links_to_a_subject_established_from_a_cda_document(
    cda_corpus: CorpusSummary,
) -> None:
    """The numero nosologico is what joins the two, and it is in a defined element.

    This is why the record number is scoped by the custodian's *name* and not by
    the encounter identifier's OID: DICOM states its authority as
    ``InstitutionName`` and has no OID to compare, so scoping by the OID would
    lose every imaging study silently while every count still looked right.
    """
    corpus = read_corpus(cda_corpus.root)

    linked = sum(len(subject.imaging) for subject in corpus.subjects)
    written = len(list((cda_corpus.root / "imaging").iterdir()))
    assert written > 0
    assert linked == written


def test_the_misprinted_root_is_reachable_from_a_generated_corpus(
    cda_corpus: CorpusSummary,
) -> None:
    """A path no corpus exercises is not covered, whatever the percentage says.

    The reader's handling of the specification's own misprint is the single most
    specification-specific decision in this module, so it is reached from
    ``generate`` rather than from a hand-written string alone.
    """
    injected = [
        defect
        for defect in cda_corpus.manifest.defects
        if defect.defect_id == "cda.misdeclared_cf_namespace"
    ]
    assert injected, "raise the defect rate or change the seed: this path must be exercised"

    corpus = read_corpus(cda_corpus.root)
    reported = [
        issue
        for issue in corpus.issues
        if issue.reason == RefusalReason.MISDECLARED_IDENTIFIER_NAMESPACE.value
    ]
    reported_paths = {issue.path for issue in reported}

    # Every document the defect was injected into is reported. Not an equality:
    # `lab.duplicate_message` writes a byte-identical copy, so one injected
    # defect can land in two files and both of them carry the misprint. The
    # reader reports what it read, which is files, and the injector records what
    # it did, which is decisions.
    assert {defect.path for defect in injected} <= reported_paths
    # And nothing is reported that does not actually carry it, which is the
    # direction a count alone cannot check.
    for path in reported_paths:
        assert CODICE_FISCALE_ROOT_MISPRINT in read_exact(cda_corpus.root / path)

    # The detail has to name the fix, not merely the fault.
    assert CODICE_FISCALE_ROOT in reported[0].detail
    assert CODICE_FISCALE_ROOT_MISPRINT in reported[0].detail


def test_the_misprint_does_not_split_a_patient_into_two_subjects(
    cda_corpus: CorpusSummary,
) -> None:
    """Measured before the corroboration rule existed, and it was the argument for it.

    Refusing the misprinted root outright gave one person two subjects whenever
    some of their documents carried it and some did not — and the two then
    claimed the same numero nosologico, so the ambiguity check correctly refused
    that number and the patient's imaging attached to nobody. Every step was
    reported and it was still a worse answer than the document supports.
    """
    corpus = read_corpus(cda_corpus.root)
    reasons = Counter(issue.reason for issue in corpus.issues)

    assert len(corpus.subjects) == cda_corpus.manifest.subject_count
    assert reasons[RefusalReason.AMBIGUOUS_RECORD_NUMBER.value] == 0


def test_an_unreadable_document_costs_one_issue_and_not_the_corpus(
    cda_corpus: CorpusSummary, tmp_path: Path
) -> None:
    """One bad file in an export must not take the other two hundred with it."""
    root = tmp_path / "raw"
    root.mkdir()
    for source in ("cda", "imaging", "reports"):
        directory = cda_corpus.root / source
        if directory.exists():
            target = root / source
            target.mkdir()
            for path in directory.iterdir():
                target.write_bytes if False else (target / path.name).write_bytes(path.read_bytes())
    (root / "cda" / "broken.xml").write_text("<ClinicalDocument><nope", encoding="utf-8")

    corpus = read_corpus(root)
    reasons = Counter(issue.reason for issue in corpus.issues)

    assert reasons[RefusalReason.UNREADABLE_CDA_DOCUMENT.value] == 1
    assert corpus.subjects
    assert corpus.record_count > 0


# --------------------------------------------------------------------------
# The field ledger
# --------------------------------------------------------------------------


def test_every_declared_cda_field_is_one_a_document_really_carries(
    cda_corpus: CorpusSummary,
) -> None:
    """Declared against observed keys, because the first attempt was not.

    The keys were first written as full element paths from ``ClinicalDocument``,
    which is how the specification writes its conformance rules and is not how a
    document is observed. Every declared row came back at zero while the fields
    the build really carries were all reported as removed — a table saying the
    pipeline carried nothing, from a build that carried everything.
    """
    observed: set[str] = set()
    for path in (cda_corpus.root / "cda").iterdir():
        observed |= cda_fields(path)

    declared = set(CARRIED_FIELDS["cda"])
    assert declared <= observed, f"declared but never observed: {sorted(declared - observed)}"


def test_the_ledger_accounts_for_what_a_document_carried(cda_corpus: CorpusSummary) -> None:
    """A field nobody declared is still reported, which is the whole point."""
    ledgers = {ledger.modality: ledger for ledger in observe_corpus(cda_corpus.root)}

    cda = ledgers["cda"]
    assert cda.files_read == cda_corpus.manifest.files.cda
    assert cda.unreadable == ()
    assert cda.count("kept") > 0
    assert cda.count("replaced") > 0
    # The numero nosologico is read for linkage and then dropped, so it is
    # removed rather than replaced -- the distinction the manifest exists for.
    fields = {item.key: item for item in cda.fields}
    assert fields["encompassingEncounter/id"].disposition == "removed"
    assert fields["patientRole/id"].disposition == "replaced"
    # And the lab ledger is present at zero rather than absent, so a reader can
    # tell "looked, found none" from "did not look".
    assert ledgers["lab"].files_read == 0


# --------------------------------------------------------------------------
# End to end
# --------------------------------------------------------------------------


def test_a_dataset_built_from_cda_removes_what_was_planted(
    cda_corpus: CorpusSummary, tmp_path: Path
) -> None:
    """The headline claim, on CDA input, with a number rather than a caveat.

    The survivors are asserted to be the *documented* limit — a clinician named
    in prose with nothing in the structured half declaring them — rather than
    merely few. A bound alone stays green while the failure changes character
    into something that is a defect and not a limit.
    """
    corpus = read_corpus(cda_corpus.root)
    out = tmp_path / "ds"
    spec = BuildSpec(
        dataset_name="cda",
        description="built from CDA R2 laboratory documents",
        hdab="HDAB SINTETICO",
        publisher="ENTE SINTETICO",
        contact_point="referente@esempio.invalid",
        access_url="https://esempio.invalid/permit",
    )
    summary = build_dataset(corpus, KEY, spec, out)
    write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=spec)

    assert summary.report_files > 0
    assert summary.lab_files > 0

    report = measure(cda_corpus.root, out)
    assert report.measurable > 0
    recall = report.recall
    assert recall is not None
    assert recall > 0.99, f"recall fell to {recall:.4%}"

    categories = {miss.category.value for miss in report.misses}
    assert categories <= {"provider_name", "person_name"}

    # **The `person_name` survivor is a collision and not a leak, and that had
    # to be read rather than assumed.** Traced: the string is a patient's family
    # name, and it survived inside an *unredacted clinician name* in a different
    # subject's report -- `reports.missing_author` meeting
    # `reports.identifier_in_prose`, the documented limit, where the signature
    # block was the only structured field naming that clinician. Two people in
    # one cohort share a surname, so one leak is counted under two categories.
    # `measure` asks whether an exact string survived and cannot ask whose it
    # was; that is a property of the instrument, not a defect in it.
    providers = {miss.text for miss in report.misses if miss.category.value == "provider_name"}
    for miss in report.misses:
        if miss.category.value == "person_name":
            assert any(miss.text in provider for provider in providers), (
                f"{miss.text!r} survived without a clinician name to explain it, so this "
                "is no longer the documented limit -- find out what changed before "
                "widening the assertion"
            )

    # And no patient's full name escaped, which is the claim that matters and
    # which a surname collision cannot produce.
    joined = "\n".join(
        path.read_text(encoding="utf-8") for path in out.rglob("*") if path.is_file()
    )
    for subject in corpus.subjects:
        for identity in subject.identities:
            assert identity.full_name not in joined


def test_the_narrative_is_scrubbed_and_the_clinical_content_survives(
    cda_corpus: CorpusSummary, tmp_path: Path
) -> None:
    """Both halves of the only check nobody can automate, asserted separately.

    A scrubber that removed everything would score perfectly on recall and
    destroy the dataset, so the measurement has to be paired with evidence that
    the measurements themselves came through.
    """
    corpus = read_corpus(cda_corpus.root)
    out = tmp_path / "ds"
    spec = BuildSpec(dataset_name="cda", description="d", hdab="H", publisher="P")
    build_dataset(corpus, KEY, spec, out)

    reports = sorted(out.glob("sub-*/ses-*/reports/*_report.txt"))
    assert reports
    joined = "\n".join(path.read_text(encoding="utf-8") for path in reports)

    # Gone: the institution, the absolute date, the patient's name.
    assert "[INSTITUTION]" in joined
    assert "[NAME]" in joined
    assert "day_offset:" in joined
    assert "/2024" not in joined
    assert "OSPEDALE SINTETICO" not in joined
    # Kept: the clinical content, which is what the dataset is for.
    assert "Hemoglobin" in joined or "Glucose" in joined
    assert "mg/dL" in joined or "g/dL" in joined

    tables = sorted(out.glob("sub-*/ses-*/lab/*_lab.tsv"))
    assert tables
    rows = tables[0].read_text(encoding="utf-8").splitlines()
    assert len(rows) > 1
    assert rows[0].split("\t")[:2] == ["day_offset", "loinc_code"]


def test_the_manifest_reports_the_cda_source_and_the_new_key_kind(
    cda_corpus: CorpusSummary, tmp_path: Path
) -> None:
    """Both additions are in the document written to be believed."""
    corpus = read_corpus(cda_corpus.root)
    out = tmp_path / "ds"
    spec = BuildSpec(dataset_name="cda", description="d", hdab="H", publisher="P")
    summary = build_dataset(corpus, KEY, spec, out)
    manifest = write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=spec)

    modalities = manifest["modalities"]
    assert isinstance(modalities, list)
    assert {entry["modality"] for entry in modalities} == {"lab", "cda", "reports", "imaging"}

    source = manifest["source"]
    assert isinstance(source, dict)
    keys = source["subject_keys"]
    assert isinstance(keys, dict)
    # Both kinds are reported, and both are non-zero: a CDA corpus now carries
    # patients identified by an ENI, STP, ANA or TEAM code as well as by a
    # codice fiscale. This asserted `assigned_identifier == 0`, which was true
    # only because no corpus could produce one.
    assert keys["assigned_identifier"] > 0
    assert keys["national_id"] > 0
    assert sum(keys.values()) == len(corpus.subjects)


def test_the_manifest_never_quotes_a_planted_identifier(
    cda_corpus: CorpusSummary, tmp_path: Path
) -> None:
    """The class-level guard, extended to a fourth source.

    Three of the four leaks this project has found in its own manifest were a
    field that looked like metadata and carried something derived from the
    input. A test naming the fields would pass on the next field somebody adds,
    so this one asks whether *any* planted identifier appears anywhere in the
    document.
    """
    corpus = read_corpus(cda_corpus.root)
    out = tmp_path / "ds"
    spec = BuildSpec(dataset_name="cda", description="d", hdab="H", publisher="P")
    summary = build_dataset(corpus, KEY, spec, out)
    manifest = write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=spec)
    serialised = json.dumps(manifest, ensure_ascii=False)

    planted = {
        span.text
        for span in cda_corpus.spans
        if span.path.startswith("cda/") and len(span.text) >= 4
    }
    assert planted
    leaked = sorted(value for value in planted if value in serialised)
    assert not leaked, f"the manifest quotes planted identifiers: {leaked}"
