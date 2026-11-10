"""De-identify free text, using what the structured exports already told us.

Free text is where de-identification fails, and the usual approach is named
entity recognition: look at the prose and try to work out which words are
names. It is the obvious approach and it is the weak one, because it has to
decide, for every capitalised word, whether this is a person. Published work
puts general-purpose tools well below what a clinical release needs.

This module does something different, and it is only possible because the corpus
has been linked first. **It already knows what to look for.** The laboratory
message states this patient's family name, given name, national identifier and
record number. It states the ordering clinician. The message header states the
sending institution. So the problem stops being "find the names" and becomes
"remove these specific strings", which is a different and far more tractable
problem — exact, auditable, and reportable.

That is the argument for linking modalities before de-identifying them, and it
is worth stating because the opposite order is the intuitive one.

What remains genuinely hard, and is reported rather than hidden:

- **A name nobody declared.** A colleague mentioned in passing who appears in no
  structured field cannot be found this way. :attr:`ScrubReport.residual_risk`
  names this.
- **Dates**, which are found by shape rather than by prior knowledge, and
  rewritten as offsets from the subject's baseline so the interval survives.
- **Inflected or abbreviated forms.** ``PIRAS`` is found; ``Dott. P.`` is not.

Nothing here claims to be complete. What it does claim is to be *measurable*:
run it over a generated corpus and the ground-truth annotations say exactly
which spans it missed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Final

from commissura import layout
from commissura.deident.pseudonymise import Pseudonymiser
from commissura.read.corpus import Identity

PLACEHOLDER_NAME = "[NAME]"
PLACEHOLDER_NATIONAL_ID = "[NATIONAL-ID]"
PLACEHOLDER_PATIENT_ID = "[PATIENT-ID]"
PLACEHOLDER_PROVIDER = "[PROVIDER]"
PLACEHOLDER_INSTITUTION = "[INSTITUTION]"
PLACEHOLDER_CONTACT = "[CONTACT]"
PLACEHOLDER_BIRTH_DATE = "[BIRTH-DATE]"
PLACEHOLDER_ADDRESS = "[ADDRESS]"

_ALL_PLACEHOLDERS: tuple[str, ...] = (
    PLACEHOLDER_NAME,
    PLACEHOLDER_NATIONAL_ID,
    PLACEHOLDER_PATIENT_ID,
    PLACEHOLDER_PROVIDER,
    PLACEHOLDER_INSTITUTION,
    PLACEHOLDER_CONTACT,
    PLACEHOLDER_BIRTH_DATE,
    PLACEHOLDER_ADDRESS,
)
"""Every marker this module writes.

The residual-risk detector has to ignore them: the placeholders are
all-capitals too, so without this it reports its own output as unremoved
identifiers, which is exactly what happened on the first real run.
"""

CATEGORY_DISPOSITION: Final[dict[str, str]] = {
    "address": "removed",
    "age": "replaced",
    "contact": "removed",
    "date": "replaced",
    "date_of_birth": "removed",
    "institution": "removed",
    "national_id": "removed",
    "patient_id": "removed",
    "person_name": "removed",
    "provider_name": "removed",
}
"""What became of each category of thing this module substitutes.

The same three-way vocabulary the structured modalities use, so one reading of
the manifest covers all three -- except that nothing in free text is ever
*kept*, because a body of prose is carried whole and only its identifiers are
touched. What is left is the distinction that matters to an auditor, and only
two of the ten fall on the other side of it:

* ``date`` becomes ``[day_offset:N]``, which still states the interval to every
  other event in the subject's record, so the original is partly recoverable by
  whoever holds the baseline -- **replaced**;
* ``age`` becomes the age-ceiling marker, which states that the original was
  above the ceiling -- **replaced**;
* everything else becomes a placeholder carrying nothing of the original --
  **removed**.

``date_of_birth`` is in the second group deliberately and is the one that looks
like it belongs in the first. It is removed rather than offset, because an
offset from the subject's own baseline would state the birth date exactly in a
dataset that also carries the baseline. The decision log of 2026-11-07 has the
reasoning; this table has to agree with it.

A category missing from here raises ``KeyError`` when the manifest is written,
which is deliberate: a manifest that silently described an unknown category as
one thing or the other would be worse than a build that stopped.
"""

_AGE_PATTERN = re.compile(r"\b(\d{1,3})\s*anni\b", re.IGNORECASE)
_EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE_PATTERN = re.compile(r"\+?\d[\d\s]{7,}\d")

_MINIMUM_REDACTABLE = 4
"""Shortest string worth replacing by exact match.

