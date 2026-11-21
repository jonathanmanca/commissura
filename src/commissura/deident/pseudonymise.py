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

from commissura.deident.keys import KEY_BYTES, SecretKey
from commissura.read.identity import IdentityKey, KeyKind

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

RULE_VERSION: Final = "1.1.0"
"""Version of the derivation rules in this module.

Recorded in the manifest. If any derivation here changes, this must change with
it: two datasets built from the same key but different rule versions are not
linkable, and the manifest is the only place that can say so.

**1.1.0, 2026-11-13.** Two changes, and the minor number rather than the major
is a claim worth being precise about.

A subject established from a *well-formed* codice fiscale derives from the
normalised identifier, and a well-formed codice fiscale normalises to itself —
so every label this tool has issued from valid input is unchanged, and a
1.0.0 dataset remains linkable with a 1.1.0 one. Verified rather than assumed:
every subject label in the twenty-five-subject walkthrough corpus and in a
second four-subject corpus is identical before and after.

What does change: a corpus whose identifiers were lowercase, or carried internal
whitespace, or were compatibility-encoded, previously produced one label per
spelling and now produces one label per person. Those labels were wrong, and the
rule version is how a holder tells that a rebuild will move them. Subjects
established from a record number are new in 1.1.0 and have no 1.0.0 counterpart:
the records that now form them were previously merged under whatever placeholder
their export sent.

A rebuild is the whole of the migration, and there is deliberately no in-place
upgrade: a dataset whose subjects were merged wrongly cannot be corrected by
relabelling, because the records inside a merged subject have to be separated
first. :mod:`commissura.read.identity` is where the policy that decides that
lives.
"""

_DOMAIN_SUBJECT: Final = "subject|"
_DOMAIN_SUBJECT_RECORD_NUMBER: Final = "subject-mrn|"
_DOMAIN_OFFSET: Final = "offset|"
_DOMAIN_UID: Final = "uid|"
_DOMAIN_ACCESSION: Final = "accession|"
_DOMAIN_MANIFEST: Final = "manifest|"
_DOMAIN_PERMIT: Final = "permit|"

DOMAIN_PURPOSES: Final[dict[str, str]] = {
    _DOMAIN_SUBJECT: "subject label, from a validated national identifier",
    _DOMAIN_SUBJECT_RECORD_NUMBER: (
        "subject label, from an institution-scoped medical record number"
    ),
    _DOMAIN_OFFSET: "per-subject date shift, for values that must stay valid dates",
    _DOMAIN_UID: "DICOM unique identifier",
    _DOMAIN_ACCESSION: "laboratory accession number",
    _DOMAIN_MANIFEST: "authentication tag over the manifest's own content",
    _DOMAIN_PERMIT: "subkey scoping every other derivation to one data permit",
}
"""What each domain prefix derives, for the manifest's declaration.

Exported rather than kept private because D7.2 section 4.4 (p. 40) asks that the
"exact specification of inputs" be saved alongside a cryptographically generated
pseudonym, and a reader of the manifest alone cannot otherwise reconstruct the
derivation. Keeping the mapping beside the prefixes means a new prefix added
without a purpose is a visible omission rather than a silent one.
"""


def scope_to_permit(key: SecretKey, permit_reference: str) -> SecretKey:
    """Return a subkey whose whole label space belongs to one data permit.

    TEHDAS2 D7.2 section 4.4 (p. 41) states, in capitals, that "Pseudonyms MUST
    NOT be reused across different data permits, to minimise risks of
    intentional or unintentional linkage of data by the data user". One key
    gives one label space for ever, so a holder who builds two permits' datasets
    from the same key hands the same subject labels to two data users -- which
    is exactly the unevaluated linkage that requirement exists to prevent.
    Section 4.3 (p. 38) makes the same point from the other side: the holder's
    output can reach the data user without the access body re-pseudonymising it
    *only* if the holder "can implement per project pseudonym generation".

    A subkey rather than a wider input, and the distinction is the whole reason
    this is safe to add. Folding the permit into the ``"subject|"`` input would
    change every label in every dataset ever built here. Deriving a subkey is
    reached only when a permit is named, so a build without one is byte-for-byte
    what it was before, which a test pins.

    The subkey is a full-length HMAC-SHA256 digest, which is exactly
    :data:`commissura.deident.keys.KEY_BYTES`, so it is an ordinary
    :class:`SecretKey` and every derivation downstream is unchanged. Its
    fingerprint differs from the root key's, and that is the point: a fingerprint
    is how an access body tells whether two datasets are relinkable, and under
    this scheme two datasets for one permit are and two for different permits
    are not.

    The root key is not recoverable from the subkey, so a subkey is also the
    safest thing to hand to a step that does not need the root secret. Nothing
    does that today; it is a property worth knowing before somebody needs it.

    Args:
        key: The root secret, from the key file.
        permit_reference: The data permit this build is answering. Not
            validated: a permit identifier's shape is for a health data access
            body to define, and Italy has not designated one.

    Returns:
        A derived key, usable anywhere the root key is.
    """
    return SecretKey(_derive(key, _DOMAIN_PERMIT, permit_reference))


