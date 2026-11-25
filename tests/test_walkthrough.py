"""Re-run the README's walkthrough and compare it against its captured output.

The README opens its walkthrough with a promise: *"Every output below was
captured from a real run, not written by hand."* Nothing checked it, and it
drifted three times — found by reading, never by a test:

* 2026-11-12, the ``measure`` block: captured, then never recaptured. Ten of its
  values went stale, the headline ``recall 100.00% of 3440`` against a real 3431
  among them, and ``records not included 13`` where the build block forty lines
  above said 3.
* 2026-11-21, the ``build`` block: ``0 warning(s)`` where the run printed 7, two
  residual-risk entries where there is one, and dropped-record paths from a
  different corpus.
* 2026-11-22, the ``generate`` block: a line the command prints — the ``cda``
  count at zero — simply absent from the capture.

Each time the block had been recaptured in parts, and each time the value that
drifted was one nobody thought to compare. The lesson recorded on 2026-11-21 is
that **"every captured number is unchanged" is a claim about the numbers you
compared, and a list of numbers is not a diff.** This is the diff.

**It runs the README's own commands**, parsed out of the same fenced blocks, not
a copy of them kept here. A copy would let this file pass while the command a
stranger types is wrong, which is the defect of 2026-11-07 — a conformance test
that drove the library while the CLI could not emit a conformant description —
arriving in a new place.

**Contiguous runs, which is what makes one mechanism catch both directions.** A
captured block is cut at its hand-written elisions into segments, and each
segment must appear in the real output as consecutive lines, in order. A changed
value makes its line unmatchable; a line the command prints and the capture
omits breaks the run just as surely, which a subsequence check would not notice.
That second direction is the one the ``cda`` count needed.

**What cannot be compared, and why.**

* The key is not in this repository and must not be, so a run here derives
  different pseudonyms from a different secret. Lines carrying the fingerprint
  or a ``sub-`` label are left out. The captured fingerprint is deliberately the
  old one, for the reason recorded on 2026-11-10: recapturing it would change
  every subject label printed beside it.
* ``Wrote N files to …`` is compared on its count alone, because the command
  prints an absolute path and a README must not carry one.
* The ``keygen`` block is not compared: its text says whether the platform
  honours POSIX file modes, so no two machines agree on it.
* The ``validate`` block is not compared line by line either, and that is the
  real gap in this file. Every warning it prints names a pseudonymous file, and
  the hint under each is prose the command emits unwrapped while the README
  wraps it to fit. Its one portable line — the ``CONFORMANT:`` summary, warning
  count and rule total included — is compared on its own below.

Every identifier in the walkthrough is synthetic.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import pytest

README = Path(__file__).resolve().parents[1] / "README.md"
"""Resolved from this file, for the reason `test_readme` gives."""

WALKTHROUGH_HEADING = "## The whole thing, start to finish"

EXTRA_SECTIONS: tuple[str, ...] = ("### `commissura measure`",)
"""Captured command output outside the walkthrough that is checked all the same.

``measure`` is documented in its own section rather than as a numbered step,
and it is the block that drifted worst, so leaving it out because of where it
sits on the page would miss the thing this file was written for.
"""

UNCOMPARED_STEPS = frozenset({"1", "4"})
"""Walkthrough steps whose output no two runs could agree on.

Step 1 is ``keygen`` and step 4 is ``validate``; the module docstring says what
is wrong with each. Both still run, because the steps after them need what they
produce, and :func:`test_the_validate_summary_line_is_real` covers the one line
of step 4 that travels.
"""

_FINGERPRINT = re.compile(r"\b[0-9a-f]{16}\b")
"""A key fingerprint, which a run with another key cannot reproduce."""

_SUBJECT_LABEL = re.compile(r"sub-[0-9a-f]{12}")
"""A pseudonymous label, which derives from the key."""

_WROTE = re.compile(r"^Wrote (\d+) files to ")
"""The one line whose tail is an absolute path, so only its count travels."""

_ELISION = re.compile(r"^\.\.\. .* \.\.\.$")
"""A hand-written elision, such as ``... six more of the same ...``.

The command's own ``... and 19 more linkage issue(s)`` is deliberately not one
of these: it is real output, and it is compared like any other line.
"""


@dataclass(frozen=True, slots=True)
class Step:
    """One captured command in the README.

    Attributes:
        title: The heading, so a failure names the block.
        command: The command from the ``bash`` fence.
        captured: The output from the fence under it.
        compared: Whether its lines are compared at all.
    """

    title: str
    command: str
    captured: str
    compared: bool


def _fences(body: str) -> tuple[str, str] | None:
    """Return a section's command and captured output, if it has both."""
    fences = re.findall(r"```(bash)?\n(.*?)```", body, re.DOTALL)
    if len(fences) < 2 or fences[0][0] != "bash":
        return None
    return fences[0][1].strip(), fences[1][1]


