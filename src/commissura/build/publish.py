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

**What is not promised, stated precisely because the usual word for this is
"atomic" and it would be an overclaim.** Publication is two renames: the old
root moves aside, then the staged root moves in. Between them the destination
does not exist. A process killed in that window leaves the previous dataset at
``<name>.commissura-previous-<pid>`` and nothing at the destination — recoverable
by hand, and the message says so. ``os.replace`` cannot do better for a
directory: POSIX refuses to rename over a non-empty directory and Windows
refuses to rename over a directory at all. A single atomic swap would need
``renameat2(RENAME_EXCHANGE)``, which is Linux-only, so the choice is between a
portable two-step and a platform-specific one-step, and a tool whose
cross-platform claim is tested on both chose the portable one.

**Nothing is deleted that this tool did not write.** A destination that exists,
is not empty and does not look like a commissura dataset is refused outright.
There is deliberately no ``--force``: the flag would exist so that somebody could
aim it at a directory this check is there to protect.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from commissura import layout

STAGING_SUFFIX = ".commissura-staging"
"""Suffix for the directory a build is assembled in.

A sibling of the destination rather than a system temporary directory, so that
the final move is a rename within one filesystem instead of a copy across two.
A cross-device copy would be slow on a hospital-sized dataset and, worse, would
not be a rename at all — it would reintroduce a window in which the destination
holds half of each dataset.
"""

PREVIOUS_SUFFIX = ".commissura-previous"
"""Suffix for the outgoing dataset while the new one is moved into place.

Moved aside rather than removed, so a failure during publication leaves the
previous dataset recoverable instead of leaving nothing at all.
"""


class PublicationError(Exception):
    """The destination cannot be published to, and nothing has been changed."""


@dataclass(frozen=True, slots=True)
class Staged:
    """A dataset assembled somewhere other than its destination.

    Attributes:
        root: Where the dataset was built.
        destination: Where it will be published.
    """

    root: Path
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


def begin(destination: Path) -> Staged:
    """Prepare a staging directory for a build, refusing an unsafe destination.

    Called before anything is written, so that a refusal costs nothing.

    Args:
        destination: Where the finished dataset should end up.

    Returns:
        The staging area and the destination it will be published to.

    Raises:
        PublicationError: If the destination exists, is not empty, and is not
            a dataset this tool wrote. Publishing would replace somebody's
            files, and no flag overrides it.
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

    staging = destination.with_name(f"{destination.name}{STAGING_SUFFIX}-{os.getpid()}")
    if staging.exists():  # pragma: no cover - a previous run died mid-build
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    return Staged(root=staging, destination=destination)


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
    previous: Path | None = None

    if destination.exists():
        previous = destination.with_name(f"{destination.name}{PREVIOUS_SUFFIX}-{os.getpid()}")
        if previous.exists():  # pragma: no cover - a previous run died mid-publish
            shutil.rmtree(previous)
        destination.replace(previous)

    try:
        staged.root.replace(destination)
    except OSError as exc:
        if previous is not None and not destination.exists():
            # Put the old dataset back. The window this recovers from is the one
            # the module docstring describes, and leaving the destination empty
            # would turn a failed rebuild into a lost dataset.
            previous.replace(destination)
        raise PublicationError(
            f"could not publish the staged dataset to {destination}: {exc}. "
            f"The build is complete at {staged.root} and can be moved by hand."
        ) from exc

    if previous is not None:
        shutil.rmtree(previous)
    return destination


def abandon(staged: Staged) -> None:
    """Remove a staging directory after a build that will not be published.

    Never touches the destination: a failed build must leave it exactly as it
    was, which is the other half of the contract.

    Args:
        staged: The staging area to remove.
    """
    shutil.rmtree(staged.root, ignore_errors=True)
