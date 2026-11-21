"""The dataset layout: one source of truth for what a conformant dataset is.

This module is deliberately the first thing written for ``validate``, and it
holds no logic. It is the schema itself — what must exist, what the names mean,
which columns carry what — stated once so that the validator and, later,
``build`` cannot drift apart. Two components that each know the layout
separately will disagree eventually, and the disagreement will surface as a
dataset that passes its own validator and nothing else.

**Why BIDS, and where this departs from it.** BIDS gives neuroimaging a layout
that tools already understand, so reusing its grammar means `commissura`
datasets are readable by software nobody here wrote. What BIDS has no concept of
is laboratory results or clinical reports tied to the same subject, so two
datatype directories are added — ``lab`` and ``reports`` — following BIDS naming
rules rather than inventing new ones. A BIDS validator will not recognise them;
it will also not be confused by them, because BIDS permits unknown datatypes to
be ignored.

**The date rule is structural, not cosmetic.** Nothing in a dataset carries an
absolute date. Times are expressed as ``day_offset``, an integer count of days
from the subject's own baseline, so intervals stay exact while the calendar
anchor is gone. That is why :data:`ABSOLUTE_DATE_PATTERNS` exists here rather
than in a de-identification module: a dataset containing a real date is not a
de-identification weakness, it is a malformed dataset.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

SCHEMA_VERSION: Final = "1.1.0"
"""Version of the layout this module describes.

Written into ``dataset_description.json`` so a reader can tell which revision of
the schema a dataset was built against, and into the manifest as
``tool_versions.layout_schema``.

**1.1.0, 2026-11-21.** It had read 1.0.0 since the initial commit while three
things a reader of a dataset can observe changed under it, which is the defect
this project recorded on 2026-11-10 as "the schema version is part of the schema
change, not a chore afterwards" and then committed anyway. All three are
additive, so nothing valid at 1.0.0 became invalid:

* ``healthdcat-ap.jsonld`` is a file the dataset did not have at 1.0.0.
* the ``age`` column can hold a band such as ``40-49``, where 1.0.0 offered only
  an integer, ``90+`` or ``n/a``. A consumer already had to cope with
  non-integers; this is a third form, and ``generalisation.age`` in the manifest
  says which was used.
* a report's ``Eta:`` line carries the same band when one is in force.

The honest limit: datasets built before today say 1.0.0 and may already carry
the first two, so 1.0.0 in the wild is ambiguous. A version only separates what
comes after it from what came before.
"""

BIDS_VERSION: Final = "1.9.0"
"""The BIDS release whose naming grammar and required fields are followed."""

# --- Top level -------------------------------------------------------------

DATASET_DESCRIPTION: Final = "dataset_description.json"
HEALTHDCAT_DESCRIPTION: Final = "healthdcat-ap.jsonld"
"""The HealthDCAT-AP dataset description, kept separate from the BIDS one.

Two files because they are two different statements to two different readers.
``dataset_description.json`` is BIDS: plain JSON, read by tools that walk the
dataset. ``healthdcat-ap.jsonld`` is the Article 77 description: RDF, read by a
catalogue and by a Health Data Access Body. Merging them would mean inventing a
hybrid that satisfies neither specification.
"""

PARTICIPANTS_TSV: Final = "participants.tsv"
PARTICIPANTS_JSON: Final = "participants.json"
DEIDENT_DIR: Final = ".deident"
MANIFEST_JSON: Final = "manifest.json"
RISK_REPORT_JSON: Final = "risk_report.json"
DERIVATIVES_DIR: Final = "derivatives"

REQUIRED_TOP_LEVEL: Final = (DATASET_DESCRIPTION, PARTICIPANTS_TSV)
"""Files without which the directory is not a dataset at all."""

KNOWN_TOP_LEVEL: Final = frozenset(
    {
        DATASET_DESCRIPTION,
        HEALTHDCAT_DESCRIPTION,
        PARTICIPANTS_TSV,
        PARTICIPANTS_JSON,
        DEIDENT_DIR,
        DERIVATIVES_DIR,
        "README",
        "README.md",
        "CHANGES",
        "LICENSE",
        "samples.tsv",
        "samples.json",
    }
)
"""Entries expected at the dataset root. Anything else is reported, not rejected.

Reported rather than rejected because a stray file is usually a working copy or
an editor artefact, and a validator that refuses a dataset over
``participants.tsv.bak`` is a validator people route around.
"""

# --- dataset_description.json ---------------------------------------------

REQUIRED_DESCRIPTION_KEYS: Final = ("Name", "BIDSVersion")
"""Required by BIDS itself."""

RECOMMENDED_DESCRIPTION_KEYS: Final = (
    "DatasetType",
    "License",
    "Authors",
    "GeneratedBy",
    "CommissuraSchemaVersion",
)
"""Recommended here. ``GeneratedBy`` and ``CommissuraSchemaVersion`` matter most.

