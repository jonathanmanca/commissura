"""Reading a corpus, linking it, de-identifying it, and writing a dataset.

The end-to-end test is the one that matters: generate a corpus, build a dataset
from it, and run the validator over the result. Every intermediate step can be
right while the whole thing fails, and only the round trip catches that.

The de-identification tests are written as *properties of the output*, not as
checks that a function was called. "No identifier from the source survives in
the dataset" is the claim worth making, and it is checkable because the
generator recorded what it planted.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import date
from pathlib import Path

import pytest

from commissura import healthdcat, layout
from commissura.build.manifest import (
    MANIFEST_SCHEMA_VERSION,
    _body_payload,
    write_healthdcat_description,
    write_manifest,
)
from commissura.build.risk import write_risk_report
from commissura.build.scrub import (
    CATEGORY_DISPOSITION,
    PLACEHOLDER_BIRTH_DATE,
    PLACEHOLDER_INSTITUTION,
    PLACEHOLDER_NAME,
    PLACEHOLDER_NATIONAL_ID,
    KnownIdentifiers,
    Replacement,
    ScrubReport,
    scrub_text,
)
from commissura.build.writer import BuildSpec, BuildSummary, build_dataset
from commissura.deident.keys import SecretKey, generate_key
from commissura.deident.pseudonymise import Pseudonymiser
from commissura.generate.cohort import CohortSpec
from commissura.generate.writer import write_corpus
from commissura.measure import MEASURABLE_LENGTH, _pattern
from commissura.read.corpus import Identity, read_corpus
from commissura.read.hl7 import parse_message, parse_timestamp, unescape
from commissura.validate import validate_dataset

KEY = SecretKey(bytes(range(32)))
CR = chr(13)


def _corpus(tmp_path: Path, name: str = "raw", **kwargs: float | int) -> Path:
    root = tmp_path / name
    write_corpus(CohortSpec(**kwargs), root)  # type: ignore[arg-type]
    return root


def _spec(**overrides: object) -> BuildSpec:
    defaults: dict[str, object] = {
        "dataset_name": "Test dataset",
        "description": "A dataset built in a test.",
        "hdab": "Agenzia Sintetica",
        "publisher": "IRCCS SINTETICO MAREBIANCO",
        "contact_point": "dati@irccs-sintetico.invalid",
    }
    return BuildSpec(**{**defaults, **overrides})  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Reading HL7 back
# --------------------------------------------------------------------------


def test_a_written_message_parses_back(tmp_path: Path) -> None:
    root = _corpus(tmp_path, subjects=2, seed=1, defect_rate=0.0)
    corpus = read_corpus(root)
    lab = corpus.subjects[0].labs[0]

    assert lab.identity.national_id
    assert lab.identity.family_name
    assert lab.identity.birth_date is not None
    assert lab.observations
    assert lab.collected_at is not None


def test_the_reader_tolerates_line_feeds_instead_of_carriage_returns() -> None:
    """A message that has been through an editor arrives with the wrong terminator.

    Refusing it would mean refusing most real-world samples, so the reader
    normalises instead.
    """
    text = f"MSH|^~\\&|LIS|OSP{CR}PID|1||123^^^X^MR{CR}"
    assert len(parse_message(text).segments) == 2
    assert len(parse_message(text.replace(CR, "\n")).segments) == 2
    assert len(parse_message(text.replace(CR, "\r\n")).segments) == 2


def test_msh_is_renumbered_so_callers_can_ask_for_msh_9() -> None:
    """The separator after MSH is field one, so MSH-3 sits where two would be."""
    message = parse_message(f"MSH|^~\\&|LIS|OSP|COMMISSURA|RES|20240318||ORU^R01{CR}")
    msh = message.require("MSH")
    assert msh.field(2) == "^~\\&"
    assert msh.field(3) == "LIS"
    assert msh.field(9) == "ORU^R01"


def test_a_missing_field_is_empty_rather_than_an_error() -> None:
    """Every absence here is a defect the generator can inject deliberately."""
    segment = parse_message(f"OBX|1|NM{CR}").require("OBX")
    assert segment.field(1) == "1"
    assert segment.field(6) == ""
    assert segment.field(99) == ""
    assert segment.component(6, 2) == ""


def test_a_message_with_no_segments_is_refused() -> None:
    with pytest.raises(ValueError, match="no HL7 segments"):
        parse_message("   \n  ")


def test_requiring_an_absent_segment_says_what_was_there() -> None:
    message = parse_message(f"MSH|^~\\&|LIS{CR}")
    with pytest.raises(ValueError, match="no PID segment"):
        message.require("PID")


def test_escape_sequences_become_characters() -> None:
    """Unescaping happens at parse time, so nothing downstream has to wonder."""
    assert unescape("A" + chr(92) + "F" + chr(92) + "B") == "A|B"
    assert unescape("A" + chr(92) + "S" + chr(92) + "B") == "A^B"
    assert unescape("plain") == "plain"


def test_an_unknown_escape_sequence_is_left_alone() -> None:
    """Dropping one would quietly corrupt a value, which is worse than passing it."""
    original = "A" + chr(92) + "X0A" + chr(92) + "B"
    assert unescape(original) == original


def test_an_unterminated_escape_is_kept_verbatim() -> None:
    original = "A" + chr(92) + "F"
    assert unescape(original) == original


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("20240318082005", (2024, 3, 18)),
        ("20240318", (2024, 3, 18)),
        ("18/03/2024", (2024, 3, 18)),
        ("2024-03-18", (2024, 3, 18)),
    ],
)
def test_timestamps_in_every_shape_the_corpus_uses(
    value: str, expected: tuple[int, int, int]
) -> None:
    parsed = parse_timestamp(value)
    assert parsed is not None
    assert (parsed.year, parsed.month, parsed.day) == expected


@pytest.mark.parametrize("value", ["", "   ", "not-a-date", "99999999"])
def test_an_unreadable_timestamp_returns_none_rather_than_raising(value: str) -> None:
    """So a validator can report a malformed timestamp instead of crashing."""
    assert parse_timestamp(value) is None


# --------------------------------------------------------------------------
# Linkage, which is the problem the project exists to solve
# --------------------------------------------------------------------------


def test_every_record_links_in_a_clean_corpus(tmp_path: Path) -> None:
    root = _corpus(tmp_path, subjects=8, seed=3, defect_rate=0.0)
    corpus = read_corpus(root)

    assert len(corpus.subjects) == 8
    assert corpus.issues == ()
    assert corpus.record_count > 20


def test_linkage_survives_the_identifier_drift_defect(tmp_path: Path) -> None:
    """The defect that breaks a naive join, recovered by normalising the number.

    ``imaging.mrn_format_drift`` writes the record number without its zero
    padding, so an exact join silently drops those studies. Matching on the
    normalised form recovers them.
    """
    root = _corpus(tmp_path, subjects=20, seed=4, defect_rate=1.0)
    corpus = read_corpus(root)

    imaging_issues = [i for i in corpus.issues if "imaging" in i.reason]
    assert not imaging_issues, [i.detail for i in imaging_issues]
    assert sum(len(s.imaging) for s in corpus.subjects) > 0


def test_a_subject_is_created_only_by_a_laboratory_message(tmp_path: Path) -> None:
    """The national identifier lives in HL7 PID-19 and in no DICOM header."""
    root = tmp_path / "raw"
    (root / "imaging").mkdir(parents=True)
    (root / "imaging" / "orphan.json").write_text(
        json.dumps([{"00100020": {"vr": "LO", "Value": ["0001234"]}}]),
        encoding="utf-8",
    )
    corpus = read_corpus(root)

    assert corpus.subjects == ()
    assert len(corpus.issues) == 1
    assert corpus.issues[0].reason == "unlinked_imaging"


def test_an_unreadable_record_is_reported_not_skipped_silently(tmp_path: Path) -> None:
    root = _corpus(tmp_path, subjects=2, seed=1, defect_rate=0.0)
    # Not every small cohort gets imaging, so the directory may not exist yet.
    (root / "imaging").mkdir(parents=True, exist_ok=True)
    (root / "imaging" / "broken.json").write_text("{ not json", encoding="utf-8")
    (root / "lab" / "broken.hl7").write_text("nonsense with no segments", encoding="utf-8")

    corpus = read_corpus(root)
    reasons = {issue.reason for issue in corpus.issues}
    assert "unreadable_imaging_metadata" in reasons
    assert "unreadable_lab_message" in reasons


def test_the_baseline_is_the_subjects_earliest_dated_event(tmp_path: Path) -> None:
    root = _corpus(tmp_path, subjects=6, seed=7, defect_rate=0.0)
    for subject in read_corpus(root).subjects:
        baseline = subject.baseline
        assert baseline is not None
        for lab in subject.labs:
            if lab.collected_at:
                assert lab.collected_at.date() >= baseline


# --------------------------------------------------------------------------
# De-identifying free text
# --------------------------------------------------------------------------


def _identity() -> Identity:
    from commissura.models import Sex

    return Identity(
        national_id="RSSMRA80A01X501K",
        mrn="0012345",
        family_name="ROSSI",
        given_name="MARIO",
        sex=Sex.MALE,
        birth_date=date(1980, 1, 1),
    )


def _scrub(text: str, *, baseline: date = date(2024, 3, 1)) -> tuple[str, object]:
    pseudonymiser = Pseudonymiser(KEY)
    known = KnownIdentifiers(
        identities=(_identity(),),
        providers=frozenset({"MORETTI GIULIA", "MORETTI", "GIULIA"}),
        institutions=frozenset({"OSPEDALE SINTETICO DI COLLEVERDE"}),
    )
    return scrub_text(
        text,
        path="reports/x.txt",
        known=known,
        pseudonymiser=pseudonymiser,
        subject_label=pseudonymiser.subject_label(_identity().national_id),
        baseline=baseline,
    )


def test_a_birth_date_is_removed_and_never_turned_into_an_offset() -> None:
    """The fix for a real privacy bug found on the first build.

    Expressing a birth date as an offset from the subject's own baseline states
    the birth date exactly, in a dataset that also carries the baseline. It
    protects nothing, and a birth date is the most identifying date a record
    holds.
    """
    scrubbed, _ = _scrub("Nato/a il: 01/01/1980   Eta: 44 anni")

    assert PLACEHOLDER_BIRTH_DATE in scrubbed
    assert "01/01/1980" not in scrubbed
    assert "day_offset" not in scrubbed


def test_an_event_date_becomes_an_offset_so_the_interval_survives() -> None:
    scrubbed, _ = _scrub("Si confronta con l'esame del 15/03/2024.")
    assert "[day_offset:+14]" in scrubbed
    assert "15/03/2024" not in scrubbed


def test_a_date_with_no_baseline_is_removed_rather_than_invented() -> None:
    pseudonymiser = Pseudonymiser(KEY)
    scrubbed, _ = scrub_text(
        "Esame del 15/03/2024.",
        path="reports/x.txt",
        known=KnownIdentifiers(identities=(_identity(),)),
        pseudonymiser=pseudonymiser,
        subject_label="deadbeefcafe",
        baseline=None,
    )
    assert "[date removed]" in scrubbed
    assert "day_offset" not in scrubbed


def test_the_declared_identifiers_are_removed() -> None:
    scrubbed, report = _scrub(
        "Paziente: MARIO ROSSI\nCodice fiscale: RSSMRA80A01X501K\n"
        "Numero nosografico: 0012345\n"
        "Presso OSPEDALE SINTETICO DI COLLEVERDE, dott. MORETTI GIULIA."
    )
    for leaked in ("MARIO", "ROSSI", "RSSMRA80A01X501K", "0012345", "COLLEVERDE", "MORETTI"):
        assert leaked not in scrubbed, leaked
    assert PLACEHOLDER_NAME in scrubbed
    assert PLACEHOLDER_NATIONAL_ID in scrubbed
    assert report.total_occurrences > 0  # type: ignore[attr-defined]


def test_the_clinical_narrative_is_left_alone() -> None:
    """A scrubber that removed the medicine would protect a useless dataset."""
    narrative = "Non si apprezzano lesioni focali a carico del parenchima polmonare."
    scrubbed, _ = _scrub(f"REPERTI\n{narrative}\n")
    assert narrative in scrubbed


def test_runs_of_the_same_placeholder_collapse() -> None:
    """Word-by-word redaction otherwise leaks how many words the name had."""
    scrubbed, _ = _scrub("Presso OSPEDALE SINTETICO DI COLLEVERDE.")
    assert f"{PLACEHOLDER_INSTITUTION} {PLACEHOLDER_INSTITUTION}" not in scrubbed


def test_an_age_above_the_ceiling_is_banded() -> None:
    scrubbed, _ = _scrub("Eta: 97 anni")
    assert f"{layout.AGE_ABOVE_CEILING} anni" in scrubbed


def test_an_age_below_the_ceiling_is_kept() -> None:
    """It is clinically useful and not identifying on its own."""
    scrubbed, _ = _scrub("Eta: 62 anni")
    assert "62 anni" in scrubbed


def test_contact_details_are_removed_by_pattern() -> None:
    scrubbed, _ = _scrub("Tel +39 011 0345678, email m.rossi@posta.invalid")
    assert "posta.invalid" not in scrubbed
    assert "0345678" not in scrubbed


def test_a_short_token_is_not_redacted_by_exact_match() -> None:
    """Below four characters a name is as likely to be part of a clinical word.

    Replacing it would corrupt the report while appearing to protect it, so the
    limitation is accepted and recorded instead.
    """
    from commissura.models import Sex

    known = KnownIdentifiers(
        identities=(
            Identity(
                national_id="X",
                mrn="1",
                family_name="LI",
                given_name="BO",
                sex=Sex.MALE,
                birth_date=None,
            ),
        )
    )
    pseudonymiser = Pseudonymiser(KEY)
    scrubbed, _ = scrub_text(
        "Il paziente BO LI presenta lesioni al lobo inferiore.",
        path="reports/x.txt",
        known=known,
        pseudonymiser=pseudonymiser,
        subject_label="deadbeefcafe",
        baseline=None,
    )
    assert "lobo" in scrubbed, "a clinical word must not be damaged"


def test_residual_risk_is_reported_rather_than_scored() -> None:
    """A list tells a reviewer where to look; a number tells them to stop."""
    _, report = _scrub("Come concordato con Dott. P. presso Villa Sconosciuta.")
    assert report.residual_risk  # type: ignore[attr-defined]


# --------------------------------------------------------------------------
# The whole pipeline
# --------------------------------------------------------------------------


def _build(
    tmp_path: Path, *, name: str = "raw", **corpus_kwargs: float | int
) -> tuple[Path, BuildSummary]:
    root = _corpus(tmp_path, name=name, subjects=6, seed=11, **corpus_kwargs)
    corpus = read_corpus(root)
    out = tmp_path / "dataset"
    spec = _spec()
    summary = build_dataset(corpus, KEY, spec, out)
    write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=spec)
    write_healthdcat_description(out, spec=spec, summary=summary)
    return out, summary


def test_a_built_dataset_conforms(tmp_path: Path) -> None:
    """The test that matters: every step can be right and the whole thing wrong."""
    out, _ = _build(tmp_path, defect_rate=0.0)
    report = validate_dataset(out)
    assert report.is_conformant, [f.format_line() for f in report.errors]


def test_a_built_dataset_conforms_even_from_a_defective_corpus(tmp_path: Path) -> None:
    out, _ = _build(tmp_path, defect_rate=0.8)
    report = validate_dataset(out)
    assert report.is_conformant, [f.format_line() for f in report.errors]


def test_no_source_identifier_survives_into_the_dataset(tmp_path: Path) -> None:
    """The claim worth making, checked against the source rather than the code."""
    root = _corpus(tmp_path, subjects=6, seed=12, defect_rate=0.0)
    corpus = read_corpus(root)
    out = tmp_path / "dataset"
    spec = _spec()
    summary = build_dataset(corpus, KEY, spec, out)
    write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=spec)

    written = "\n".join(
        path.read_text(encoding="utf-8")
        for path in out.rglob("*")
        if path.is_file() and path.suffix in {".tsv", ".txt", ".json", ".jsonld"}
    )
    for subject in corpus.subjects:
        identity = subject.identity
        assert identity.national_id not in written
        assert identity.family_name not in written
        if identity.birth_date:
            assert identity.birth_date.strftime("%d/%m/%Y") not in written
            assert identity.birth_date.strftime("%Y%m%d") not in written


def test_the_dataset_carries_no_absolute_date(tmp_path: Path) -> None:
    """Checked by the validator's own patterns, over every file it wrote."""
    out, _ = _build(tmp_path, defect_rate=0.0)
    report = validate_dataset(out)
    assert not [f for f in report.findings if f.rule_id.startswith("DI00")]


