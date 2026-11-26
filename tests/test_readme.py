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
from commissura.read.identity import RefusalReason
from commissura.validate import registered_rules

DROP_REASONS = frozenset({"undated_record", "subject_has_no_dated_event"})
"""The two reasons a record that linked is still absent from the dataset.

Unlike :class:`RefusalReason` these are string literals in
``build/writer.py``, so there is nothing to import and this set is a
transcription. The honest limit that follows: the guard below catches a reason
the README invents or misspells, and not a third reason the code grows.
"""

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


def test_the_readme_links_nothing_relatively() -> None:
    """The README is the long description, so a relative link is broken on PyPI.

    `pyproject.toml` declares `readme = "README.md"`, so this file is what
    renders as the project page. PyPI does not resolve a relative target
    against the repository that produced the archive, and it has no reason to:
    the archive could have come from anywhere. So `[LICENSE](LICENSE)` resolves
    under `pypi.org/project/commissura/` and 404s, while reading as a working
    link right up until somebody clicks it.

    Eight of them shipped in 0.1.0 and 0.1.1 before anybody looked, found on
    2026-11-25 while adding the badge row — one of whose links would have been
    the ninth. The README has two audiences and only one of them can follow a
    relative path; an absolute URL works for both.

    Anchors are deliberately not caught: `#section` resolves on either.

    **Raw HTML counts too**, which the first version of this guard missed. It
    matched Markdown link syntax only, and the logo added on 2026-11-26 is an
    `<img src=...>` -- so a relative path there would have been the ninth 404
    on the page, past a test written to stop the eighth.
    """
    body = README.read_text(encoding="utf-8")
    relative = re.findall(r"\]\((?!https?://|#)([^)]+)\)", body)
    relative += re.findall(r'(?:src|srcset|href)="(?!https?://|#)([^"]+)"', body)
    assert relative == [], relative


def _heading_slugs(text: str) -> set[str]:
    """Return the anchor GitHub and PyPI derive from each heading.

    Both lowercase the text, drop everything that is not a letter, a digit, a
    space or a hyphen, and join the rest with hyphens. Backticks and
    apostrophes vanish, which is why `` `commissura risk` `` becomes
    `commissura-risk` and "the profile's own shapes" becomes
    `the-profiles-own-shapes`.
    """
    slugs = set()
    for heading in re.findall(r"^#{1,6} +(.+?)\s*$", text, re.MULTILINE):
        kept = re.sub(r"[^\w\- ]", "", heading.lower(), flags=re.UNICODE)
        slugs.add(re.sub(r"\s+", "-", kept.strip()))
    return slugs


def test_every_anchor_in_the_readme_has_a_heading() -> None:
    """An anchor with no heading is a link that silently does nothing.

    It is worse than the relative links above rather than better: a 404 at
    least tells the reader something went wrong, while a dangling `#section`
    leaves the page exactly where it was, which reads as the link being
    ignored by the browser.

    PyPI does resolve these, which was not obvious and was measured rather
    than assumed: `readme_renderer` emits no `id` on a heading at all, so the
    rendered HTML alone suggests every in-page link is dead. Warehouse adds
    them afterwards, prefixed `user-content-`, and rewrites the anchors to
    match — so of the eight in-page links on the published 0.1.1 page, seven
    jumped and exactly one did not.

    That one was `#the-de-identification-manifest`, pointing at a heading that
    has never existed, broken on GitHub for as long as it has been there and
    found on 2026-11-25 by reading the live page rather than the source.
    """
    text = README.read_text(encoding="utf-8")
    anchors = set(re.findall(r"\]\(#([^)]+)\)", text))
    assert anchors, "the README uses no in-page links, so this guard checks nothing"
    assert anchors <= _heading_slugs(text), sorted(anchors - _heading_slugs(text))


def test_the_readme_counts_the_same_records_twice_and_agrees_with_itself() -> None:
    """The walkthrough's build block and the manifest fragment describe one run.

    They are forty lines apart and were recaptured apart, which is how the
    fragment came to read 17 + 12 = 29 linkage issues under a block printing
    49. A third reason had appeared in between, `invalid_national_identifier`
    at 20, and nothing compared the two.

    That is the third time a README number has gone stale because the output
    was recaptured in parts, so this checks the arithmetic that ties them:
    the reasons in the fragment must add up to the number the command printed,
    and the dropped records must agree across all three places they are
    stated. It cannot see a number stale in every place at once, which is what
    `tests/test_walkthrough.py` is for — it re-runs the command.
    """
    text = README.read_text(encoding="utf-8")

    printed = re.search(r"^  linkage issues +(\d+)$", text, re.MULTILINE)
    dropped = re.search(r"^  records dropped +(\d+)", text, re.MULTILINE)
    assert printed and dropped, "the build block no longer prints these lines"

    counts = [int(n) for n in re.findall(r'"reason": "\w+",? *"count": (\d+)', text)]
    assert len(counts) == 4, counts  # three linkage reasons and one drop reason
    assert sum(counts[:3]) == int(printed.group(1)), (counts, printed.group(1))
    assert counts[3] == int(dropped.group(1)), (counts, dropped.group(1))

    stated = re.search(r'"records_not_in_dataset": +(\d+)', text)
    assert stated and stated.group(1) == dropped.group(1), "the two totals disagree"


def test_every_refusal_reason_the_readme_names_is_one_the_code_emits() -> None:
    """A worked manifest fragment must not invent a reason, or misspell one.

    The fragment is the only place a reader sees what `linkage_issues` looks
    like, so a reason that no build can produce teaches them to look for
    something that will never appear.
    """
    named = set(re.findall(r'"reason": "(\w+)"', README.read_text(encoding="utf-8")))
    assert named, "the README shows no worked reasons, so this guard checks nothing"
    real = {reason.value for reason in RefusalReason} | DROP_REASONS
    assert named <= real, sorted(named - real)


def test_the_rule_total_the_readme_prints_is_the_real_one() -> None:
    """`from N rules` appears twice, and only one of the two is ever re-run.

    `tests/test_walkthrough.py` executes the walkthrough's `validate` and
    compares its summary line, so that occurrence is pinned by a run. The
    other sits in the `commissura validate` section as a hand-written example
    of a dataset that does not conform, and nothing has ever checked it. Both
    say 40 today; a rule added to the registry would move one and leave the
    other, which is the shape of drift this project keeps finding.
    """
    totals = {int(n) for n in re.findall(r"from (\d+) rules", README.read_text(encoding="utf-8"))}
    assert totals, "the README prints no rule total, so this guard checks nothing"
    assert totals == {len(registered_rules())}, (totals, len(registered_rules()))


def test_the_readme_counts_the_packages_the_lockfile_pins() -> None:
    """A number stating how many dependencies are pinned, next to the lockfile.

    It read 36 while `uv.lock` held 41 entries, one of which is `commissura`
    itself — so the dependency set had grown by four and the sentence beside
    it had not. Nobody would notice: the figure is plausible, it is in a
    paragraph about reproducibility, and the lockfile is the one file in the
    repository nobody reads.
    """
    lock = README.parent / "uv.lock"
    entries = len(re.findall(r"^\[\[package\]\]", lock.read_text(encoding="utf-8"), re.MULTILINE))
    stated = re.search(r"pins all (\d+) packages", README.read_text(encoding="utf-8"))
    assert stated, "the README no longer states how many packages the lock pins"
    assert int(stated.group(1)) == entries - 1, (stated.group(1), entries)
