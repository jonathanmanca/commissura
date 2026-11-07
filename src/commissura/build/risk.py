"""k-anonymity over the participant attributes.

A dataset with no name in it can still identify somebody. If one participant is
the only 94-year-old woman in the cohort, the row is unique on attributes nobody
thinks of as identifiers, and anyone who knows a 94-year-old woman was in the
study knows which row is hers. That is what k-anonymity measures: for each
combination of quasi-identifiers, how many participants share it.

The quasi-identifiers are the recommended participant columns, ``age`` and
``sex``, because those are what the dataset actually carries. Reading them from
:data:`commissura.layout.RECOMMENDED_PARTICIPANT_COLUMNS` rather than listing
them again means adding a column to the table also adds it to the assessment.

What this deliberately is not: an Article 78 quality and utility label. The
criteria for that are not published — the EU project QUANTUM is still developing
them — so there is nothing to build against yet.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from commissura import layout
from commissura.validate.context import DatasetContext

K_THRESHOLD = 5
"""Combinations shared by fewer than this many participants are flagged.

Five is the conventional threshold in statistical disclosure control and the one
this project's brief names. It is a convention, not a law: a cohort of forty
cannot reach it on age and sex together, which is a property of small cohorts
rather than a mistake in the dataset.
"""


def assess(root: Path, *, threshold: int = K_THRESHOLD) -> dict[str, object]:
    """Measure k-anonymity over a dataset's participant attributes.

    Args:
        root: Dataset root.
        threshold: Report combinations shared by fewer participants than this.

    Returns:
        The risk report payload.
    """
    table = DatasetContext(root).participants
    columns = [c for c in layout.RECOMMENDED_PARTICIPANT_COLUMNS if c in table.header]

    if not columns:
        return {
            "schema_version": layout.SCHEMA_VERSION,
            "quasi_identifiers": [],
            "threshold": threshold,
            "participants": len(table.rows),
            "minimum_k": None,
            "combinations_below_threshold": [],
            "note": (
                "The participants table carries none of the quasi-identifier columns, "
                "so there is nothing to assess. That is not the same as no risk."
            ),
        }

    indices = [table.header.index(c) for c in columns]
    combinations = Counter(
        tuple(row[i] for i in indices) for row in table.rows if len(row) > max(indices)
    )

    below = [
        {"values": dict(zip(columns, values, strict=True)), "k": count}
        for values, count in sorted(combinations.items())
        if count < threshold
    ]

    return {
        "schema_version": layout.SCHEMA_VERSION,
        "quasi_identifiers": columns,
        "threshold": threshold,
        "participants": sum(combinations.values()),
        "minimum_k": min(combinations.values()) if combinations else None,
        "combinations_below_threshold": below,
        "note": (
            f"{len(below)} of {len(combinations)} attribute combinations are shared by "
            f"fewer than {threshold} participants. A combination with k=1 identifies "
            "one person to anyone who knows they took part."
        ),
    }


def write_risk_report(root: Path, *, threshold: int = K_THRESHOLD) -> dict[str, object]:
    """Assess a dataset and write ``.deident/risk_report.json``.

    Args:
        root: Dataset root.
        threshold: Passed to :func:`assess`.

    Returns:
        The payload written.
    """
    payload = assess(root, threshold=threshold)
    path = root / layout.DEIDENT_DIR / layout.RISK_REPORT_JSON
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="",
    )
    return payload
