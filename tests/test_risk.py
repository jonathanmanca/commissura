"""k-anonymity over the participant attributes."""

from __future__ import annotations

import json
from pathlib import Path

from commissura import layout
from commissura.build.risk import K_THRESHOLD, assess, write_risk_report


def _participants(root: Path, rows: list[list[str]], header: list[str] | None = None) -> None:
    columns = header or [layout.PARTICIPANT_ID_COLUMN, "age", "sex"]
    lines = ["\t".join(columns), *("\t".join(row) for row in rows)]
    root.mkdir(parents=True, exist_ok=True)
    (root / layout.PARTICIPANTS_TSV).write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_a_unique_combination_gives_k_of_one(tmp_path: Path) -> None:
    """The finding the command exists to surface: one row, one person."""
    _participants(tmp_path, [["sub-a", "64", "F"], ["sub-b", "71", "M"]])
    report = assess(tmp_path)

    assert report["minimum_k"] == 1
    assert len(report["combinations_below_threshold"]) == 2  # type: ignore[arg-type]


def test_shared_combinations_raise_k(tmp_path: Path) -> None:
    _participants(tmp_path, [[f"sub-{n}", "64", "F"] for n in range(6)])
    report = assess(tmp_path)

    assert report["minimum_k"] == 6
    assert report["combinations_below_threshold"] == []


def test_only_combinations_below_the_threshold_are_listed(tmp_path: Path) -> None:
    rows = [[f"sub-{n}", "64", "F"] for n in range(5)]
    rows.append(["sub-rare", "94", "M"])
    _participants(tmp_path, rows)
    report = assess(tmp_path)

    below = report["combinations_below_threshold"]
    assert isinstance(below, list)
    assert len(below) == 1
    assert below[0]["values"] == {"age": "94", "sex": "M"}
    assert below[0]["k"] == 1


def test_the_threshold_is_configurable(tmp_path: Path) -> None:
    _participants(tmp_path, [[f"sub-{n}", "64", "F"] for n in range(3)])
    assert assess(tmp_path, threshold=2)["combinations_below_threshold"] == []
    assert assess(tmp_path, threshold=4)["combinations_below_threshold"] != []


def test_the_quasi_identifiers_come_from_the_layout(tmp_path: Path) -> None:
    """Adding a column to the table adds it to the assessment."""
    _participants(tmp_path, [["sub-a", "64", "F"]])
    assert assess(tmp_path)["quasi_identifiers"] == list(layout.RECOMMENDED_PARTICIPANT_COLUMNS)


def test_a_table_with_no_quasi_identifiers_says_so(tmp_path: Path) -> None:
    """No assessment is not the same as no risk, and the report says that."""
    _participants(tmp_path, [["sub-a"]], header=[layout.PARTICIPANT_ID_COLUMN])
    report = assess(tmp_path)

    assert report["quasi_identifiers"] == []
    assert report["minimum_k"] is None
    assert "not the same as no risk" in str(report["note"])


def test_a_ragged_row_is_skipped_rather_than_crashing(tmp_path: Path) -> None:
    _participants(tmp_path, [["sub-a", "64", "F"], ["sub-b"]])
    assert assess(tmp_path)["participants"] == 1


def test_the_report_is_written_where_validate_looks_for_it(tmp_path: Path) -> None:
    _participants(tmp_path, [["sub-a", "64", "F"]])
    payload = write_risk_report(tmp_path)

    path = tmp_path / layout.DEIDENT_DIR / layout.RISK_REPORT_JSON
    assert json.loads(path.read_text(encoding="utf-8")) == payload
    assert payload["threshold"] == K_THRESHOLD