A dataset that cannot say which tool and which schema revision produced it
cannot be reproduced, and reproducibility is the whole claim being made when a
dataset is handed to somebody under a data permit.
"""

# --- participants.tsv ------------------------------------------------------

PARTICIPANT_ID_COLUMN: Final = "participant_id"
"""Must be the first column, per BIDS."""

RECOMMENDED_PARTICIPANT_COLUMNS: Final = ("age", "sex")

NOT_APPLICABLE: Final = "n/a"
"""BIDS spells a missing value this way. An empty cell is ambiguous."""

AGE_CEILING: Final = 89
"""Ages above this are reported as :data:`AGE_ABOVE_CEILING`.

Adopted from HIPAA Safe Harbor as a defensible threshold, not because GDPR
mandates it — it does not. The reasoning that carries over is sound: in a small
cohort an age of 97 is close to a unique identifier, and the information lost by
truncating is negligible for most research questions.
"""

AGE_ABOVE_CEILING: Final = "90+"

AGE_BAND_SEPARATOR: Final = "-"
"""Joins the two inclusive bounds of a banded age, as in ``40-44``.

Cannot be confused with a surviving calendar date by
:data:`ABSOLUTE_DATE_PATTERNS`: every bound is at most two digits, because ages
stop at :data:`AGE_CEILING`.
"""

MINIMUM_AGE_BAND: Final = 2
"""The narrowest band worth asking for.

A width of one is not banding, it is the exact age, which is what omitting the
option already gives. Accepting it would put ``42-42`` in the dataset and a
declared band width of one in the manifest -- a true statement about nothing,
and a reader would have to work out that no generalisation had been applied.
"""


def age_band(age: int, width: int) -> str:
    """Return the inclusive band an age falls in, as the dataset writes it.

    Bands are anchored at zero, so a width of five gives ``0-4``, ``5-9`` and so
    on and a width of ten gives decades. The upper bound is clamped to
    :data:`AGE_CEILING`, which keeps the two mechanisms from interfering: a
    width of seven would otherwise place an 85-year-old in ``84-90`` and state
    that they might be 90, which is exactly what the ceiling exists to prevent.
    Truncation at the ceiling is a de-identification invariant of this project;
    banding is a disclosure-control choice the holder makes per release, and
    collapsing them into one option would make the invariant look optional.

    **Logic in `layout`, which is meant to hold none**, and the reason is that
    this is the format rather than a decision about it: the writer composes the
    string and the description reader takes it apart again, so a second copy of
    the rule in either place is a copy that can disagree.

    Args:
        age: Whole years, at or below :data:`AGE_CEILING`.
        width: Band width in years, at least :data:`MINIMUM_AGE_BAND`.

    Returns:
        ``"<low><separator><high>"``, both bounds inclusive.
    """
    low = age // width * width
    high = min(low + width - 1, AGE_CEILING)
    return f"{low}{AGE_BAND_SEPARATOR}{high}"


def age_bounds(value: str) -> tuple[int, int] | None:
    """Return the inclusive bounds an age cell states, or None if it states none.

    Accepts both forms the ``age`` column can carry, because a reader of the
    column cannot know which a dataset used: an exact age is its own lower and
    upper bound, and a band gives two. ``n/a`` and :data:`AGE_ABOVE_CEILING`
    give nothing, which is not an error -- the first says the age is unknown and
    the second says only that it is above the ceiling.

    Args:
        value: One cell of the ``age`` column.

    Returns:
        ``(low, high)``, or None.
    """
    low, separator, high = value.partition(AGE_BAND_SEPARATOR)
    try:
        if not separator:
            exact = int(value)
            return exact, exact
        return int(low), int(high)
    except ValueError:
        return None


# --- Subject and session directories --------------------------------------

SUBJECT_PREFIX: Final = "sub-"
SESSION_PREFIX: Final = "ses-"

LABEL_PATTERN: Final = re.compile(r"^[a-zA-Z0-9]+$")
"""BIDS labels are alphanumeric only: no underscores, hyphens or dots.