def readme_steps() -> list[Step]:
    """Return every captured command this file checks, in page order.

    Returns:
        The walkthrough's numbered steps followed by :data:`EXTRA_SECTIONS`.

    Raises:
        AssertionError: If a heading or a fence has moved. A parser that
            silently returned nothing would make this whole file pass while
            checking none of it, which is the shape of failure this project has
            recorded four times.
    """
    text = README.read_text(encoding="utf-8")
    assert WALKTHROUGH_HEADING in text, f"the README no longer has {WALKTHROUGH_HEADING!r}"
    section = text.split(WALKTHROUGH_HEADING, 1)[1].split("\n## ", 1)[0]

    steps: list[Step] = []
    for heading in re.finditer(r"^### (\d+)\. (.+)$", section, re.MULTILINE):
        pair = _fences(section[heading.end() :].split("\n### ", 1)[0])
        if pair is None:
            continue
        steps.append(
            Step(
                title=f"{heading[1]}. {heading[2]}",
                command=pair[0],
                captured=pair[1],
                compared=heading[1] not in UNCOMPARED_STEPS,
            )
        )
    assert len(steps) == 5, [step.title for step in steps]

    for name in EXTRA_SECTIONS:
        assert name in text, f"the README no longer has a {name!r} section"
        pair = _fences(text.split(name, 1)[1].split("\n### ", 1)[0])
        assert pair is not None, f"{name} no longer carries a command and its output"
        steps.append(Step(title=name, command=pair[0], captured=pair[1], compared=True))

    return steps


def argv(command: str) -> list[str]:
    """Return a README command as arguments, without the program name.

    Backslash-newline continuations are joined first, because ``build`` is
    written across five lines the way somebody would type it.
    """
    parts = shlex.split(command.replace("\\\n", " "))
    assert parts[0] == "commissura", parts[0]
    return parts[1:]


def comparable(text: str) -> list[str]:
    """Return a block's lines, wrap-joined and normalised, minus what cannot travel.

    A line indented further than the indented line above it is joined onto it,
    because the README hard-wraps long detail lines that the command prints
    whole. Joining first is what lets this assert on the content instead of on
    the column somebody wrapped it at.

    Args:
        text: A captured block, or a command's real output.

    Returns:
        The lines worth comparing, whitespace collapsed.
    """
    joined: list[tuple[str, int]] = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip())
        previous = joined[-1][1] if joined else -1
        if joined and indent > previous >= 4:
            joined[-1] = (f"{joined[-1][0]} {raw.strip()}", previous)
        else:
            joined.append((raw.strip(), indent))

    kept: list[str] = []
    for line, _ in joined:
        if _FINGERPRINT.search(line) or _SUBJECT_LABEL.search(line):
            continue
        wrote = _WROTE.match(line)
        kept.append(f"Wrote {wrote[1]} files" if wrote else " ".join(line.split()))
    return kept


def segments(lines: list[str]) -> list[list[str]]:
    """Split captured lines at their elisions into runs that must be contiguous."""
    found: list[list[str]] = [[]]
    for line in lines:
        if _ELISION.match(line):
            found.append([])
        else:
            found[-1].append(line)
    return [segment for segment in found if segment]


def locate(segment: list[str], real: list[str], start: int) -> int | None:
    """Return where ``segment`` appears in ``real`` at or after ``start``."""
    for index in range(start, len(real) - len(segment) + 1):
        if real[index : index + len(segment)] == segment:
            return index
    return None


def divergence(segment: list[str], real: list[str], start: int) -> str:
    """Return the most useful failure message for a segment that did not match.

    The candidate position with the longest matching prefix is the one the
    reader wants: it names the first line that differs and what the command
    printed in its place, rather than dumping both blocks.
    """
    best_index, best_length = start, -1
    for index in range(start, max(start + 1, len(real))):
        length = 0
        while (
            length < len(segment)
            and index + length < len(real)
            and real[index + length] == segment[length]
        ):
            length += 1
        if length > best_length:
            best_index, best_length = index, length
    position = best_index + max(best_length, 0)
    printed = real[position] if position < len(real) else "<nothing: the output ended>"
    expected = segment[best_length] if best_length < len(segment) else "<nothing more>"
    return f"the README says:\n    {expected}\n  the command printed:\n    {printed}"


class Walkthrough(NamedTuple):
    """What one run of the README's own commands produced.

    The directory is kept alongside the output because the README quotes the
    manifest as well as the terminal, and a fragment of a document the run
    wrote can only be checked against the document itself.
    """

    printed: dict[str, str]
    root: Path


