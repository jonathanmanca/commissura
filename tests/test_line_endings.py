"""Every text file this repository tracks holds LF line endings on disk.

`.gitattributes` declares `* text=auto eol=lf`, and its own comment says the
rule holds on every platform and in every working copy. The reason given there
is exact bytes: the corpus writer exists to put them on disk, every recorded
PHI offset is a character position into a file, and HL7 v2 terminates a segment
with a bare carriage return -- so a newline conversion applied to a fixture
would shift every offset after the first and be nearly invisible in a diff.

**Nothing checked it, and eleven files had drifted.** Found on 2026-11-25 by
comparing the wheel uploaded to TestPyPI against `src/commissura` file by file:
five modules and six test modules were pure CRLF in the working tree. They were
harmless, because git normalises on commit, so the repository, the wheel and
every fresh checkout were LF -- and that is exactly why nobody noticed. `git
status` was clean throughout, which this project has recorded once already is
not evidence that anything is as it should be.

**This test can only fail on a working copy, never in CI**, because a CI run
checks the tree out fresh and `eol=lf` makes that checkout LF whatever was
written locally. That is not a reason to leave the rule unguarded: the drift
happens on the machine where files are written, which is the only place it can
be seen, and a rule nothing checks is one this project has watched go stale
repeatedly. It was watched failing on those eleven files before they were
normalised.

**It asks git rather than walking the tree**, and the first version walked.
A walk reports whatever happens to be lying in the working directory -- it
flagged a gitignored `commissura.key` on the first run -- and a guard that
cries wolf over untracked scratch files is one somebody deletes. The rule
belongs to `.gitattributes`, which governs what git tracks, so that is the set
to ask about.

`third_party/` is excluded. `-text` switches off every conversion there on
purpose -- the decision of 2026-11-19, so that the repository holds what the
publisher serves and `NOTICE`'s claim that each vendored file is unmodified
stays true if upstream ever ships CRLF.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARRIAGE_RETURN = b"\r"
BYTE_FOR_BYTE = "third_party"


def _is_text(data: bytes) -> bool:
    """Return whether these bytes are text, decided without a list of suffixes."""
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _tracked_text_files() -> list[tuple[Path, bytes]]:
    """Return every tracked text file the line-ending rule covers, with its bytes."""
    listed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    found: list[tuple[Path, bytes]] = []
    for entry in sorted(listed.split(b"\0")):
        if not entry:
            continue
        relative = Path(entry.decode())
        if relative.parts[0] == BYTE_FOR_BYTE:
            continue
        path = ROOT / relative
        if not path.is_file():
            continue
        data = path.read_bytes()
        if _is_text(data):
            found.append((path, data))
    return found


def test_there_is_something_to_check() -> None:
    names = {path.name for path, _ in _tracked_text_files()}
    assert {"pyproject.toml", "README.md", "scrub.py", "LICENSE"} <= names


def test_no_tracked_text_file_carries_a_carriage_return() -> None:
    offenders: list[str] = []
    for path, data in _tracked_text_files():
        count = data.count(CARRIAGE_RETURN)
        if count:
            offenders.append(f"{path.relative_to(ROOT).as_posix()} ({count} CR)")
    assert offenders == [], (
        "`.gitattributes` declares LF in every working copy; these tracked files "
        "hold carriage returns on disk: " + ", ".join(offenders)
    )