Below this, a "name" is as likely to be a fragment of a clinical word, and
replacing it would corrupt the report while appearing to protect it. A patient
initialled ``Li`` is a real limitation, recorded rather than papered over.
"""


@dataclass(frozen=True, slots=True)
class Replacement:
    """One substitution made in a document."""

    category: str
    original: str
    replacement: str
    occurrences: int


@dataclass(slots=True)
class ScrubReport:
    """What was removed from one document, and what may still be in it."""

    path: str
    replacements: list[Replacement] = field(default_factory=list)
    residual_risk: list[str] = field(default_factory=list)

    @property
    def total_occurrences(self) -> int:
        """Return how many substitutions were made in total."""
        return sum(r.occurrences for r in self.replacements)

    def categories(self) -> dict[str, int]:
        """Return occurrences per category, for the manifest."""
        tally: dict[str, int] = {}
        for item in self.replacements:
            tally[item.category] = tally.get(item.category, 0) + item.occurrences
        return tally


@dataclass(frozen=True, slots=True)
class KnownIdentifiers:
    """Everything the structured exports said about one subject's documents.

    Assembled from the laboratory messages and the imaging metadata, which is
    what makes targeted redaction possible. ``providers`` and ``institutions``
    are per-corpus rather than per-subject: a clinician who signed one report
    signs others, and removing their name everywhere is both safer and cheaper
    than deciding case by case.
    """

    identity: Identity
    providers: frozenset[str] = frozenset()
    institutions: frozenset[str] = frozenset()
    addresses: frozenset[str] = frozenset()


_PROSE_HEADINGS: frozenset[str] = frozenset(
    {
        "ALLA",
        "CLINICO",
        "CONCLUSIONI",
        "DECORSO",
        "DELLA",
        "DIAGNOSTICA",
        "DIMISSIONE",
        "ESAME",
        "IMMAGINI",
        "INDICAZIONI",
        "LETTERA",
        "MOTIVO",
        "NELLA",
        "QUESITO",
        "REFERTO",
        "REPERTI",
        "RICOVERO",
        "TECNICA",
        "TERAPIA",
    }
)
"""Section headings the generated reports use, in capitals like the names.

