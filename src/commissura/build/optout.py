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

**One form, not both.** Twelve lowercase hex and sixteen alphanumerics are
distinguishable, so a tool could accept either and decide per line. Guessing is
how a file gets read in the wrong mode and nobody is excluded — and the whole
value of the identifier form is the check character, which a guesser gives up
the moment it treats an unrecognised value as "probably a label".

**Refuse what is provably wrong; report what is merely suspicious.** An
unreadable file and a line that is not a usable national identifier are refused
before anything is written, because no legitimate reading of them exists. An
empty list and an entry that matches no subject in this corpus are reported and
not refused, because both have a legitimate reading — nobody has objected yet,
and the person has no records in this export — and the tool cannot tell those
from a mistake. Refusing would be deciding on the holder's behalf, which this
project already declines to do for the access tier and the age band width.

**The limit, stated here because it is not visible from the flag.** A subject
this corpus established from something other than a national identifier — an
institution's own record number, or an ENI, STP or ANA code — carries no codice
fiscale for a list to match, so no entry can reach them. ``build`` says so on
the terminal when such subjects exist, and ``source.subject_keys`` in the
manifest says how many there are.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from commissura.read.identity import IdentityKey, classify_national_id

COMMENT_PREFIX: Final = "#"
"""Lines starting with this are ignored, after stripping.

A standing list accumulates over months and a holder will want to say when an
objection arrived and under which ticket. Supporting that costs one condition
and keeps the note beside the identifier rather than in somebody's memory.
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
            True when the list names them. Always False for a subject keyed on
            anything but a national identifier, which is the limit recorded in
            this module's docstring rather than a silent miss.
        """
        return key in self.keys

    def unmatched(self, matched: Iterable[IdentityKey]) -> tuple[str, ...]:
        """Return the normalised identifiers that matched no subject.

        **For the operator's terminal and never for the manifest.** These are
        patient identifiers, and a list of them is a list of people who
        objected.

        Args:
            matched: The keys of the subjects actually excluded.

        Returns:
            The identifiers, sorted, so two runs over one corpus report the
            same thing in the same order.
        """
        remaining = self.keys - set(matched)
        return tuple(sorted(key.value for key in remaining))


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
    unmatched: tuple[str, ...]
    excluded_paths: frozenset[str]


def read_exclusions(path: Path) -> Exclusions:
    """Read a list of people who have objected, one identifier per line.

    Blank lines and lines beginning with ``#`` are ignored. Everything else must
    be a usable national identifier; see this module's docstring for why that
    and not a subject label.

    Args:
        path: The file to read.

    Returns:
        The exclusions, possibly empty. An empty list is not an error: a holder
        keeping a standing list has one before anybody objects, and a build that
        failed every day until somebody did would teach them to ignore it.

    Raises:
        ExclusionFileError: The file cannot be read, or a line is not a usable
            national identifier. The message names the line number and the
            value, because the holder has to go and fix that line.
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
        classified = classify_national_id(entry)
        if not classified.is_usable:
            raise ExclusionFileError(
                f"{path}, line {number}: {entry!r} is not a usable national "
                f"identifier ({classified.status.value}). Every line must be a "
                "codice fiscale, because a subject label cannot be checked for "
                "transcription errors and is only valid for one key and permit."
            )
        keys.add(IdentityKey.national(classified.normalised))

    return Exclusions(keys=frozenset(keys))
