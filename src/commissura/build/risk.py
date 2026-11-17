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

A second assessment covers the laboratory values, where the same reasoning
applies to clinical measurements rather than to demographics: a result nobody
else in the cohort shares is a handle on whoever has it. That one answers a
harsher question and the answer is usually worse, which is the point — see
:func:`assess_laboratory`.

**Neither assessment alters the data, and that is a decision rather than an
omission.** Every remedy — suppressing rare rows, top and bottom coding,
rounding to bands — destroys exactly the clinically interesting cases, because
the unusual value is both the re-identification risk and the reason somebody
wants the dataset. Adding noise is worse in a clinical setting than in most:
an analyst who does not know how far wrong their numbers are cannot reason
about them at all. Which remedy is acceptable depends on the release
arrangement, the permit and the recipient, and only the data holder knows
those. So this measures and reports; the choice is theirs.

What this deliberately is not: an Article 78 quality and utility label. The
criteria for that are not published — the EU project QUANTUM is still developing
them — so there is nothing to build against yet.

And what it must never be read as: a certificate of anonymity. For continuous,
multivariate clinical data full k-anonymity is not reachable at all, and the
numbers below say so plainly rather than implying a threshold was met. That
unreachability is not a gap in this tool — it is the reason the EHDS protects
secondary use with secure processing environments and data permits instead of
with anonymisation.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from commissura import layout
from commissura.validate.context import DatasetContext

LABORATORY_SAMPLE = 50
"""How many rare laboratory combinations to list, out of however many there are.

On continuous values nearly every combination is unique, so a complete list
would be the dataset again with its rarest values highlighted — a worse artefact
than the dataset itself, written into a file that travels. The count is always
exact; the listing is a sample to look at.
"""

K_THRESHOLD = 5
"""Combinations shared by fewer than this many participants are flagged.

Five is the conventional threshold in statistical disclosure control and the one
this project's brief names. It is a convention, not a law: a cohort of forty
cannot reach it on age and sex together, which is a property of small cohorts
rather than a mistake in the dataset.
"""


