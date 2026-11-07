"""Synthetic identifiers that are structurally valid but provably not real.

Generating fake identifiers has a trap in it. An identifier that is merely
*random* will occasionally be a real one: a random codice fiscale belongs to a
living person roughly as often as the identifier space is populated, and a
random phone number reaches someone. For a project whose first hard constraint
is that no real patient data ever enters it, "probably nobody" is not good
enough, and "it is only test data" is exactly the sentence that precedes an
incident.

The approach taken here is to make every identifier **structurally valid but
impossible**, by placing it in a part of the format that no issuing authority
assigns:

- **Codice fiscale**: the four-character place-of-birth component uses an ``X``
  prefix. Italian municipalities are assigned codes from ``A`` to ``M`` and
  foreign states the ``Z`` range, so ``X`` codes correspond to no registry
  entry. The checksum is still computed correctly, so the values exercise a real
  validator rather than bouncing off it.
- **Telephone**: Italian subscriber numbers never begin with ``0`` after the
  area code, so a leading zero in the subscriber part cannot be dialled.
- **Email**: the ``.invalid`` top-level domain is reserved by RFC 2606 for
  precisely this purpose and can never be registered.
- **DICOM UID**: the ``2.25`` arc holds UUIDs rendered as integers (ITU-T X.667).
  It requires no registration and collides with nobody, which makes it the
  correct choice for synthetic studies. Inventing a prefix under somebody else's
  registered root would be the wrong one.

Every function takes an explicit :class:`random.Random`. None of them touches
the module-level :mod:`random` functions. Global random state is a hidden
dependency: it makes output depend on what else ran first, which turns
reproducibility into luck and tests into a source of mystery.
"""

from __future__ import annotations

import uuid
from datetime import date
from random import Random

from commissura.models import Sex

_VOWELS = frozenset("AEIOU")

CF_MONTH_LETTERS = "ABCDEHLMPRST"
"""Month codes used by the codice fiscale, January to December.

The sequence skips letters that could be confused with digits when handwritten,
which is why it is not simply A to L.
"""

_CF_ODD_VALUES = {
    "0": 1, "1": 0, "2": 5, "3": 7, "4": 9, "5": 13, "6": 15, "7": 17,
    "8": 19, "9": 21, "A": 1, "B": 0, "C": 5, "D": 7, "E": 9, "F": 13,
    "G": 15, "H": 17, "I": 19, "J": 21, "K": 2, "L": 4, "M": 18, "N": 20,
    "O": 11, "P": 3, "Q": 6, "R": 8, "S": 12, "T": 14, "U": 16, "V": 10,
    "W": 22, "X": 25, "Y": 24, "Z": 23,
}  # fmt: skip
"""Weights for characters in odd positions, one-indexed. From the 1976 decree."""


def _even_value(char: str) -> int:
    """Return the weight of a character sitting in an even position.

    Even positions use the obvious mapping: digits are their own value and
    letters their position in the alphabet.
    """
    return int(char) if char.isdigit() else ord(char) - ord("A")


def _consonants(text: str) -> str:
    """Return the consonants of ``text``, uppercased, in order."""
    return "".join(c for c in text.upper() if c.isalpha() and c not in _VOWELS)


def _vowels(text: str) -> str:
    """Return the vowels of ``text``, uppercased, in order."""
    return "".join(c for c in text.upper() if c in _VOWELS)


def cf_family_name_code(family_name: str) -> str:
    """Return the three-character family-name component of a codice fiscale.

    The rule is consonants first in order of appearance, then vowels, padded
    with ``X`` if the name is too short.

    Args:
        family_name: The family name.

    Returns:
        Exactly three uppercase characters.
    """
    return (_consonants(family_name) + _vowels(family_name) + "XXX")[:3]


def cf_given_name_code(given_name: str) -> str:
    """Return the three-character given-name component of a codice fiscale.

    The given name follows a different rule from the family name, which is the
    detail most reimplementations get wrong: when the name has four or more
    consonants, the first, third and fourth are taken, skipping the second.

    Args:
        given_name: The given name.

    Returns:
        Exactly three uppercase characters.
    """
    consonants = _consonants(given_name)
    if len(consonants) >= 4:
        return consonants[0] + consonants[2] + consonants[3]
    return (consonants + _vowels(given_name) + "XXX")[:3]


def cf_check_character(first_fifteen: str) -> str:
    """Return the final check character of a codice fiscale.

    Characters in odd positions, counting from one, are weighted by a lookup
    table; characters in even positions take their face value. The total modulo
    26 selects a letter.

    Args:
        first_fifteen: The first fifteen characters of the code.

    Returns:
        A single uppercase letter.

    Raises:
        ValueError: If the input is not fifteen characters long.
    """
    if len(first_fifteen) != 15:
        raise ValueError(f"expected 15 characters, got {len(first_fifteen)}")
    total = 0
    for index, char in enumerate(first_fifteen.upper(), start=1):
        total += _CF_ODD_VALUES[char] if index % 2 else _even_value(char)
    return chr(ord("A") + total % 26)


