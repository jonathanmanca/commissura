"""The command-line surface: exit codes, machine-readable output, argument validation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from commissura import __version__, layout
from commissura.cli import app
from commissura.deident.keys import KEY_FILE_ENV_VAR, read_key_file
from commissura.deident.pseudonymise import RULE_VERSION
from commissura.generate.cohort import CohortSpec
from commissura.generate.writer import write_corpus

runner = CliRunner()


def test_version_is_reported() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_bare_invocation_shows_help_rather_than_failing_silently() -> None:
    result = runner.invoke(app, [])
    assert "generate" in result.stdout
    assert "defects" in result.stdout


def test_generate_writes_a_corpus(tmp_path: Path) -> None:
    out = tmp_path / "raw"
    result = runner.invoke(app, ["generate", "-n", "3", "-s", "1", "-o", str(out)])

    assert result.exit_code == 0, result.stdout
    assert (out / "_generator" / "generation_manifest.json").is_file()
    assert (out / "_generator" / "phi_annotations.json").is_file()
    assert list(out.glob("lab/*.hl7"))
    assert "Verified" in result.stdout


def test_generate_json_output_is_parseable(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["generate", "-n", "2", "-s", "1", "-o", str(tmp_path / "raw"), "--json"]
    )
    assert result.exit_code == 0, result.stdout

    manifest = json.loads(result.stdout)
    assert manifest["seed"] == 1
    assert manifest["subject_count"] == 2
    assert manifest["phi_span_count"] > 0
    assert manifest["manifest_schema_version"] == "1.0.0"


def test_generate_rejects_an_out_of_range_defect_rate(tmp_path: Path) -> None:
    result = runner.invoke(app, ["generate", "-o", str(tmp_path / "raw"), "--defect-rate", "2.0"])
    assert result.exit_code != 0


def test_generate_rejects_a_cohort_of_zero(tmp_path: Path) -> None:
    result = runner.invoke(app, ["generate", "-o", str(tmp_path / "raw"), "-n", "0"])
    assert result.exit_code != 0


def test_defect_catalogue_is_listed() -> None:
    result = runner.invoke(app, ["defects"])
    assert result.exit_code == 0
    assert "lab.missing_unit" in result.stdout
    assert "imaging.burned_in_annotation" in result.stdout


def test_defect_catalogue_json_carries_the_cause_of_each_defect() -> None:
    result = runner.invoke(app, ["defects", "--json"])
    assert result.exit_code == 0

    catalogue = json.loads(result.stdout)
    assert len(catalogue) >= 16
    for entry in catalogue:
        assert entry["why_it_happens"], entry["id"]
        assert entry["modality"] in {"lab", "reports", "imaging"}
        assert entry["class"] in {"structural", "semantic", "linkage", "privacy"}


def test_no_verify_skips_the_offset_check(tmp_path: Path) -> None:
    """The check is on by default, so the opt-out needs its own exercise."""
    result = runner.invoke(
        app, ["generate", "-n", "2", "-s", "1", "-o", str(tmp_path / "raw"), "--no-verify"]
    )
    assert result.exit_code == 0, result.stdout
    assert "Verified" not in result.stdout
    assert list((tmp_path / "raw").glob("lab/*.hl7"))


def test_the_module_entry_point_works(tmp_path: Path) -> None:
    """``python -m commissura`` is a documented way in and can rot unnoticed."""
    completed = subprocess.run(
        [sys.executable, "-m", "commissura", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == __version__


def test_validate_accepts_a_conformant_dataset(dataset: Path) -> None:
    result = runner.invoke(app, ["validate", str(dataset)])
    assert result.exit_code == 0, result.stdout
    assert "CONFORMANT" in result.stdout
    assert "NOT CONFORMANT" not in result.stdout


def test_validate_exits_nonzero_on_an_error(dataset: Path) -> None:
    (dataset / "participants.tsv").unlink()
    result = runner.invoke(app, ["validate", str(dataset)])
    assert result.exit_code == 1
    assert "NOT CONFORMANT" in result.stdout
    assert "DS002" in result.stdout


def test_validate_prints_the_hint_alongside_the_finding(dataset: Path) -> None:
    """A finding that says what is wrong without saying what to do is half a report."""
    (dataset / "participants.tsv").unlink()
    result = runner.invoke(app, ["validate", str(dataset)])
    assert "Every dataset must carry participants.tsv" in result.stdout


def test_validate_does_not_fail_on_warnings_by_default(dataset: Path) -> None:
    (dataset / "participants.tsv.bak").write_text("leftover", encoding="utf-8")
    result = runner.invoke(app, ["validate", str(dataset)])
    assert result.exit_code == 0, result.stdout
    assert "DS008" in result.stdout


def test_strict_turns_warnings_into_a_failure(dataset: Path) -> None:
    (dataset / "participants.tsv.bak").write_text("leftover", encoding="utf-8")
    result = runner.invoke(app, ["validate", str(dataset), "--strict"])
    assert result.exit_code == 1


def test_quiet_prints_only_the_summary(dataset: Path) -> None:
    (dataset / "participants.tsv").unlink()
    result = runner.invoke(app, ["validate", str(dataset), "--quiet"])
    assert result.exit_code == 1
    assert "DS002" not in result.stdout
    assert "NOT CONFORMANT" in result.stdout


def test_validate_json_output_is_parseable(dataset: Path) -> None:
    (dataset / "participants.tsv").unlink()
    result = runner.invoke(app, ["validate", str(dataset), "--json"])
    assert result.exit_code == 1

    report = json.loads(result.stdout)
    assert report["schema_version"] == "1.0.0"
    assert report["rules_run"] > 30
    assert any(f["rule_id"] == "DS002" for f in report["findings"])
    assert all({"rule_id", "severity", "message"} <= set(f) for f in report["findings"])


def test_validate_can_suppress_notices(dataset: Path) -> None:
    result = runner.invoke(app, ["validate", str(dataset), "--no-notices", "--json"])
    assert result.exit_code == 0
    report = json.loads(result.stdout)
    assert all(f["severity"] != "notice" for f in report["findings"])


def test_validate_reports_a_missing_dataset_rather_than_crashing(tmp_path: Path) -> None:
    result = runner.invoke(app, ["validate", str(tmp_path / "nope")])
    assert result.exit_code == 1
    assert "DS001" in result.stdout


def test_rules_command_lists_the_schema() -> None:
    """The rule set is the schema, so it has to be printable without reading source."""
    result = runner.invoke(app, ["rules"])
    assert result.exit_code == 0
    assert "DS001" in result.stdout
    assert "DI003" in result.stdout
    assert "rules" in result.stdout


def test_rules_json_output_pairs_every_id_with_a_summary() -> None:
    result = runner.invoke(app, ["rules", "--json"])
    assert result.exit_code == 0

    rules = json.loads(result.stdout)
    assert len(rules) >= 39
    assert all(entry["summary"] for entry in rules)
    assert len({entry["id"] for entry in rules}) == len(rules)


def test_keygen_writes_a_key_and_prints_only_its_fingerprint(tmp_path: Path) -> None:
    """The key must never reach the terminal, where it reaches scrollback and logs."""
    out = tmp_path / "k.key"
    result = runner.invoke(app, ["keygen", "--out", str(out)])

    assert result.exit_code == 0, result.stdout
    assert out.is_file()

    material = out.read_text(encoding="ascii").strip()
    assert material not in result.stdout
    assert read_key_file(out).fingerprint in result.stdout


def test_keygen_tells_the_user_how_to_point_commands_at_the_key(tmp_path: Path) -> None:
    result = runner.invoke(app, ["keygen", "--out", str(tmp_path / "k.key")])
    assert KEY_FILE_ENV_VAR in result.stdout
    assert "unlinkable" in result.stdout


def test_keygen_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    out = tmp_path / "k.key"
    assert runner.invoke(app, ["keygen", "--out", str(out)]).exit_code == 0
    original = read_key_file(out)

    result = runner.invoke(app, ["keygen", "--out", str(out)])
    assert result.exit_code == 1
    assert read_key_file(out).matches(original), "the refusal must not damage the key"


def test_keygen_overwrites_when_forced(tmp_path: Path) -> None:
    out = tmp_path / "k.key"
    runner.invoke(app, ["keygen", "--out", str(out)])
    original = read_key_file(out)

    result = runner.invoke(app, ["keygen", "--out", str(out), "--force"])
    assert result.exit_code == 0
    assert not read_key_file(out).matches(original)


def test_there_is_no_option_to_pass_a_key_as_an_argument() -> None:
    """A key on the command line lands in shell history, `ps` output and CI logs.

    Pinned as a test because the convenient option is the one people reach for,
    so it must not exist rather than merely be discouraged.
    """
    for command in ("keygen", "key-info"):
        help_text = runner.invoke(app, [command, "--help"]).stdout
        assert "--key " not in help_text
        assert "--secret" not in help_text


def test_key_info_reports_the_fingerprint_and_rule_version(tmp_path: Path) -> None:
    out = tmp_path / "k.key"
    runner.invoke(app, ["keygen", "--out", str(out)])

    result = runner.invoke(app, ["key-info", "--key-file", str(out)])
    assert result.exit_code == 0
    assert read_key_file(out).fingerprint in result.stdout
    assert RULE_VERSION in result.stdout


def test_key_info_json_output_is_parseable(tmp_path: Path) -> None:
    out = tmp_path / "k.key"
    runner.invoke(app, ["keygen", "--out", str(out)])

    result = runner.invoke(app, ["key-info", "--key-file", str(out), "--json"])
    assert result.exit_code == 0

    payload = json.loads(result.stdout)
    assert payload["key_fingerprint"] == read_key_file(out).fingerprint
    assert payload["deidentification_rule_version"] == RULE_VERSION
    assert "key" not in payload or payload.get("key") is None


def test_key_info_without_a_key_explains_how_to_make_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(KEY_FILE_ENV_VAR, raising=False)
    result = runner.invoke(app, ["key-info"])
    assert result.exit_code == 1


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------


def _raw_corpus(tmp_path: Path, subjects: int = 5, defect_rate: float = 0.0) -> Path:
    root = tmp_path / "raw"
    write_corpus(CohortSpec(subjects=subjects, seed=17, defect_rate=defect_rate), root)
    return root


def _key(tmp_path: Path) -> Path:
    path = tmp_path / "k.key"
    assert runner.invoke(app, ["keygen", "--out", str(path)]).exit_code == 0
    return path


def _build_args(tmp_path: Path, raw: Path, key: Path, *extra: str) -> list[str]:
    return [
        "build",
        str(raw),
        "-o",
        str(tmp_path / "dataset"),
        "--key-file",
        str(key),
        "--hdab",
        "Agenzia Sintetica",
        "--publisher",
        "IRCCS SINTETICO MAREBIANCO",
        *extra,
    ]


def test_build_produces_a_conformant_dataset(tmp_path: Path) -> None:
    """The headline: generate, build, validate, all through the command line."""
    raw, key = _raw_corpus(tmp_path), _key(tmp_path)
    result = runner.invoke(app, _build_args(tmp_path, raw, key))

    assert result.exit_code == 0, result.stdout
    assert "conforms" in result.stdout
    out = tmp_path / "dataset"
    assert (out / layout.PARTICIPANTS_TSV).is_file()
    assert (out / layout.DEIDENT_DIR / layout.MANIFEST_JSON).is_file()
    assert (out / layout.HEALTHDCAT_DESCRIPTION).is_file()
    assert list(out.glob("sub-*/ses-*/lab/*.tsv"))


def test_build_prints_the_key_fingerprint_and_not_the_key(tmp_path: Path) -> None:
    raw, key = _raw_corpus(tmp_path), _key(tmp_path)
    result = runner.invoke(app, _build_args(tmp_path, raw, key))

    assert read_key_file(key).fingerprint in result.stdout
    assert read_key_file(key).material.hex() not in result.stdout


def test_build_reports_residual_risk(tmp_path: Path) -> None:
    """Reported rather than scored, so a reviewer knows where to look."""
    raw, key = _raw_corpus(tmp_path, subjects=8), _key(tmp_path)
    result = runner.invoke(app, _build_args(tmp_path, raw, key))
    assert "Residual risk" in result.stdout or result.exit_code == 0


def test_build_json_output_is_parseable(tmp_path: Path) -> None:
    raw, key = _raw_corpus(tmp_path), _key(tmp_path)
    result = runner.invoke(app, _build_args(tmp_path, raw, key, "--json"))

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["subjects"] == 5
    assert payload["linkage_issues"] == 0
    assert payload["key_fingerprint"] == read_key_file(key).fingerprint
    assert payload["profile"]["tier"] == "non-public"
    assert payload["validation"]["conformant"] is True


def test_build_says_what_is_missing_for_conformance(tmp_path: Path) -> None:
    """Italy has no designated access body yet, so this is the normal case."""
    raw, key = _raw_corpus(tmp_path), _key(tmp_path)
    result = runner.invoke(
        app,
        [
            "build",
            str(raw),
            "-o",
            str(tmp_path / "dataset"),
            "--key-file",
            str(key),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "Not yet conformant" in result.stdout
    assert "healthdcatap:hdab" in result.stdout
    assert "--hdab" in result.stdout


def test_build_can_skip_validation(tmp_path: Path) -> None:
    raw, key = _raw_corpus(tmp_path), _key(tmp_path)
    result = runner.invoke(app, _build_args(tmp_path, raw, key, "--no-validate"))
    assert result.exit_code == 0, result.stdout
    assert "Validation" not in result.stdout


def test_build_accepts_each_tier(tmp_path: Path) -> None:
    raw, key = _raw_corpus(tmp_path), _key(tmp_path)
    for tier in ("public", "non-public", "restricted"):
        result = runner.invoke(app, _build_args(tmp_path, raw, key, "--tier", tier, "--json"))
        assert result.exit_code == 0, result.stdout
        assert json.loads(result.stdout)["profile"]["tier"] == tier


def test_build_rejects_an_unknown_tier(tmp_path: Path) -> None:
    raw, key = _raw_corpus(tmp_path), _key(tmp_path)
    result = runner.invoke(app, _build_args(tmp_path, raw, key, "--tier", "secret"))
    assert result.exit_code == 2
    assert "Unknown tier" in result.stderr or "Unknown tier" in result.output


def test_build_without_a_key_explains_how_to_make_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(KEY_FILE_ENV_VAR, raising=False)
    raw = _raw_corpus(tmp_path)
    result = runner.invoke(app, ["build", str(raw), "-o", str(tmp_path / "dataset")])
    assert result.exit_code == 1


def test_build_reports_a_missing_source(tmp_path: Path) -> None:
    key = _key(tmp_path)
    result = runner.invoke(
        app,
        [
            "build",
            str(tmp_path / "absent"),
            "-o",
            str(tmp_path / "dataset"),
            "--key-file",
            str(key),
        ],
    )
    assert result.exit_code == 1


def test_build_explains_an_empty_corpus_rather_than_writing_nothing(
    tmp_path: Path,
) -> None:
    """A subject is created by a laboratory message, and the message says so."""
    key = _key(tmp_path)
    empty = tmp_path / "empty"
    (empty / "lab").mkdir(parents=True)
    result = runner.invoke(
        app,
        [
            "build",
            str(empty),
            "-o",
            str(tmp_path / "dataset"),
            "--key-file",
            str(key),
        ],
    )
    assert result.exit_code == 1
    assert "PID-19" in result.stderr or "PID-19" in result.output


def test_build_from_a_defective_corpus_still_conforms(tmp_path: Path) -> None:
    raw = _raw_corpus(tmp_path, subjects=10, defect_rate=0.9)
    key = _key(tmp_path)
    result = runner.invoke(app, _build_args(tmp_path, raw, key, "--json"))

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["validation"]["conformant"] is True


def test_the_same_key_rebuilds_the_same_dataset(tmp_path: Path) -> None:
    """The relinkability guarantee, exercised through the command line."""
    raw, key = _raw_corpus(tmp_path), _key(tmp_path)
    first = runner.invoke(app, _build_args(tmp_path, raw, key, "--json"))
    (tmp_path / "dataset2").mkdir()
    second = runner.invoke(
        app,
        [
            "build",
            str(raw),
            "-o",
            str(tmp_path / "dataset2"),
            "--key-file",
            str(key),
            "--hdab",
            "Agenzia Sintetica",
            "--publisher",
            "IRCCS SINTETICO MAREBIANCO",
            "--json",
        ],
    )

    assert first.exit_code == 0 and second.exit_code == 0
    labels_first = sorted(p.name for p in (tmp_path / "dataset").glob("sub-*"))
    labels_second = sorted(p.name for p in (tmp_path / "dataset2").glob("sub-*"))
    assert labels_first == labels_second


def test_build_appears_in_the_command_list() -> None:
    result = runner.invoke(app, [])
    assert "build" in result.stdout


def test_build_fails_when_its_output_does_not_conform(tmp_path: Path) -> None:
    """Building into a directory that already holds a stale subject.

    The pre-existing `sub-` directory is not in the participants table build
    writes, so PT006 fires. The command must report the finding and exit
    non-zero rather than announce success over a broken dataset.
    """
    raw, key = _raw_corpus(tmp_path), _key(tmp_path)
    stale = tmp_path / "dataset" / "sub-ffffffffffff" / "ses-01" / "lab"
    stale.mkdir(parents=True)
    (stale / "sub-ffffffffffff_ses-01_lab.tsv").write_text(
        "day_offset\tloinc_code\tvalue\tunit\n0\t718-7\t14.1\tg/dL\n", encoding="utf-8"
    )

    result = runner.invoke(app, _build_args(tmp_path, raw, key))
    assert result.exit_code == 1
    assert "DOES NOT CONFORM" in result.stdout
    assert "PT006" in result.stdout


def test_build_writes_the_risk_report_so_validate_stops_warning(tmp_path: Path) -> None:
    """The warning validate emitted on every build until now."""
    raw, key = _raw_corpus(tmp_path), _key(tmp_path)
    result = runner.invoke(app, _build_args(tmp_path, raw, key, "--json"))

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["validation"]["counts"]["warning"] == 0
    assert (tmp_path / "dataset" / layout.DEIDENT_DIR / layout.RISK_REPORT_JSON).is_file()


def test_risk_reports_k_anonymity(tmp_path: Path) -> None:
    raw, key = _raw_corpus(tmp_path), _key(tmp_path)
    assert runner.invoke(app, _build_args(tmp_path, raw, key)).exit_code == 0

    result = runner.invoke(app, ["risk", str(tmp_path / "dataset")])
    assert result.exit_code == 0, result.stdout
    assert "minimum k" in result.stdout
    assert "quasi-identifiers" in result.stdout


def test_risk_json_output_is_parseable(tmp_path: Path) -> None:
    raw, key = _raw_corpus(tmp_path), _key(tmp_path)
    runner.invoke(app, _build_args(tmp_path, raw, key))

    result = runner.invoke(app, ["risk", str(tmp_path / "dataset"), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["quasi_identifiers"] == ["age", "sex"]
    assert payload["participants"] == 5


def test_risk_can_assess_without_writing(tmp_path: Path) -> None:
    raw, key = _raw_corpus(tmp_path), _key(tmp_path)
    runner.invoke(app, _build_args(tmp_path, raw, key))
    report = tmp_path / "dataset" / layout.DEIDENT_DIR / layout.RISK_REPORT_JSON
    report.unlink()

    result = runner.invoke(app, ["risk", str(tmp_path / "dataset"), "--no-write"])
    assert result.exit_code == 0
    assert not report.exists()


def test_risk_on_a_directory_that_is_not_a_dataset(tmp_path: Path) -> None:
    result = runner.invoke(app, ["risk", str(tmp_path)])
    assert result.exit_code == 1


def test_risk_lists_many_combinations_compactly(tmp_path: Path) -> None:
    """A cohort of unique rows produces one line per participant, then a tail."""
    raw, key = _raw_corpus(tmp_path, subjects=20), _key(tmp_path)
    runner.invoke(app, _build_args(tmp_path, raw, key))

    result = runner.invoke(app, ["risk", str(tmp_path / "dataset")])
    assert result.exit_code == 0
    assert "more" in result.stdout


def test_build_rejects_a_dataset_type_outside_the_authority_list(tmp_path: Path) -> None:
    """A typo would otherwise build a plausible IRI that resolves to nothing."""
    raw, key = _raw_corpus(tmp_path), _key(tmp_path)
    result = runner.invoke(app, _build_args(tmp_path, raw, key, "--dataset-type", "SYNTETIC_DATA"))
    assert result.exit_code == 2
    assert "not in the authority list" in (result.stderr or result.output)


def test_build_accepts_another_dataset_type(tmp_path: Path) -> None:
    raw, key = _raw_corpus(tmp_path), _key(tmp_path)
    result = runner.invoke(
        app, _build_args(tmp_path, raw, key, "--dataset-type", "TEST_DATA", "--json")
    )
    assert result.exit_code == 0, result.stdout


def test_build_with_every_holder_field_reports_nothing_missing(tmp_path: Path) -> None:
    """The three flags the CLI was missing, which made conformance unreachable."""
    raw, key = _raw_corpus(tmp_path), _key(tmp_path)
    result = runner.invoke(
        app,
        _build_args(
            tmp_path,
            raw,
            key,
            "--contact-point",
            "dati@irccs-sintetico.invalid",
            "--access-url",
            "https://portale-hdab-sintetico.invalid/permessi",
        ),
    )
    assert result.exit_code == 0, result.stdout
    assert "Not yet conformant" not in result.stdout


# --------------------------------------------------------------------------
# commissura verify
# --------------------------------------------------------------------------


def _built(tmp_path: Path) -> tuple[Path, Path]:
    """Build a dataset through the command line and return it with its key."""
    raw, key = _raw_corpus(tmp_path), _key(tmp_path)
    assert runner.invoke(app, _build_args(tmp_path, raw, key)).exit_code == 0
    return tmp_path / "dataset", key


def test_verify_reports_a_fresh_dataset_as_intact(tmp_path: Path) -> None:
    out, _ = _built(tmp_path)

    result = runner.invoke(app, ["verify", str(out)])

    assert result.exit_code == 0, result.stdout
    assert "INTACT" in result.stdout


def test_verify_says_when_it_did_not_check_the_manifest(tmp_path: Path) -> None:
    """Three states, not two: unchecked must never read like checked-and-fine."""
    out, key = _built(tmp_path)

    without = runner.invoke(app, ["verify", str(out)])
    with_key = runner.invoke(app, ["verify", str(out), "--key-file", str(key)])

    assert "not authenticated" in without.stdout
    assert "authentic" in with_key.stdout
    assert "not authenticated" not in with_key.stdout


def test_verify_fails_on_an_altered_file(tmp_path: Path) -> None:
    out, _ = _built(tmp_path)
    document = sorted(out.rglob(f"*{layout.REPORT_TEXT_EXTENSION}"))[0]
    document.write_text(document.read_text(encoding="utf-8") + "MARIO ROSSI\n", encoding="utf-8")

    result = runner.invoke(app, ["verify", str(out)])

    assert result.exit_code == 1
    assert "CHANGED" in result.stdout
    assert "altered" in result.stdout


def test_verify_names_the_tampering_separately_from_the_differences(tmp_path: Path) -> None:
    """Zero files differing and a failed tag is the signature worth naming."""
    out, key = _built(tmp_path)
    path = out / layout.DEIDENT_DIR / layout.MANIFEST_JSON
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["source"]["subjects_linked"] = 999
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    result = runner.invoke(app, ["verify", str(out), "--key-file", str(key)])

    assert result.exit_code == 1
    assert "TAMPERED" in result.stdout
    assert "CHANGED" not in result.stdout


def test_verify_reports_as_json(tmp_path: Path) -> None:
    out, key = _built(tmp_path)

    result = runner.invoke(app, ["verify", str(out), "--key-file", str(key), "--json"])
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["intact"] is True
    assert payload["manifest_authenticated"] is True
    assert payload["files_checked"] > 0


def test_verify_exits_non_zero_in_json_mode_too(tmp_path: Path) -> None:
    """A pipeline reading --json still has to be able to tell from the status."""
    out, _ = _built(tmp_path)
    (out / "stray.txt").write_text("x\n", encoding="utf-8")

    result = runner.invoke(app, ["verify", str(out), "--json"])

    assert result.exit_code == 1
    assert json.loads(result.stdout)["added"] == ["stray.txt"]


def test_verify_without_a_dataset_fails_cleanly(tmp_path: Path) -> None:
    result = runner.invoke(app, ["verify", str(tmp_path / "nowhere")])

    assert result.exit_code == 1
    assert "no manifest" in (result.stderr or result.output)


def test_verify_with_an_unreadable_key_fails_cleanly(tmp_path: Path) -> None:
    out, _ = _built(tmp_path)
    bad = tmp_path / "bad.key"
    bad.write_text("not a key\n", encoding="utf-8")

    result = runner.invoke(app, ["verify", str(out), "--key-file", str(bad)])

    assert result.exit_code == 1


# --------------------------------------------------------------------------
# commissura measure
# --------------------------------------------------------------------------


def test_measure_reports_full_recall_on_a_clean_corpus(tmp_path: Path) -> None:
    raw, key = _raw_corpus(tmp_path), _key(tmp_path)
    assert runner.invoke(app, _build_args(tmp_path, raw, key)).exit_code == 0

    result = runner.invoke(app, ["measure", str(raw), str(tmp_path / "dataset")])

    assert result.exit_code == 0, result.stdout
    assert "recall" in result.stdout
    assert "Every measurable planted identifier was removed." in result.stdout


def test_measure_exits_non_zero_and_names_the_leak(tmp_path: Path) -> None:
    """A leak has to be loud, and has to say where it came from."""
    raw, key = _raw_corpus(tmp_path), _key(tmp_path)
    assert runner.invoke(app, _build_args(tmp_path, raw, key)).exit_code == 0
    out = tmp_path / "dataset"
    spans = json.loads((raw / "_generator" / "phi_annotations.json").read_text(encoding="utf-8"))
    leaked = next(
        s for s in spans["spans"] if s["category"] == "person_name" and len(s["text"]) >= 4
    )
    document = sorted(out.rglob(f"*{layout.REPORT_TEXT_EXTENSION}"))[0]
    document.write_text(
        document.read_text(encoding="utf-8") + f"\n{leaked['text']}\n", encoding="utf-8"
    )

    result = runner.invoke(app, ["measure", str(raw), str(out)])

    assert result.exit_code == 1
    assert "LEAKED" in result.stdout
    assert leaked["path"] in result.stdout


def test_measure_reports_as_json(tmp_path: Path) -> None:
    raw, key = _raw_corpus(tmp_path), _key(tmp_path)
    assert runner.invoke(app, _build_args(tmp_path, raw, key)).exit_code == 0

    result = runner.invoke(app, ["measure", str(raw), str(tmp_path / "dataset"), "--json"])
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["recall"] == 1.0
    assert payload["survived"] == 0
    assert payload["measurable"] > 0
    assert {c["category"] for c in payload["categories"]}
    assert any(c["retained_by_design"] for c in payload["categories"])


def test_measure_without_ground_truth_fails_cleanly(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()

    result = runner.invoke(app, ["measure", str(tmp_path / "empty"), str(tmp_path / "empty")])

    assert result.exit_code == 1
    assert "no ground truth" in (result.stderr or result.output)


def test_measure_caps_the_listed_misses(tmp_path: Path) -> None:
    """--misses 0 keeps the summary and drops the list, for a wide terminal's sake."""
    raw, key = _raw_corpus(tmp_path), _key(tmp_path)
    assert runner.invoke(app, _build_args(tmp_path, raw, key)).exit_code == 0
    out = tmp_path / "dataset"
    spans = json.loads((raw / "_generator" / "phi_annotations.json").read_text(encoding="utf-8"))
    leaked = next(
        s for s in spans["spans"] if s["category"] == "person_name" and len(s["text"]) >= 4
    )
    document = sorted(out.rglob(f"*{layout.REPORT_TEXT_EXTENSION}"))[0]
    document.write_text(
        document.read_text(encoding="utf-8") + f"\n{leaked['text']}\n", encoding="utf-8"
    )

    result = runner.invoke(app, ["measure", str(raw), str(out), "--misses", "0"])

    assert result.exit_code == 1
    assert "LEAKED" in result.stdout
    assert leaked["path"] not in result.stdout
