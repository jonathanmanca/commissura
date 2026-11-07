"""Derive every pseudonym in the dataset from one secret key.

The construction, as decided in the brief::

    subject_id  = HMAC-SHA256(key, "subject|" + national_id)[:12]
    date_offset = HMAC-SHA256(key, "offset|"  + subject_id)  % 730 - 365
    dicom_uid   = "2.25." + int(HMAC-SHA256(key, "uid|" + original_uid))

Three properties make this work, and each is worth stating because each has a
tempting wrong alternative.

**Keyed, not plain.** ``sha256(national_id)`` would be useless. A codice fiscale
is drawn from a space small enough to enumerate: the format encodes a name, a
birth date, a sex and a place of birth, so an attacker holding a candidate list
hashes it and reverses the whole dataset over a weekend. With an HMAC the
attacker needs the key, and without the key the pseudonyms are
information-theoretically unhelpful.

**Domain-separated by prefix.** Every derivation prepends a label naming what is
being derived. Without it, a subject identifier and a UID derived from the same
input string would collide, and worse, a value observed in one role could be
replayed in another. The separator is part of the HMAC input, not of the output,
so it costs nothing and closes the whole class.

**Deterministic across runs and across modalities.** The same national
identifier gives the same subject identifier today and in three years, in the
laboratory branch and the imaging branch, on any machine. That is what makes a
multimodal dataset possible at all: the three exports are linked by the fact
that they derive the same pseudonym from the same person.

**On truncation.** Subject identifiers keep 48 bits of the digest. For any
realistic cohort the collision probability is negligible — the birthday bound
puts a 50% chance at roughly 17 million subjects — but "negligible" is not
"zero", so :class:`Pseudonymiser` records what it has issued and raises on a
collision rather than silently merging two people. A collision that is handled
is a curiosity; one that is not is two patients' data in one record.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass, field
from datetime import date, timedelta
from hashlib import sha256
from typing import Final

from commissura.deident.keys import SecretKey

SUBJECT_ID_HEX_CHARS: Final = 12
"""Hex characters kept from the subject digest: 48 bits.

Long enough that collisions are a theoretical concern rather than a practical
one, short enough that a subject directory name stays readable in a path and in
a terminal.
"""

DATE_OFFSET_SPAN: Final = 730
"""Width of the date-shift window in days, giving a shift in [-365, +365]."""

UID_ROOT: Final = "2.25"
"""The registration-free OID arc for UUIDs rendered as integers.

Chosen over inventing a suffix under somebody else's registered root, which
produces identifiers that are not ours to issue. Anyone may generate under
``2.25`` without applying for an OID.
"""

RULE_VERSION: Final = "1.0.0"
"""Version of the derivation rules in this module.