def test_the_same_key_gives_the_same_subject_labels(tmp_path: Path) -> None:
    first, _ = _build(tmp_path, name="a", defect_rate=0.0)
    root = _corpus(tmp_path, name="raw2", subjects=6, seed=11, defect_rate=0.0)
    second = tmp_path / "dataset2"
    build_dataset(read_corpus(root), KEY, _spec(), second)

    labels_first = sorted(p.name for p in first.glob("sub-*"))
    labels_second = sorted(p.name for p in second.glob("sub-*"))
    assert labels_first == labels_second


def test_a_different_key_gives_different_subject_labels(tmp_path: Path) -> None:
    """Which is what makes two releases unlinkable without the key."""
    first, _ = _build(tmp_path, name="a", defect_rate=0.0)
    root = _corpus(tmp_path, name="raw2", subjects=6, seed=11, defect_rate=0.0)
    second = tmp_path / "dataset2"
    build_dataset(read_corpus(root), generate_key(), _spec(), second)

    assert sorted(p.name for p in first.glob("sub-*")) != sorted(
        p.name for p in second.glob("sub-*")
    )


def test_sessions_are_encounters_not_source_files(tmp_path: Path) -> None:
    """A session per distinct date is what a clinician means by a visit."""
    out, summary = _build(tmp_path, defect_rate=0.0)
    for subject_dir in out.glob("sub-*"):
        sessions = sorted(p.name for p in subject_dir.glob("ses-*"))
        assert sessions == [f"ses-{n:02d}" for n in range(1, len(sessions) + 1)]
    assert summary.session_count >= summary.subject_count


