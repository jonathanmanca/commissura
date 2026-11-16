"""Build somewhere else, then put it in place. Or refuse, and change nothing.

A build used to write straight into its destination, which meant a second build
into the same directory left the first build's files wherever the second one did
not happen to overwrite them. The audit of 2026-11-13 found what that costs: an
imaging study was withdrawn from the corpus, the dataset was rebuilt into the
same directory, the build reported ``conforms`` with a zero exit code — and the
withdrawn study was still there, digested into the new manifest and certified
``INTACT`` by ``commissura verify`` for as long as the dataset existed.

A data holder acting on a patient's objection by removing records and rebuilding
had not removed them. That is the failure this module exists to make impossible.

**The contract.** A successful build publishes exactly what the current corpus
and configuration produced. Nothing from a previous build survives it. A failed
build leaves the destination as it was.

**Nothing is deleted that this tool did not write, and the mechanism is a
marker rather than a name.** The first version of this module named its working
directory ``<destination>.commissura-staging-<pid>`` and, if that path already
existed, removed it with ``shutil.rmtree``. Two things were wrong with that. The
name was predictable — process ids are small and reused — so an unrelated
directory could occupy it. And the removal established ownership from the name
alone, which is not evidence of anything.

Both working directories are now created with :func:`tempfile.mkdtemp`, in the
destination's parent. That is atomic, mode ``0o700``, and cannot collide, so
**the "if it already exists, delete it" branch does not exist** — the fix was to
make it unnecessary rather than to guard it. Each holds a marker naming the
destination it is for, and every removal in this module verifies that marker
first. A directory without one is refused and left alone.

**The layout, which has a reason.** The dataset is built in ``payload/`` *inside*
the working directory, beside the marker:

```
<destination's parent>/
    commissura-staging-<random>/
        .commissura-staging.json   the marker, never published
        payload/                   the dataset being built
```

Publishing moves ``payload`` into place, so the marker cannot end up in the
released dataset. Putting the marker inside the tree being published and
deleting it just before the rename would also work and would be one more thing
to get wrong.

**What is not promised, stated precisely because the usual word for this is
"atomic" and it would be an overclaim.** Publication is two renames: the old
root moves aside, then the staged root moves in. Between them the destination
does not exist. A process killed in that window leaves the previous dataset in
a working directory whose marker names where it came from, and nothing at the
destination — recoverable by hand, and the message says so. ``os.replace``
cannot do better for a directory: POSIX refuses to rename over a non-empty
directory and Windows refuses to rename over a directory at all. A single atomic
swap would need ``renameat2(RENAME_EXCHANGE)``, which is Linux-only, so the
choice is between a portable two-step and a platform-specific one-step, and a
tool whose cross-platform claim is tested on both chose the portable one.

**Concurrency is not serialised, and that is a documented limit rather than an
oversight.** Two builds publishing to one destination each get their own working
directory, so neither can corrupt the other's output, and each rename is atomic
— so the destination always holds one *complete* dataset and never a mixture of
two. Which of them wins is undefined, and the loser may find the destination
already moved by the time it looks: that is caught and reported rather than
raised as a traceback. Locking would be the fix if this were a service. The
expected load is one person running a command-line tool on a folder of files.

**There is deliberately no ``--force``.** A destination that exists, is not
empty and does not look like a commissura dataset is refused outright. The flag
would exist so that somebody could aim it at the directory this check protects.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from commissura import layout

WORKING_PREFIX: Final = "commissura-staging-"
"""Prefix for the directory a build is assembled in.

A sibling of the destination rather than a system temporary directory, so the
final move is a rename within one filesystem instead of a copy across two. A
cross-device copy would be slow on a hospital-sized dataset and, worse, would
not be a rename at all — it would reintroduce a window in which the destination
holds half of each dataset.
"""

OUTGOING_PREFIX: Final = "commissura-previous-"
"""Prefix for the directory the outgoing dataset is moved into.

