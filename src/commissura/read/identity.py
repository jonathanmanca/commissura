"""Who a record belongs to, decided once and refused when it cannot be.

This module exists because the pipeline had a layer for parsing, a layer for
de-identifying, a layer for writing and a layer for validating, and no layer for
the step between parsing and de-identifying: deciding who is who. That step was
two dictionaries and four lookups inside ``read_corpus``, and everything
downstream trusted its answer without being able to check it.

**Why that is the most dangerous place in the pipeline.** Targeted redaction
removes the identifiers the structured exports declared *for that subject*. So a
grouping error does not merely mis-attribute a record — it changes what gets
redacted. Two people merged under one key leave only one identity in the known
set, and the second person's name is never looked for. That is not a theory: the
audit of 2026-11-13 built a dataset containing ``Paziente: FRANCESCA FONTANA``
from two messages whose national identifier was the string ``UNKNOWN``, with no
error, no warning and no linkage issue.

Three rules follow, and they are the whole of this module's policy.

**Missing identity is not shared identity.** Two records that both fail to say
who they belong to have told you nothing in common. The old code keyed a subject
on the raw string, so every record carrying the same sentinel became one person.
A value that is absent, a placeholder, or structurally impossible is therefore
never an identity key — it is a *diagnosis*, recorded as such, and the record
falls back to another key or is refused.

**A record number belongs to the institution that issued it.** A medical record
number is a hospital's own number and two hospitals both number their patients
from 1, so an unscoped index is wrong in any corpus assembled from more than one
site. The assigning authority is in PID-3 component 4 and the sending facility
is in MSH-4; both were already parsed and then discarded at the point where they
mattered. Here they are part of the key.

**An ambiguity is refused, not resolved.** Where one scoped record number maps
to two different people, every record that would resolve through it becomes a
finding. Not the first, not the last, not the one whose filename sorted higher.
The result depends only on the set of inputs, never on the order they were read.

**On what this does not change.** A subject established from a valid codice
fiscale gets the same pseudonymous label it got before, because the derivation
input is the normalised identifier and a well-formed codice fiscale normalises
to itself — verified on two corpora, not assumed. The cases that *do* change,
and what a holder has to do about them, are in
:data:`commissura.deident.pseudonymise.RULE_VERSION`.

**What is deliberately not validated**, because the omissions matter as much as
the rules: only the codice fiscale has a validator, so an ENI or STP code or any
other country's national identifier falls back to a scoped record number and is
not relinkable across institutions. The place code is not checked against a
registry of municipalities — this project's own synthetic identifiers use the
unassigned ``X`` range precisely so they are well formed and cannot belong to
anybody, and a registry would also reject identifiers issued before a
municipality was merged or renamed. ``source.subject_keys`` in the manifest is
how a reader finds out which subjects rest on which kind of key.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Final, Protocol

from commissura.identifiers import CF_MONTH_LETTERS, cf_check_character

CODICE_FISCALE_LENGTH: Final = 16
"""A codice fiscale is sixteen characters. Nothing else is one."""

_OMOCODIA_DIGIT_POSITIONS: Final = (6, 7, 9, 10, 12, 13, 14)
"""Zero-indexed positions that hold digits in a plain codice fiscale.

Year (7-8), day (10-11) and the numeric part of the place code (13-15), counting
from one. These are the seven positions the *omocodia* rule may substitute.
"""

_OMOCODIA_SUBSTITUTIONS: Final[dict[str, str]] = {
    "L": "0", "M": "1", "N": "2", "P": "3", "Q": "4",
    "R": "5", "S": "6", "T": "7", "U": "8", "V": "9",
}  # fmt: skip
"""The official letter-for-digit substitutions, per DM 23 December 1976.

When two people would be assigned the same codice fiscale, the Agenzia delle
Entrate replaces digits with these letters, from the rightmost digit leftwards.
A validator that does not know this rejects genuine identifiers — which is why
this table is here and not a simplification. The check character is computed
over the *substituted* form, so structure is validated after reversing the
substitution and the checksum is validated on the value as issued.
"""

PLACEHOLDER_IDENTIFIERS: Final[frozenset[str]] = frozenset(
    {
        "ANONIMO",
        "DUMMY",
        "IGNOTO",
        "NA",
        "N/A",
        "NOCF",
        "NONE",
        "NULL",
        "SCONOSCIUTO",
        "TBD",
        "TEMP",
        "TEST",
        "UNK",
        "UNKNOWN",
        "XXX",
    }
)
"""Values a real interface writes when it has no identifier to send.