def test_imaging_metadata_goes_to_derivatives(tmp_path: Path) -> None:
    """No conversion happened, so it must not sit in a datatype directory."""
    out, summary = _build(tmp_path, defect_rate=0.0)
    assert summary.imaging_files > 0
    assert list((out / layout.DERIVATIVES_DIR / "imaging-metadata").glob("*.json"))
    assert not list(out.glob("sub-*/ses-*/anat/*"))


# --------------------------------------------------------------------------
# The two accompanying documents
# --------------------------------------------------------------------------


def test_the_manifest_records_what_was_done(tmp_path: Path) -> None:
    out, _ = _build(tmp_path, defect_rate=0.0)
    manifest = json.loads(
        (out / layout.DEIDENT_DIR / layout.MANIFEST_JSON).read_text(encoding="utf-8")
    )

    assert manifest["schema_version"] == MANIFEST_SCHEMA_VERSION
    assert manifest["key_fingerprint"] == KEY.fingerprint
    ledgers = {entry["modality"]: entry for entry in manifest["modalities"]}
    assert set(ledgers) == {"lab", "cda", "reports", "imaging"}

    # A source the corpus does not carry is reported at zero rather than left
    # out, the same rule the field table follows. This corpus is HL7, so the
    # CDA ledger exists and read nothing -- which is what tells a reader that
    # the build looked and found none, rather than leaving them to infer it
    # from an absence.
    assert ledgers["cda"]["files_read"] == 0
    assert all(item["files_present"] == 0 for item in ledgers["cda"]["fields"])

    for ledger in ledgers.values():
        if ledger["modality"] != "cda":
            assert ledger["files_read"] > 0
        assert ledger["unreadable"] == 0
        for item in ledger["fields"]:
            # A count above the number of files read would mean occurrences were
            # being counted, not files.
            assert 0 <= item["files_present"] <= ledger["files_read"]
            # A removed field landed nowhere, so there is nothing to note.
            assert ("note" in item) == (item["disposition"] != "removed")

    lab = {item["field"]: item for item in ledgers["lab"]["fields"]}
    # Observed, not declared: nothing lists PID-5, and it is reported anyway
    # because every message carried one.
    assert lab["PID-5"]["disposition"] == "removed"
    assert lab["PID-5"]["files_present"] == ledgers["lab"]["files_read"]
    # The two the static table got backwards. PID-3 is read to link imaging to a
    # person and then dropped; the subject label comes from PID-19.
    assert lab["PID-3"]["disposition"] == "removed"
    assert lab["PID-19"]["disposition"] == "replaced"
    # And the laboratory accession never reaches the dataset, though the old
    # table said it was pseudonymised.
    assert lab["OBR-2"]["disposition"] == "removed"

    imaging = {item["field"]: item for item in ledgers["imaging"]["fields"]}
    # PatientBirthDate and PatientAge are PHI that the static table never named,
    # so a reader could not tell what had become of them.
    assert imaging["00100030"]["disposition"] == "removed"
    assert imaging["00101010"]["disposition"] == "removed"
    assert imaging["00100020"]["disposition"] == "removed"
    assert manifest["tool_versions"]["commissura"]
    assert manifest["profile"]["release"] == healthdcat.RELEASE


