"""k-anonymity over the participant attributes."""

from __future__ import annotations

import json
from pathlib import Path

from commissura import layout
from commissura.build.risk import (
    K_THRESHOLD,
    LABORATORY_SAMPLE,
    assess,
    assess_laboratory,
    write_risk_report,
)


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


# --------------------------------------------------------------------------
# Laboratory value rarity
# --------------------------------------------------------------------------


def _lab_dataset(tmp_path: Path, rows_by_subject: dict[str, list[tuple[str, str]]]) -> Path:
    """Write a minimal dataset carrying only the lab tables these tests need."""
    root = tmp_path / "dataset"
    for subject, rows in rows_by_subject.items():
        base = root / subject / "ses-01" / "lab"
        base.mkdir(parents=True, exist_ok=True)
        header = "\t".join(layout.LAB_REQUIRED_COLUMNS)
        body = "\n".join(f"0\t{code}\t{value}\tg/dL" for code, value in rows)
        (base / f"{subject}_ses-01_{layout.LAB_SUFFIX}.tsv").write_text(
            f"{header}\n{body}\n", encoding="utf-8", newline=""
        )
    return root


def test_a_value_only_one_subject_has_is_reported(tmp_path: Path) -> None:
    """The same question as age and sex, asked of a column nobody calls identifying."""
    root = _lab_dataset(
        tmp_path,
        {
            "sub-aaaaaaaaaaaa": [("718-7", "13.0")],
            "sub-bbbbbbbbbbbb": [("718-7", "13.0")],
            "sub-cccccccccccc": [("718-7", "99.9")],
        },
    )

    report = assess_laboratory(root, threshold=2)

    assert report["subjects_with_results"] == 3
    assert report["distinct_combinations"] == 2
    assert report["minimum_k"] == 1
    rare = report["combinations_below_threshold"]
    assert isinstance(rare, list)
    assert rare == [{"loinc_code": "718-7", "value": "99.9", "k": 1}]


def test_counting_is_per_subject_not_per_row(tmp_path: Path) -> None:
    """Otherwise frequent bloods would make a patient look less identifiable.

    Which is backwards: the same person measured twice at the same value is one
    person, and a row count would reward having more tests.
    """
    root = _lab_dataset(
        tmp_path,
        {
            "sub-aaaaaaaaaaaa": [("718-7", "13.0"), ("718-7", "13.0"), ("718-7", "13.0")],
            "sub-bbbbbbbbbbbb": [("718-7", "14.0")],
        },
    )

    report = assess_laboratory(root, threshold=5)

    rare = report["combinations_below_threshold"]
    assert isinstance(rare, list)
    assert {(item["loinc_code"], item["value"], item["k"]) for item in rare} == {
        ("718-7", "13.0", 1),
        ("718-7", "14.0", 1),
    }


def test_a_shared_value_reaches_the_threshold(tmp_path: Path) -> None:
    """The measure has to be able to report something other than k=1."""
    root = _lab_dataset(
        tmp_path,
        {f"sub-{i:012d}": [("718-7", "13.0")] for i in range(6)},
    )

    report = assess_laboratory(root, threshold=5)

    assert report["minimum_k"] == 6
    assert report["below_threshold_count"] == 0
    assert report["combinations_below_threshold"] == []


def test_not_applicable_values_are_not_counted(tmp_path: Path) -> None:
    """An absent result is not a rare one."""
    root = _lab_dataset(
        tmp_path,
        {
            "sub-aaaaaaaaaaaa": [("718-7", layout.NOT_APPLICABLE)],
            "sub-bbbbbbbbbbbb": [(layout.NOT_APPLICABLE, "13.0")],
            "sub-cccccccccccc": [("718-7", "13.0")],
        },
    )

    report = assess_laboratory(root, threshold=5)

    assert report["distinct_combinations"] == 1


def test_a_dataset_with_no_laboratory_values_says_so(tmp_path: Path) -> None:
    """Rather than reporting zero risk, which is a different claim."""
    (tmp_path / "dataset").mkdir()

    report = assess_laboratory(tmp_path / "dataset")

    assert report["distinct_combinations"] == 0
    assert report["minimum_k"] is None
    assert "not the same as no risk" in str(report["note"])


def test_the_listing_is_capped_but_the_count_is_not(tmp_path: Path) -> None:
    """A complete list would be the dataset again with its rarest values marked.

    Which is a worse artefact than the dataset, written into a file that
    travels. The count stays exact; the listing is a sample to look at.
    """
    root = _lab_dataset(
        tmp_path,
        {"sub-aaaaaaaaaaaa": [("718-7", f"{i}.0") for i in range(LABORATORY_SAMPLE + 20)]},
    )

    report = assess_laboratory(root, threshold=5)

    assert report["below_threshold_count"] == LABORATORY_SAMPLE + 20
    listed = report["combinations_below_threshold"]
    assert isinstance(listed, list)
    assert len(listed) == LABORATORY_SAMPLE
    assert report["combinations_listed"] == LABORATORY_SAMPLE


def test_the_note_never_claims_anonymity(tmp_path: Path) -> None:
    """The one sentence this report must never be read as.

    For continuous multivariate clinical data full k-anonymity is unreachable,
    and the EHDS protects secondary use with secure environments and permits
    instead. A report that implied otherwise would be worse than no report.
    """
    root = _lab_dataset(tmp_path, {"sub-aaaaaaaaaaaa": [("718-7", "13.0")]})

    note = str(assess_laboratory(root)["note"])

    assert "not a certificate of anonymity" in note.lower()
    assert "not reachable" in note
    assert "secure" in note


def test_the_section_rides_along_with_the_risk_report(tmp_path: Path) -> None:
    """One report, two assessments: whoever reads one should meet the other."""
    root = _lab_dataset(tmp_path, {"sub-aaaaaaaaaaaa": [("718-7", "13.0")]})
    (root / layout.PARTICIPANTS_TSV).write_text(
        "participant_id\tage\tsex\nsub-aaaaaaaaaaaa\t40\tM\n", encoding="utf-8", newline=""
    )

    payload = assess(root)

    assert "laboratory_values" in payload
    assert isinstance(payload["laboratory_values"], dict)
