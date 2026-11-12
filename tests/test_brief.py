"""Checks on the brief, which is this project's memory and drifts like any prose.

``CLAUDE.md`` is read first in every new session, and its summary sections went
stale once while the decision log below them stayed accurate: the list of
finished commands still named five when there were eight, so a new reader would
have concluded that ``build`` did not exist and that conformance was still
unproven. Most of that file is prose and no test can judge it. The list of
commands is not prose, and it is the one fact in the file whose going stale was
expensive, so it is pinned here.
"""

from __future__ import annotations

import re
from pathlib import Path

from typer.main import get_command

from commissura.cli import app

BRIEF = Path(__file__).resolve().parents[1] / "CLAUDE.md"
"""Resolved from this file, not from the working directory.

A path relative to the working directory makes a test pass or skip depending on
where ``pytest`` was started, which has already caught this project out once.
"""

CURRENT_STATE = "## Current state"


def registered_command_names() -> set[str]:
    """Return the command names ``commissura --help`` actually offers.

    Returns:
        The names typer resolved: those it derived from the function names, and
        the explicit ones given to the commands whose functions are called
        something else. Asking typer rather than reading the decorators is the
        point — a test that re-implemented the naming rule could agree with
        itself while disagreeing with the CLI.
    """
    group = get_command(app)
    commands = getattr(group, "commands", None)
    assert commands is not None, "the CLI stopped being a group of commands"
    return set(commands)


def paragraph_under_current_state() -> str:
    """Return the first paragraph of the brief's ``## Current state`` section.

    Returns:
        The text between the heading and the first blank line after it.
    """
    text = BRIEF.read_text(encoding="utf-8")
    assert CURRENT_STATE in text, f"CLAUDE.md no longer has a {CURRENT_STATE!r} section"
    return text.split(CURRENT_STATE, 1)[1].lstrip("\n").split("\n\n", 1)[0]


def test_the_brief_names_every_command_and_no_others() -> None:
    """The one drift in the brief a machine can catch, caught.

    An exact comparison, not a subset check: a subset check would not notice a
    command that had been removed. That is why the paragraph is kept free of
    other backquoted lower-case words.
    """
    named = set(re.findall(r"`([a-z][a-z-]*)`", paragraph_under_current_state()))
    assert named == registered_command_names()


def test_the_brief_says_that_the_list_is_pinned() -> None:
    """Whoever rewrites that paragraph should learn from it that it is checked.

    Without the sentence the check is invisible: somebody edits the list, this
    test fails, and they have to go looking for the reason.

    Whitespace is collapsed before looking. Adding a command lengthens the list
    and rewraps the prose around it, and a sentinel that broke on a line break
    would fail for the one edit it exists to accompany — telling the author
    their correct change is wrong, which is how a check gets deleted.
    """
    flattened = " ".join(paragraph_under_current_state().split())

    assert "A test pins that list" in flattened