@pytest.fixture(scope="module")
def walkthrough(tmp_path_factory: pytest.TempPathFactory) -> Walkthrough:
    """Run every captured command in one directory and return what each printed.

    They share a directory because they share their artefacts: `build` reads
    what `generate` wrote and `measure` compares the two. The commands are the
    README's own, so they write to ``./raw`` and read ``./commissura.key``,
    which is why each runs with its working directory moved there rather than
    with paths invented here.

    Run as subprocesses through ``python -m commissura`` rather than in process:
    what the README shows is what a terminal shows, and that is the thing being
    compared.
    """
    root = tmp_path_factory.mktemp("walkthrough")
    produced: dict[str, str] = {}

    for step in readme_steps():
        finished = subprocess.run(
            [sys.executable, "-m", "commissura", *argv(step.command)],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        assert finished.returncode == 0, f"{step.title}\n{finished.stdout}{finished.stderr}"
        produced[step.title] = finished.stdout

    return Walkthrough(printed=produced, root=root)


@pytest.mark.parametrize(
    "step",
    [step for step in readme_steps() if step.compared],
    ids=lambda step: step.title,
)
def test_the_captured_block_is_what_the_command_prints(
    step: Step, walkthrough: Walkthrough
) -> None:
    """Every captured segment, as consecutive lines of the real output.

    One assertion for both kinds of drift: a value that changed makes its line
    unmatchable, and a line the command prints that the capture skips breaks
    the run. The second is what four days of a missing ``cda`` count needed,
    and what a subsequence check would have let through.
    """
    real = comparable(walkthrough.printed[step.title])
    position = 0

    for segment in segments(comparable(step.captured)):
        index = locate(segment, real, position)
        assert index is not None, (
            f"the capture for {step.title} has drifted from the real run.\n  "
            + divergence(segment, real, position)
        )
        position = index + len(segment)


def test_the_validate_summary_line_is_real(walkthrough: Walkthrough) -> None:
    """The one line of step 4 that two machines can agree on.

    It carries the error, warning and notice counts and the number of rules
    that ran, which is every number in that block. The rest names pseudonymous
    files. The warning count is also stated in the build block, and the two had
    drifted apart once: `test_readme` compares those two with each other, and
    this compares one of them with a run.
    """
    step = next(step for step in readme_steps() if step.title.startswith("4."))
    stated = [line for line in comparable(step.captured) if line.startswith("CONFORMANT:")]
    real = comparable(walkthrough.printed[step.title])

    assert len(stated) == 1, stated
    assert stated[0] in real, f"the README says:\n  {stated[0]}\nthe command printed:\n  {real[-1]}"


def test_this_file_declares_nothing_about_a_step_that_is_gone() -> None:
    """A guard on this file's own hand-written judgement.

    :data:`UNCOMPARED_STEPS` is a claim about the README that nothing else
    checks, and a step renumbered or removed would turn it into an exemption
    for a block that is not there — which silently stops comparing one that
    is.
    """
    numbers = {step.title.split(".", 1)[0] for step in readme_steps() if step.title[0].isdigit()}

    assert numbers >= UNCOMPARED_STEPS


def test_the_readme_says_the_walkthrough_is_re_run() -> None:
    """So whoever edits a captured block learns that it is checked.

    Without the sentence the check is invisible, and an invisible check is one
    somebody fights rather than uses. Whitespace is collapsed before looking,
    for the reason `test_readme` gives.
    """
    text = " ".join(README.read_text(encoding="utf-8").split())

    assert "A test re-runs this walkthrough" in text


ILLUSTRATIVE_FIELDS = frozenset({"other labelled lines"})
"""Ledger rows the README shows that this corpus cannot produce.

`other labelled lines` is the row that appears when a report carries a header
label this tool does not recognise, and the walkthrough's corpus uses labels
it does. The README says so beside the fragment; this names it here so that
the comparison below can be exact about everything else.
"""


def test_the_manifest_fragments_are_what_the_build_wrote(walkthrough: Walkthrough) -> None:
    """Every ledger row the README quotes, against the manifest of a real run.

    The README quotes the per-modality table in fragments, and a fragment is
    recaptured by hand or not at all. Two of them had gone stale by the time
    anybody looked: the imaging rows still said `files_present: 13` from a
    ten-subject era while the walkthrough writes twenty-seven sidecars, and
    the prose under them restated it as "three of thirteen".

    The build already runs for this module, so checking its manifest costs
    nothing. It is the same argument that paid for re-running the walkthrough
    itself: the README promises these came from a real run, and a promise with
    no check behind it is the thing this file exists to retire.
    """
    manifest = json.loads(
        (walkthrough.root / "dataset" / ".deident" / "manifest.json").read_text(encoding="utf-8")
    )
    written = {
        row["field"]: row
        for modality in manifest["modalities"]
        for row in modality.get("fields", [])
    }

    quoted = re.findall(r'\{\s*"field": "([^"]+)"(.*?)\}', README.read_text(encoding="utf-8"), re.S)
    checked = 0
    for field, body in quoted:
        if field in ILLUSTRATIVE_FIELDS:
            continue
        assert field in written, f"the README quotes a row for {field!r} that no build wrote"
        present = re.search(r'"files_present": (\d+)', body)
        if present:
            assert int(present.group(1)) == written[field]["files_present"], (
                field,
                present.group(1),
                written[field]["files_present"],
            )
            checked += 1
    assert checked >= 3, f"only {checked} quoted rows carried a count"