Not hypothetical and not rare: an export whose source system allows a blank
identifier will fill it with one of these, and every patient in that export then
carries the same one. Listed explicitly rather than inferred, because a
structural test alone cannot tell ``UNKNOWN`` from a short malformed code, and
the two deserve different diagnoses.

Matched after normalisation, so case and whitespace variants are covered. A
value whose characters are all the same (``0000000000000000``, ``XXXXXXXXXXXX``)
is treated as a placeholder too, by :func:`_is_placeholder`, because enumerating
every repeat length would be absurd.
"""

_WHITESPACE = re.compile(r"\s+")


class IdentifierStatus(StrEnum):
    """What a value handed to us as a national identifier turned out to be.

    Only :attr:`VALID` may become an identity key. The rest are diagnoses, each
    reported under its own name so that an operator knows whether to go and fix
    an export's mapping, its source data, or a single message.
    """

    VALID = "valid"
    MISSING = "missing"
    PLACEHOLDER = "placeholder"
    MALFORMED = "malformed"
    BAD_CHECKSUM = "bad_checksum"


class KeyKind(StrEnum):
    """Which kind of identifier established a subject.

    Recorded in the manifest per subject, because a reader needs to know whether
    a subject is relinkable across institutions — a national identifier is, an
    institution-scoped record number is not.
    """

    NATIONAL_ID = "national_id"
    SCOPED_RECORD_NUMBER = "scoped_record_number"


UNSCOPED_AUTHORITY: Final = "(unscoped)"
"""The namespace for record numbers whose assigning authority is unknown.

An authority is never invented. When a message names none, its record numbers
share this one namespace, which is right for the single-site export that is the
common case — and where two different people then share a number, the ambiguity
check refuses both rather than guessing. The value is parenthesised so it cannot
collide with a real facility name.
"""


@dataclass(frozen=True, slots=True)
class NationalIdentifier:
    """A value offered as a national identifier, and what it actually is.

    Attributes:
        raw: Exactly what the message carried, kept for diagnostics and for
            targeted redaction. Never used as an identity key.
        normalised: The canonical form, or an empty string if there was nothing
            to canonicalise.
        status: The verdict.
    """

    raw: str
    normalised: str
    status: IdentifierStatus

    @property
    def is_usable(self) -> bool:
        """Return whether this value may establish a subject."""
        return self.status is IdentifierStatus.VALID


@dataclass(frozen=True, slots=True, order=True)
class IdentityKey:
    """What makes two records the same person, and on whose authority.

    Ordered so that a corpus's subjects can be emitted in a stable sequence
    without the caller sorting on a tuple it has to assemble itself.

    Attributes:
        kind: Which identifier established the subject.
        authority: The assigning authority, for a scoped record number. Empty
            for a national identifier, which is national by definition.
        value: The normalised identifier.
    """

    kind: KeyKind
    authority: str
    value: str

    @classmethod
    def national(cls, value: str) -> IdentityKey:
        """Return a key for a validated, normalised national identifier."""
        return cls(kind=KeyKind.NATIONAL_ID, authority="", value=value)

    @classmethod
    def scoped_record_number(cls, authority: str, value: str) -> IdentityKey:
        """Return a key for a record number within one assigning authority."""
        return cls(
            kind=KeyKind.SCOPED_RECORD_NUMBER,
            authority=authority or UNSCOPED_AUTHORITY,
            value=value,
        )

    @property
    def derivation_input(self) -> str:
        """Return the string the pseudonymiser derives a subject label from.

        For a national identifier this is the identifier itself, which is what
        keeps every label this tool has ever issued from a well-formed codice
        fiscale unchanged. For a scoped record number the authority is part of
        the input, because the same number at two hospitals is two people and
        must not produce one label.
        """
        if self.kind is KeyKind.NATIONAL_ID:
            return self.value
        return f"{self.authority}|{self.value}"


class RefusalReason(StrEnum):
    """Why a record could not be attached to anybody.

    These are the values that reach ``.deident/manifest.json`` as linkage-issue
    reasons, so they are an interface. Enumerated here rather than written as
    literals at each construction site: the manifest's reader has to know the
    whole set, and a set that exists only as scattered string literals cannot be
    documented or pinned by a test.
    """

    UNREADABLE_LAB_MESSAGE = "unreadable_lab_message"
    UNREADABLE_REPORT = "unreadable_report"
    UNREADABLE_IMAGING_METADATA = "unreadable_imaging_metadata"
    NO_USABLE_IDENTIFIER = "no_usable_identifier"
    INVALID_NATIONAL_IDENTIFIER = "invalid_national_identifier"
    AMBIGUOUS_RECORD_NUMBER = "ambiguous_record_number"
    UNLINKED_REPORT = "unlinked_report"
    UNLINKED_IMAGING = "unlinked_imaging"
    CONFLICTING_IDENTITY = "conflicting_identity"
    CONFLICTING_REPORT_NAME = "conflicting_report_name"


def report_name_conflicts(declared: str, known: Iterable[str]) -> bool:
    """Return whether a report's declared name looks like a different person.

    **The policy, and it is deliberately conservative.** A conflict is reported
    only when the declared name shares *no* redactable word with any name the
    subject is known by. Comparison is on the set of words, folded, so order
    does not matter: a header writing ``ROSSI MARIO`` where the laboratory
    message said ``MARIO ROSSI`` is the same person written the other way round
    and must not be reported, and nor is ``MARIA LUISA DE LUCA`` against
    ``DE LUCA MARIA LUISA``.

    What that deliberately does not report: an abbreviated given name
    (``M. ROSSI``), a middle name present in one source and not the other, a
    married name alongside a maiden name. Each shares a surname, and each is
    far more often one person recorded twice than two people confused. Crying
    wolf on those would bury the case this exists for — a document filed
    against the wrong patient, where the two names have nothing in common.

    Redaction does not depend on this answer. The declared name is removed
    either way; this only decides whether the discrepancy is *reported*, which
    it must be, because a name that disagrees can mean the document belongs to
    somebody else and no amount of redacting makes that right.

    Args:
        declared: The name the report's header carried.
        known: Every name the subject is known by, from its identities.

    Returns:
        Whether to report a conflict.
    """
    declared_words = {
        _fold_name(word) for word in declared.split() if len(word) >= _COMPARABLE_NAME_LENGTH
    }
    if not declared_words:
        return False
    for name in known:
        shared = declared_words & {
            _fold_name(word) for word in name.split() if len(word) >= _COMPARABLE_NAME_LENGTH
        }
        if shared:
            return False
    return True


_COMPARABLE_NAME_LENGTH: Final = 4
"""Below this a name fragment is not worth comparing.