def declare(
    key: SecretKey,
    *,
    permit_reference: str | None = None,
    root_fingerprint: str | None = None,
) -> dict[str, object]:
    """Describe this derivation for the manifest, without carrying the secret.

    D7.2 section 4.4 (p. 40) asks a controller generating cryptographic
    pseudonyms to save the "function used, exact specification of inputs, value
    of salt", with the salt "kept separate and secure"; section 4.3 (p. 37) asks
    the catalogue record to state whether the method is reversible; and section
    4.3 (p. 38) has the access body *approve* the algorithm. None of that was
    reconstructable from a manifest carrying a key fingerprint and a rule
    version, so a reader could not assess an algorithm they are expected to
    approve.

    The salt is named and never carried, which is the same rule the rest of this
    module follows: :attr:`SecretKey.fingerprint` identifies the secret without
    being it.

    ``reversible`` is ``False`` in D7.2's own sense -- section 4.2 (p. 36) makes
    a scheme reversible exactly when the secrets mapping pseudonyms back to
    identifiers are kept, and no such mapping is ever written. The document
    discourages irreversible pseudonymisation, so the consequences are spelled
    out in the payload rather than left for a reader to work out: an opt-out
    still works, because it starts from a named person and `commissura whois`
    derives forward from one, and a significant finding does not, because it
    starts from a row.

    Args:
        key: The key that produced this dataset's pseudonyms -- the subkey when
            the build is permit-scoped.
        permit_reference: The permit this dataset answers, or ``None``.
        root_fingerprint: The root key's fingerprint, when ``key`` is a subkey.

    Returns:
        The payload for the manifest's ``pseudonymisation`` section.
    """
    scoped = permit_reference is not None
    return {
        "algorithm": "HMAC-SHA256",
        # `salt_custody` and not `secret`, and the name was chosen by a guard
        # rather than by taste: `layout.FORBIDDEN_MANIFEST_KEYS` reserves
        # "secret" precisely because a manifest property of that name is what a
        # leaked key would look like, and nobody should have to read the value to
        # find out. The guard failed the build immediately, which is what it is
        # for -- the second time it has renamed a field here, after `key` became
        # `field` in the per-input table on 2026-11-10.
        "salt_custody": (
            f"A {KEY_BYTES}-byte key, held by the data holder, kept outside the dataset and "
            "named here only by the fingerprint above. D7.2 section 4.4 (p. 40) "
            "requires the salt be kept separate and secure."
        ),
        "key_fingerprint": key.fingerprint,
        "root_key_fingerprint": root_fingerprint,
        "rule_version": RULE_VERSION,
        "subject_label_hex_chars": SUBJECT_ID_HEX_CHARS,
        "domain_separation": "the prefix below is part of the HMAC input, never of the output",
        "domains": dict(DOMAIN_PURPOSES),
        "policy": "deterministic",
        "policy_note": (
            "The same identifier and key always give the same label, across runs, "
            "machines and modalities. That is what links the three exports to one "
            "person, and D7.2 section 4.4 advises it for the EHDS because it lets a "
            "data user recognise the same patient within a dataset."
        ),
        # Not the bare word "key": `layout.FORBIDDEN_MANIFEST_KEYS` is a text
        # search over the whole manifest, so a *value* of "key" trips the guard
        # that exists to catch a *property* named that. The guard is crude
        # because that is the only thing a text search can be, and weakening it
        # to parse property names would weaken a guard protecting the one
        # secret this project has. These names are clearer anyway.
        "scope": "permit-scoped" if scoped else "key-wide",
        "permit_reference": permit_reference,
        "scope_note": (
            (
                "Every pseudonym here derives from a subkey of the holder's key and "
                "this permit reference, so another permit built from the same key "
                "produces different labels. D7.2 section 4.4 requires that. The "
                "fingerprint above is the subkey's: two datasets sharing it answer "
                "the same permit and are relinkable."
            )
            if scoped
            else (
                "Not scoped to a data permit. Every dataset built from this key "
                "carries the same subject labels, so two permits answered with this "
                "key would hand the same labels to two data users -- which D7.2 "
                "section 4.4 says MUST NOT happen. Pass --permit to scope a build."
            )
        ),
        "reversible": False,
        "reversibility_note": (
            "Irreversible in the sense of D7.2 section 4.2: no mapping from "
            "pseudonym back to identifier is stored anywhere, so no party can "
            "reverse a label, the holder included. The document discourages this, so "
            "what follows is stated rather than left to be discovered. An opt-out "
            "works: it starts from a named person, and `commissura whois` derives "
            "that person's label forward from their identifier and this key. The "
            "return of a significant finding does not: it starts from a row, and "
            "reaching the person needs the holder to re-derive labels across their "
            "own population and match. A stored mapping would make that a lookup "
            "and would be the enumerable table this scheme exists to avoid."
        ),
    }


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