def codice_fiscale(
    family_name: str,
    given_name: str,
    birth_date: date,
    sex: Sex,
    place_code: str,
) -> str:
    """Assemble a complete, checksum-valid codice fiscale.

    Args:
        family_name: Family name.
        given_name: Given name.
        birth_date: Date of birth.
        sex: Administrative sex. Female codes add 40 to the day of birth, which
            is how the format encodes sex without a separate field.
        place_code: Four-character place-of-birth code. Use
            :func:`synthetic_place_code` to get one that cannot be real.

    Returns:
        A sixteen-character codice fiscale.
    """
    day = birth_date.day + (40 if sex is Sex.FEMALE else 0)
    body = (
        cf_family_name_code(family_name)
        + cf_given_name_code(given_name)
        + f"{birth_date.year % 100:02d}"
        + CF_MONTH_LETTERS[birth_date.month - 1]
        + f"{day:02d}"
        + place_code.upper()
    )
    return body + cf_check_character(body)


def synthetic_place_code(rng: Random) -> str:
    """Return a place-of-birth code that no municipality or state holds.

    Assigned codes run ``A000`` to ``M999`` for Italian municipalities and
    ``Z100`` upwards for foreign states. ``X`` is outside both ranges, so the
    resulting codice fiscale is well formed, passes checksum validation, and
    still cannot belong to anybody.

    Args:
        rng: Seeded random source.

    Returns:
        A four-character code such as ``X417``.
    """
    return f"X{rng.randrange(1000):03d}"


def medical_record_number(rng: Random) -> str:
    """Return a hospital medical record number.

    Zero-padded to seven digits, which is the shape that later lets the
    generator inject a realistic defect: the same patient appearing as
    ``0012345`` in one export and ``12345`` in another.

    Args:
        rng: Seeded random source.

    Returns:
        A seven-character numeric string.
    """
    return f"{rng.randrange(1, 10_000_000):07d}"


def accession_number(rng: Random, prefix: str) -> str:
    """Return a laboratory or radiology accession number.

    Args:
        rng: Seeded random source.
        prefix: Short department prefix, for example ``LAB`` or ``RAD``.

    Returns:
        A value such as ``LAB24081503``.
    """
    return f"{prefix}{rng.randrange(10**8):08d}"


def dicom_uid(rng: Random) -> str:
    """Return a globally unique DICOM UID that needs no registered root.

    The ``2.25`` arc is defined to contain UUIDs written as a single decimal
    integer. Anyone may generate under it without applying for an OID, and the
    result cannot collide with a real institution's UIDs. The alternative,
    inventing a suffix under somebody else's registered prefix, produces
    identifiers that are not yours to issue.

    The UUID is drawn from the seeded generator rather than :func:`uuid.uuid4`,
    because a corpus has to be reproducible from its seed alone.

    Args:
        rng: Seeded random source.

    Returns:
        A UID such as ``2.25.329800735698586629295641978511506172918``, always
        within the 64-character limit the standard imposes.
    """
    return f"2.25.{uuid.UUID(int=rng.getrandbits(128), version=4).int}"


def device_serial_number(rng: Random) -> str:
    """Return a scanner serial number.

    Recorded as an identifier in the ground truth because a serial number plus
    a date narrows a study to one machine in one department, which is enough to
    re-identify in a small series even with the patient fields removed.

    Args:
        rng: Seeded random source.

    Returns:
        A value such as ``SN-48213``.
    """
    return f"SN-{rng.randrange(10_000, 100_000)}"


def landline_number(rng: Random, area_code: str) -> str:
    """Return an Italian landline number that cannot be dialled.

    Subscriber numbers never start with ``0`` after the area code, so forcing a
    leading zero yields a well-shaped number that reaches nobody.

    Args:
        rng: Seeded random source.
        area_code: Area code without the leading zero, for example ``11`` for
            Turin or ``2`` for Milan.

    Returns:
        A value such as ``+39 011 0345678``.
    """
    subscriber = f"0{rng.randrange(10**6):06d}"
    return f"+39 0{area_code} {subscriber}"


def email_address(given_name: str, family_name: str, rng: Random) -> str:
    """Return an email address in a domain that can never exist.

    RFC 2606 reserves the ``.invalid`` top-level domain so that examples and
    test data cannot accidentally address a real mailbox.

    Args:
        given_name: Given name.
        family_name: Family name.
        rng: Seeded random source, used to vary the local-part shape.

    Returns:
        A value such as ``m.rossi@posta.invalid``.
    """
    given = given_name.lower()
    family = family_name.lower().replace(" ", "")
    local = rng.choice([f"{given[0]}.{family}", f"{given}.{family}", f"{family}{given[0]}"])
    return f"{local}@{rng.choice(['posta', 'mail', 'webmail'])}.invalid"