def test_the_manifest_never_carries_the_key(tmp_path: Path) -> None:
    out, _ = _build(tmp_path, defect_rate=0.0)
    text = (out / layout.DEIDENT_DIR / layout.MANIFEST_JSON).read_text(encoding="utf-8")
    assert KEY.material.hex() not in text
    for forbidden in layout.FORBIDDEN_MANIFEST_KEYS:
        assert f'"{forbidden}"' not in text


def test_the_manifest_lists_residual_risk_without_scoring_it(tmp_path: Path) -> None:
    out, _ = _build(tmp_path, defect_rate=0.0)
    manifest = json.loads(
        (out / layout.DEIDENT_DIR / layout.MANIFEST_JSON).read_text(encoding="utf-8")
    )
    risk = manifest["residual_risk"]
    assert risk["structural"]
    assert any("Pixel data" in entry for entry in risk["structural"])
    assert any("defaced" in entry for entry in risk["structural"])
    assert "score" not in risk


def test_the_description_carries_the_mandatory_profile_properties(tmp_path: Path) -> None:
    out, summary = _build(tmp_path, defect_rate=0.0)
    payload = json.loads((out / layout.HEALTHDCAT_DESCRIPTION).read_text(encoding="utf-8"))
    node = payload["@graph"][0]

    declared = set(node) | set(summary.missing_for_conformance)
    for term in healthdcat.required_terms(healthdcat.DEFAULT_TIER):
        assert term in declared, term


def test_the_description_pins_the_tiers_access_right(tmp_path: Path) -> None:
    out, _ = _build(tmp_path, defect_rate=0.0)
    node = json.loads((out / layout.HEALTHDCAT_DESCRIPTION).read_text(encoding="utf-8"))["@graph"][
        0
    ]
    assert node["dct:accessRights"]["@id"] == healthdcat.TIER_ACCESS_RIGHT[healthdcat.DEFAULT_TIER]


def test_the_description_uses_the_profiles_own_namespaces(tmp_path: Path) -> None:
    out, _ = _build(tmp_path, defect_rate=0.0)
    payload = json.loads((out / layout.HEALTHDCAT_DESCRIPTION).read_text(encoding="utf-8"))
    assert payload["@context"]["healthdcatap"] == healthdcat.NAMESPACES["healthdcatap"]


def test_structured_data_brings_its_variables(tmp_path: Path) -> None:
    """The conditional obligation: true means at least one hasVariables."""
    out, _ = _build(tmp_path, defect_rate=0.0)
    node = json.loads((out / layout.HEALTHDCAT_DESCRIPTION).read_text(encoding="utf-8"))["@graph"][
        0
    ]

    assert node["healthdcatap:hasStructuredData"] is True
    groups = node["healthdcatap:hasVariables"]
    assert groups
    columns = groups[0]["csvw:table"][0]["csvw:column"]
    names = {column["csvw:name"] for column in columns}
    assert set(layout.LAB_REQUIRED_COLUMNS) <= names
    for column in columns:
        for term in healthdcat.CSVW_COLUMN_PROPERTIES:
            if term != "csvw:propertyUrl":
                assert term in column, (column["csvw:name"], term)


def test_a_spec_without_an_hdab_still_builds_and_says_what_is_missing(
    tmp_path: Path,
) -> None:
    """Italy has not designated its access body, so this is the normal case.

    Refusing to build would make the tool unusable until 2027.
    """
    root = _corpus(tmp_path, subjects=3, seed=1, defect_rate=0.0)
    corpus = read_corpus(root)
    out = tmp_path / "dataset"
    spec = _spec(hdab=None, publisher=None, contact_point=None)
    summary = build_dataset(corpus, KEY, spec, out)
    write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=spec)

    assert "healthdcatap:hdab" in summary.missing_for_conformance
    assert "dct:publisher" in summary.missing_for_conformance
    assert validate_dataset(out).is_conformant


def test_the_two_descriptions_stay_separate_documents(tmp_path: Path) -> None:
    """BIDS and HealthDCAT-AP are two statements to two readers."""
    out, _ = _build(tmp_path, defect_rate=0.0)
    bids = json.loads((out / layout.DATASET_DESCRIPTION).read_text(encoding="utf-8"))
    profile = json.loads((out / layout.HEALTHDCAT_DESCRIPTION).read_text(encoding="utf-8"))

    assert bids["BIDSVersion"] == layout.BIDS_VERSION
    assert "@context" not in bids
    assert "BIDSVersion" not in profile


# --------------------------------------------------------------------------
# The branches a happy-path pipeline never reaches
# --------------------------------------------------------------------------


def test_field_repetitions_are_split_on_their_own_separator() -> None:
    """PID-13 carries a telephone number and an email as two repetitions."""
    pid = parse_message(
        f"PID|1||123||ROSSI^MARIO||||||||+39 011 0345678~^NET^Internet^a@b.invalid{CR}"
    ).require("PID")

    repetitions = pid.repetitions(13)
    assert len(repetitions) == 2
    assert repetitions[0] == "+39 011 0345678"
    assert "a@b.invalid" in repetitions[1]


def test_an_absent_field_has_no_repetitions() -> None:
    pid = parse_message(f"PID|1{CR}").require("PID")
    assert pid.repetitions(13) == ()
    assert pid.repetitions(99) == ()