def authenticate(key: SecretKey, payload: str) -> str:
    """Return a hex HMAC over text, for proving the manifest was not edited.

    Lives here rather than in the module that calls it so that **every** use of
    the secret stays in one file, and so that the domain separator comes from
    the same list as the pseudonymisation domains. A manifest tag derived under
    its own prefix can never collide with a subject label, which is the whole
    reason the prefixes exist.

    This is authentication, not pseudonymisation, and the two share a key only
    because there is one key. The trade-off is recorded in the decision log of
    2026-11-11: an attacker who holds the key can forge the tag, but an attacker
    who holds the key can also recompute every pseudonym, so the tag protects
    exactly as much as the rest of the scheme and no less.

    Args:
        key: The secret.
        payload: Canonical text to authenticate.

    Returns:
        The HMAC as a hex string.
    """
    return _derive(key, _DOMAIN_MANIFEST, payload).hex()


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
    _witnesses: dict[str, str] = field(default_factory=dict, repr=False)

    @property
    def key_fingerprint(self) -> str:
        """Return the key's public identifier, for the manifest."""
        return self.key.fingerprint

    def _label(self, domain: str, value: str) -> str:
        """Derive one truncated subject label, refusing a truncation collision.

        **Retains no identifier.** The collision witness is the *untruncated*
        digest, which distinguishes two inputs exactly as well as the inputs do
        and is not patient data. The previous version kept the national
        identifier in two dictionaries for the lifetime of the build while this
        module's own docstring said it kept nothing — see the audit of
        2026-11-13, finding 7.

        There is deliberately no cache. A cache would have to be keyed on the
        derivation input, which would put the identifier straight back into the
        object it was just removed from, and an HMAC-SHA256 over a short string
        costs microseconds against a build that reads files from disk.

        Args:
            domain: The domain separator for this kind of subject key.
            value: The derivation input.

        Returns:
            Twelve lowercase hex characters.

        Raises:
            ValueError: If two different inputs collide on one label.
                Vanishingly unlikely, and silently merging two people would be
                far worse than failing.
        """
        full = _derive(self.key, domain, value).hex()
        label = full[:SUBJECT_ID_HEX_CHARS]

        previous = self._witnesses.get(label)
        if previous is not None and previous != full:
            raise ValueError(
                f"subject label {label!r} derived from two different inputs. "
                "This is a truncation collision: widen SUBJECT_ID_HEX_CHARS rather than "
                "letting two people share a record."
            )

        self._witnesses[label] = full
        return label

    def subject_label(self, national_id: str) -> str:
        """Return the BIDS subject label for one national identifier.

        The label is the bare hex, without the ``sub-`` prefix: the prefix
        belongs to the filename grammar, not to the identifier, and baking it in
        here would mean stripping it everywhere the identifier is used as a key.

        **The caller must pass the normalised identifier.** Normalisation is
        :func:`commissura.read.identity.normalise_national_id`'s job, not this
        module's: deciding what counts as the same identifier is identity
        policy, while this module is derivation. ``commissura whois`` and
        ``build`` both go through that function, which is what makes the label
        an operator derives for an opt-out the same one the dataset carries.

        Args:
            national_id: The normalised national identifier. Used and
                discarded: see :meth:`_label` for what is retained instead.

        Returns:
            Twelve lowercase hex characters.
        """
        return self._label(_DOMAIN_SUBJECT, national_id)

    def subject_label_for(self, key: IdentityKey) -> str:
        """Return the subject label for any kind of identity key.

        The two kinds derive under different domain separators, so a record
        number can never produce the label a national identifier would. Both
        are stable across runs and across institutions holding the same key,
        which is what makes a multimodal dataset linkable at all.

        Args:
            key: What established the subject.

        Returns:
            Twelve lowercase hex characters.
        """
        domain = (
            _DOMAIN_SUBJECT if key.kind is KeyKind.NATIONAL_ID else _DOMAIN_SUBJECT_RECORD_NUMBER
        )
        return self._label(domain, key.derivation_input)

    def subject_directory(self, national_id: str) -> str:
        """Return the subject directory name, prefix included.

        Args:
            national_id: The normalised national identifier.

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
        """Return how many distinct labels have been issued so far."""
        return len(self._witnesses)
