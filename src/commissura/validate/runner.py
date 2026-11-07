"""Run the rule set over a dataset and assemble the report."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from commissura.validate.context import DatasetContext
from commissura.validate.findings import Finding, Report, Severity, sort_findings
from commissura.validate.rules import Rule, registered_rules


def validate_dataset(
    root: Path,
    *,
    rules: tuple[Rule, ...] | None = None,
    include_notices: bool = True,
) -> Report:
    """Validate one dataset directory and return everything found.

    A rule that raises is not allowed to take the run down with it. The failure
    is converted into a finding against the rule itself, because a validator
    that dies on one unexpected dataset tells the user nothing about the other
    thirty checks that would have passed — and the one time it matters is the
    one time somebody is trying to find out what is wrong with their data.

    Args:
        root: The dataset root.
        rules: The rules to run. Defaults to every registered rule. Passing a
            subset is how a test exercises one rule in isolation.
        include_notices: Whether to keep ``NOTICE`` findings in the report.

    Returns:
        The report, findings ordered most severe first.
    """
    selected = registered_rules() if rules is None else rules
    context = DatasetContext(root)

    collected: list[Finding] = []
    for entry in selected:
        try:
            collected.extend(entry.check(context))
        # Deliberately broad: a rule with a bug must not take the run down with
        # it, because the one time it happens is the one time somebody is trying
        # to find out what is wrong with their data.
        except Exception as exc:
            collected.append(
                Finding(
                    rule_id=entry.rule_id,
                    severity=Severity.ERROR,
                    message=f"rule {entry.rule_id} failed to run: {type(exc).__name__}: {exc}",
                    hint="This is a bug in the validator, not necessarily in the dataset.",
                )
            )

    if not include_notices:
        collected = [f for f in collected if f.severity is not Severity.NOTICE]

    return Report(
        dataset_root=str(context.root),
        checked_at=datetime.now(UTC),
        rules_run=len(selected),
        findings=sort_findings(collected),
    )