Moved aside rather than removed, so a failure during publication leaves the
previous dataset recoverable instead of leaving nothing at all.
"""

MARKER_NAME: Final = ".commissura-staging.json"
"""The file that makes a working directory provably ours.

Read before anything in this module removes a directory. A directory without a
marker, or with one naming a different destination, is refused and left alone —
which is the difference between deleting what we created and deleting what
happens to sit at a path we guessed.
"""

PAYLOAD_NAME: Final = "payload"
"""The subdirectory the dataset is built in, so the marker is never published."""


class PublicationError(Exception):
    """The destination cannot be published to, and nothing has been changed."""


@dataclass(frozen=True, slots=True)
class Staged:
    """A dataset being assembled somewhere other than its destination.

    Attributes:
        root: Where the dataset is built. This is what a caller writes into.
        holding: The working directory that contains ``root`` and the marker.
            Nothing outside this module needs it.
        destination: Where the dataset will be published.
    """

    root: Path
    holding: Path
    destination: Path


def looks_like_our_dataset(root: Path) -> bool:
    """Return whether a directory looks like something this tool produced.

    The test is the presence of a file only ``build`` writes:
    ``.deident/manifest.json``, or ``dataset_description.json`` for a dataset
    built before the manifest existed. Deliberately narrow — this is the guard
    that stands between a mistyped ``--out`` and somebody's home directory, so
    it answers "did we write this" and not "does this look datasetish".

    Args:
        root: The directory to inspect.

    Returns:
        Whether publishing over it would be replacing our own output.
    """
    if (root / layout.DEIDENT_DIR / layout.MANIFEST_JSON).is_file():
        return True
    return (root / layout.DATASET_DESCRIPTION).is_file()


def _is_empty(root: Path) -> bool:
    """Return whether a directory holds nothing at all."""
    return not any(root.iterdir())


def _write_marker(holding: Path, destination: Path) -> None:
    """Record which destination this working directory belongs to."""
    payload = {
        "tool": "commissura",
        "destination": str(destination),
        "pid": os.getpid(),
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    with (holding / MARKER_NAME).open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2) + "\n")


def _verify_marker(holding: Path, destination: Path) -> None:
    """Refuse to touch a working directory that is not provably ours.

    Checked before every removal in this module, because establishing ownership
    from a path is not establishing ownership. A symlink is refused outright: a
    marker read through one says nothing about what the removal would reach.

    Args:
        holding: The directory to verify.
        destination: The destination it must name.

    Raises:
        PublicationError: If the directory is a symlink, or holds no readable
            marker, or holds one naming a different destination.
    """
    if holding.is_symlink():
        raise PublicationError(
            f"{holding} is a symbolic link, not a directory this build created. "
            "Refusing to touch it."
        )
    marker = holding / MARKER_NAME
    try:
        recorded = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicationError(
            f"{holding} carries no readable {MARKER_NAME}, so it is not provably a "
            f"working directory this build created. Refusing to touch it: {exc}"
        ) from None
    if not isinstance(recorded, dict) or recorded.get("destination") != str(destination):
        raise PublicationError(
            f"the {MARKER_NAME} in {holding} does not name {destination}. Refusing to touch it."
        )


def _remove_verified(holding: Path, destination: Path) -> None:
    """Remove a working directory, after proving it is one of ours."""
    _verify_marker(holding, destination)
    shutil.rmtree(holding)


def _new_holding(destination: Path, prefix: str) -> Path:
    """Create a fresh working directory beside the destination.

    :func:`tempfile.mkdtemp` creates it atomically with a random name and mode
    ``0o700``, so it cannot collide with anything and there is nothing to
    remove first.

    Args:
        destination: The dataset's destination; its parent is used.
        prefix: :data:`WORKING_PREFIX` or :data:`OUTGOING_PREFIX`.

    Returns:
        The new directory.

    Raises:
        PublicationError: If it could not be created, which usually means the
            destination's parent is missing or not writable.
    """
    parent = destination.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix=prefix, dir=parent))
    except OSError as exc:
        raise PublicationError(
            f"could not create a working directory beside {destination}: {exc}. "
            "The build needs somewhere to assemble the dataset on the same "
            "filesystem as its destination."
        ) from None


def begin(destination: Path) -> Staged:
    """Prepare a working directory for a build, refusing an unsafe destination.

    Called before anything is written, so that a refusal costs nothing.

    Args:
        destination: Where the finished dataset should end up.

    Returns:
        The staging area and the destination it will be published to.

    Raises:
        PublicationError: If the destination exists, is not empty, and is not a
            dataset this tool wrote — publishing would replace somebody's files,
            and no flag overrides it — or if a working directory could not be
            created.
    """
    destination = destination.resolve()
    if destination.exists():
        if not destination.is_dir():
            raise PublicationError(f"{destination} is not a directory. Pick a directory for --out.")
        if not _is_empty(destination) and not looks_like_our_dataset(destination):
            raise PublicationError(
                f"{destination} is not empty and does not look like a commissura "
                f"dataset: it holds no {layout.DEIDENT_DIR}/{layout.MANIFEST_JSON} "
                f"and no {layout.DATASET_DESCRIPTION}. Refusing to publish over it. "
                "Choose an empty directory, or move that one aside yourself."
            )

    holding = _new_holding(destination, WORKING_PREFIX)
    _write_marker(holding, destination)
    root = holding / PAYLOAD_NAME
    root.mkdir()
    return Staged(root=root, holding=holding, destination=destination)


def publish(staged: Staged) -> Path:
    """Move a staged dataset into its destination, keeping the old one until it is in.

    Args:
        staged: The staging area and its destination.

    Returns:
        The destination, now holding exactly the staged dataset.

    Raises:
        PublicationError: If the move failed. The message says where the
            previous dataset is, because by then it may be the only copy.
    """
    destination = staged.destination
    _verify_marker(staged.holding, destination)

    outgoing: Path | None = None
    if destination.exists():
        outgoing = _new_holding(destination, OUTGOING_PREFIX)
        _write_marker(outgoing, destination)
        try:
            destination.replace(outgoing / PAYLOAD_NAME)
        except FileNotFoundError:
            # Another build published between the check and the rename. Nothing
            # is lost -- the destination holds a complete dataset either way --
            # and this build still has its own to put there.
            _remove_verified(outgoing, destination)
            outgoing = None
        except OSError as exc:
            _remove_verified(outgoing, destination)
            raise PublicationError(
                f"could not move the existing dataset at {destination} aside: {exc}. "
                f"Nothing was changed; the new build is complete at {staged.root}."
            ) from None

    try:
        staged.root.replace(destination)
    except OSError as exc:
        if outgoing is not None and not destination.exists():
            # Put the old dataset back. The window this recovers from is the one
            # the module docstring describes, and leaving the destination empty
            # would turn a failed rebuild into a lost dataset.
            (outgoing / PAYLOAD_NAME).replace(destination)
            _remove_verified(outgoing, destination)
        raise PublicationError(
            f"could not publish the staged dataset to {destination}: {exc}. "
            f"The build is complete at {staged.root} and can be moved by hand."
        ) from None

    if outgoing is not None:
        _remove_verified(outgoing, destination)
    _remove_verified(staged.holding, destination)
    return destination


def abandon(staged: Staged) -> None:
    """Remove a working directory after a build that will not be published.

    Never touches the destination: a failed build must leave it exactly as it
    was, which is the other half of the contract. Never removes a directory
    whose marker does not name this destination, which is the other half of
    not deleting what we did not write.

    Args:
        staged: The staging area to remove.
    """
    try:
        _remove_verified(staged.holding, staged.destination)
    except (PublicationError, OSError):
        # Abandoning runs on the way out of a failed build, so it must not
        # replace the original failure with one of its own. A working directory
        # left behind is visible, named and harmless; it carries a marker
        # saying what it was for.
        return