def channels(root: Path, *, scored: tuple[str, ...]) -> list[dict[str, object]]:
    """Name every quasi-identifier channel this dataset carries.

    TEHDAS2 D7.2 section 4.5 (p. 41) makes two things an explicit activity for
    whoever pseudonymises: "identification of quasi-identifiers and handing over
    information on them to the data minimisation process", and providing
    "health-data specific quasi-identifiers beyond what is in the EDPB
    guidelines (e.g., dates of visits in the hospital also become quickly
    identifying)". Section 3.2 (p. 17) lists "a sequence of hospital visit
    dates" among its own examples.

    This file is that hand-over, and it was under-reporting. ``quasi_identifiers``
    named the participant columns and the laboratory assessment covered analyte
    values, so a reader taking the machine-readable artefact at its word -- which
    is what a machine-readable artefact is for -- would conclude the set was age
    and sex, generalise those, and ship a dataset whose every subject still
    carries an exactly aligned event timeline. One true date for one subject,
    from any other source, then recovers that subject's whole history. The README
    has said so in prose since 2026-11-11; this file did not say it at all.

    **A channel with no computable k is still a channel.** The interval sequence
    is the one that matters here and k-anonymity cannot score it: the measure
    counts how many people share a combination of attribute values, and a
    sequence of offsets is not an attribute with a value domain. Omitting it for
    being unscoreable is how the strongest channel in the dataset became the one
    the report did not mention, so each entry carries ``scored`` and, when that
    is false, why not and what the holder would have to do about it.

    Derived from the dataset, not declared: a channel is listed when the files
    that would carry it are present. A static list would report the interval
    channel for a dataset of nothing but single-session subjects, where there is
    no sequence to align.

    Args:
        root: Dataset root.
        scored: The quasi-identifier columns k was actually computed over, so
            the entry for them can say so rather than claiming a measurement
            that was skipped.

    Returns:
        One entry per channel present, most identifying first.
    """
    context = DatasetContext(root)
    found: list[dict[str, object]] = []

    sessions = sorted({path.parent.parent.name for path in root.glob("sub-*/ses-*/*/*")})
    if sessions:
        found.append(
            {
                "channel": "event interval sequence",
                "where": "day_offset, in every lab and report sidecar",
                "kind": "health-specific quasi-identifier (D7.2 section 3.2, p. 17)",
                "scored": False,
                "why_not_scored": (
                    "k-anonymity counts people sharing a combination of attribute "
                    "values. A sequence of day offsets is not an attribute with a "
                    "value domain, so no k describes it."
                ),
                "risk": (
                    "Intervals between a subject's events are exact. One true "
                    "calendar date for that subject, from any other source, dates "
                    "every other event in their record. This is the most likely "
                    "route from a dataset built here back to a person."
                ),
                "kept_because": (
                    "The interval is what makes the data clinically usable; the "
                    "calendar anchor is what had to go. Blurring the intervals "
                    "would destroy the thing the offsets exist to preserve, so this "
                    "is a documented trade-off and not an oversight. Mitigating it "
                    "is the data minimisation step's decision, which is why it is "
                    "handed over here."
                ),
            }
        )

    if scored:
        found.append(
            {
                "channel": "participant demographics",
                "where": f"participants.tsv: {', '.join(scored)}",
                "kind": "quasi-identifier (D7.2 section 3.2, p. 17)",
                "scored": True,
                "risk": (
                    "A combination shared by one participant identifies them to "
                    "anyone who knows they took part."
                ),
                "mitigation_available": (
                    "Generalisation. D7.2 section 3.3.1 (p. 22) asks that age be "
                    "exact only when indispensable and that extreme values be "
                    "categorised. Ages above 89 are already carried as 90+; banding "
                    "the rest is not implemented, and the width is the holder's "
                    "judgement about their cohort and their permit."
                ),
            }
        )

    if any(root.glob("sub-*/ses-*/lab/*.tsv")):
        found.append(
            {
                "channel": "laboratory measurement values",
                "where": "lab/*.tsv, analyte and value",
                "kind": "quasi-identifier, continuous",
                "scored": True,
                "risk": (
                    "A measured value is a near-unique quantity rather than a "
                    "category, so most analyte-and-value pairs are shared by very "
                    "few subjects. Counted in laboratory_values below."
                ),
                "mitigation_available": (
                    "Suppression, top and bottom coding, banding or noise -- each of "
                    "which removes or alters the unusual value that is "
                    "simultaneously the risk and the reason somebody asked for the "
                    "dataset. None is applied, and the choice depends on the permit."
                ),
            }
        )

    if context.imaging_metadata():
        found.append(
            {
                "channel": "imaging acquisition metadata",
                "where": "derivatives/imaging-metadata/*.json",
                "kind": "quasi-identifier, and possibly a direct identifier",
                "scored": False,
                "why_not_scored": (
                    "No k is computed over imaging metadata. Device, protocol and "
                    "series descriptions are free of a fixed value domain."
                ),
                "risk": (
                    "Identifiers can survive in vendor private tags, in series "
                    "descriptions, in burned-in pixel annotations and in the head "
                    "volume itself. This tool reads metadata and never pixels, so a "
                    "study whose own metadata reports burned-in annotation is "
                    "reported by validate rule DI009 and is not fixed here."
                ),
                "kept_because": (
                    "The acquisition parameters are what makes imaging metadata "
                    "worth carrying at all."
                ),
            }
        )

    return found


