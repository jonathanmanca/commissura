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
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Final

from commissura import layout
from commissura.deident.pseudonymise import Pseudonymiser
from commissura.read.corpus import DeclaredIdentity, Identity

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

    **``identities`` is plural, and that is a correctness property rather than a
    convenience.** A subject assembled from several laboratory messages has one
    identity per message, and they can differ — a second institution spells the
    given name differently or sends its own record number. This used to carry
    one identity, so every name in the others was a name redaction never looked
    for. The audit of 2026-11-13 leaked a patient's full name through exactly
    that gap. Every identity the subject carries contributes its names, its
    identifiers and its birth date to the plan.

    Attributes:
        identities: Every identity observed for this subject, primary first,
            from the laboratory messages that established it.
        declared: What this subject's *reports* say about who they are about.
            Separate from ``identities`` because a report writes one unsplit
            name, and because a report can name somebody else — a mis-filed
            document — in which case that name still has to be removed. It
            used to reach nothing, and the name was published.
        providers: Clinician names, gathered across the corpus.
        institutions: Institution names, gathered across the corpus.
        addresses: Institution address fragments, gathered across the corpus.
    """

    identities: tuple[Identity, ...]
    declared: tuple[DeclaredIdentity, ...] = ()
    providers: frozenset[str] = frozenset()
    institutions: frozenset[str] = frozenset()
    addresses: frozenset[str] = frozenset()


_PROSE_HEADINGS: frozenset[str] = frozenset(
    {
        "ALLA",
        "CHIMICA",
        "CLINICO",
        "CONCLUSIONI",
        "DECORSO",
        "DELLA",
        "DIAGNOSTICA",
        "DIMISSIONE",
        "EMATOLOGIA",
        "ESAME",
        "ESAMI",
        "IMMAGINI",
        "INDICAZIONI",
        "LABORATORIO",
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
"""Section headings a document's own structure contributes, in capitals.

Listed so the risk detector does not report a heading as an identifier it
failed to remove. A real corpus would need its own list, which is why this
is a named constant rather than a literal buried in the detector.

