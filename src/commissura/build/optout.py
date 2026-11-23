"""Keep the people who objected out of the dataset, and record that they are.

EHDS Article 71 gives a natural person the right to object to the secondary use
of their electronic health data, and TEHDAS2 D6.1 Annex 6 A6.2 (p. 68) makes
acting on it *Mandatory* for a health data holder, in those words: "Identify and
remove data of natural persons who opted-out." §3.2.1 (p. 16) is the obligation
behind it — where national law provides, holders "must implement and manage the
opt-out mechanism".

Until this module there was nowhere to put that instruction. :mod:`commissura`
could already derive the handle an objection points at — ``commissura whois``
exists for exactly that and says so — and ``build`` then read the whole corpus
and built all of it. So a holder deleted files from the corpus by hand, and if
they missed one nothing noticed; worse, the manifest recorded no exclusion at
all, so **a dataset built after an objection was indistinguishable from one
built before it**. That is the shape of the withdrawal that did not withdraw
(2026-11-13), seen from the documentation side.

**The list holds national identifiers, not subject labels.** Both were
defensible and the decision is this module's reason to exist, so the argument
is here rather than in a commit message:

- *A subject label is scoped to a key and to a permit; an objection is not.* A
  label is ``HMAC(key, "subject|" + identifier)``, and with ``build --permit``
  the key is itself a per-permit subkey. So a file of labels is valid for
  exactly one ``(key, permit)`` pair and, used with any other, matches nobody
  and excludes nobody — silently, which is precisely the failure
  ``commissura whois``'s own guards exist to prevent. An objection is permanent
  and a key can be rotated.
- *A mistyped codice fiscale can be caught; a mistyped label cannot.* Sixteen
  characters with a check character go through
  :func:`commissura.read.identity.classify_national_id` and a transcription
  error is refused by name. Twelve hex characters are twelve hex characters, and
  a holder who mistypes one sees a successful build and has not acted on the
  objection. The dangerous failure here is the one that looks like success.
- *The holder already has the identifier.* An objection arrives from a named
  person. A label has to be derived first, one ``whois`` run per person.

Against it, honestly: the file on disk is a list of patient identifiers, and
specifically a list of people who exercised a right, which is a disclosure in
itself. It sits on the machine that already holds the raw clinical corpus in the
clear, so it is a strictly smaller exposure than what is beside it; it never
enters the dataset; and the manifest records counts and never a value.

**Never subject labels, and never guessed.** Twelve lowercase hex and sixteen
alphanumerics are distinguishable, so a tool *could* accept either and decide
per line. Guessing is how a file gets read in the wrong mode and nobody is
excluded — and the whole value of the identifier form is the check character,
which a guesser gives up the moment it treats an unrecognised value as
"probably a label".

**What the list may name is now any kind of subject key, because a line
declares its own kind.** That is not the thing the paragraph above rejects: a
declared kind is a statement by the holder, where the rejected design would
have inferred one from the shape of a value. Every kind is still validated on
its own terms — a codice fiscale by its check character, a record number by
needing both an authority and a number, an assigned code by its own structure —
so a transcription error is still refused by name rather than silently matching
nobody.

An unprefixed line is a codice fiscale, exactly as before. **A standing
opt-out list accumulates over months and must not need rewriting because the
tool grew**, so the form a holder already has keeps working byte for byte, and
the two new forms are additions to the same file rather than a second file. One
obligation, one list: splitting it by how a hospital happens to identify each
person would make "is this person excluded?" a two-document question.

The prefixes are :class:`commissura.read.identity.KeyKind`'s own values rather
than words invented here, so the file's vocabulary is the model's and cannot
drift from it.

**Refuse what is provably wrong; report what is merely suspicious.** An
unreadable file and a line that is not a usable national identifier are refused
before anything is written, because no legitimate reading of them exists. An
empty list and an entry that matches no subject in this corpus are reported and
not refused, because both have a legitimate reading — nobody has objected yet,
and the person has no records in this export — and the tool cannot tell those
from a mistake. Refusing would be deciding on the holder's behalf, which this
project already declines to do for the access tier and the age band width.

**The limit that used to be here is closed**, and what replaced it is a
narrower one worth stating. A subject this corpus established from an
institution's own record number, or from an ENI, STP or ANA code, carries no
codice fiscale — and could therefore not be reached by any entry at all until
2026-11-23. Now it can, by naming the kind. What is left is that **the holder
has to write the authority exactly as their own exports declare it**: an
institution name for a record number, an issuing OID for an assigned code. Both
are compared in their normalised form, so spacing, case and leading zeros do
not matter, but a different institution name does — and it has to, because two
hospitals' record numbers are deliberately not one namespace.

``build`` prints, per kind, how many subjects a corpus holds, so a holder can
see which authorities are in play before writing a line.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from commissura.read.identity import (
    IdentityKey,
    KeyKind,
    classify_national_id,
    normalise_authority,
    normalise_national_id,
    normalise_record_number,
)

COMMENT_PREFIX: Final = "#"
"""Lines starting with this are ignored, after stripping.

