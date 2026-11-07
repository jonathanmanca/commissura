"""What a validation run reports.

The shape of this module encodes the answer to "what should a validator do when
it finds a problem?", and the answer is: record it and keep going. The question
``validate`` exists to answer is *what is missing*, in the plural. A validator
that raises on the first problem makes somebody fix one thing, run again, and
discover the next — turning a single review into a dozen round trips.

So nothing here raises. Rules yield :class:`Finding` objects and the run
collects them all.

**Severity separates two different questions.** ``ERROR`` means the dataset does
not conform and a tool reading it may break. ``WARNING`` means it conforms but
something is inadvisable — a missing recommended field, an empty directory.
``NOTICE`` is an observation worth surfacing that implies no fault. Collapsing
these into a single pass/fail would force every judgement call to become a
rejection, and a validator that rejects for stylistic reasons gets switched off.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Severity(StrEnum):
    """How much a finding matters.

    Ordered from most to least severe so that sorting by this field is
    meaningful; :data:`SEVERITY_ORDER` holds the ranking, because ``StrEnum``
    compares alphabetically and that would put ``ERROR`` after ``NOTICE``.
    """

    ERROR = "error"
    WARNING = "warning"
    NOTICE = "notice"


SEVERITY_ORDER: dict[Severity, int] = {
    Severity.ERROR: 0,
    Severity.WARNING: 1,
    Severity.NOTICE: 2,
}
"""Explicit ranking, since the enum's own comparison is alphabetical."""


class Finding(BaseModel):
    """One thing a rule noticed.

    Attributes:
        rule_id: Stable identifier such as ``DS001``. Referenced in output and
            in tests, so it must not change once released.
        severity: How much it matters.
        message: What is wrong, stated so that somebody who has not read the
            schema can act on it.
        path: Dataset-relative path the finding concerns, if any. A finding
            about the dataset as a whole has none.
        hint: How to fix it. Separate from ``message`` so that machine-readable
            output can carry both without a caller having to split prose.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: str
    severity: Severity
    message: str
    path: str | None = None
    hint: str | None = None

    def format_line(self) -> str:
        """Return a single line for terminal output.

        The path is omitted from the prefix when the message already names it.
        Messages are written to stand on their own, because a consumer of the
        JSON output may read ``message`` and nothing else — but repeating the
        path in the terminal prefix produces lines that say the same filename
        twice, which is noise exactly where somebody is scanning for the next
        problem. Deduplicating here keeps both readers well served.
        """
        show_path = self.path is not None and self.path not in self.message
        location = f" {self.path}" if show_path else ""
        return f"{self.severity.value.upper():7s} {self.rule_id}{location}: {self.message}"


class Report(BaseModel):
    """The result of a validation run.

    Attributes:
        schema_version: Version of this report format.
        dataset_root: Absolute path that was checked.
        checked_at: When, timezone-aware.
        rules_run: How many rules were executed. Reported because a run that
            skipped most of its rules, because the dataset root was unreadable,
            should not look like a clean bill of health.
        findings: Everything noticed, ordered most severe first.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "1.0.0"
    dataset_root: str
    checked_at: datetime
    rules_run: int = Field(ge=0)
    findings: tuple[Finding, ...] = ()

    @property
    def errors(self) -> tuple[Finding, ...]:
        """Return only the findings that make the dataset non-conformant."""
        return tuple(f for f in self.findings if f.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[Finding, ...]:
        """Return only the warnings."""
        return tuple(f for f in self.findings if f.severity is Severity.WARNING)

    @property
    def notices(self) -> tuple[Finding, ...]:
        """Return only the notices."""
        return tuple(f for f in self.findings if f.severity is Severity.NOTICE)

    @property
    def is_conformant(self) -> bool:
        """Return whether the dataset conforms.

        Warnings do not affect this. A dataset can be conformant and still have
        things worth improving, and conflating the two would mean a validator
        that never reports anything short of a rejection.
        """
        return not self.errors

    def counts_by_severity(self) -> dict[str, int]:
        """Return how many findings of each severity were recorded."""
        tally = Counter(f.severity.value for f in self.findings)
        return {severity.value: tally.get(severity.value, 0) for severity in Severity}

    def counts_by_rule(self) -> dict[str, int]:
        """Return how many findings each rule produced, most frequent first."""
        tally = Counter(f.rule_id for f in self.findings)
        return dict(tally.most_common())


def sort_findings(findings: list[Finding]) -> tuple[Finding, ...]:
    """Order findings for presentation: severity, then rule, then path.

    A stable order matters more than it looks. Without one, two runs over the
    same unchanged dataset produce output that differs by line order, which
    makes the report useless to diff and impossible to assert on in a test.

    Args:
        findings: The findings to order.

    Returns:
        The same findings, ordered.
    """
    return tuple(
        sorted(
            findings,
            key=lambda f: (SEVERITY_ORDER[f.severity], f.rule_id, f.path or "", f.message),
        )
    )