The same floor the scrubber refuses to replace at, for the same reason: a
two-letter particle matches inside ordinary words, so ``DI`` shared between two
names is not evidence that they are the same person.
"""


def _fold_name(value: str) -> str:
    """Return a name fragment in the form two spellings of it compare equal in."""
    return unicodedata.normalize("NFKD", value).casefold()


REASON_KEEPS_RECORD: Final[dict[RefusalReason, bool]] = {
    RefusalReason.UNREADABLE_LAB_MESSAGE: False,
    RefusalReason.UNREADABLE_REPORT: False,
    RefusalReason.UNREADABLE_IMAGING_METADATA: False,
    RefusalReason.NO_USABLE_IDENTIFIER: False,
    RefusalReason.AMBIGUOUS_RECORD_NUMBER: False,
    RefusalReason.UNLINKED_REPORT: False,
    RefusalReason.UNLINKED_IMAGING: False,
    RefusalReason.INVALID_NATIONAL_IDENTIFIER: True,
    RefusalReason.CONFLICTING_IDENTITY: True,
    RefusalReason.CONFLICTING_REPORT_NAME: True,
}
"""Whether a record reported under each reason still reached the dataset.

**This exists because the manifest was overstating how many records were
absent, and no corpus produced the reasons that made it wrong.**
``source.records_not_in_dataset`` was defined on 2026-11-12 as the linkage
issues plus the dropped records, which was correct then: every reason that
existed meant a record that could not be attached to anybody. Three reasons
added since attach the record *and* report it — an unusable national identifier
rescued by a scoped record number, two messages disagreeing about who one
identifier belongs to, and a report header naming somebody else. For those the
record is in the dataset and merely suspect.

