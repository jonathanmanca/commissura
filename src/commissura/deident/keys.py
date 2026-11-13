"""The secret key: how it is made, where it lives, and how it is referred to.

Everything in the pseudonymisation design derives from one secret. That makes
the handling of this one value the most consequential code in the project, so
the decisions are stated here rather than left implicit.

**There is no ``--key <value>`` option, and there will not be.** A key passed on
the command line lands in shell history, in the output of ``ps`` for every other
user on the machine, and in the logs of any CI system that runs the command. The
only ways in are a key file and an environment variable naming that file. This
is a deliberate refusal: offering the convenient option and documenting that it
is unsafe does not work, because the convenient option is the one people use.

**The key never enters the dataset.** What goes into the manifest is a
*fingerprint*: a digest of the key, domain-separated so that it cannot be
confused with any pseudonym derived from the same key. The fingerprint answers
"were these two datasets built from the same key?" — which determines whether
they can be linked, and whether a dataset whose key is lost is permanently
orphaned — without answering "what is the key?".

**File permissions are reported honestly.** On POSIX the key file is created
mode 0600. On Windows that mode is largely ignored and the file inherits
directory ACLs instead, so :func:`write_key_file` says what it actually managed
to do rather than implying a protection it did not apply. A tool that claims to
have secured something it did not is worse than one that admits the limit.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

KEY_BYTES: Final = 32
"""Key length in bytes.

256 bits, matching the block size of the SHA-256 used in the HMAC. A longer key
would be hashed down to the block size before use and buy nothing; a shorter one
would reduce the security margin for no saving worth having.
"""

KEY_FILE_ENV_VAR: Final = "COMMISSURA_KEY_FILE"
"""Environment variable naming the key *file*, not holding the key.

Pointing at a file rather than carrying the value means the secret is not in the
process environment, which is readable from ``/proc`` on Linux by the same user
and is routinely dumped wholesale into crash reports and CI diagnostics.
"""

FINGERPRINT_LENGTH: Final = 16
"""Hex characters of fingerprint recorded in the manifest.

64 bits is far more than enough to tell two keys apart in any realistic archive,
and a truncated digest leaks correspondingly less about the input.
"""

_FINGERPRINT_DOMAIN: Final = b"fingerprint|v1"
"""Domain separator for the fingerprint.

Without it the fingerprint would be a digest of the key under the same
construction used for pseudonyms, which invites the question of whether one can
be derived from the other. With it, the answer is structurally no.
"""


class KeyMaterialError(Exception):
    """Base class for key handling failures."""


class KeyNotFoundError(KeyMaterialError):
    """No key file was given and none could be found."""


class InvalidKeyError(KeyMaterialError):
    """A key file exists but does not contain usable key material."""


@dataclass(frozen=True, slots=True, eq=False)
class SecretKey:
    """Key material, wrapped so it is hard to leak by accident.

    ``eq=False``, so ``==`` is identity and :meth:`matches` is the only way to
    compare two keys. The generated ``__eq__`` compared ``material`` with
    ordinary bytes equality, which short-circuits on the first differing byte --
    two ways to ask one question, one of them constant-time and one not, with
    nothing steering a caller to the safe one. No timing oracle exists in a
    local command-line tool, which is why this was Informational rather than a
    vulnerability; removing the unsafe path cost one keyword.

    The wrapper exists because a bare ``bytes`` object prints itself. A key that
    reaches a log line, a traceback or a debugger session is compromised, and
    the most likely route there is an f-string written in a hurry. So
    :meth:`__repr__` and :meth:`__str__` both return the fingerprint, and the
    material is reachable only through :attr:`material`, which has to be asked
    for by name.
    """

    material: bytes

    def __post_init__(self) -> None:
        """Reject key material of the wrong length.

        Raises:
            InvalidKeyError: If the material is not exactly :data:`KEY_BYTES` long.
        """
        if len(self.material) != KEY_BYTES:
            raise InvalidKeyError(
                f"key must be exactly {KEY_BYTES} bytes, got {len(self.material)}"
            )

    @property
    def fingerprint(self) -> str:
        """Return the public identifier of this key.

        Safe to write into a manifest, a log or a filename: it identifies the
        key without carrying it.
        """
        digest = hashlib.sha256(_FINGERPRINT_DOMAIN + self.material).hexdigest()
        return digest[:FINGERPRINT_LENGTH]

    def __repr__(self) -> str:
        """Return a representation that cannot leak the key."""
        return f"SecretKey(fingerprint={self.fingerprint!r})"

    def __str__(self) -> str:
        """Return the fingerprint, so interpolation cannot leak the key."""
        return self.fingerprint

    def matches(self, other: SecretKey) -> bool:
        """Compare two keys in constant time.

        Args:
            other: The key to compare against.

        Returns:
            Whether the two hold the same material.
        """
        return hmac.compare_digest(self.material, other.material)


def generate_key() -> SecretKey:
    """Create a new key from the operating system's cryptographic source.

    Uses :mod:`secrets`, which draws from the platform CSPRNG. Deliberately not
    :mod:`random`, and deliberately not seeded or reproducible: a key that can
    be regenerated from something guessable is not a secret. This is the one
    place in the project where determinism is the wrong property.

    Returns:
        A fresh key.
    """
    return SecretKey(secrets.token_bytes(KEY_BYTES))


@dataclass(frozen=True, slots=True)
class KeyFileReport:
    """What :func:`write_key_file` actually managed to do.

    Attributes:
        path: Where the key was written.
        fingerprint: The key's public identifier.
        permissions_restricted: Whether the file was successfully restricted to
            the owner. False on Windows, where the creation mode is largely
            ignored and the file inherits directory ACLs.
        advice: A line to show the user about what they still have to do.
    """

    path: Path
    fingerprint: str
    permissions_restricted: bool
    advice: str


def write_key_file(key: SecretKey, path: Path, *, overwrite: bool = False) -> KeyFileReport:
    """Write a key to disk, as restrictively as the platform allows.

    The file is created with :func:`os.open` and ``O_EXCL`` rather than
    :meth:`Path.write_bytes`, for two reasons: the mode can be set at creation
    rather than in a second step that leaves a window where the file is readable,
    and ``O_EXCL`` makes overwriting an existing key an explicit choice instead
    of an accident. Overwriting a key orphans every dataset built from it.

    Args:
        key: The key to write.
        path: Destination.
        overwrite: Whether to replace an existing file.

    Returns:
        A report of what was written and what protection was applied.

    Raises:
        FileExistsError: If the path exists and ``overwrite`` is false.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if overwrite else os.O_EXCL)
    descriptor = os.open(path, flags, 0o600)
    try:
        os.write(descriptor, key.material.hex().encode("ascii") + b"\n")
    finally:
        os.close(descriptor)

    restricted = _restrict_permissions(path)
    if restricted:
        advice = (
            "The key file is readable only by you. Back it up somewhere safe: "
            "every dataset built with it becomes permanently unlinkable if it is lost."
        )
    else:
        advice = (
            "This platform does not honour POSIX file modes, so the key file inherits "
            "the directory's permissions. Move it somewhere only you can read, or keep "
            "it in an encrypted store. Back it up: every dataset built with it becomes "
            "permanently unlinkable if it is lost."
        )

    return KeyFileReport(
        path=path,
        fingerprint=key.fingerprint,
        permissions_restricted=restricted,
        advice=advice,
    )