The restriction is not arbitrary. Underscores separate entities and hyphens
separate a key from its value, so a label containing either makes the filename
grammar ambiguous.
"""

# --- Datatype directories --------------------------------------------------

BIDS_DATATYPES: Final = frozenset(
    {"anat", "func", "dwi", "fmap", "perf", "pet", "eeg", "meg", "ieeg", "beh", "micr", "nirs"}
)
"""Datatypes defined by BIDS. Only ``anat`` and ``pet`` are produced here, but a
dataset may legitimately contain others alongside."""

COMMISSURA_DATATYPES: Final = frozenset({"lab", "reports"})
"""The extension this project exists to add: laboratory results and clinical
reports, keyed to the same subject and session as the imaging."""

KNOWN_DATATYPES: Final = BIDS_DATATYPES | COMMISSURA_DATATYPES

# --- Filename grammar ------------------------------------------------------

ENTITY_PATTERN: Final = re.compile(r"^([a-zA-Z0-9]+)-([a-zA-Z0-9]+)$")
"""One ``key-value`` pair of a BIDS filename."""


@dataclass(frozen=True, slots=True)
class BidsName:
    """A parsed BIDS filename.

    Attributes:
        entities: The ``key-value`` pairs, in the order they appeared.
        suffix: The final underscore-separated token, such as ``lab`` or ``T1w``.
        extension: Everything from the first dot of the suffix onwards,
            including the dot, such as ``.tsv`` or ``.nii.gz``.
    """

    entities: tuple[tuple[str, str], ...]
    suffix: str
    extension: str

    def get(self, key: str) -> str | None:
        """Return the value of one entity, or ``None`` if it is absent."""
        for name, value in self.entities:
            if name == key:
                return value
        return None


def parse_bids_name(filename: str) -> BidsName | None:
    """Parse a BIDS-style filename into entities, suffix and extension.

    Args:
        filename: A bare filename, with no directory part.

    Returns:
        The parsed name, or ``None`` if the filename does not follow the
        grammar — a bare ``notes.txt`` has no entities and no suffix, and
        reporting that as a parse failure is more useful than guessing.

    Examples:
        >>> parsed = parse_bids_name("sub-a3f9_ses-01_lab.tsv")
        >>> parsed.get("sub"), parsed.suffix, parsed.extension
        ('a3f9', 'lab', '.tsv')
    """
    # The extension starts at the first dot after the last underscore, so that
    # a compound extension such as .nii.gz survives intact.
    head, _, tail = filename.partition(".")
    extension = f".{tail}" if tail else ""

    tokens = head.split("_")
    if len(tokens) < 2:
        return None

    *entity_tokens, suffix = tokens
    if not suffix or ENTITY_PATTERN.match(suffix):
        # A trailing token that parses as an entity means the suffix is missing.
        return None

    entities: list[tuple[str, str]] = []
    for token in entity_tokens:
        match = ENTITY_PATTERN.match(token)
        if match is None:
            return None
        entities.append((match.group(1), match.group(2)))

    return BidsName(entities=tuple(entities), suffix=suffix, extension=extension)


# --- lab datatype ----------------------------------------------------------

LAB_SUFFIX: Final = "lab"
LAB_REQUIRED_COLUMNS: Final = ("day_offset", "loinc_code", "value", "unit")
LAB_RECOMMENDED_COLUMNS: Final = (
    "display",
    "reference_low",
    "reference_high",
    "abnormal_flag",
    "panel_code",
)

# --- reports datatype ------------------------------------------------------

REPORT_SUFFIX: Final = "report"
REPORT_TEXT_EXTENSION: Final = ".txt"
REPORT_SIDECAR_EXTENSION: Final = ".json"
REPORT_REQUIRED_SIDECAR_KEYS: Final = ("kind", "day_offset")

# --- .deident/manifest.json -----------------------------------------------

MANIFEST_REQUIRED_KEYS: Final = (
    "schema_version",
    "deidentification_rule_version",
    "key_fingerprint",
    "tool_versions",
    "modalities",
)
"""What the manifest must record to be auditable.

``key_fingerprint`` identifies *which* secret key produced the pseudonyms,
without carrying the key. That makes two datasets built from the same key
provably relinkable, and a dataset built from a lost key provably orphaned —
both of which somebody will need to know years later.
"""

KEY_FINGERPRINT_PATTERN: Final = re.compile(r"^[0-9a-f]{16,64}$")
"""A fingerprint is a lowercase hex digest. Anything else may be the key itself."""

FORBIDDEN_MANIFEST_KEYS: Final = frozenset({"key", "secret", "secret_key", "hmac_key", "password"})
"""Keys whose presence suggests the secret leaked into the dataset.

The pseudonymisation design makes the dataset useless without the key. A
manifest that carries the key undoes that in one step, and it is an easy mistake
to make while debugging.
"""

# --- De-identification invariants -----------------------------------------

ABSOLUTE_DATE_PATTERNS: Final = (
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),  # 2024-03-18
    re.compile(r"\b\d{2}/\d{2}/\d{4}\b"),  # 18/03/2024
    re.compile(r"\b\d{2}\.\d{2}\.\d{4}\b"),  # 18.03.2024
    re.compile(r"\b(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\b"),  # 20240318
)
"""Shapes that indicate a surviving absolute date.

Deliberately conservative: it matches date-shaped text rather than trying to
understand it. A false positive costs somebody a glance at one cell; a false
negative ships a dataset with a real date in it.

The last pattern is anchored to plausible years and valid month and day ranges
so that an eight-digit accession number or a measurement is not mistaken for a
date.
"""

IDENTIFIER_COLUMN_NAMES: Final = frozenset(
    {
        "name",
        "family_name",
        "given_name",
        "full_name",
        "patient_name",
        "codice_fiscale",
        "fiscal_code",
        "ssn",
        "tax_code",
        "mrn",
        "medical_record_number",
        "patient_id",
        "birth_date",
        "date_of_birth",
        "dob",
        "address",
        "street",
        "postal_code",
        "phone",
        "telephone",
        "email",
        "accession",
        "accession_number",
    }
)
"""Column names that name a direct identifier.

Checking the header rather than the values catches the mistake earlier and more
reliably: a column called ``mrn`` is wrong whatever it currently contains, and a
dataset whose MRN column happens to be empty today will not stay empty.
"""