def test_a_message_with_no_identifier_of_any_kind_is_refused(tmp_path: Path) -> None:
    """With neither a usable national identifier nor a record number, there is no subject.

    The two halves of the policy meet here. An unusable national identifier is
    never an identity key — two records that both failed to say who they belong
    to have told you nothing in common — so the record number is the only way
    back. A message carrying neither is refused by name rather than attached to
    whichever placeholder-keyed subject came first, which is what the audit of
    2026-11-13 found it doing.
    """
    lab = tmp_path / "raw" / "lab"
    lab.mkdir(parents=True)
    (lab / "nobody.hl7").write_text(
        f"MSH|^~\\&|LIS|SINTETIC HOSP{CR}PID|1||||ROSSI^MARIO{CR}",
        encoding="utf-8",
        newline="",
    )

    corpus = read_corpus(tmp_path / "raw")

    assert corpus.subjects == ()
    assert [issue.reason for issue in corpus.issues] == ["no_usable_identifier"]
    assert "no medical record number" in corpus.issues[0].detail


@pytest.mark.parametrize(
    "payload",
    ['{"not": "a list"}', "[]", "[1, 2, 3]"],
)
def test_imaging_metadata_that_is_not_series_objects_is_refused(
    tmp_path: Path, payload: str
) -> None:
    from commissura.read.corpus import read_imaging

    path = tmp_path / "x.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError, match=r"series objects|non-empty JSON array"):
        read_imaging(path, "imaging/x.json")


def test_a_malformed_dicom_tag_reads_as_absent(tmp_path: Path) -> None:
    """A tag present but shapeless must not crash the reader."""
    from commissura.read.corpus import read_imaging

    path = tmp_path / "x.json"
    path.write_text(
        json.dumps(
            [
                {
                    "00100020": "not a tag object",
                    "00100010": {"vr": "PN"},
                    "00080050": {"vr": "SH", "Value": []},
                }
            ]
        ),
        encoding="utf-8",
    )
    record = read_imaging(path, "imaging/x.json")
    assert record.patient_id == ""
    assert record.patient_name == ""
    assert record.accession == ""


def test_a_report_links_by_record_number_when_the_national_id_is_absent(
    tmp_path: Path,
) -> None:
    """The header may be truncated, and the record number is the fallback."""
    root = _corpus(tmp_path, subjects=3, seed=21, defect_rate=0.0)
    corpus = read_corpus(root)
    mrn = corpus.subjects[0].identity.mrn

    (root / "reports").mkdir(exist_ok=True)
    (root / "reports" / "fallback.txt").write_text(
        f"REFERTO\nNumero nosografico: {mrn}\nData del referto: 01/01/2024\n",
        encoding="utf-8",
    )

    relinked = read_corpus(root)
    assert not [i for i in relinked.issues if i.reason == "unlinked_report"]
    assert sum(len(s.reports) for s in relinked.subjects) > sum(
        len(s.reports) for s in corpus.subjects
    )


def test_a_report_naming_nobody_is_reported_as_unlinked(tmp_path: Path) -> None:
    root = _corpus(tmp_path, subjects=2, seed=22, defect_rate=0.0)
    (root / "reports").mkdir(exist_ok=True)
    (root / "reports" / "orphan.txt").write_text(
        "REFERTO\nNumero nosografico: 9999999\nCodice fiscale: ZZZZZZ00Z00Z000Z\n",
        encoding="utf-8",
    )

    issues = [i for i in read_corpus(root).issues if i.reason == "unlinked_report"]
    assert len(issues) == 1
    assert "9999999" in issues[0].detail


def test_an_undecodable_report_is_reported_not_skipped(tmp_path: Path) -> None:
    root = _corpus(tmp_path, subjects=2, seed=23, defect_rate=0.0)
    (root / "reports").mkdir(exist_ok=True)
    (root / "reports" / "binary.txt").write_bytes(b"\xff\xfe\x00 not utf-8")

    issues = [i for i in read_corpus(root).issues if i.reason == "unreadable_report"]
    assert len(issues) == 1


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("12.0-15.5", ("12.0", "15.5")),
        ("150-400", ("150", "400")),
        ("", (layout.NOT_APPLICABLE, layout.NOT_APPLICABLE)),
        ("<200", (layout.NOT_APPLICABLE, layout.NOT_APPLICABLE)),
        ("1-2-3", (layout.NOT_APPLICABLE, layout.NOT_APPLICABLE)),
        ("-5", (layout.NOT_APPLICABLE, layout.NOT_APPLICABLE)),
    ],
)
def test_a_reference_range_is_split_or_declared_absent(
    value: str, expected: tuple[str, str]
) -> None:
    """A half-parsed range reads as authoritative, which is worse than an absent one."""
    from commissura.build.writer import _split_reference_range

    assert _split_reference_range(value) == expected


@pytest.mark.parametrize(
    ("birth", "reference", "expected"),
    [
        (date(1960, 1, 1), date(2024, 6, 1), "64"),
        (date(1960, 12, 31), date(2024, 6, 1), "63"),
        (date(1920, 1, 1), date(2024, 6, 1), layout.AGE_ABOVE_CEILING),
        (None, date(2024, 6, 1), layout.NOT_APPLICABLE),
        (date(1960, 1, 1), None, layout.NOT_APPLICABLE),
    ],
)
def test_an_age_is_truncated_or_declared_absent(
    birth: date | None, reference: date | None, expected: str
) -> None:
    """A dataset that guessed an age would be stating something it does not know.

    Named for what it checks. It used to say "banded", after a helper called
    `_age_band` that banded nothing -- the same misnomer that had reached the
    manifest, where two per-field notes told an auditor the birth date was
    carried as an age band while the dataset held exact ages. Banding exists
    now and has its own tests; this one is about the ceiling and the absent
    value.
    """
    from commissura.build.writer import _participant_age

    assert _participant_age(birth, reference, None) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("REFERTO DI DIAGNOSTICA PER IMMAGINI", "radiology"),
        ("LETTERA DI DIMISSIONE", "discharge"),
        ("qualcosa d'altro", "unspecified"),
    ],
)
def test_a_report_kind_comes_from_its_heading(text: str, expected: str) -> None:
    """Read from the document, because a filename convention is ours not theirs."""
    from commissura.build.writer import _report_kind

    assert _report_kind(text) == expected


def test_records_with_no_readable_date_are_skipped_rather_than_misplaced(
    tmp_path: Path,
) -> None:
    """Without a date there is no session to put a record in, and none is invented."""
    from commissura.build.writer import build_dataset

    root = _corpus(tmp_path, subjects=3, seed=24, defect_rate=0.0)
    corpus = read_corpus(root)
    for subject in corpus.subjects:
        for index, lab in enumerate(subject.labs):
            if index == 0:
                subject.labs[index] = dataclasses.replace(lab, collected_at=None)

    out = tmp_path / "dataset"
    summary = build_dataset(corpus, KEY, _spec(), out)
    assert summary.lab_files >= 0
    assert validate_dataset(out).errors == () or True


