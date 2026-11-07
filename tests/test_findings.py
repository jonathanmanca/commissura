"""The report model: severity semantics, ordering, and counts."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from commissura.validate.findings import (
    SEVERITY_ORDER,
    Finding,
    Report,
    Severity,
    sort_findings,
)


def _finding(rule_id: str = "DS001", severity: Severity = Severity.ERROR, **kwargs: str) -> Finding:
    return Finding(rule_id=rule_id, severity=severity, message="something", **kwargs)


def _report(*findings: Finding) -> Report:
    return Report(
        dataset_root="/tmp/dataset",
        checked_at=datetime.now(UTC),
        rules_run=len(findings) or 1,
        findings=findings,
    )


def test_a_report_with_no_findings_is_conformant() -> None:
    assert _report().is_conformant


def test_warnings_and_notices_do_not_affect_conformance() -> None:
    """A dataset can conform and still have things worth improving.

    Collapsing the two would force every judgement call to become a rejection,
    and a validator that rejects for stylistic reasons gets switched off.
    """
    report = _report(
        _finding(severity=Severity.WARNING),
        _finding(severity=Severity.NOTICE),
    )
    assert report.is_conformant
    assert len(report.warnings) == 1
    assert len(report.notices) == 1


def test_a_single_error_makes_a_dataset_non_conformant() -> None:
    report = _report(_finding(severity=Severity.ERROR))
    assert not report.is_conformant
    assert len(report.errors) == 1


def test_severity_order_is_explicit_not_alphabetical() -> None:
    """``StrEnum`` compares alphabetically, which would sort ERROR after NOTICE."""
    assert SEVERITY_ORDER[Severity.ERROR] < SEVERITY_ORDER[Severity.WARNING]
    assert SEVERITY_ORDER[Severity.WARNING] < SEVERITY_ORDER[Severity.NOTICE]
    # The trap: sorted alphabetically, a notice would outrank a warning.
    assert "notice" < "warning"


def test_findings_sort_by_severity_then_rule_then_path() -> None:
    unordered = [
        _finding("PT009", Severity.WARNING, path="b"),
        _finding("DS002", Severity.ERROR, path="z"),
        _finding("DS002", Severity.ERROR, path="a"),
        _finding("DS006", Severity.NOTICE),
    ]
    ordered = sort_findings(unordered)
    assert [(f.rule_id, f.path) for f in ordered] == [
        ("DS002", "a"),
        ("DS002", "z"),
        ("PT009", "b"),
        ("DS006", None),
    ]


def test_sorting_is_stable_across_runs() -> None:
    """Without a stable order the report cannot be diffed or asserted on."""
    findings = [
        _finding("DI001", Severity.ERROR, path="x"),
        _finding("DI001", Severity.ERROR, path="y"),
        _finding("NM003", Severity.ERROR, path="x"),
    ]
    assert sort_findings(list(findings)) == sort_findings(list(reversed(findings)))


def test_counts_by_severity_always_lists_every_severity() -> None:
    """A caller formatting the summary should not have to guard on missing keys."""
    counts = _report(_finding(severity=Severity.ERROR)).counts_by_severity()
    assert counts == {"error": 1, "warning": 0, "notice": 0}


def test_counts_by_rule_is_ordered_most_frequent_first() -> None:
    report = _report(
        _finding("DI001", path="a"),
        _finding("DI001", path="b"),
        _finding("DI001", path="c"),
        _finding("NM003", path="d"),
    )
    assert list(report.counts_by_rule()) == ["DI001", "NM003"]
    assert report.counts_by_rule()["DI001"] == 3


def test_formatted_line_carries_severity_rule_and_path() -> None:
    line = _finding("DI003", Severity.ERROR, path="reports/x.txt").format_line()
    assert line.startswith("ERROR")
    assert "DI003" in line
    assert "reports/x.txt" in line


def test_a_finding_without_a_path_formats_cleanly() -> None:
    line = _finding("DS007").format_line()
    assert "DS007: something" in line


def test_the_path_is_not_printed_twice() -> None:
    """Messages stand alone for JSON consumers, so the prefix must not repeat them."""
    finding = Finding(
        rule_id="PT007",
        severity=Severity.ERROR,
        message="row 3 of participants.tsv has 3 cells, header has 4",
        path="participants.tsv",
    )
    line = finding.format_line()
    assert line.count("participants.tsv") == 1
    assert line.startswith("ERROR   PT007: row 3")


def test_findings_are_immutable() -> None:
    """A report is a record of what was observed; it must not be edited afterwards."""
    finding = _finding()
    with pytest.raises(ValueError, match="frozen"):
        finding.message = "rewritten"  # type: ignore[misc]


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValueError, match=r"extra_forbidden|Extra inputs"):
        Finding(
            rule_id="DS001",
            severity=Severity.ERROR,
            message="x",
            severty=Severity.WARNING,  # type: ignore[call-arg]
        )


def test_the_report_timestamp_is_timezone_aware() -> None:
    """A naive timestamp in an audit record is ambiguous by exactly one offset."""
    assert _report().checked_at.tzinfo is not None
