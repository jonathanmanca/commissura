"""Whether a dataset is still the one the manifest describes.

The manifest says what was done. Nothing in it said that the dataset had not
been changed since, and the gap was not academic: anyone can edit a value in a
``lab/*.tsv``, or paste a name back into a report, and every statement in the
manifest goes on reading as though it were still true. A de-identification
record that cannot be tied to the bytes it describes is a record of something
else.

So ``build`` writes a SHA-256 per produced file and ``commissura verify``
recomputes them. This is the mirror image of
:func:`commissura.generate.writer.verify_corpus`, which re-reads the *input*
corpus and confirms the recorded PHI offsets still quote the text on disk. Same
principle at the other end of the pipeline: a claim about bytes is checked
against the bytes.

**What this does and does not prove.** The digests catch a changed file, a lost
file and an added file — which is what actually happens: a TSV opened in a
spreadsheet and saved back, an incomplete copy, a stray export dropped into the
tree. They cannot by themselves catch tampering, because the list of digests
lives in the manifest and whoever can edit a report can edit the manifest beside
it. That is what ``manifest_hmac`` is for, and why checking it needs the key.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from commissura import layout
from commissura.deident.keys import SecretKey
from commissura.deident.pseudonymise import authenticate

DIGEST_ALGORITHM: Final = "sha256"
"""Named in the manifest so the field is self-describing, and used to hash.

A bare hex string says nothing about how it was produced, and the next
generation of this file may not use SHA-256.

**The constant causes the behaviour rather than describing it**, which is the
point of passing it to :func:`hashlib.new` below instead of calling
``hashlib.sha256`` beside it. Two places naming the same algorithm is two places
for one to move: a manifest that declared ``sha256`` over digests produced some
other way would send anybody verifying by hand to the wrong conclusion, and the
dataset would read as altered when nothing had touched it.
"""

HMAC_FIELD: Final = "manifest_hmac"
"""The one field excluded from the manifest's own authentication tag.

A digest cannot cover the bytes that hold it. Excluding exactly one named field
is the smallest escape from that, and it is reversible: a verifier removes the
same field and recomputes.
"""

_CHUNK: Final = 1 << 16


def digest_file(path: Path) -> str:
    """Return a file's SHA-256 as hex.

    Read in binary and in chunks: the files this covers include a dataset's
    whole ``derivatives/`` tree, and a text-mode read would translate newlines
    and digest something other than what is on disk — which in this project is
    the one mistake that invalidates everything downstream.

    Args:
        path: The file to digest.

    Returns:
        The hex digest.
    """
    digest = hashlib.new(DIGEST_ALGORITHM)
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def digest_tree(root: Path, *, exclude: frozenset[str] = frozenset()) -> dict[str, str]:
    """Digest every file under ``root``, keyed by relative POSIX path.

    Args:
        root: The dataset root.
        exclude: Relative POSIX paths to leave out.

    Returns:
        Path to hex digest, sorted by path so the manifest's own bytes are
        stable across runs on the same dataset.
    """
    found: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in exclude:
            continue
        found[relative] = digest_file(path)
    return dict(sorted(found.items()))


def canonical_payload(payload: Mapping[str, object]) -> str:
    """Return the manifest's canonical text for authentication.

    Sorted keys, no insignificant whitespace, and :data:`HMAC_FIELD` removed, so
    that the tag covers the manifest's *content* and not its formatting. A
    reformatted manifest still authenticates, which is the intended behaviour:
    pretty-printing a JSON file is not tampering, and a tag that failed on it
    would train people to ignore the tag.

    Args:
        payload: The manifest, with or without its tag.

    Returns:
        The canonical JSON text.
    """
    without_tag = {key: value for key, value in payload.items() if key != HMAC_FIELD}
    return json.dumps(without_tag, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def tag_manifest(payload: Mapping[str, object], key: SecretKey) -> str:
    """Return the authentication tag for a manifest payload.

    Args:
        payload: The manifest, without its tag.
        key: The secret that built the dataset.

    Returns:
        The hex HMAC.
    """
    return authenticate(key, canonical_payload(payload))


@dataclass(frozen=True, slots=True)
class IntegrityReport:
    """What changed in a dataset since its manifest was written.

    Attributes:
        altered: Files whose digest no longer matches.
        missing: Files the manifest records that are no longer there.
        added: Files present that the manifest does not record.
        checked: How many files were compared.
        authenticated: True if the manifest's own tag verified, False if it did
            not, and None if no key was supplied — three states, because "not
            checked" and "checked and wrong" must never print the same way.
    """

    altered: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    added: tuple[str, ...] = ()
    checked: int = 0
    authenticated: bool | None = None

    @property
    def is_intact(self) -> bool:
        """Return whether the dataset matches its manifest.

        An unchecked tag does not make a dataset broken, so ``authenticated`` of
        ``None`` is not a failure. A tag that was checked and did not match is.
        """
        return not (self.altered or self.missing or self.added) and self.authenticated is not False

    @property
    def difference_count(self) -> int:
        """Return how many files differ in any way."""
        return len(self.altered) + len(self.missing) + len(self.added)


def verify_dataset(root: Path, *, key: SecretKey | None = None) -> IntegrityReport:
    """Recompute a dataset's digests and report what differs from its manifest.

    Args:
        root: The dataset root.
        key: The secret that built it. Supplying it also checks the manifest's
            own tag, which is the only part of this that detects an edit made
            deliberately rather than by accident.

    Returns:
        The report.

    Raises:
        FileNotFoundError: If there is no manifest to verify against.
        ValueError: If the manifest records no integrity section, which means it
            was written by a version of this tool that did not produce one.
    """
    manifest_path = root / layout.DEIDENT_DIR / layout.MANIFEST_JSON
    if not manifest_path.is_file():
        raise FileNotFoundError(f"no manifest at {manifest_path}")

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    integrity = payload.get("integrity")
    if not isinstance(integrity, dict) or not isinstance(integrity.get("files"), dict):
        raise ValueError(
            "this manifest records no per-file digests, so there is nothing to "
            "verify against. It was written before commissura recorded them."
        )

    recorded: dict[str, str] = integrity["files"]
    manifest_relative = (manifest_path.relative_to(root)).as_posix()
    actual = digest_tree(root, exclude=frozenset({manifest_relative}))

    altered = tuple(
        path for path, digest in recorded.items() if path in actual and actual[path] != digest
    )
    missing = tuple(path for path in recorded if path not in actual)
    added = tuple(path for path in actual if path not in recorded)

    authenticated: bool | None = None
    if key is not None:
        tag = payload.get(HMAC_FIELD)
        authenticated = isinstance(tag, str) and tag == tag_manifest(payload, key)

    return IntegrityReport(
        altered=tuple(sorted(altered)),
        missing=tuple(sorted(missing)),
        added=tuple(sorted(added)),
        checked=len(recorded),
        authenticated=authenticated,
    )