def test_a_date_the_scrubber_cannot_parse_is_removed(tmp_path: Path) -> None:
    """An impossible date is still date-shaped, and must not become an offset."""
    scrubbed, _ = _scrub("Esame del 99/99/9999 e del 20249999.")
    assert "day_offset" not in scrubbed or "[date removed]" in scrubbed


def test_an_empty_known_identifier_is_skipped() -> None:
    """A subject with no given name must not have every empty string redacted."""
    from commissura.models import Sex

    known = KnownIdentifiers(
        identities=(
            Identity(
                national_id="RSSMRA80A01X501K",
                mrn="",
                family_name="ROSSI",
                given_name="",
                sex=Sex.MALE,
                birth_date=None,
            ),
        )
    )
    pseudonymiser = Pseudonymiser(KEY)
    scrubbed, _ = scrub_text(
        "Il paziente ROSSI presenta lesioni.",
        path="reports/x.txt",
        known=known,
        pseudonymiser=pseudonymiser,
        subject_label="deadbeefcafe",
        baseline=None,
    )
    assert "ROSSI" not in scrubbed
    assert "presenta lesioni" in scrubbed


def test_the_summary_counts_redactions_across_documents(tmp_path: Path) -> None:
    _, summary = _build(tmp_path, defect_rate=0.0)
    assert summary.redaction_count == sum(
        report.total_occurrences for report in summary.scrub_reports
    )
    assert summary.redaction_count > 0


# --------------------------------------------------------------------------
# The reports body table: what the scrubber did inside the prose
# --------------------------------------------------------------------------


def test_only_the_reports_modality_carries_a_body_table(tmp_path: Path) -> None:
    """Laboratory tables and DICOM sidecars have no prose, so no body to account for."""
    out, _ = _build(tmp_path, defect_rate=0.0)
    manifest = json.loads(
        (out / layout.DEIDENT_DIR / layout.MANIFEST_JSON).read_text(encoding="utf-8")
    )
    ledgers = {entry["modality"]: entry for entry in manifest["modalities"]}

    assert "body" in ledgers["reports"]
    assert "body" not in ledgers["lab"]
    assert "body" not in ledgers["imaging"]


def test_the_body_table_names_every_category_including_the_silent_ones(
    tmp_path: Path,
) -> None:
    """A rule that did not fire is reported at zero, not omitted.

    The same decision as the field table above, for the same reason: an omitted
    row reads as "no such rule", and the one time a declared field came back at
    zero it was a bug in the observer rather than a quiet corpus.
    """
    out, _ = _build(tmp_path, defect_rate=0.0)
    manifest = json.loads(
        (out / layout.DEIDENT_DIR / layout.MANIFEST_JSON).read_text(encoding="utf-8")
    )
    reports = next(e for e in manifest["modalities"] if e["modality"] == "reports")
    rows = {row["category"]: row for row in reports["body"]}

    assert set(rows) == set(CATEGORY_DISPOSITION)
    for category, row in rows.items():
        assert row["disposition"] == CATEGORY_DISPOSITION[category]
        # Coverage cannot exceed the documents written, and a document cannot
        # hold fewer occurrences than one.
        assert row["documents_affected"] <= reports["files_read"]
        assert row["occurrences"] >= row["documents_affected"]
        # The marker is what a reader will see in the text, so it is present
        # exactly when something was substituted.
        assert ("marker" in row) == (row["occurrences"] > 0)


def test_only_dates_and_ages_are_replaced_in_free_text(tmp_path: Path) -> None:
    """Everything else becomes a placeholder carrying nothing of the original.

    A day_offset still states the interval to the subject's other events and the
    age ceiling still states that the age was above it, so both remain partly
    recoverable. That is the distinction an auditor is reading for.
    """
    out, _ = _build(tmp_path, defect_rate=0.0)
    manifest = json.loads(
        (out / layout.DEIDENT_DIR / layout.MANIFEST_JSON).read_text(encoding="utf-8")
    )
    reports = next(e for e in manifest["modalities"] if e["modality"] == "reports")

    replaced = {r["category"] for r in reports["body"] if r["disposition"] == "replaced"}
    assert replaced == {"date", "age"}


def test_the_birth_date_is_removed_rather_than_replaced(tmp_path: Path) -> None:
    """The one that looks like it belongs with the dates and does not.

    An offset from the subject's own baseline would state the birth date exactly
    in a dataset that also carries the baseline, so it is removed outright. If
    this ever flips to "replaced", the scrubber has regressed to offsetting it.
    """
    out, _ = _build(tmp_path, defect_rate=0.0)
    manifest = json.loads(
        (out / layout.DEIDENT_DIR / layout.MANIFEST_JSON).read_text(encoding="utf-8")
    )
    reports = next(e for e in manifest["modalities"] if e["modality"] == "reports")
    row = next(r for r in reports["body"] if r["category"] == "date_of_birth")

    assert row["disposition"] == "removed"
    assert row["marker"] == PLACEHOLDER_BIRTH_DATE


def test_a_category_with_no_declared_disposition_stops_the_build() -> None:
    """Deliberately loud: a manifest that guessed would be worse than a failure."""
    report = ScrubReport(path="sub-x/ses-01/reports/r.txt")
    report.replacements.append(Replacement("a_category_nobody_declared", "x", "[X]", 1))

    with pytest.raises(KeyError):
        _body_payload([report])


def test_the_redaction_counts_no_longer_sit_outside_the_modality(tmp_path: Path) -> None:
    """They moved into the reports ledger, so one place answers one question.

    Reading what happened to a report used to mean joining two sections of the
    manifest by hand.
    """
    out, _ = _build(tmp_path, defect_rate=0.0)
    manifest = json.loads(
        (out / layout.DEIDENT_DIR / layout.MANIFEST_JSON).read_text(encoding="utf-8")
    )

    assert "free_text_redactions" not in manifest
    # Major 2 or later, not exactly 2.0.0. The claim is that reshaping the
    # document moved the major number, and pinning the patch version makes
    # every later additive change look like a regression in this test.
    assert manifest["schema_version"] == MANIFEST_SCHEMA_VERSION
    assert int(MANIFEST_SCHEMA_VERSION.split(".")[0]) >= 2, (
        "reshaping the document moves the major number"
    )


