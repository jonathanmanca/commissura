"""Dataset validation: is this dataset conformant, and what is missing?

The public surface is deliberately small. Everything a caller needs is here, so
``from commissura.validate import validate_dataset`` is the whole integration
story for somebody embedding this in their own pipeline.
"""

from __future__ import annotations

from commissura.validate.context import DatasetContext
from commissura.validate.findings import Finding, Report, Severity
from commissura.validate.rules import Rule, get_rule, registered_rules
from commissura.validate.runner import validate_dataset

__all__ = [
    "DatasetContext",
    "Finding",
    "Report",
    "Rule",
    "Severity",
    "get_rule",
    "registered_rules",
    "validate_dataset",
]