def _restrict_permissions(path: Path) -> bool:
    """Try to make a file readable only by its owner.

    Returns:
        Whether the restriction demonstrably took effect. On Windows this is
        false: ``chmod`` there only toggles the read-only attribute, and the
        file's real protection comes from ACLs this function does not set.
    """
    if sys.platform == "win32":
        return False
    try:
        path.chmod(0o600)
    except OSError:  # pragma: no cover - platform-dependent
        return False
    mode = stat.S_IMODE(path.stat().st_mode)
    return mode == 0o600


def read_key_file(path: Path) -> SecretKey:
    """Read a key from a file written by :func:`write_key_file`.

    Accepts the hex digits with surrounding whitespace, which is what a user who
    opened the file in an editor is likely to leave behind.

    Args:
        path: The key file.

    Returns:
        The key.

    Raises:
        KeyNotFoundError: If the file does not exist.
        InvalidKeyError: If the contents are not the expected hex material.
    """
    if not path.is_file():
        raise KeyNotFoundError(f"no key file at {path}")
    try:
        text = path.read_text(encoding="ascii").strip()
    except UnicodeDecodeError:
        # The decode error names the offending byte and its position, so
        # interpolating it leaks one byte of the secret -- by value and by
        # index -- into a terminal, a CI log or a bug report. One byte of 256
        # does not break the HMAC; this module is still the one place where
        # "key material must not leak through exceptions" is a stated goal.
        raise InvalidKeyError(
            f"key file {path} is not ASCII text; it should hold {KEY_BYTES * 2} hex characters"
        ) from None
    except OSError as exc:
        raise InvalidKeyError(f"key file {path} could not be read: {exc}") from exc

    try:
        material = bytes.fromhex(text)
    except ValueError as exc:
        raise InvalidKeyError(
            f"key file {path} does not contain {KEY_BYTES * 2} hex characters"
        ) from exc
    return SecretKey(material)


def resolve_key(
    explicit: Path | None = None, *, environ: dict[str, str] | None = None
) -> SecretKey:
    """Find and load the key, in the one documented order of precedence.

    Looks at the explicit path first, then the :data:`KEY_FILE_ENV_VAR`
    environment variable. There is no implicit default location: a tool that
    silently picks up a key from a well-known path will one day pseudonymise a
    dataset with the wrong key and say nothing, and the result is two datasets
    that look linkable and are not.

    Args:
        explicit: A path given directly, usually from a command-line option.
        environ: Environment to consult. Defaults to the real one; injectable so
            a test does not have to mutate global state.

    Returns:
        The key.

    Raises:
        KeyNotFoundError: If neither source names a readable key file.
        InvalidKeyError: If the named file is not valid key material.
    """
    if explicit is not None:
        return read_key_file(explicit)

    env = os.environ if environ is None else environ
    from_env = env.get(KEY_FILE_ENV_VAR)
    if from_env:
        return read_key_file(Path(from_env))

    raise KeyNotFoundError(
        "no key given. Pass --key-file, or set "
        f"{KEY_FILE_ENV_VAR} to the path of a key file. "
        "Create one with: commissura keygen --out <path>"
    )
