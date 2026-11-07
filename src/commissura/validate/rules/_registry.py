"""The rule registry: how a check becomes part of the validator.

A rule is a function that reads a :class:`~commissura.validate.context.DatasetContext`
and yields findings. The decorator below attaches an identifier and a one-line
summary and records it, which buys three things that a single large validation
function does not:

- **The rule set is enumerable.** ``commissura validate --list-rules`` prints it,
  so the schema is discoverable without reading the source.
- **Each rule is testable in isolation.** A test can run one rule against one
  deliberately broken dataset and assert on exactly what it reports, instead of
  sifting a combined report.
- **Identifiers are checked for collisions at import time.** Two rules sharing
  an id would make a finding ambiguous and a test unreliable; it is caught when
  the module loads rather than when somebody notices the report is wrong.

Rules yield rather than return, so a rule that scans a thousand files does not
build a thousand-element list before the first finding can be shown.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from commissura.validate.context import DatasetContext
from commissura.validate.findings import Finding

RuleCheck = Callable[[DatasetContext], Iterator[Finding]]
"""The signature every rule implements."""


@dataclass(frozen=True, slots=True)
class Rule:
    """One registered check.

    Attributes:
        rule_id: Stable identifier such as ``DS001``, quoted in every finding
            the rule produces and in the tests that pin its behaviour.
        summary: One line describing what the rule checks, written for somebody
            reading ``--list-rules`` rather than the source.
        check: The implementation.
    """

    rule_id: str
    summary: str
    check: RuleCheck


_REGISTRY: dict[str, Rule] = {}


def rule(rule_id: str, summary: str) -> Callable[[RuleCheck], RuleCheck]:
    """Register a function as a validation rule.

    Args:
        rule_id: Stable identifier. Must be unique across the whole validator.
        summary: One line describing the check.

    Returns:
        A decorator that registers the function and returns it unchanged, so
        the function stays directly callable from a test.

    Raises:
        ValueError: If ``rule_id`` is already registered.
    """

    def decorator(check: RuleCheck) -> RuleCheck:
        if rule_id in _REGISTRY:
            raise ValueError(
                f"duplicate rule id {rule_id!r}: already registered by "
                f"{_REGISTRY[rule_id].check.__name__}"
            )
        _REGISTRY[rule_id] = Rule(rule_id=rule_id, summary=summary, check=check)
        return check

    return decorator


def registered_rules() -> tuple[Rule, ...]:
    """Return every registered rule, ordered by identifier.

    Ordered so that a report's contents do not depend on module import order,
    which would otherwise make output unstable between runs.
    """
    return tuple(_REGISTRY[rule_id] for rule_id in sorted(_REGISTRY))


def get_rule(rule_id: str) -> Rule:
    """Return one rule by identifier.

    Args:
        rule_id: The identifier to look up.

    Returns:
        The rule.

    Raises:
        KeyError: If no such rule is registered.
    """
    if rule_id not in _REGISTRY:
        raise KeyError(f"unknown rule id: {rule_id!r}")
    return _REGISTRY[rule_id]