A standing list accumulates over months and a holder will want to say when an
objection arrived and under which ticket. Supporting that costs one condition
and keeps the note beside the identifier rather than in somebody's memory.
"""


FIELD_SEPARATOR: Final = "|"
"""What separates a declared kind from the authority and the value.

A vertical bar rather than a tab, and the reason is the holder rather than the
parser: an institution name arrives with spaces and punctuation, and a tab is
invisible in the file, survives a copy-and-paste badly and is silently rewritten
by most editors. A bar is visible, is not a character any institution has in its
name, and makes a malformed line malformed on sight.
"""


class ExclusionFileError(ValueError):
    """An exclusion list this tool will not act on.

    Raised for the two things that cannot be a legitimate list: a file that
    cannot be read, and a line that is not a usable national identifier. Both
    are refused before the build begins, so a holder learns about them in a
    second rather than after a corpus has been read and a dataset staged.
    """


@dataclass(frozen=True, slots=True)
class Exclusions:
    """The people a holder has said must not appear in this dataset.

    Held as identity keys rather than as raw identifiers so that matching is the
    same comparison the linker made. A subject established from a national
    identifier is keyed on the normalised value, so an entry and a subject agree
    exactly or not at all — no second normalisation policy, and no key material
    needed to decide it.

    Attributes:
        keys: One key per distinct identifier on the list, deduplicated. A
            standing list accumulated over months will repeat entries, and a
            repeated objection is one objection.
    """

    keys: frozenset[IdentityKey]

    def __len__(self) -> int:
        """Return how many distinct people the list names."""
        return len(self.keys)

    def excludes(self, key: IdentityKey) -> bool:
        """Return whether this subject must be left out of the dataset.

        Args:
            key: What established the subject.

        Returns:
            True when the list names them, whichever kind of key established
            them. The comparison is on the whole key -- kind, authority and
            value -- so a record number excluded at one hospital does not
            exclude the same number at another, which is the property
            :func:`commissura.read.identity.normalise_record_number` exists to
            protect.
        """
        return key in self.keys

    def by_kind(self) -> dict[str, int]:
        """Return how many entries name each kind of subject key.

        Counts and never values, so this is safe for the manifest -- and it is
        the one thing an auditor cannot otherwise learn: whether the list a
        holder acted on could reach subjects that no codice fiscale names. A
        kind nobody listed is reported at zero rather than omitted, for the
        reason a declared field the corpus never carried is (2026-11-10).
        """
        counts = {kind.value: 0 for kind in KeyKind}
        for key in self.keys:
            counts[key.kind.value] += 1
        return counts

    def unmatched(self, matched: Iterable[IdentityKey]) -> tuple[str, ...]:
        """Return the normalised identifiers that matched no subject.

        **For the operator's terminal and never for the manifest.** These are
        patient identifiers, and a list of them is a list of people who
        objected.

        Args:
            matched: The keys of the subjects actually excluded.

        Returns:
            The entries, sorted, so two runs over one corpus report the same
            thing in the same order. A scoped entry is printed with its
            authority, because a bare record number is not enough for the
            holder to find the line they have to fix -- and the whole point of
            this list is that the same number can belong to two people at two
            institutions.
        """
        remaining = self.keys - set(matched)
        return tuple(sorted(_describe(key) for key in remaining))


@dataclass(frozen=True, slots=True)
class OptOutRecord:
    """What an exclusion list did to one build.

    Recorded during the build because nothing afterwards can reconstruct it: the
    dataset is what remains, and a subject who was excluded leaves no trace in
    it at all. That is the point of excluding them and the reason this record
    has to exist — without it a dataset built after an objection is
    indistinguishable from one built before it, which is the whole of risk R-08.

    Attributes:
        entries: How many distinct people the list named.
        subjects_excluded: How many of them this corpus actually held.
        records_excluded: How many input records belonged to those subjects and
            were therefore not written.
        entries_by_kind: How many entries named each kind of subject key.
        unmatched: The identifiers that matched no subject here. **Terminal
            output only.** They are patient identifiers, and a list of them is a
            list of people who objected, so they never reach the manifest.
        excluded_paths: The corpus files belonging to excluded subjects.
            **Build bookkeeping, and never written anywhere.** An export names
            its files after the record they hold, so a list of paths is a list
            of record numbers; here it would be a list of record numbers
            belonging to people who objected. It exists so that counts derived
            from the corpus can tell which of its records reached the dataset.
    """

    entries: int
    subjects_excluded: int
    records_excluded: int
    entries_by_kind: Mapping[str, int]
    unmatched: tuple[str, ...]
    excluded_paths: frozenset[str]


def _describe(key: IdentityKey) -> str:
    """Return an entry in the form a holder would have written it.

    Used for the terminal report of entries that matched nobody, so that what
    they are shown is the line they have to go and look at rather than a value
    they then have to place.
    """
    if key.kind is KeyKind.NATIONAL_ID:
        return key.value
    return f"{key.kind.value}{FIELD_SEPARATOR}{key.authority}{FIELD_SEPARATOR}{key.value}"


def _national(path: Path, number: int, value: str) -> IdentityKey:
    """Return a national key, or refuse the line.

    Raises:
        ExclusionFileError: The value is not a usable codice fiscale.
    """
    classified = classify_national_id(value)
    if not classified.is_usable:
        raise ExclusionFileError(
            f"{path}, line {number}: {value!r} is not a usable national "
            f"identifier ({classified.status.value}). An unprefixed line is a "
            "codice fiscale; to name a subject keyed on something else, write "
            f"{KeyKind.SCOPED_RECORD_NUMBER.value}{FIELD_SEPARATOR}authority"
            f"{FIELD_SEPARATOR}number or "
            f"{KeyKind.ASSIGNED_IDENTIFIER.value}{FIELD_SEPARATOR}oid"
            f"{FIELD_SEPARATOR}code."
        )
    return IdentityKey.national(classified.normalised)


def _parse_line(path: Path, number: int, entry: str) -> IdentityKey:
    """Return the key one non-comment line names.

    Args:
        path: For the message.
        number: Line number, for the message.
        entry: The stripped line.

    Returns:
        The key, normalised the way the readers normalise the same kind, so
        that a holder's spacing and leading zeros do not decide whether an
        objection is acted on.

    Raises:
        ExclusionFileError: The line names no kind this tool knows, carries the
            wrong number of fields for the kind it names, leaves a field empty,
            or gives a value that kind cannot have.
    """
    if FIELD_SEPARATOR not in entry:
        return _national(path, number, entry)

    fields = [field.strip() for field in entry.split(FIELD_SEPARATOR)]
    declared, rest = fields[0], fields[1:]
    try:
        kind = KeyKind(declared)
    except ValueError:
        permitted = ", ".join(sorted(member.value for member in KeyKind))
        raise ExclusionFileError(
            f"{path}, line {number}: {declared!r} is not a kind of subject key. "
            f"Write one of {permitted}, or no prefix at all for a codice fiscale."
        ) from None

    expected = 1 if kind is KeyKind.NATIONAL_ID else 2
    if len(rest) != expected or not all(rest):
        shape = (
            f"{kind.value}{FIELD_SEPARATOR}value"
            if expected == 1
            else f"{kind.value}{FIELD_SEPARATOR}authority{FIELD_SEPARATOR}value"
        )
        raise ExclusionFileError(
            f"{path}, line {number}: a {kind.value} entry is written {shape}, "
            f"and this line has {len(rest)} field(s) after the kind. An "
            "authority is never guessed: an identifier scoped to one is "
            "meaningless without it, and two institutions' record numbers are "
            "deliberately not one namespace."
        )

    if kind is KeyKind.NATIONAL_ID:
        return _national(path, number, rest[0])
    if kind is KeyKind.SCOPED_RECORD_NUMBER:
        authority, value = normalise_authority(rest[0]), normalise_record_number(rest[1])
        if not value:
            raise ExclusionFileError(
                f"{path}, line {number}: {rest[1]!r} normalises to nothing, so "
                "it names no record number. Leading zeros are stripped, which "
                "is what matches the same patient across two exports."
            )
        return IdentityKey.scoped_record_number(authority, value)

    value = normalise_national_id(rest[1])
    if not value:
        raise ExclusionFileError(
            f"{path}, line {number}: {rest[1]!r} normalises to nothing, so it "
            "names no assigned identifier."
        )
    # The authority passes through as written, where a record number's is
    # case-folded: an issuing namespace is an OID, and an OID is not prose.
    return IdentityKey.assigned_identifier(rest[0], value)


def read_exclusions(path: Path) -> Exclusions:
    """Read a list of people who have objected, one person per line.

    Blank lines and lines beginning with ``#`` are ignored. Every other line is
    one of three forms:

    * a bare codice fiscale, which is what the file held before 2026-11-23 and
      still means exactly the same thing;
    * ``scoped_record_number|authority|number``, for a subject this corpus
      established from an institution's own record number -- the authority being
      the institution name as that institution's own exports declare it;
    * ``assigned_identifier|oid|code``, for an ENI, STP or ANA code, the OID
      being the namespace the document declared it under.

    A line declares its kind rather than having one inferred from the shape of
    its value; this module's docstring says why that distinction matters.

    Args:
        path: The file to read.

    Returns:
        The exclusions, possibly empty. An empty list is not an error: a holder
        keeping a standing list has one before anybody objects, and a build that
        failed every day until somebody did would teach them to ignore it.

    Raises:
        ExclusionFileError: The file cannot be read, or a line is not a usable
            entry. The message names the line number and what to write instead,
            because the holder has to go and fix that line.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        raise ExclusionFileError(f"Cannot read the exclusion list at {path}: {exc}") from exc

    keys: set[IdentityKey] = set()
    for number, line in enumerate(text.splitlines(), start=1):
        entry = line.strip()
        if not entry or entry.startswith(COMMENT_PREFIX):
            continue
        keys.add(_parse_line(path, number, entry))

    return Exclusions(keys=frozenset(keys))