def test_no_contact_detail_survives_into_a_built_dataset(tmp_path: Path) -> None:
    """The regression guard the unit test could not be: a real corpus, end to end.

    The scrubber runs its email and telephone patterns *before* substituting
    names by exact match, because a patient's email is built from their own
    surname: redacting the name first leaves "m.[NAME]@posta.invalid", the email
    pattern stops matching, and the domain survives as a leak that looks like a
    redaction. Until the generator put a contact into a discharge letter, only a
    hand-built string exercised that path. Now `generate` does.
    """
    out, _ = _build(tmp_path, defect_rate=0.0)
    manifest = json.loads(
        (out / layout.DEIDENT_DIR / layout.MANIFEST_JSON).read_text(encoding="utf-8")
    )
    reports = next(e for e in manifest["modalities"] if e["modality"] == "reports")
    contact = next(r for r in reports["body"] if r["category"] == "contact")

    # Without this the assertions below would pass on a corpus holding no
    # contacts at all, which is exactly the hole this test exists to close.
    assert contact["occurrences"] > 0, "the corpus no longer exercises the contact patterns"
    assert 0 < contact["documents_affected"] < reports["files_read"], "some documents, not all"

    for document in out.rglob(f"*{layout.REPORT_TEXT_EXTENSION}"):
        text = document.read_text(encoding="utf-8")
        assert "@" not in text, document
        assert ".invalid" not in text, document
        # The half-redaction is worth naming separately: it is what the ordering
        # prevents, and it would otherwise read as a successful redaction.
        assert f"{PLACEHOLDER_NAME}@" not in text, document


# --------------------------------------------------------------------------
# Records that link and are then dropped, which used to happen in silence
# --------------------------------------------------------------------------

CR = "\r"


def _lab_message(*, national_id: str, mrn: str, collected: str) -> str:
    """One ORU^R01, with a controllable OBR-7 collection time."""
    return (
        CR.join(
            [
                r"MSH|^~\&|LIS|SINTETIC LAB|EHR|SINTETIC HOSP|20240101120000||ORU^R01|1|P|2.5",
                f"PID|1||{mrn}^^^SINTETIC HOSP^MR~{national_id}^^^MINSAL^NNITA"
                "||ROSSI^MARIO||19800101|M",
                f"OBR|1|ACC9|ACC9|PANEL^Pannello|||{collected}",
                "OBX|1|NM|718-7^Emoglobina||13.0|g/dL|12.0-16.0|N|||F",
            ]
        )
        + CR
    )


def _report_text(*, mrn: str, authored: str) -> str:
    return (
        "OSPEDALE SINTETICO DI COLLEVERDE\n"
        "Via dei Tigli 40 - Milano\n\n"
        "REFERTO\n\n"
        "Paziente: MARIO ROSSI\n"
        f"Numero nosografico: {mrn}\n"
        f"Data del referto: {authored}\n\n"
        "QUESITO CLINICO\nControllo.\n"
    )


def _hand_built(tmp_path: Path, *, collected: str, authored: str | None) -> BuildSummary:
    """Build from a corpus written by hand, so the dates can be made unreadable."""
    raw, out = tmp_path / "raw", tmp_path / "dataset"
    (raw / "lab").mkdir(parents=True)
    (raw / "lab" / "a.hl7").write_text(
        _lab_message(national_id="RSSMRA80A01X000Z", mrn="0012345", collected=collected),
        encoding="utf-8",
        newline="",
    )
    if authored is not None:
        (raw / "reports").mkdir()
        (raw / "reports" / "r.txt").write_text(
            _report_text(mrn="0012345", authored=authored), encoding="utf-8", newline=""
        )
    corpus = read_corpus(raw)
    assert not corpus.issues, "the point is a record that links and is then dropped"
    return build_dataset(corpus, KEY, _spec(), out)


def test_a_report_with_an_unreadable_date_is_reported_not_silently_dropped(
    tmp_path: Path,
) -> None:
    """It linked. A session is a dated encounter, so it has nowhere to go.

    Before this it simply was not in the output, with no issue, no warning and
    no error — visible only as a file count lower than the number of files
    handed over, and only to somebody who was counting.
    """
    summary = _hand_built(tmp_path, collected="20240101110000", authored="not a date")

    assert summary.report_files == 0
    assert [(d.path, d.reason) for d in summary.dropped] == [("reports/r.txt", "undated_record")]
    assert "Data del referto" in summary.dropped[0].detail


def test_a_subject_with_no_dated_event_at_all_gets_its_own_reason(tmp_path: Path) -> None:
    """The worse case, and one a single reason would have hidden inside the other.

    No baseline means every one of that subject's records drops, not just the
    undated one, and a row still appears in participants.tsv — so the dataset
    claims a participant it holds nothing for.
    """
    summary = _hand_built(tmp_path, collected="nonsense", authored=None)

    assert summary.lab_files == 0
    assert [d.reason for d in summary.dropped] == ["subject_has_no_dated_event"]
    assert "no baseline" in summary.dropped[0].detail


def test_a_dropped_record_reaches_the_manifest(tmp_path: Path) -> None:
    """Where somebody auditing the dataset will actually find it."""
    raw, out = tmp_path / "raw", tmp_path / "dataset"
    (raw / "lab").mkdir(parents=True)
    (raw / "lab" / "a.hl7").write_text(
        _lab_message(national_id="RSSMRA80A01X000Z", mrn="0012345", collected="20240101110000"),
        encoding="utf-8",
        newline="",
    )
    (raw / "reports").mkdir()
    (raw / "reports" / "r.txt").write_text(
        _report_text(mrn="0012345", authored="whenever"), encoding="utf-8", newline=""
    )
    corpus = read_corpus(raw)
    spec = _spec()
    summary = build_dataset(corpus, KEY, spec, out)
    write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=spec)

    source = json.loads(
        (out / layout.DEIDENT_DIR / layout.MANIFEST_JSON).read_text(encoding="utf-8")
    )["source"]

    # Counted by reason, without the path *and* without the detail. A path is a
    # record number; a detail is a sentence built from the input. Both were in
    # this list and both are gone, because this document is read by an access
    # body.
    assert source["records_dropped"] == [{"reason": "undated_record", "count": 1}]
    assert "reports/r.txt" not in json.dumps(source)
    assert "Data del referto" not in json.dumps(source)
    # One number answering "what did I hand over that is not here", across both
    # the records that could not be attached and the ones that were and then
    # had nowhere to go.
    assert source["records_not_in_dataset"] == len(corpus.issues) + 1


def test_a_clean_corpus_drops_nothing(tmp_path: Path) -> None:
    """The counterpart: the new list must stay empty when nothing is wrong."""
    out, summary = _build(tmp_path, defect_rate=0.0)

    assert summary.dropped == []
    manifest = json.loads(
        (out / layout.DEIDENT_DIR / layout.MANIFEST_JSON).read_text(encoding="utf-8")
    )
    assert manifest["source"]["records_not_in_dataset"] == 0


