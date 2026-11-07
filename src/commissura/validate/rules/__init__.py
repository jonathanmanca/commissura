"""The rule set.

Importing this package imports every rule module, which is what populates the
registry. Nothing else is needed to add a rule: write the function, decorate it,
and import its module here.

The imports look unused and are not. ``__all__`` and the re-exports below make
that explicit so a future reader — or a linter — does not helpfully delete them.
"""

from __future__ import annotations

from commissura.validate.rules import deident, extension, naming, participants, structure
from commissura.validate.rules._registry import Rule, RuleCheck, get_rule, registered_rules

__all__ = [
    "Rule",
    "RuleCheck",
    "deident",
    "extension",
    "get_rule",
    "naming",
    "participants",
    "registered_rules",
    "structure",
]