def assess_laboratory(root: Path, *, threshold: int = K_THRESHOLD) -> dict[str, object]:
    """Measure how many subjects share each analyte-and-value combination.

    The demographic assessment asks who is unique on age and sex. This asks who
    is unique on a measurement, which is the same question about a column nobody
    thinks of as identifying. A haemoglobin of 13.2 shared by nobody else in the
    cohort is a handle on whoever has it, for anyone who knows that one value.

    Counted **per subject, not per row**. The same person measured twice at the
    same value is one person, and counting rows would report a patient with
    frequent bloods as less identifiable than one with a single test, which is
    backwards.

    Args:
        root: Dataset root.
        threshold: Report combinations shared by fewer subjects than this.

    Returns:
        The laboratory section of the risk report. ``combinations_below_threshold``
        is capped, because on continuous values almost every combination is
        unique and a complete list would be a copy of the dataset with the
        rarest values highlighted — which is a worse artefact than the dataset.

    Raises:
        Nothing. A dataset with no laboratory tables returns zero counts, which
        is honest: there is nothing to assess, which is not the same as no risk.
    """
    context = DatasetContext(root)
    per_combination: dict[tuple[str, str], set[str]] = {}

    for data_file in context.files_of_datatype("lab"):
        if data_file.path.suffix != ".tsv":
            continue
        table = context.read_tsv(data_file.relative)
        header = table.header
        if "loinc_code" not in header or "value" not in header:
            continue
        analyte, measured = header.index("loinc_code"), header.index("value")
        for row in table.rows:
            if len(row) <= max(analyte, measured):
                continue
            code, value = row[analyte].strip(), row[measured].strip()
            if not code or not value or layout.NOT_APPLICABLE in (code, value):
                continue
            per_combination.setdefault((code, value), set()).add(data_file.subject)

    if not per_combination:
        return {
            "subjects_with_results": 0,
            "distinct_combinations": 0,
            "threshold": threshold,
            "minimum_k": None,
            "combinations_below_threshold": [],
            "below_threshold_count": 0,
            "note": (
                "This dataset carries no laboratory values to assess. That is not "
                "the same as no risk."
            ),
        }

    counts = {key: len(subjects) for key, subjects in per_combination.items()}
    below = sorted(
        (key for key, count in counts.items() if count < threshold),
        key=lambda key: (counts[key], key),
    )
    subjects = {subject for subjects in per_combination.values() for subject in subjects}

    return {
        "subjects_with_results": len(subjects),
        "distinct_combinations": len(counts),
        "threshold": threshold,
        "minimum_k": min(counts.values()),
        "below_threshold_count": len(below),
        "combinations_below_threshold": [
            {"loinc_code": code, "value": value, "k": counts[(code, value)]}
            for code, value in below[:LABORATORY_SAMPLE]
        ],
        "combinations_listed": min(len(below), LABORATORY_SAMPLE),
        "note": (
            f"{len(below)} of {len(counts)} analyte-and-value combinations are "
            f"shared by fewer than {threshold} subjects, across "
            f"{len(subjects)} subjects with results. On continuous measurements "
            "this is expected to be most of them: a value is a near-unique "
            "quantity, not a category. Reported, not corrected - suppression, "
            "banding and rounding destroy the clinically interesting cases, and "
            "noise leaves an analyst unable to say how wrong their numbers are. "
            "This is a measurement and not a certificate of anonymity; for "
            "continuous multivariate clinical data full k-anonymity is not "
            "reachable, which is why the EHDS protects secondary use with secure "
            "processing environments and data permits instead."
        ),
    }


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
            "quasi_identifier_channels": channels(root, scored=()),
            "threshold": threshold,
            "participants": len(table.rows),
            "minimum_k": None,
            "combinations_below_threshold": [],
            "note": (
                "The participants table carries none of the quasi-identifier columns, "
                "so there is nothing to assess. That is not the same as no risk."
            ),
            "laboratory_values": assess_laboratory(root, threshold=threshold),
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
        "quasi_identifier_channels": channels(root, scored=tuple(columns)),
        "threshold": threshold,
        "participants": sum(combinations.values()),
        "minimum_k": min(combinations.values()) if combinations else None,
        "combinations_below_threshold": below,
        "note": (
            f"{len(below)} of {len(combinations)} attribute combinations are shared by "
            f"fewer than {threshold} participants. A combination with k=1 identifies "
            "one person to anyone who knows they took part."
        ),
        "laboratory_values": assess_laboratory(root, threshold=threshold),
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
