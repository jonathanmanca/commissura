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

**An identifier is one of several kinds, keyed by who issued it.** The codice
fiscale is the Italian case and not the only one. HL7 Italia's CDA R2 laboratory
report names five mutually exclusive possibilities for `patientRole/id` — the
codice fiscale, a TEAM card plus personal number for somebody insured abroad, an
ENI code for a European not enrolled in the SSN, an STP code for a foreigner
temporarily present, and an ANA code — each distinguished by the OID in
`id/@root`. FHIR expresses the same model with `identifier.system`. So
:class:`PatientIdentifierKind` and :func:`classify_patient_identifier` live here,
beside :func:`classify_national_id`, while the table mapping a *root OID* to a
kind lives in the reader for the format that spells it that way. That split is
deliberate: the kinds and their structural rules are identity policy, and the
spelling is a property of the document format.

**Only the codice fiscale has a checksum, and the others are checked for what
their own specification states and nothing more.** An ENI or STP code is sixteen
characters and must begin with those three letters, which is a rule worth
applying because it recognises the kind even when the issuing OID is a regional
one this tool cannot know. A TEAM extension is an ISO 3166-1 alpha-3 country
code, a dot, and a number. An ANA code has no published structure at all, so it
is checked for presence and for not being a placeholder, and nothing is invented
beyond that.

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


class PatientIdentifierKind(StrEnum):
    """Which of the recognised kinds of patient identifier a value is.

    The five named kinds are the cases HL7 Italia's CDA R2 laboratory report
    enumerates for ``recordTarget/patientRole/id``, and they are mutually
    exclusive by that specification's own wording. TEAM is two kinds rather than
    one because the specification requires **two** ``id`` elements for it and
    they are not interchangeable: the card number identifies a card, which can
    be reissued, and only the personal number identifies the person. Keying a
    subject on a card number would split one patient across two cards.

    :attr:`UNRECOGNISED` is a verdict and not a failure. An export may carry a
    regional identifier under an OID this tool has never seen, and saying so is
    more useful than refusing to classify it.
    """

    CODICE_FISCALE = "codice_fiscale"
    TEAM_CARD = "team_card"
    TEAM_PERSONAL = "team_personal"
    ENI = "eni"
    STP = "stp"
    ANA = "ana"
    UNRECOGNISED = "unrecognised"


