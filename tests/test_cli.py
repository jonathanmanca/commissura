"""The command-line surface: exit codes, machine-readable output, argument validation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from commissura import __version__
from commissura.cli import app
from commissura.deident.keys import KEY_FILE_ENV_VAR, read_key_file
from commissura.deident.pseudonymise import RULE_VERSION

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