``CHIMICA``, ``EMATOLOGIA``, ``ESAMI`` and ``LABORATORIO`` come from a different
place than the rest and are the ones a real deployment is most likely to keep:
they are words from Tabella 44 of the HL7 Italia laboratory specification, the
LOINC laboratory specialties, which a CDA document carries as the title of its
specialty section. The others are this project's own report template. Both
reached the detector the same way — measured on a built dataset, where a
specialty title was being reported as an unrecognised all-capitals token on
every single document, which is how a useful list of residual risks becomes a
list nobody reads.
"""


def _identity_entries(
    identities: tuple[Identity, ...],
) -> list[tuple[str, str, str]]:
    """Return the redaction entries for every identity a subject carries.

    Order within one identity is the order that was already here: the full name
    before its parts, so ``MARIO ROSSI`` is replaced once rather than leaving a
    doubled placeholder. Order between identities is the order they were
    observed, primary first, which keeps the plan deterministic.

    Longest first is deliberately **not** used here, and that is a statement
    about identities only: the full name is already the longest form of a name,
    so the structure supplies the ordering, and reordering identifiers against
    each other would make the plan depend on the data rather than on the schema.
    The flat sets of institutions, providers and addresses have no such
    structure and do need it — see :func:`_longest_first`, which exists because
    the absence of it leaked a clinician's surname.

    Args:
        identities: Every identity observed for one subject.

    Returns:
        ``(category, value, placeholder)`` entries, duplicates removed.
    """
    entries: list[tuple[str, str, str]] = []
    for identity in identities:
        entries += [
            ("person_name", identity.full_name, PLACEHOLDER_NAME),
            ("national_id", identity.national_id, PLACEHOLDER_NATIONAL_ID),
            ("patient_id", identity.mrn, PLACEHOLDER_PATIENT_ID),
            ("person_name", identity.family_name, PLACEHOLDER_NAME),
            ("person_name", identity.given_name, PLACEHOLDER_NAME),
        ]
    seen: set[tuple[str, str, str]] = set()
    unique: list[tuple[str, str, str]] = []
    for entry in entries:
        if entry not in seen:
            seen.add(entry)
            unique.append(entry)
    return unique


def _declared_entries(
    declared: tuple[DeclaredIdentity, ...],
) -> list[tuple[str, str, str]]:
    """Return the redaction entries for what a subject's reports declared.

    The same three categories a laboratory identity contributes, plus the words
    of the name: a header writes ``GIOVANNA ESPOSITO`` and the prose below it
    writes ``ESPOSITO``, so replacing only the whole string leaves the second
    one standing. The name is never split into given and family, because a
    report does not say which is which.

    Args:
        declared: What the subject's reports said about who they are about.

    Returns:
        ``(category, value, placeholder)`` entries, duplicates removed, whole
        names before their words so a two-word name is replaced once rather
        than leaving a doubled placeholder.
    """
    entries: list[tuple[str, str, str]] = []
    for one in declared:
        entries += [
            ("person_name", one.full_name, PLACEHOLDER_NAME),
            ("national_id", one.national_id, PLACEHOLDER_NATIONAL_ID),
            ("patient_id", one.mrn, PLACEHOLDER_PATIENT_ID),
        ]
        entries += [("person_name", word, PLACEHOLDER_NAME) for word in sorted(one.words())]
    seen: set[tuple[str, str, str]] = set()
    unique: list[tuple[str, str, str]] = []
    for entry in entries:
        if entry not in seen:
            seen.add(entry)
            unique.append(entry)
    return unique


def _longest_first(values: Iterable[str]) -> list[str]:
    """Order values so that no shorter one can consume a longer one.

    Exact-match substitution is destructive: once ``DAVIDE`` has become
    ``[PROVIDER]``, the string ``LOMBARDI DAVIDE`` is no longer present for the
    longer entry to match, and the surname survives beside a placeholder that
    says it was handled. So within any flat set of values, the longest must go
    first.

    Ties break alphabetically, so the plan stays deterministic — two corpora
    with the same declared values produce the same substitution order, which is
    what makes a build reproducible and a manifest comparable.

    **This is not the ordering question :func:`_identity_entries` settles**, and
    the difference is worth keeping straight. An identity has structure: it
    contributes its full name, then the family and given parts, and placing the
    whole before its pieces is what stops a two-word name leaving a doubled
    placeholder. Length is not needed there and would make the plan depend on
    the data. The institution, provider and address sets have no such structure
    — they are bare collections, and length is the only thing standing between
    a short member and a long one.

    Args:
        values: The declared values of one category.

    Returns:
        The same values, longest first.
    """
    return sorted(values, key=lambda value: (-len(value), value))


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
            for one in known.identities
            if one.birth_date
            for rendered in _render_date_forms(one.birth_date)
        ),
        *_identity_entries(known.identities),
        *_declared_entries(known.declared),
    ]
    # Longest first, and this is a PHI leak that shipped. These three sets are
    # flat: unlike an identity, which contributes its full name before its
    # parts, they are bare collections that genuinely contain both `DAVIDE` and
    # `LOMBARDI DAVIDE`. Sorted alphabetically, `DAVIDE` was substituted first,
    # so `collega LOMBARDI DAVIDE` became `collega LOMBARDI [PROVIDER]` — the
    # longer entry no longer matched and the surname survived attached to the
    # placeholder.
    #
    # That is the failure mode recorded on 2026-11-07 about emails:
    # **a leak that looks like a redaction.** Worse here, because a reader
    # seeing `[PROVIDER]` concludes the name was handled. Found by reviewing
    # the CDA work, present identically on HL7 input, and measured: four
    # survivors at ten subjects and rate 0.5, on both input formats.
    ordered += [
        ("institution", name, PLACEHOLDER_INSTITUTION)
        for name in _longest_first(known.institutions)
    ]
    ordered += [
        ("provider_name", name, PLACEHOLDER_PROVIDER) for name in _longest_first(known.providers)
    ]
    ordered += [
        ("address", value, PLACEHOLDER_ADDRESS) for value in _longest_first(known.addresses)
    ]

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
    report.residual_risk = assess_residual_risk(scrubbed, known=known)
    return scrubbed, report


def _render_date_forms(value: date) -> tuple[str, ...]:
    """Return the ways one date is written in clinical prose.

    Redacting a known date by exact match is stronger than finding it by shape,
    because it cannot confuse a birth date with an appointment. It needs every
    rendering a report might use, which is what this produces.
    """
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


_NAME_LABELS: Final[tuple[str, ...]] = (
    "Paziente",
    "Nome",
    "Assistito",
    "Medico",
    "Medico curante",
    "Refertante",
    "Richiedente",
)
"""Header labels whose value is a person's name, whatever its capitalisation.