class KeyKind(StrEnum):
    """Which kind of identifier established a subject.

    Recorded in the manifest per subject, because a reader needs to know whether
    a subject is relinkable across institutions — a national identifier is, an
    institution-scoped record number is not.

    :attr:`ASSIGNED_IDENTIFIER` is the middle case and exists because collapsing
    it into either neighbour would state something false. An ENI code assigned
    nationally *is* relinkable across every institution in Italy, so calling it
    an institution-scoped record number would understate it; it carries no
    checksum and its namespace may be one region's, so calling it a national
    identifier would overstate it. The authority is the issuing namespace as the
    document declared it.
    """

    NATIONAL_ID = "national_id"
    SCOPED_RECORD_NUMBER = "scoped_record_number"
    ASSIGNED_IDENTIFIER = "assigned_identifier"


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

    @classmethod
    def assigned_identifier(cls, authority: str, value: str) -> IdentityKey:
        """Return a key for an identifier issued under a declared namespace.

        Args:
            authority: The issuing namespace exactly as the document declared
                it — for CDA, the OID in ``id/@root``. Never invented: an
                identifier of this kind is meaningless without the namespace
                that scopes it, so a caller with no namespace to offer must not
                use this constructor.
            value: The normalised identifier.
        """
        return cls(
            kind=KeyKind.ASSIGNED_IDENTIFIER,
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

        **A third kind has to name itself, and the reason is the other two.**
        Those two forms are fixed by the labels already issued from them, so a
        new kind cannot adopt either without moving existing labels. An assigned
        identifier therefore prefixes its kind, which also makes it impossible
        for an OID-scoped code to collide with a record number at a facility
        whose name happened to be that OID.
        """
        if self.kind is KeyKind.NATIONAL_ID:
            return self.value
        if self.kind is KeyKind.SCOPED_RECORD_NUMBER:
            return f"{self.authority}|{self.value}"
        return f"{self.kind.value}|{self.authority}|{self.value}"


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
    UNREADABLE_CDA_DOCUMENT = "unreadable_cda_document"
    NO_USABLE_IDENTIFIER = "no_usable_identifier"
    INVALID_NATIONAL_IDENTIFIER = "invalid_national_identifier"
    MISDECLARED_IDENTIFIER_NAMESPACE = "misdeclared_identifier_namespace"
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
    RefusalReason.UNREADABLE_CDA_DOCUMENT: False,
    RefusalReason.NO_USABLE_IDENTIFIER: False,
    RefusalReason.AMBIGUOUS_RECORD_NUMBER: False,
    RefusalReason.UNLINKED_REPORT: False,
    RefusalReason.UNLINKED_IMAGING: False,
    RefusalReason.INVALID_NATIONAL_IDENTIFIER: True,
    RefusalReason.MISDECLARED_IDENTIFIER_NAMESPACE: True,
    RefusalReason.CONFLICTING_IDENTITY: True,
    RefusalReason.CONFLICTING_REPORT_NAME: True,
}
"""Whether a record reported under each reason still reached the dataset.

**This exists because the manifest was overstating how many records were
absent, and no corpus produced the reasons that made it wrong.**
``source.records_not_in_dataset`` was defined on 2026-11-12 as the linkage
issues plus the dropped records, which was correct then: every reason that
existed meant a record that could not be attached to anybody. Four reasons
added since attach the record *and* report it — an unusable national identifier
rescued by a scoped record number, two messages disagreeing about who one
identifier belongs to, a report header naming somebody else, and a CDA document
declaring its codice fiscale under the wrong namespace. For those the record is
in the dataset and merely suspect.

A reason on this side of the table never implies the record is present on its
own: it says that *this* diagnosis did not remove it. A document whose namespace
was misdeclared and which nothing else could key then also produces
:attr:`RefusalReason.NO_USABLE_IDENTIFIER`, which is on the other side and is
what counts the absence. So the two reasons co-exist on one file without
double-counting it.

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


ASSIGNED_CODE_LENGTH: Final = 16
"""Length of an ENI or STP code, per the CDA R2 laboratory specification.

Both tables state sixteen characters. The same length as a codice fiscale, which
is a coincidence and not a shared rule, so the two are checked separately.
"""

ASSIGNED_CODE_PREFIX: Final[dict[PatientIdentifierKind, str]] = {
    PatientIdentifierKind.ENI: "ENI",
    PatientIdentifierKind.STP: "STP",
}
"""The three letters an ENI or STP code must begin with, and what it means.

**This is what makes a regionally-assigned code usable.** The specification
fixes a national OID for each kind but allows "l'OID locale assegnato
dall'organizzazione che ha rilasciato il codice identificativo" when the code is
assigned regionally, so a reader cannot recognise those by namespace. It can
recognise them by this prefix, because the specification requires it in the same
table: the extension "Deve iniziare con la stringa" ``ENI`` or ``STP``.

So this is reading a stated rule, not guessing from a pattern. The alternative
would be refusing every regionally-assigned code, which is to say refusing
exactly the population these codes exist for.
"""

_TEAM_COUNTRY_LENGTH: Final = 3
"""An ISO 3166-1 alpha-3 country code prefixes every TEAM extension."""


@dataclass(frozen=True, slots=True)
class PatientIdentifier:
    """One ``patientRole/id``, classified: what kind it is and whether it works.

    Two axes rather than one, because they answer different questions. The
    *kind* says which of the specification's five cases this is, which decides
    how it may key a subject. The *status* says whether this particular value is
    fit to be used at all, and reuses the same vocabulary a national identifier
    is judged by, so that a placeholder is a placeholder whatever kind it was
    offered as.

    Attributes:
        kind: Which recognised kind of identifier this is.
        authority: The issuing namespace as the document declared it, which for
            CDA is ``id/@root``. Never invented.
        raw: Exactly what the document carried, kept for targeted redaction.
        normalised: The canonical form, or an empty string.
        status: Whether the value may establish a subject.
    """

    kind: PatientIdentifierKind
    authority: str
    raw: str
    normalised: str
    status: IdentifierStatus

    @property
    def is_usable(self) -> bool:
        """Return whether this value may establish a subject."""
        return self.status is IdentifierStatus.VALID

    @property
    def keys_a_person(self) -> bool:
        """Return whether this kind identifies a person rather than a document.

        False for a TEAM card number. The specification requires both TEAM ids
        and only the personal one names the holder: a card is reissued on expiry
        or loss, so two cards for one patient would become two subjects, and two
        patients handed the same recycled serial would become one. The card
        number is still read, still redacted, and never a key.
        """
        return self.kind is not PatientIdentifierKind.TEAM_CARD


def classify_patient_identifier(
    kind: PatientIdentifierKind, authority: str, raw: str
) -> PatientIdentifier:
    """Decide whether a value offered as ``kind`` is fit to establish a subject.

    The order of the tests mirrors :func:`classify_national_id` and for the same
    reason: absence, then a known stand-in, then whatever structure the kind's
    own specification states. A placeholder is caught before any structural rule
    because an export writing ``UNKNOWN`` into an ENI field has told us nothing
    about the patient, and the diagnosis an operator can act on is that the
    field was never filled in.

    Args:
        kind: Which kind the document declared this value to be.
        authority: The issuing namespace, as declared.
        raw: The value as the document carried it.

    Returns:
        The classified identifier.
    """
    normalised = normalise_national_id(raw)
    if not normalised:
        return PatientIdentifier(kind, authority, raw, normalised, IdentifierStatus.MISSING)
    if _is_placeholder(normalised):
        return PatientIdentifier(kind, authority, raw, normalised, IdentifierStatus.PLACEHOLDER)
    return PatientIdentifier(kind, authority, raw, normalised, _assigned_status(kind, normalised))


def _assigned_status(kind: PatientIdentifierKind, normalised: str) -> IdentifierStatus:
    """Return whether a normalised value satisfies its own kind's structure.

    Only what each specification actually states. **ANA is deliberately checked
    for nothing beyond presence**: the laboratory specification fixes its root
    OID and defers every further detail to a later release, so there is no
    published rule to apply and inventing one would reject genuine codes. Same
    for an unrecognised namespace, where by definition no rule is known.
    """
    if kind is PatientIdentifierKind.CODICE_FISCALE:
        return _codice_fiscale_status(normalised)
    expected = ASSIGNED_CODE_PREFIX.get(kind)
    if expected is not None:
        if len(normalised) != ASSIGNED_CODE_LENGTH or not normalised.startswith(expected):
            return IdentifierStatus.MALFORMED
        return IdentifierStatus.VALID
    if kind in {PatientIdentifierKind.TEAM_CARD, PatientIdentifierKind.TEAM_PERSONAL}:
        return _team_status(normalised)
    return IdentifierStatus.VALID


def _team_status(normalised: str) -> IdentifierStatus:
    """Return whether a TEAM extension has the shape the specification states.

    An ISO 3166-1 alpha-3 country code, a dot, then the number. **Split on the
    first dot only**: the specification's own worked example of a card number is
    ``NLD.096074309.80528070070000000001``, whose serial contains a further dot,
    so splitting on every dot would reject the example the specification gives.

    The country code is checked for shape and not against the ISO list. A
    registry would reject a code issued before a country was renamed, which is
    the same reason the codice fiscale's place code is not checked against a
    list of municipalities.
    """
    country, dot, number = normalised.partition(".")
    if not dot or len(country) != _TEAM_COUNTRY_LENGTH or not country.isalpha():
        return IdentifierStatus.MALFORMED
    return IdentifierStatus.VALID if number else IdentifierStatus.MALFORMED


def kind_from_assigned_code(raw: str) -> PatientIdentifierKind | None:
    """Return the kind a value declares by its own prefix, if it declares one.

    For the case the specification creates and does not solve: an ENI or STP
    code assigned regionally carries a local OID, so the namespace cannot
    identify the kind and the value has to. Returns ``None`` when nothing is
    declared, which is the honest answer for a code under a namespace this tool
    does not know.

    Args:
        raw: The value as the document carried it.

    Returns:
        The kind, or ``None``.
    """
    normalised = normalise_national_id(raw)
    if len(normalised) != ASSIGNED_CODE_LENGTH:
        return None
    for kind, prefix in ASSIGNED_CODE_PREFIX.items():
        if normalised.startswith(prefix):
            return kind
    return None


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
        self,
        identity: PatientFacts,
        scope: AuthorityScope,
        *,
        assigned: Iterable[PatientIdentifier] = (),
    ) -> tuple[IdentityKey, NationalIdentifier] | Refusal:
        """Decide which subject a laboratory record or CDA document belongs to.

        A laboratory message or a CDA laboratory report is what creates a
        subject, because those are the sources that carry a national
        identifier. This is therefore the one place a new key may be minted, and
        it stays one place so that the preference order cannot differ between
        input formats.

        The order is national identifier, then any other identifier the document
        declared under a named namespace, then the institution-scoped record
        number. That ranks relinkability: a codice fiscale links across Italy, an
        ENI or STP code links within whatever namespace issued it, and a record
        number links within one hospital. Taking them in any other order would
        key a subject on something narrower than what the document offered.

        Args:
            identity: What the record said about the patient.
            scope: The institution the record came from.
            assigned: Other identifiers the document declared, in the order the
                reader found them. Only those that identify a *person* and are
                usable are considered; a TEAM card number is neither.

        Returns:
            The key and the classified national identifier, or a refusal.
        """
        classified = classify_national_id(identity.national_id)
        if classified.is_usable:
            key = IdentityKey.national(classified.normalised)
            self._register_record_number(identity.mrn, scope, key)
            return key, classified

        # No usable codice fiscale. An ENI, STP, TEAM personal or ANA code is
        # the next best thing: it has no checksum to verify, but the document
        # named the namespace that issued it, so it is a real key within that
        # namespace rather than a value two silent records would share.
        for candidate in assigned:
            if candidate.is_usable and candidate.keys_a_person:
                key = IdentityKey.assigned_identifier(candidate.authority, candidate.normalised)
                self._register_record_number(identity.mrn, scope, key)
                return key, classified

        # Nothing national and nothing assigned. The identifier we were handed
        # is never a key -- two records that both failed to say who they belong
        # to have nothing in common -- but the record number may still identify
        # the patient within the institution that issued it.
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