So the number was wrong from 2026-11-13, and the first corpus to show it was the
one generated once ``lab.conflicting_identity`` and ``reports.wrong_patient_name``
existed: 190 records all linked, 3 genuinely absent, and a manifest claiming 32.

Looked up **without a default**, like
:data:`commissura.build.manifest.CATEGORY_DISPOSITION`, so a reason added
without declaring which side it falls on raises ``KeyError`` and stops the
build. A manifest that guessed would be worse than a build that stopped, and
the guess would be in the one document written to be believed.
"""


@dataclass(frozen=True, slots=True)
class Refusal:
    """A resolution that did not succeed, with the reason and a detail.

    The detail is for a human reading a terminal. It never reaches the manifest:
    an unlinked report's detail names the identifier it could not match, and
    that identifier is patient data. The decision is recorded in the log of
    2026-11-12.
    """

    reason: RefusalReason
    detail: str


def normalise_national_id(raw: str) -> str:
    """Return the canonical form of a value offered as a national identifier.

    Three transformations, each safe for a codice fiscale and each chosen
    because leaving it out caused a real failure:

    * **NFKC** folds the compatibility forms a copy-and-paste from a PDF or a
      spreadsheet introduces — full-width Latin letters most of all, which look
      identical and compare unequal.
    * **All whitespace removed, not only surrounding.** The reader already
      stripped the ends. An internal space or a non-breaking space survived it
      and produced a second subject for one person.
    * **Uppercased.** A codice fiscale is conventionally uppercase and a sender
      is not obliged to send it that way. The audit of 2026-11-13 showed one
      person becoming two subjects, with two different baselines, from a case
      difference alone.

    Nothing else. A cleverer normaliser would start merging identifiers that are
    not the same identifier, and in this direction a false match is far worse
    than a miss.

    Args:
        raw: The value as the message carried it.

    Returns:
        The canonical form, possibly empty.
    """
    folded = unicodedata.normalize("NFKC", raw)
    return _WHITESPACE.sub("", folded).upper()


def _is_placeholder(normalised: str) -> bool:
    """Return whether a normalised value is a stand-in rather than an identifier."""
    if normalised in PLACEHOLDER_IDENTIFIERS:
        return True
    # A run of one repeated character is a placeholder at any length: 0000...,
    # XXXX..., ----. Enumerating the lengths would be absurd and would miss one.
    return len(set(normalised)) == 1


def classify_national_id(raw: str) -> NationalIdentifier:
    """Decide what a value offered as a national identifier actually is.

    The order of the tests is the useful part. Absence, then a known stand-in,
    then structure, then the check character — so the diagnosis names the
    earliest thing that is wrong, which is the thing an operator can act on. A
    checksum failure reported for ``UNKNOWN`` would send somebody looking for a
    transcription error in a field that was never filled in.

    Args:
        raw: The value as the message carried it.

    Returns:
        The value, its canonical form and the verdict.
    """
    normalised = normalise_national_id(raw)
    if not normalised:
        return NationalIdentifier(raw, normalised, IdentifierStatus.MISSING)
    if _is_placeholder(normalised):
        return NationalIdentifier(raw, normalised, IdentifierStatus.PLACEHOLDER)
    return NationalIdentifier(raw, normalised, _codice_fiscale_status(normalised))


def _codice_fiscale_status(value: str) -> IdentifierStatus:
    """Return whether a normalised value is a well-formed codice fiscale."""
    if len(value) != CODICE_FISCALE_LENGTH or not value.isalnum() or not value.isascii():
        return IdentifierStatus.MALFORMED

    plain = _reverse_omocodia(value)
    if plain is None:
        return IdentifierStatus.MALFORMED
    if not _structure_is_valid(plain):
        return IdentifierStatus.MALFORMED
    # The check character covers the value as issued, substitutions included.
    if value[15] != cf_check_character(value[:15]):
        return IdentifierStatus.BAD_CHECKSUM
    return IdentifierStatus.VALID


def _reverse_omocodia(value: str) -> str | None:
    """Return the value with substituted letters turned back into digits.

    Args:
        value: A sixteen-character normalised candidate.

    Returns:
        The de-substituted form, or ``None`` if a position that must hold a
        digit or a substitution letter holds neither.
    """
    chars = list(value)
    for position in _OMOCODIA_DIGIT_POSITIONS:
        char = chars[position]
        if char.isdigit():
            continue
        replacement = _OMOCODIA_SUBSTITUTIONS.get(char)
        if replacement is None:
            return None
        chars[position] = replacement
    return "".join(chars)


def _structure_is_valid(plain: str) -> bool:
    """Return whether a de-substituted codice fiscale has the right shape.

    Checks what the format actually constrains: six letters of name, a month
    from the format's own twelve-letter sequence, a day in range for the sex the
    day encodes, and a place code that is a letter followed by three digits.
    Deliberately does **not** check that the place code names a real
    municipality: this project's own synthetic identifiers use the unassigned
    ``X`` range precisely so that they are well formed and cannot belong to
    anybody, and rejecting them would make the validator unusable against the
    only corpus available to test it.
    """
    if not plain[:6].isalpha():
        return False
    if plain[8] not in CF_MONTH_LETTERS:
        return False
    if not plain[11].isalpha():
        return False
    day = int(plain[9:11])
    # Female codes add 40 to the day of birth, which is how the format encodes
    # sex without a separate field.
    return 1 <= day <= 31 or 41 <= day <= 71


@dataclass(frozen=True, slots=True)
class AuthorityScope:
    """Where a record number came from, as the source stated it.

    Attributes:
        assigning_authority: PID-3 component 4, the authority that issued the
            record number. Authoritative when present, because it describes the
            identifier rather than the message.
        sending_facility: MSH-4. A fallback: it names who sent the message,
            which is usually but not always who issued the number.
    """

    assigning_authority: str = ""
    sending_facility: str = ""

    @property
    def authority(self) -> str:
        """Return the authority to scope a record number by, or an empty string.

        Never invents one. An export that names neither gets
        :data:`UNSCOPED_AUTHORITY` from :meth:`IdentityKey.scoped_record_number`,
        and the ambiguity check is what keeps that safe.
        """
        return normalise_authority(self.assigning_authority or self.sending_facility)


def normalise_authority(value: str) -> str:
    """Return the comparable form of an institution name.

    Case and internal spacing only. An institution's name is prose and arrives
    with inconsistent whitespace; it is not an identifier and must not be
    normalised as aggressively as one, because two genuinely different hospitals
    can have names that differ in little more than punctuation.

    Args:
        value: The name as the source gave it.

    Returns:
        The comparable form, possibly empty.
    """
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", value)).strip().upper()


def normalise_record_number(value: str) -> str:
    """Return the comparable form of a medical record number.

    Strips surrounding whitespace and leading zeros and folds case, which is
    what recovers the ``imaging.mrn_format_drift`` defect: the same patient as
    ``0012345`` in one export and ``12345`` in another.

    That stripping widens the collision surface, which is why it may only be
    applied **within** an assigning authority. ``0012345`` at one hospital and
    ``12345`` at another are now two keys, where a flat index made them one.

    Args:
        value: The number as the source gave it.

    Returns:
        The comparable form, possibly empty.
    """
    return _WHITESPACE.sub("", unicodedata.normalize("NFKC", value)).lstrip("0").upper()


class PatientFacts(Protocol):
    """The four fields identity resolution needs from a parsed record.

    A protocol rather than an import of :class:`commissura.read.corpus.Identity`,
    which would be a cycle: the corpus module imports this one. Structural
    typing is the right tool here for a second reason as well — this module
    decides identity and has no business knowing the shape of a laboratory
    record.
    """

    @property
    def national_id(self) -> str:
        """The value offered as a national identifier."""

    @property
    def mrn(self) -> str:
        """The medical record number."""

    @property
    def family_name(self) -> str:
        """The family name."""

    @property
    def birth_date(self) -> date | None:
        """The date of birth, if the record carried a readable one."""


def identities_conflict(left: PatientFacts, right: PatientFacts) -> bool:
    """Return whether two identities disagree about who the person is.

    Only on facts a valid codice fiscale itself encodes — family name and birth
    date. A difference in the record number is normal across institutions, and a
    difference in the given name is common enough in real exports (a middle
    name, an abbreviation) that reporting it would bury the cases that matter.

    Args:
        left: One identity.
        right: Another.

    Returns:
        Whether they disagree materially.
    """
    if (
        left.family_name
        and right.family_name
        and normalise_authority(left.family_name) != normalise_authority(right.family_name)
    ):
        return True
    return bool(left.birth_date and right.birth_date and left.birth_date != right.birth_date)


@dataclass(slots=True)
class IdentityIndex:
    """Resolves records to identity keys, or refuses and says why.

    Mutable, because resolution is stateful: the second record carrying a record
    number is what reveals that the number is ambiguous. The mutation is
    monotone — a key never stops being ambiguous once it is — so the result
    depends on the *set* of records seen and not on their order. That is the
    property the old code lacked, where the last assignment won and "last" meant
    whichever filename sorted highest.
    """

    _by_record_number: dict[tuple[str, str], IdentityKey] = field(default_factory=dict)
    _ambiguous: set[tuple[str, str]] = field(default_factory=set)
    _findings: list[Refusal] = field(default_factory=list)

    def establish(
        self, identity: PatientFacts, scope: AuthorityScope
    ) -> tuple[IdentityKey, NationalIdentifier] | Refusal:
        """Decide which subject a laboratory record belongs to.

        A laboratory message is what creates a subject, because it is the only
        source that carries a national identifier. This is therefore the one
        place a new key may be minted.

        Args:
            identity: What the message said about the patient.
            scope: The institution the message came from.

        Returns:
            The key and the classified national identifier, or a refusal.
        """
        classified = classify_national_id(identity.national_id)
        if classified.is_usable:
            key = IdentityKey.national(classified.normalised)
            self._register_record_number(identity.mrn, scope, key)
            return key, classified

        # The national identifier is unusable. It is never a key -- two records
        # that both failed to say who they belong to have nothing in common --
        # but the record number may still identify the patient within the
        # institution that issued it.
        number = normalise_record_number(identity.mrn)
        if not number:
            return Refusal(
                RefusalReason.NO_USABLE_IDENTIFIER,
                f"the national identifier is {classified.status.value} and there is "
                "no medical record number to fall back on",
            )
        key = IdentityKey.scoped_record_number(scope.authority, number)
        self._register_record_number(identity.mrn, scope, key)
        return key, classified

    def _register_record_number(self, mrn: str, scope: AuthorityScope, key: IdentityKey) -> None:
        """Record that this scoped record number belongs to this subject.

        Never overwrites. A second subject claiming the same scoped number marks
        it ambiguous, and from then on nothing resolves through it — including
        the record that claimed it first, whose own linkage was established by
        its national identifier and is unaffected.
        """
        number = normalise_record_number(mrn)
        if not number:
            return
        authority = scope.authority or UNSCOPED_AUTHORITY
        # Registered twice when the authority is known: once scoped, and once in
        # the unscoped namespace. A report header names no facility and a DICOM
        # header may name none, so those sources can only look a number up
        # unscoped -- and in a single-site corpus that must still work. Where two
        # institutions share a number the unscoped entry becomes ambiguous and
        # resolves to nothing, which is the refusal we want: the scoped lookups
        # still succeed for whoever can name their institution.
        namespaces = {authority, UNSCOPED_AUTHORITY}
        for namespace in namespaces:
            index = (namespace, number)
            existing = self._by_record_number.get(index)
            if existing is None:
                self._by_record_number[index] = key
            elif existing != key:
                self._ambiguous.add(index)

    def resolve_record_number(self, mrn: str, scope: AuthorityScope) -> IdentityKey | Refusal:
        """Find the subject a record number belongs to, within its authority.

        Args:
            mrn: The record number as the source gave it.
            scope: The institution the record came from.

        Returns:
            The key, or a refusal naming why the lookup could not be trusted.
        """
        number = normalise_record_number(mrn)
        if not number:
            return Refusal(
                RefusalReason.NO_USABLE_IDENTIFIER, "the record carries no record number"
            )
        index = (scope.authority or UNSCOPED_AUTHORITY, number)
        if index in self._ambiguous:
            return Refusal(
                RefusalReason.AMBIGUOUS_RECORD_NUMBER,
                f"record number {mrn!r} is used by more than one person at "
                f"{index[0]}, so this record cannot be attributed to either",
            )
        found = self._by_record_number.get(index)
        if found is None:
            return Refusal(
                RefusalReason.NO_USABLE_IDENTIFIER,
                f"no subject holds record number {mrn!r} at {index[0]}",
            )
        return found

    def ambiguous_record_numbers(self) -> tuple[tuple[str, str], ...]:
        """Return every scoped record number that more than one person claimed."""
        return tuple(sorted(self._ambiguous))
