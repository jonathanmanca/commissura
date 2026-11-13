"""Key material: generation, storage, and the ways it must not leak."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from commissura.deident import keys as keys_module
from commissura.deident.keys import (
    FINGERPRINT_LENGTH,
    KEY_BYTES,
    KEY_FILE_ENV_VAR,
    InvalidKeyError,
    KeyNotFoundError,
    SecretKey,
    generate_key,
    read_key_file,
    resolve_key,
    write_key_file,
)

KNOWN_MATERIAL = bytes(range(KEY_BYTES))


def test_a_generated_key_is_the_expected_length() -> None:
    assert len(generate_key().material) == KEY_BYTES


def test_generated_keys_are_not_reproducible() -> None:
    """The one place in this project where determinism would be the wrong property.

    A key that can be regenerated from something guessable is not a secret, so
    generation draws from the platform CSPRNG rather than a seeded generator.
    """
    keys = {generate_key().material for _ in range(50)}
    assert len(keys) == 50


@pytest.mark.parametrize("length", [0, 1, 16, 31, 33, 64])
def test_key_material_of_the_wrong_length_is_rejected(length: int) -> None:
    with pytest.raises(InvalidKeyError, match=f"exactly {KEY_BYTES} bytes"):
        SecretKey(bytes(length))


def test_the_key_never_appears_in_its_own_representations() -> None:
    """The likeliest route to a leaked key is an f-string written in a hurry."""
    key = SecretKey(KNOWN_MATERIAL)
    hex_material = KNOWN_MATERIAL.hex()

    for rendered in (repr(key), str(key), f"{key}", f"{key!s}", format(key)):
        assert hex_material not in rendered
        assert key.fingerprint in rendered or rendered == key.fingerprint


def test_the_fingerprint_is_not_the_key() -> None:
    key = SecretKey(KNOWN_MATERIAL)
    assert key.fingerprint != KNOWN_MATERIAL.hex()[:FINGERPRINT_LENGTH]
    assert len(key.fingerprint) == FINGERPRINT_LENGTH
    assert all(character in "0123456789abcdef" for character in key.fingerprint)


def test_the_fingerprint_is_stable_for_one_key() -> None:
    assert SecretKey(KNOWN_MATERIAL).fingerprint == SecretKey(KNOWN_MATERIAL).fingerprint


def test_different_keys_have_different_fingerprints() -> None:
    fingerprints = {generate_key().fingerprint for _ in range(100)}
    assert len(fingerprints) == 100


def test_keys_compare_by_material() -> None:
    key = SecretKey(KNOWN_MATERIAL)
    assert key.matches(SecretKey(KNOWN_MATERIAL))
    assert not key.matches(generate_key())


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------


def test_a_key_round_trips_through_a_file(tmp_path: Path) -> None:
    key = generate_key()
    report = write_key_file(key, tmp_path / "k.key")
    assert read_key_file(report.path).matches(key)
    assert report.fingerprint == key.fingerprint


def test_the_key_file_holds_only_hex(tmp_path: Path) -> None:
    key = generate_key()
    path = write_key_file(key, tmp_path / "k.key").path
    text = path.read_text(encoding="ascii").strip()
    assert text == key.material.hex()
    assert len(text) == KEY_BYTES * 2


def test_writing_creates_missing_parent_directories(tmp_path: Path) -> None:
    report = write_key_file(generate_key(), tmp_path / "a" / "b" / "k.key")
    assert report.path.is_file()


def test_an_existing_key_file_is_not_overwritten_by_accident(tmp_path: Path) -> None:
    """Replacing a key orphans every dataset built from it, so it cannot be implicit."""
    path = tmp_path / "k.key"
    first = generate_key()
    write_key_file(first, path)

    with pytest.raises(FileExistsError):
        write_key_file(generate_key(), path)

    assert read_key_file(path).matches(first), "the original key must survive the refusal"


def test_overwriting_is_possible_when_asked_for(tmp_path: Path) -> None:
    path = tmp_path / "k.key"
    write_key_file(generate_key(), path)
    replacement = generate_key()
    write_key_file(replacement, path, overwrite=True)
    assert read_key_file(path).matches(replacement)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes are not honoured")
def test_on_posix_the_key_file_is_owner_only(tmp_path: Path) -> None:
    report = write_key_file(generate_key(), tmp_path / "k.key")
    assert report.permissions_restricted
    assert stat.S_IMODE(report.path.stat().st_mode) == 0o600


@pytest.mark.skipif(sys.platform != "win32", reason="checks the Windows-specific report")
def test_on_windows_the_tool_admits_it_did_not_restrict_access(tmp_path: Path) -> None:
    """A tool that claims to have secured something it did not is worse than honest."""
    report = write_key_file(generate_key(), tmp_path / "k.key")
    assert not report.permissions_restricted
    assert "does not honour POSIX file modes" in report.advice


def test_the_advice_always_mentions_backing_the_key_up(tmp_path: Path) -> None:
    report = write_key_file(generate_key(), tmp_path / "k.key")
    assert "unlinkable" in report.advice


def test_reading_a_missing_key_file_says_so(tmp_path: Path) -> None:
    with pytest.raises(KeyNotFoundError, match="no key file at"):
        read_key_file(tmp_path / "absent.key")


@pytest.mark.parametrize("contents", ["", "not hex at all", "abc", "zz" * KEY_BYTES])
def test_a_key_file_that_is_not_key_material_is_rejected(tmp_path: Path, contents: str) -> None:
    path = tmp_path / "k.key"
    path.write_text(contents, encoding="ascii")
    with pytest.raises(InvalidKeyError):
        read_key_file(path)


def test_surrounding_whitespace_in_a_key_file_is_tolerated(tmp_path: Path) -> None:
    """What somebody who opened the file in an editor is likely to leave behind."""
    key = generate_key()
    path = tmp_path / "k.key"
    path.write_text(f"\n  {key.material.hex()}  \n\n", encoding="ascii")
    assert read_key_file(path).matches(key)


def test_a_key_file_with_the_wrong_number_of_bytes_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "k.key"
    path.write_text("ab" * 8, encoding="ascii")
    with pytest.raises(InvalidKeyError, match=f"exactly {KEY_BYTES} bytes"):
        read_key_file(path)


# --------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------


def test_an_explicit_path_takes_precedence(tmp_path: Path) -> None:
    wanted = generate_key()
    other = generate_key()
    explicit = write_key_file(wanted, tmp_path / "wanted.key").path
    from_env = write_key_file(other, tmp_path / "env.key").path

    resolved = resolve_key(explicit, environ={KEY_FILE_ENV_VAR: str(from_env)})
    assert resolved.matches(wanted)


def test_the_environment_variable_names_a_file_not_a_key(tmp_path: Path) -> None:
    """The secret stays out of the process environment, which is widely readable."""
    key = generate_key()
    path = write_key_file(key, tmp_path / "k.key").path
    assert resolve_key(environ={KEY_FILE_ENV_VAR: str(path)}).matches(key)


def test_a_key_in_the_environment_variable_itself_is_not_accepted(tmp_path: Path) -> None:
    key = generate_key()
    with pytest.raises(KeyNotFoundError, match="no key file at"):
        resolve_key(environ={KEY_FILE_ENV_VAR: key.material.hex()})


def test_with_no_source_the_error_says_how_to_make_a_key() -> None:
    with pytest.raises(KeyNotFoundError) as caught:
        resolve_key(environ={})
    message = str(caught.value)
    assert "--key-file" in message
    assert KEY_FILE_ENV_VAR in message
    assert "commissura keygen" in message


def test_an_empty_environment_variable_is_treated_as_absent() -> None:
    with pytest.raises(KeyNotFoundError, match="no key given"):
        resolve_key(environ={KEY_FILE_ENV_VAR: ""})


def test_there_is_no_implicit_default_key_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A silently discovered key would one day pseudonymise with the wrong secret.

    The result is two datasets that look linkable and are not, which is worse
    than a command that refuses to run.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(KEY_FILE_ENV_VAR, raising=False)
    for candidate in ("commissura.key", ".commissura.key", "key", "secret.key"):
        (tmp_path / candidate).write_text(generate_key().material.hex(), encoding="ascii")

    with pytest.raises(KeyNotFoundError):
        resolve_key()


def test_the_real_environment_is_consulted_when_none_is_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = generate_key()
    path = write_key_file(key, tmp_path / "k.key").path
    monkeypatch.setenv(KEY_FILE_ENV_VAR, str(path))
    assert resolve_key().matches(key)
    assert os.environ[KEY_FILE_ENV_VAR] == str(path)


def test_a_key_file_that_is_not_ascii_is_reported_not_raised(tmp_path: Path) -> None:
    """A binary file where a key was expected must give a clear message."""
    path = tmp_path / "k.key"
    path.write_bytes(b"\xff\xfe\x00 definitely not ascii")
    with pytest.raises(InvalidKeyError, match="not ASCII text"):
        read_key_file(path)


def test_a_binary_key_file_error_names_no_byte_of_the_key(tmp_path: Path) -> None:
    """Audit finding 9: the decode error used to name the first non-ASCII byte.

    ``UnicodeDecodeError`` says which byte failed and where, so interpolating it
    disclosed one byte of the secret — by value and by index — into whatever
    caught the message: a terminal, a CI log, a bug report. One byte of 256 does
    not break the HMAC, and this is still the one module whose stated design
    goal is that key material must not leave through an exception.
    """
    key = generate_key()
    path = tmp_path / "raw.key"
    # The plausible operator mistake: raw bytes where hex was expected.
    path.write_bytes(key.material)

    with pytest.raises(InvalidKeyError) as caught:
        read_key_file(path)

    message = str(caught.value)
    assert "not ASCII text" in message
    assert not [byte for byte in key.material if f"0x{byte:02x}" in message]
    assert "position" not in message


def test_two_keys_cannot_be_compared_with_equality() -> None:
    """Audit finding 11: ``__eq__`` compared key material in non-constant time.

    :meth:`SecretKey.matches` exists to avoid exactly that, so having both was
    two ways to ask one question with nothing steering a caller to the safe one.
    No timing oracle exists in a local command-line tool, which is why this was
    Informational; removing the unsafe path cost one keyword.
    """
    one, two = SecretKey(bytes(32)), SecretKey(bytes(32))

    assert one != two
    assert one == one
    assert one.matches(two)


def test_the_advice_changes_when_permissions_were_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reporting logic is platform-independent even though the mechanism is not.

    On Windows the restriction never succeeds, so the success branch is only
    reachable by substituting the mechanism. What is being checked here is that
    the tool describes what it actually did.
    """
    monkeypatch.setattr(keys_module, "_restrict_permissions", lambda _: True)
    report = write_key_file(generate_key(), tmp_path / "k.key")

    assert report.permissions_restricted
    assert "readable only by you" in report.advice
    assert "does not honour POSIX file modes" not in report.advice
    assert "unlinkable" in report.advice


def test_the_posix_branch_attempts_a_chmod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercises the code POSIX would run, without claiming the result holds here.

    Windows accepts the chmod call but does not produce mode 0600, so this
    asserts only that the attempt is made and the outcome reported truthfully.
    """
    monkeypatch.setattr(sys, "platform", "linux")
    path = tmp_path / "k.key"
    path.write_text("x", encoding="ascii")

    restricted = keys_module._restrict_permissions(path)
    assert restricted == (stat.S_IMODE(path.stat().st_mode) == 0o600)