Position, not classification. A general-purpose name detector over clinical
prose produces more false positives than a reviewer will read, and this project
rejects named entity recognition for de-identification. But a line beginning
``Paziente:`` is *declared* to hold a name, so anything still sitting there
after redaction is a residue regardless of how it is written — which is the
whole gap the audit of 2026-11-13 found. Adapting this to another hospital's
template is an edit here, like :data:`commissura.read.corpus._REPORT_LABELS`.
"""

_LABELLED_NAME = re.compile(
    r"^[ \t]*(?:" + "|".join(_NAME_LABELS) + r")[ \t]*:[ \t]*(?P<value>\S.*)$",
    re.MULTILINE | re.IGNORECASE,
)

_TITLED_NAME = re.compile(r"\b(?:Dott|Dr|Prof|Sig|Sig\.ra)\.?\s+(?P<value>\S+)")

_WORD = re.compile(r"[^\W\d_]{4,}", re.UNICODE)
r"""Runs of four or more letters, accented ones included.

``[A-Z]{4,}`` was the previous pattern and it could not see ``FRANCESCA
FONTANÀ``, let alone ``Francesca Fontana``. ``[^\W\d_]`` is "a word character
that is neither a digit nor an underscore", which under :data:`re.UNICODE` is
every letter in every script.
"""


def _fold(value: str) -> str:
    """Return a value in the form two spellings of it compare equal in.

    NFKD then casefold: ``casefold`` is the aggressive sibling of ``lower``
    designed for exactly this, and the decomposition means a composed and a
    decomposed accent match. Used only for *comparison*, never for output.
    """
    return unicodedata.normalize("NFKD", value).casefold()


def _declared_values(known: KnownIdentifiers) -> set[str]:
    """Return every string the scrubber was told to remove, folded for comparison."""
    values: set[str] = set()
    for identity in known.identities:
        values.update(
            {
                identity.full_name,
                identity.family_name,
                identity.given_name,
                identity.national_id,
                identity.mrn,
            }
        )
    values.update(known.providers, known.institutions, known.addresses)
    return {_fold(v) for v in values if len(v) >= _MINIMUM_REDACTABLE}


def assess_residual_risk(text: str, *, known: KnownIdentifiers) -> list[str]:
    """Report what the scrubber knows it cannot have removed, in three layers.

    Layered on purpose, strongest first, because the three answer different
    questions and only the first is certain:

    1. **Did a value we were told about survive?** Exact, case-insensitive and
       Unicode-insensitive, with no false positives possible: these are strings
       the scrubber was handed and asked to remove. Nothing checked this before,
       which is remarkable in hindsight — the scrubber counted its own
       replacements and never looked at its own output. This is the layer that
       catches a redaction that did not fire.
    2. **Is something still sitting where a name is declared to be?** A line
       beginning ``Paziente:`` holds a name by definition, so a residue there is
       a residue whatever its capitalisation. Position does the work, which is
       what keeps the false-positive rate bounded without a name model.
    3. **Is there an unrecognised word that looks like an identifier?** The
       original heuristic, now Unicode-aware. It catches what nothing declared,
       which is its whole value, and it is the noisiest of the three.

    **This is a measurement, not a clearance.** A heuristic that reports nothing
    has reported nothing; it has not established that a document is free of
    identifiers. The counterpart measurement is ``commissura measure``, which
    asks the opposite question — whether the identifiers the generator planted
    survived — and the two fail differently on purpose.

    Args:
        text: The scrubbed document.
        known: What the scrubber was told about this subject, so that layer one
            can check its own work.

    Returns:
        One entry per category of residue found, counted rather than quoted.
    """
    risks: list[str] = []

    # --- Layer 1: a value we were given, still present. ---
    folded = _fold(text)
    survivors = {value for value in _declared_values(known) if value in folded}
    if survivors:
        lengths = sorted(len(value) for value in survivors)
        risks.append(
            f"{len(survivors)} value(s) this document declared are still present "
            f"after redaction, of {_span(lengths)}. These were handed to the "
            "scrubber by name, so this is a redaction that did not fire rather "
            "than a limit of the method. Not quoted here: this report travels "
            "with the dataset."
        )

    # --- Layer 2: something still where a name is declared to be. ---
    labelled = [
        match.group("value").strip()
        for match in _LABELLED_NAME.finditer(text)
        if _looks_unredacted(match.group("value"))
    ]
    titled = [
        match.group("value").strip()
        for match in _TITLED_NAME.finditer(text)
        if _looks_unredacted(match.group("value"))
    ]
    if labelled or titled:
        risks.append(
            f"{len(labelled) + len(titled)} field(s) that declare a person's name "
            "still carry one after redaction, in whatever case the source wrote "
            "it. Detected by position rather than by recognising the name, which "
            "is why case and accents do not hide it."
        )

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
    capitalised = {word for word in _WORD.findall(text) if word.isupper()}
    capitalised -= _PROSE_HEADINGS
    capitalised -= {
        word for placeholder in _ALL_PLACEHOLDERS for word in _WORD.findall(placeholder)
    }
    if capitalised:
        # Counted, not quoted. These tokens are by construction the ones most
        # likely to *be* identifiers, and this list is written into
        # `.deident/manifest.json`, which is the document sent to an access
        # body. A residual-risk report that prints the values it is warning
        # about hands over the very strings it says it could not remove.
        #
        # `commissura measure` found this: a patient's surname appeared in the
        # manifest of a dataset in which every other trace of it had been
        # removed, and it was here. The reviewer still gets what they need —
        # `ScrubReport.path` names the document, and the count and length
        # bound say what to look for in it.
        risks.append(
            f"{len(capitalised)} unrecognised all-capitals token(s) remain, of "
            f"{_span(sorted(len(token) for token in capitalised))}. Nothing declared "
            "them, so this is the layer that catches what was not anticipated. Not "
            "quoted here: this report travels with the dataset."
        )
    return risks


def _span(lengths: list[int]) -> str:
    """Describe a set of token lengths without quoting the tokens."""
    if lengths[0] == lengths[-1]:
        return f"{lengths[0]} characters"
    return f"{lengths[0]} to {lengths[-1]} characters"


def _looks_unredacted(value: str) -> bool:
    """Return whether a declared-name field still holds something worth reporting.

    False for a value that is only placeholders, which is what a successful
    redaction leaves, and false for something too short to be a name — the same
    floor the scrubber refuses to replace below, so the detector is not scored
    on an exam the method was not given.
    """
    remaining = value
    for placeholder in _ALL_PLACEHOLDERS:
        remaining = remaining.replace(placeholder, " ")
    remaining = re.sub(r"\[day_offset:-?\d+\]", " ", remaining)
    return any(len(word) >= _MINIMUM_REDACTABLE for word in _WORD.findall(remaining))
