"""The manifest describes this dataset, and never claims more than it can show.

The audit of 2026-11-13 found ``residual_risk.structural`` writing four fixed
prose strings into every manifest. One of them read "no k-anonymity report has
been produced for this dataset" while ``risk_report.json`` sat beside it in the
same directory, reporting ``minimum_k = 1``, digested into that same manifest's
integrity list. The document contradicted a file it authenticated.

The other three were true of the *method* and said nothing about the dataset.
``BurnedInAnnotation`` was warned about in identical words whether a dataset held
four flagged studies or none — and ``validate`` reported ``conforms`` with zero
warnings over one in which every study was flagged.

These tests pin the derived form: a limit that applies carries its own number,
and a limit that does not apply is not claimed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from commissura import layout
from commissura.build.manifest import write_healthdcat_description, write_manifest
from commissura.build.risk import write_risk_report
from commissura.build.writer import BuildSpec, build_dataset
from commissura.deident.keys import SecretKey
from commissura.generate.cohort import CohortSpec
from commissura.generate.writer import write_corpus
from commissura.read.corpus import read_corpus
from commissura.validate import validate_dataset

KEY = SecretKey(bytes(range(32)))


def _built(tmp_path: Path, *, subjects: int = 6, defect_rate: float = 0.0, seed: int = 42):  # type: ignore[no-untyped-def]
    """Build a dataset and return the pieces the manifest is assembled from."""
    raw, out = tmp_path / "raw", tmp_path / "dataset"
    write_corpus(CohortSpec(subjects=subjects, seed=seed, defect_rate=defect_rate), raw)
    corpus = read_corpus(raw)
    spec = BuildSpec(
        dataset_name="Synthetic dataset",
        description="For testing the manifest against.",
        hdab="Agenzia Sintetica",
        publisher="IRCCS SINTETICO MAREBIANCO",
        contact_point="dati@irccs-sintetico.invalid",
        access_url="https://portale-sintetico.invalid/permessi",
    )
    summary = build_dataset(corpus, KEY, spec, out)
    write_healthdcat_description(out, spec=spec, summary=summary)
    return corpus, summary, spec, out


def _structural(manifest: dict[str, object]) -> list[str]:
    residual = manifest["residual_risk"]
    assert isinstance(residual, dict)
    claims = residual["structural"]
    assert isinstance(claims, list)
    return [str(claim) for claim in claims]


# --------------------------------------------------------------------------
# The k-anonymity claim
# --------------------------------------------------------------------------


def test_the_manifest_does_not_deny_a_risk_report_it_digests(tmp_path: Path) -> None:
    """The contradiction, exactly as found.

    The manifest digests ``risk_report.json`` into its own integrity list and
    authenticates that list with ``manifest_hmac``, so denying the report's
    existence is a false statement about a file the same document vouches for.
    """
    corpus, summary, spec, out = _built(tmp_path)
    risk = write_risk_report(out)

    manifest = write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=spec, risk=risk)

    claims = " ".join(_structural(manifest))
    assert "no k-anonymity report" not in claims
    assert layout.RISK_REPORT_JSON in claims
    integrity = manifest["integrity"]
    assert isinstance(integrity, dict)
    files = integrity["files"]
    assert isinstance(files, dict)
    assert f"{layout.DEIDENT_DIR}/{layout.RISK_REPORT_JSON}" in files


def test_the_manifest_reports_the_k_the_report_computed(tmp_path: Path) -> None:
    """Describing the report rather than asserting about the method."""
    corpus, summary, spec, out = _built(tmp_path)
    risk = write_risk_report(out)

    manifest = write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=spec, risk=risk)

    claims = " ".join(_structural(manifest))
    assert f"minimum k is {risk['minimum_k']}" in claims
    assert f"threshold of {risk['threshold']}" in claims


def test_a_higher_k_is_reported_as_the_number_it_is(tmp_path: Path) -> None:
    """Not just the k=1 case: the sentence must carry whatever was computed.

    Supplied directly rather than engineered out of a cohort, because reaching
    k above one on age and sex needs a cohort this suite has no reason to
    generate — the arithmetic is in the README and is not what is under test.
    """
    corpus, summary, spec, out = _built(tmp_path)

    manifest = write_manifest(
        out,
        corpus=corpus,
        summary=summary,
        key=KEY,
        spec=spec,
        risk={
            "minimum_k": 7,
            "threshold": 5,
            "quasi_identifiers": ["age", "sex"],
            "combinations_below_threshold": [],
        },
    )

    claims = " ".join(_structural(manifest))
    assert "minimum k is 7" in claims
    assert "0 combination(s) below" in claims


def test_a_missing_risk_report_is_stated_in_those_words(tmp_path: Path) -> None:
    """Not-assessed and assessed-and-k-is-1 are different facts.

    Only one of them is reassuring, and a manifest that printed the same
    sentence for both would be hiding the difference.
    """
    corpus, summary, spec, out = _built(tmp_path)

    manifest = write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=spec)

    claims = " ".join(_structural(manifest))
    assert "no k-anonymity report was produced" in claims
    assert "minimum k" not in claims


def test_the_manifest_never_calls_the_assessment_a_certificate(tmp_path: Path) -> None:
    """The one way this section could do harm is by being read as a clearance."""
    corpus, summary, spec, out = _built(tmp_path)
    risk = write_risk_report(out)

    manifest = write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=spec, risk=risk)

    claims = " ".join(_structural(manifest))
    assert "not a certificate of anonymity" in claims


# --------------------------------------------------------------------------
# The imaging claims
# --------------------------------------------------------------------------


def test_burned_in_studies_are_counted_not_merely_warned_about(tmp_path: Path) -> None:
    """A warning that reads the same at four and at zero is not a measurement."""
    corpus, summary, spec, out = _built(tmp_path, subjects=6, defect_rate=1.0, seed=5)
    risk = write_risk_report(out)
    studies = sorted((out / "derivatives" / "imaging-metadata").glob("*.json"))
    flagged = sum(
        1
        for path in studies
        if json.loads(path.read_text(encoding="utf-8"))["burned_in_annotation"]
    )
    assert flagged, "this corpus should inject the burned-in defect"

    manifest = write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=spec, risk=risk)

    claims = " ".join(_structural(manifest))
    assert f"{flagged} of {len(studies)} studies" in claims


def test_a_dataset_with_no_imaging_makes_no_imaging_claim(tmp_path: Path) -> None:
    """A limit that does not apply is not claimed.

    A dataset of laboratory results and reports has no pixels to warn about and
    no skull to deface, and saying so anyway is how a reader learns to skim the
    section.
    """
    raw = tmp_path / "raw"
    write_corpus(CohortSpec(subjects=4, seed=3, defect_rate=0.0), raw)
    for path in (raw / "imaging").glob("*.json"):
        path.unlink()
    corpus = read_corpus(raw)
    spec = BuildSpec(dataset_name="d", description="d", hdab="H", publisher="P")
    out = tmp_path / "dataset"
    summary = build_dataset(corpus, KEY, spec, out)

    manifest = write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=spec)

    claims = " ".join(_structural(manifest))
    assert "Pixel data" not in claims
    assert "defaced" not in claims


def test_a_burned_in_dataset_does_not_validate_clean(tmp_path: Path) -> None:
    """``validate`` reported conforms with zero warnings over a dataset full of these."""
    corpus, summary, spec, out = _built(tmp_path, subjects=6, defect_rate=1.0, seed=5)
    write_risk_report(out)
    write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=spec)

    report = validate_dataset(out)

    warnings = [f for f in report.findings if f.rule_id == "DI009"]
    assert warnings, "DI009 did not fire on a dataset whose pixels carry text"
    assert all(finding.severity.value == "warning" for finding in warnings)


def test_a_clean_dataset_raises_no_pixel_warning(tmp_path: Path) -> None:
    """The other half: a rule that always fires is a rule nobody reads."""
    corpus, summary, spec, out = _built(tmp_path, subjects=4, defect_rate=0.0, seed=7)
    write_risk_report(out)
    write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=spec)

    report = validate_dataset(out)

    assert not [f for f in report.findings if f.rule_id == "DI009"]


# --------------------------------------------------------------------------
# What established each subject
# --------------------------------------------------------------------------


def test_the_manifest_says_what_established_each_subject(tmp_path: Path) -> None:
    """A subject keyed on a record number is not relinkable across institutions.

    Nothing else in the document would tell a reader which subjects those are,
    and an HDAB combining two holders' datasets needs to know.
    """
    corpus, summary, spec, out = _built(tmp_path)

    manifest = write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=spec)

    source = manifest["source"]
    assert isinstance(source, dict)
    counts = source["subject_keys"]
    assert counts == {"national_id": len(corpus.subjects), "scoped_record_number": 0}


def test_both_kinds_of_subject_key_are_reported_even_at_zero(tmp_path: Path) -> None:
    """The convention the field table established: an absent row reads as "no such thing"."""
    corpus, summary, spec, out = _built(tmp_path)

    manifest = write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=spec)

    source = manifest["source"]
    assert isinstance(source, dict)
    keys = source["subject_keys"]
    assert isinstance(keys, dict)
    assert sorted(keys) == ["national_id", "scoped_record_number"]


# --------------------------------------------------------------------------
# Through the build, after a withdrawal
# --------------------------------------------------------------------------


def test_the_manifest_is_consistent_after_a_withdrawal(tmp_path: Path) -> None:
    """Every count in the manifest must describe the dataset that was published.

    The withdrawal path is where a stale number would show: the manifest is
    rewritten from the new build, so a count carried over from the previous one
    would be a false statement about the dataset it is shipped with.
    """
    from typer.testing import CliRunner

    from commissura.cli import app

    runner = CliRunner()
    raw = tmp_path / "raw"
    write_corpus(CohortSpec(subjects=6, seed=11, defect_rate=0.0), raw)
    key_file = tmp_path / "k.key"
    key_file.write_text(bytes(range(32)).hex(), encoding="utf-8")
    argv = [
        "build",
        str(raw),
        "--out",
        str(tmp_path / "dataset"),
        "--key-file",
        str(key_file),
        "--hdab",
        "H",
        "--publisher",
        "P",
    ]
    assert runner.invoke(app, argv).exit_code == 0

    sorted(raw.glob("imaging/*.json"))[0].unlink()
    assert runner.invoke(app, argv).exit_code == 0

    manifest = json.loads(
        (tmp_path / "dataset" / layout.DEIDENT_DIR / layout.MANIFEST_JSON).read_text(
            encoding="utf-8"
        )
    )
    studies = list((tmp_path / "dataset" / "derivatives" / "imaging-metadata").glob("*.json"))
    claims = " ".join(_structural(manifest))

    assert f"of {len(studies)} studies" in claims
    assert manifest["schema_version"] == "5.0.0"


@pytest.mark.parametrize("field", ["modalities", "integrity", "residual_risk", "source"])
def test_the_manifest_keeps_its_sections(tmp_path: Path, field: str) -> None:
    """A guard on the shape, so a derived section cannot quietly vanish."""
    corpus, summary, spec, out = _built(tmp_path, subjects=3)

    manifest = write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=spec)

    assert field in manifest
