"""Checks on the README, which is the only documentation a stranger reads.

This guard used to point at ``CLAUDE.md``, where the list of finished commands
went stale once: it still named five when there were eight, so a new reader
would have concluded that ``build`` did not exist and that conformance was
unproven. The brief left this repository on 2026-11-14, so the check moved to
the README — which is the better target anyway, and not only because it is
still here. The brief is read by whoever is already working on the project; the
README is read by somebody deciding whether to. A stale command list costs more
in the second place.

Most of the README is prose and no test can judge it. The command table is not
prose, and its ``Status`` column makes a claim the project has a convention
about — *do not mark a command available before it runs end to end* — so that
is pinned too.
"""

from __future__ import annotations

import re
from pathlib import Path

from typer.main import get_command

from commissura.cli import app

README = Path(__file__).resolve().parents[1] / "README.md"
"""Resolved from this file, not from the working directory.

A path relative to the working directory makes a test pass or skip depending on
where ``pytest`` was started, which has already caught this project out once.
"""

COMMANDS_HEADING = "## Commands"

_ROW = re.compile(
    r"^\|\s*`commissura (?P<name>[a-z][a-z-]*)`\s*\|(?P<what>[^|]*)\|\s*(?P<status>[^|]+?)\s*\|$",
    re.MULTILINE,
)


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


def command_table() -> dict[str, str]:
    """Return the README's command table as name to status.

    Returns:
        One entry per row of the table under :data:`COMMANDS_HEADING`.
    """
    text = README.read_text(encoding="utf-8")
    assert COMMANDS_HEADING in text, f"the README no longer has a {COMMANDS_HEADING!r} section"
    section = text.split(COMMANDS_HEADING, 1)[1].split("\n## ", 1)[0]
    rows = {match["name"]: match["status"].strip() for match in _ROW.finditer(section)}
    assert rows, "the command table has no rows this test can read"
    return rows


def test_every_command_marked_available_exists_and_every_command_is_listed() -> None:
    """Both directions, because each one fails differently.

    A command missing from the table is a feature nobody can find. A row
    claiming a command that is not registered is a README promising something
    the tool does not do, which is worse — and the second is the one a subset
    check in the convenient direction would miss.

    Compared on the rows marked ``available`` rather than on every row, because
    the project's convention allows the table to list work that is planned. A
    row in any other state must *not* resolve to a registered command, or the
    README is understating what exists.
    """
    table = command_table()
    available = {name for name, status in table.items() if status == "available"}
    registered = registered_command_names()

    assert available == registered
    assert not [
        name for name, status in table.items() if status != "available" and name in registered
    ]


def test_the_readme_says_that_the_table_is_pinned() -> None:
    """Whoever edits the table should learn from it that it is checked.

    Without the sentence the check is invisible: somebody adds a command, this
    test fails, and they have to go looking for the reason. Whitespace is
    collapsed before looking, because adding a row rewraps the prose around it
    and a sentinel that broke on a line break would fail for the one edit it
    exists to accompany — telling the author their correct change is wrong,
    which is how a check gets deleted.
    """
    text = README.read_text(encoding="utf-8")
    section = text.split(COMMANDS_HEADING, 1)[1].split("\n## ", 1)[0]

    assert "A test pins this table" in " ".join(section.split())


def test_the_two_captured_warning_counts_agree() -> None:
    """The README states the same number twice, and the two had drifted apart.

    `build` prints its own validation line and the `validate` section prints the
    full report, so the warning count appears in two captured blocks. One was
    recaptured and the other was not: the build block read `0 warning(s)` for
    weeks while the validate block read `7` and the real run produced `7`. A
    reader comparing the two screens would conclude the tool is inconsistent.

    **What this does not do, said plainly.** It compares the README with itself,
    not with a real run, so a number stale in *both* places passes here. That
    is `test_walkthrough`'s job now: it re-runs every captured command and
    compares each block against what the command prints. This check is kept
    because the two blocks state one number twice and agreeing with each other
    is a separate claim from agreeing with a run — and because it costs nothing,
    where that one costs half a minute.
    """
    text = README.read_text(encoding="utf-8")

    counts = re.findall(r"(\d+) warning\(s\)", text)

    assert len(counts) >= 2, counts
    # The one in the "not conformant" example is deliberately a different run.
    conformant = re.findall(r"0 error\(s\), (\d+) warning\(s\)", text)
    assert len(set(conformant)) == 1, (
        "the README states two different warning counts for the same walkthrough run: "
        f"{sorted(set(conformant))}"
    )