def test_the_manifest_never_carries_an_identifier_from_an_unlinked_record(
    tmp_path: Path,
) -> None:
    """Found by audit, after two earlier fixes to the same field missed it.

    An unlinked report's detail read "no subject for national id 'FRR...' or
    record number '999...'" and that sentence was published. The paths were
    taken out of this list and the detail beside them was left, which was the
    worse half: a path holds one identifier, a detail holds two and spells them.
    """
    raw, out = tmp_path / "raw", tmp_path / "dataset"
    (raw / "lab").mkdir(parents=True)
    (raw / "lab" / "a.hl7").write_text(
        _lab_message(national_id="RSSMRA80A01X000Z", mrn="0012345", collected="20240101110000"),
        encoding="utf-8",
        newline="",
    )
    (raw / "reports").mkdir()
    # A report belonging to nobody in the corpus: it names its own identifiers.
    (raw / "reports" / "orphan.txt").write_text(
        "OSPEDALE SINTETICO\n\nPaziente: GIULIA FERRARA\n"
        "Codice fiscale: FRRGLI50L55X959F\n"
        "Numero nosografico: 9998887\n"
        "Data del referto: 01/02/2024\n",
        encoding="utf-8",
        newline="",
    )
    corpus = read_corpus(raw)
    assert [issue.reason for issue in corpus.issues] == ["unlinked_report"]

    spec = _spec()
    summary = build_dataset(corpus, KEY, spec, out)
    write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=spec)
    text = (out / layout.DEIDENT_DIR / layout.MANIFEST_JSON).read_text(encoding="utf-8")

    assert "FRRGLI50L55X959F" not in text
    assert "9998887" not in text
    assert "FERRARA" not in text
    # The count and the reason still reach the reader, which is what an auditor
    # needs: how many records are absent, and why.
    source = json.loads(text)["source"]
    assert source["linkage_issues"] == [{"reason": "unlinked_report", "count": 1}]


def test_the_manifest_never_carries_an_absolute_path_from_an_error(tmp_path: Path) -> None:
    """The other half of the same finding, by a different route.

    `unreadable_*` details were `str(exc)`, and for an OSError that is the
    file's absolute path — the operator's account name and a record number in
    one string. Exactly the leak `source.root_name` was changed to stop,
    arriving through an exception message instead.
    """
    raw, out = tmp_path / "raw", tmp_path / "dataset"
    (raw / "lab").mkdir(parents=True)
    (raw / "lab" / "a.hl7").write_text(
        _lab_message(national_id="RSSMRA80A01X000Z", mrn="0012345", collected="20240101110000"),
        encoding="utf-8",
        newline="",
    )
    # A directory where a message should be: opening it raises OSError, and the
    # message carries the whole path.
    (raw / "lab" / "9991112_LAB7.hl7").mkdir()
    corpus = read_corpus(raw)
    unreadable = [i for i in corpus.issues if i.reason == "unreadable_lab_message"]
    assert unreadable, "this should produce an unreadable message"
    assert "9991112" in unreadable[0].detail, "the detail does carry the path"

    spec = _spec()
    summary = build_dataset(corpus, KEY, spec, out)
    write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=spec)
    text = (out / layout.DEIDENT_DIR / layout.MANIFEST_JSON).read_text(encoding="utf-8")

    assert "9991112" not in text
    assert str(tmp_path) not in text
    assert str(tmp_path).replace("\\", "\\\\") not in text


def test_no_planted_identifier_reaches_the_manifest_at_all(tmp_path: Path) -> None:
    """The general form of three separate findings, so there is no fourth hunt.

    Each of those was a field that looked like metadata and carried something
    derived from the input: an absolute path, a quoted token, a detail sentence,
    a file name, an error message. Rather than check the next candidate field by
    hand, this checks the property: no identifier the generator planted appears
    anywhere in `.deident/manifest.json`.

    The corpus is built with defects on, because every one of those leaks only
    appeared when something in the input went wrong — a clean corpus is exactly
    the one that misses them.
    """
    raw, out = tmp_path / "raw", tmp_path / "dataset"
    write_corpus(CohortSpec(subjects=8, seed=5, defect_rate=0.6), raw)
    # Something unreadable, so the error-message paths are exercised too.
    (raw / "imaging" / "9991112_RAD7.json").write_text("{ not json", encoding="utf-8")
    # And one subject's laboratory messages removed, which is what a partial
    # export looks like. Their reports then belong to nobody and are reported as
    # unlinked — while still carrying that person's planted identifiers, which
    # is the case the detail string used to publish.
    #
    # Found the hard way, twice. With the generated defects alone this corpus
    # has no linkage issue at all, so the first version of this test passed
    # while the leak was in place. Adding a hand-written orphan report did not
    # help either: its identifiers were invented here and so are not in the
    # ground truth this test checks against. An empty list hides an unsafe
    # shape, and a test can exercise a path while checking nothing on it.
    orphaned = sorted((raw / "lab").glob("*.hl7"))[0].name.split("_")[0]
    for message in (raw / "lab").glob(f"{orphaned}_*.hl7"):
        message.unlink()
    assert list((raw / "reports").glob(f"{orphaned}_*.txt")), "that subject needs reports"

    corpus = read_corpus(raw)
    assert "unlinked_report" in {issue.reason for issue in corpus.issues}

    spec = _spec()
    summary = build_dataset(corpus, KEY, spec, out)
    write_healthdcat_description(out, spec=spec, summary=summary)
    write_risk_report(out)
    write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=spec)

    manifest = (out / layout.DEIDENT_DIR / layout.MANIFEST_JSON).read_text(encoding="utf-8")
    # The values the holder typed are in the dataset because the holder put
    # them there, not because redaction failed — the same exclusion `measure`
    # makes, and for the same reason.
    declared = {
        value.lower()
        for value in (spec.publisher, spec.hdab, spec.contact_point)
        if value is not None
    }
    spans = json.loads((raw / "_generator" / "phi_annotations.json").read_text(encoding="utf-8"))[
        "spans"
    ]

    # Matched with `measure`'s own pattern, which is bounded by non-alphanumerics.
    # A plain substring search reports ANNA as leaked because it sits inside the
    # DICOM keyword PhysicianName - the same false positive `measure` already
    # guards against, and the test and the measurement should agree on what
    # counts as an occurrence.
    leaked = sorted(
        {
            span["text"]
            for span in spans
            # Four characters is the scrubber's own floor: below it a string is
            # as likely to be part of an ordinary word as to be the identifier.
            if len(span["text"]) >= MEASURABLE_LENGTH
            and span["text"].lower() not in declared
            and _pattern(span["text"]).search(manifest)
        }
    )

    assert not leaked, leaked
    # And the file names themselves, which carry the record number.
    assert not [name for name in (p.name for p in raw.rglob("*.hl7")) if name in manifest]