Listed so the risk detector does not report a heading as an identifier it
failed to remove. A real corpus would need its own list, which is why this
is a named constant rather than a literal buried in the detector.
"""


def _replace_all(text: str, needle: str, placeholder: str) -> tuple[str, int]:
    """Replace ``needle`` case-insensitively, reporting how often it matched."""
    if len(needle) < _MINIMUM_REDACTABLE:
        return text, 0
    pattern = re.compile(re.escape(needle), re.IGNORECASE)
    replaced, count = pattern.subn(placeholder, text)
    return replaced, count


def scrub_text(
    text: str,
    *,
    path: str,
    known: KnownIdentifiers,
    pseudonymiser: Pseudonymiser,
    subject_label: str,
    baseline: date | None,
) -> tuple[str, ScrubReport]:
    """Remove known identifiers from a document and turn its dates into offsets.

    Order matters and is deliberate. The full name goes first, so that
    "MARIO ROSSI" becomes one placeholder rather than two adjacent ones. The
    national identifier goes before the record number, because a codice fiscale
    can contain a digit run that a shorter identifier would match inside.

    Args:
        text: The document, unmodified.
        path: Corpus-relative path, for the report.
        known: What the structured exports declared.
        pseudonymiser: Used to compute day offsets.
        subject_label: The subject's pseudonymous label.
        baseline: The subject's anchor date. Without it, dates are removed
            rather than offset, because an offset needs something to count from.

    Returns:
        The scrubbed text and an account of what was done to it.
    """
    report = ScrubReport(path=path)
    scrubbed = text
    identity = known.identity

    # Self-contained tokens go first. An email address contains the patient's
    # own surname, so an exact-match substitution reaching inside it would
    # leave "m.[NAME]@posta.invalid" and the pattern would no longer recognise
    # the address at all. The domain would survive, which is a leak that looks
    # like a redaction.
    for category, pattern, placeholder in (
        ("contact", _EMAIL_PATTERN, PLACEHOLDER_CONTACT),
        ("contact", _PHONE_PATTERN, PLACEHOLDER_CONTACT),
    ):
        scrubbed, count = pattern.subn(placeholder, scrubbed)
        if count:
            report.replacements.append(
                Replacement(category, f"<{pattern.pattern[:16]}>", placeholder, count)
            )

    ordered: list[tuple[str, str, str]] = [
        # The birth date goes first and is REMOVED, not offset. An offset from
        # the subject's own baseline would state the birth date exactly, in a
        # dataset that also carries the baseline — which protects nothing. It is
        # also the single most identifying date a record holds.
        *(
            ("date_of_birth", rendered, PLACEHOLDER_BIRTH_DATE)
            for rendered in _render_date_forms(identity.birth_date)
        ),
        ("person_name", identity.full_name, PLACEHOLDER_NAME),
        ("national_id", identity.national_id, PLACEHOLDER_NATIONAL_ID),
        ("patient_id", identity.mrn, PLACEHOLDER_PATIENT_ID),
        ("person_name", identity.family_name, PLACEHOLDER_NAME),
        ("person_name", identity.given_name, PLACEHOLDER_NAME),
    ]
    ordered += [
        ("institution", name, PLACEHOLDER_INSTITUTION) for name in sorted(known.institutions)
    ]
    ordered += [("provider_name", name, PLACEHOLDER_PROVIDER) for name in sorted(known.providers)]
    ordered += [("address", value, PLACEHOLDER_ADDRESS) for value in sorted(known.addresses)]

    for category, needle, placeholder in ordered:
        if not needle:
            continue
        scrubbed, count = _replace_all(scrubbed, needle, placeholder)
        if count:
            report.replacements.append(Replacement(category, needle, placeholder, count))

    scrubbed, date_count = _rewrite_dates(
        scrubbed, pseudonymiser=pseudonymiser, subject_label=subject_label, baseline=baseline
    )
    if date_count:
        report.replacements.append(
            Replacement("date", "<date-shaped>", "[day_offset:N]", date_count)
        )

    scrubbed, age_count = _truncate_ages(scrubbed)
    if age_count:
        report.replacements.append(
            Replacement("age", "<age above ceiling>", layout.AGE_ABOVE_CEILING, age_count)
        )

    scrubbed = _collapse_runs(scrubbed)
    report.residual_risk = _assess_residual_risk(scrubbed)
    return scrubbed, report


def _render_date_forms(value: date | None) -> tuple[str, ...]:
    """Return the ways one date is written in clinical prose.

    Redacting a known date by exact match is stronger than finding it by shape,
    because it cannot confuse a birth date with an appointment. It needs every
    rendering a report might use, which is what this produces.
    """
    if value is None:
        return ()
    forms = {
        value.strftime("%d/%m/%Y"),
        value.strftime("%d.%m.%Y"),
        value.strftime("%Y-%m-%d"),
        value.strftime("%Y%m%d"),
    }
    return tuple(sorted(forms))


def _collapse_runs(text: str) -> str:
    """Collapse consecutive identical placeholders into one.

    Redacting an institution word by word leaves
    ``[INSTITUTION] [INSTITUTION] [INSTITUTION]``, which is both unreadable and
    a small leak: it tells a reader how many words the original name had.
    """
    for placeholder in _ALL_PLACEHOLDERS:
        escaped = re.escape(placeholder)
        text = re.sub(rf"(?:{escaped})(?:\s+{escaped})+", placeholder, text)
    return text


def _rewrite_dates(
    text: str, *, pseudonymiser: Pseudonymiser, subject_label: str, baseline: date | None
) -> tuple[str, int]:
    """Replace every date-shaped string with an offset from the subject's baseline.

    Rewriting rather than deleting is the point: "si confronta con il precedente
    esame del 12/03/2023" carries clinically useful information about *when*
    relative to everything else, and an offset preserves it while destroying the
    calendar anchor. A date that cannot be parsed, or a subject with no baseline,
    gets a removal marker instead — losing the interval is better than inventing
    one.
    """
    count = 0

    def substitute(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        parsed = _parse_italian_date(match.group(0))
        if parsed is None or baseline is None:
            return "[date removed]"
        offset = pseudonymiser.day_offset(baseline, parsed)
        return f"[day_offset:{offset:+d}]"

    for pattern in layout.ABSOLUTE_DATE_PATTERNS:
        text = pattern.sub(substitute, text)
    return text, count


def _parse_italian_date(value: str) -> date | None:
    """Parse the date shapes a clinical report uses, or return ``None``."""
    for pattern in ("%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            continue
    return None


def _truncate_ages(text: str) -> tuple[str, int]:
    """Replace ages above the ceiling with the open-ended band.

    In a small cohort an age of 97 is close to a unique identifier. Ages at or
    below the ceiling are left alone: they are clinically useful and not
    identifying on their own.
    """
    count = 0

    def substitute(match: re.Match[str]) -> str:
        nonlocal count
        age = int(match.group(1))
        if age <= layout.AGE_CEILING:
            return match.group(0)
        count += 1
        return f"{layout.AGE_ABOVE_CEILING} anni"

    return _AGE_PATTERN.sub(substitute, text), count


def _assess_residual_risk(text: str) -> list[str]:
    """Report what the scrubber knows it cannot have removed.

    Honest reporting rather than a confidence score. Each entry names a category
    of identifier that targeted redaction cannot reach, so a reviewer knows
    where to look rather than being told a number.
    """
    risks: list[str] = []
    if re.search(r"\bDott\.?\s*[A-Z]\.", text):
        risks.append(
            "an abbreviated clinician name (such as 'Dott. P.') remains: too short to "
            "match by exact replacement"
        )
    if re.search(r"\bpresso\s+[A-Z][A-Za-z]{3,}", text):
        risks.append(
            "an institution is named in running prose after 'presso' and was not in the "
            "structured exports, so it could not be matched"
        )
    capitalised = set(re.findall(r"\b[A-Z]{4,}\b", text))
    capitalised -= _PROSE_HEADINGS
    capitalised -= {
        word for placeholder in _ALL_PLACEHOLDERS for word in re.findall(r"[A-Z]{4,}", placeholder)
    }
    if capitalised:
        risks.append(
            "unrecognised all-capitals tokens remain, which in this corpus is how names "
            f"are written: {', '.join(sorted(capitalised)[:5])}"
        )
    return risks