Recorded in the manifest. If any derivation here changes, this must change with
it: two datasets built from the same key but different rule versions are not
linkable, and the manifest is the only place that can say so.
"""

_DOMAIN_SUBJECT: Final = "subject|"
_DOMAIN_OFFSET: Final = "offset|"
_DOMAIN_UID: Final = "uid|"
_DOMAIN_ACCESSION: Final = "accession|"


def _derive(key: SecretKey, domain: str, value: str) -> bytes:
    """Return the raw HMAC-SHA256 digest for one domain-separated input.

    Args:
        key: The secret.
        domain: Domain separator, including its trailing delimiter.
        value: The value being pseudonymised.

    Returns:
        The 32-byte digest.
    """
    return hmac.new(key.material, (domain + value).encode("utf-8"), sha256).digest()


@dataclass(slots=True)
class Pseudonymiser:
    """Derives pseudonyms from one key, and remembers what it issued.

    Mutable, unlike most of this codebase, because the collision check needs
    state. The mutation is append-only and never changes a value already handed
    out, so a caller can rely on a pseudonym staying what it was.

    Attributes:
        key: The secret everything derives from.
        rule_version: The derivation rule version, recorded in the manifest.
    """

    key: SecretKey
    rule_version: str = RULE_VERSION
    _subject_ids: dict[str, str] = field(default_factory=dict, repr=False)
    _issued_subjects: dict[str, str] = field(default_factory=dict, repr=False)

    @property
    def key_fingerprint(self) -> str:
        """Return the key's public identifier, for the manifest."""
        return self.key.fingerprint

    def subject_label(self, national_id: str) -> str:
        """Return the BIDS subject label for one person.

        The label is the bare hex, without the ``sub-`` prefix: the prefix
        belongs to the filename grammar, not to the identifier, and baking it in
        here would mean stripping it everywhere the identifier is used as a key.

        Args:
            national_id: The real identifier, such as a codice fiscale. It is
                used and discarded; nothing here retains it.

        Returns:
            Twelve lowercase hex characters.

        Raises:
            ValueError: If two different inputs collide on one label. Vanishingly
                unlikely, and silently merging two people would be far worse than
                failing.
        """
        cached = self._subject_ids.get(national_id)
        if cached is not None:
            return cached

        label = _derive(self.key, _DOMAIN_SUBJECT, national_id).hex()[:SUBJECT_ID_HEX_CHARS]

        previous = self._issued_subjects.get(label)
        if previous is not None and previous != national_id:
            raise ValueError(
                f"subject label {label!r} derived from two different inputs. "
                "This is a truncation collision: widen SUBJECT_ID_HEX_CHARS rather than "
                "letting two people share a record."
            )

        self._subject_ids[national_id] = label
        self._issued_subjects[label] = national_id
        return label

    def subject_directory(self, national_id: str) -> str:
        """Return the subject directory name, prefix included.

        Args:
            national_id: The real identifier.

        Returns:
            A value such as ``sub-a3f9c21b4e07``.
        """
        return f"sub-{self.subject_label(national_id)}"

    def date_offset(self, subject_label: str) -> int:
        """Return the stable date shift for one subject, in days.

        Derived from the *pseudonym* rather than from the national identifier,
        so that a component holding only the de-identified label can compute it.
        Nothing is weakened by that: the derivation still needs the key.

        This shift is not what the dataset uses to express time — that is
        ``day_offset`` from the subject's own baseline. It exists for values
        that must remain a syntactically valid date for a downstream tool which
        refuses to run without one, notably DICOM ``StudyDate`` on the way into
        ``dcm2bids``. A shifted date must never reach the finished dataset.

        Args:
            subject_label: The subject's pseudonymous label.

        Returns:
            A whole number of days in ``[-365, +365]``, stable for this subject
            and this key.
        """
        digest = _derive(self.key, _DOMAIN_OFFSET, subject_label)
        return int.from_bytes(digest[:8], "big") % DATE_OFFSET_SPAN - DATE_OFFSET_SPAN // 2

    def shift_date(self, subject_label: str, original: date) -> date:
        """Apply a subject's stable shift to one date.

        Every date for a subject moves by the same amount, so intervals between
        them are preserved exactly while the calendar anchor is destroyed. The
        shift differs per subject, which is the point: a single offset for the
        whole cohort would preserve cross-subject alignment, and one known date
        anywhere would then unshift everybody.

        Args:
            subject_label: The subject's pseudonymous label.
            original: The real date.

        Returns:
            The shifted date.
        """
        return original + timedelta(days=self.date_offset(subject_label))

    def day_offset(self, baseline: date, moment: date) -> int:
        """Return days from a subject's baseline, which is what the dataset stores.

        Needs no key: it is a subtraction, and that is the whole idea. Expressing
        time as a distance from the subject's own first event removes the
        calendar without any secret being involved, so a reader can interpret
        intervals while nobody can recover a date.

        Args:
            baseline: The subject's reference event.
            moment: The date to express.

        Returns:
            Whole days, negative if ``moment`` precedes the baseline.
        """
        return (moment - baseline).days

    def uid(self, original_uid: str) -> str:
        """Return a relinkable pseudonymous DICOM UID.

        Args:
            original_uid: The real UID.

        Returns:
            A UID under the ``2.25`` arc, within the 64-character limit the
            standard imposes.
        """
        digest = _derive(self.key, _DOMAIN_UID, original_uid)
        # 112 bits keeps the decimal form comfortably inside the 64-character
        # UID limit while leaving collisions out of reach.
        return f"{UID_ROOT}.{int.from_bytes(digest[:14], 'big')}"

    def accession(self, original: str) -> str:
        """Return a pseudonymous accession number.

        Accession numbers are identifiers in their own right — they are quoted
        in letters, printed on requests and often sequential enough to reveal
        ordering and volume — so they are replaced rather than kept.

        Args:
            original: The real accession number.

        Returns:
            Sixteen lowercase hex characters.
        """
        return _derive(self.key, _DOMAIN_ACCESSION, original).hex()[:16]

    def issued_subject_count(self) -> int:
        """Return how many distinct subjects have been pseudonymised so far."""
        return len(self._subject_ids)
