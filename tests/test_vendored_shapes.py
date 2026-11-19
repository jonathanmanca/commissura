"""The conformance check's own preconditions, so it can no longer skip silently.

This project's headline claim is that `commissura` emits HealthDCAT-AP-conformant
dataset descriptions, and `tests/test_shacl_conformance.py` is what turns that
from a reading of the specification into a verdict from the specification's own
shapes. Until now it **skipped** unless the shapes happened to be on the machine:
they were downloaded on demand into a gitignored directory, so the claim was
checked wherever one person had run four `curl` commands and nowhere else. CI
showed a green tick for a check it never performed.

That is the failure mode this project has recorded three times — a skip is a
silent failure, and the README's own download commands were once broken in a way
nobody could notice precisely because the result was a tidy skip rather than an
error. The shapes are now vendored under `third_party/`, so the check runs on a
clean checkout, offline, on every push.

Vendoring somebody else's document is a licensing act as much as a technical
one, so the tests here guard both halves:

- **The bytes.** `third_party/PROVENANCE.json` records a SHA-256 per file, and
  a mismatch means either that somebody edited a third-party document or that a
  line-ending conversion rewrote it. The second is not hypothetical: all four
  files are published with CRLF endings while `.gitattributes` sets `eol=lf` for
  everything else in the repository.
- **The credit.** Both works are CC BY 4.0, which permits redistribution only
  with attribution. A file added under `third_party/` and not credited in
  `NOTICE` is a licence breach, not a tidiness problem, so a test looks.

None of this needs `pyshacl`, so these run even where the conformance check
itself cannot.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "third_party"
PROVENANCE = VENDOR / "PROVENANCE.json"
NOTICE = ROOT / "NOTICE"

EXPECTED_LICENCE = "CC-BY-4.0"


def _declared() -> list[dict[str, object]]:
    """Return every file PROVENANCE.json declares, flattened across works."""
    payload = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    return [entry for work in payload["works"] for entry in work["files"]]


def _works() -> list[dict[str, object]]:
    return list(json.loads(PROVENANCE.read_text(encoding="utf-8"))["works"])


def _vendored_files() -> list[Path]:
    return sorted(p for p in VENDOR.rglob("*") if p.is_file() and p.name != "PROVENANCE.json")


# --------------------------------------------------------------------------
# The bytes
# --------------------------------------------------------------------------


def test_the_shapes_are_in_the_repository_and_not_downloaded_on_demand() -> None:
    """The whole point: a clean checkout can check conformance.

    Asserted on the directory rather than on the test that uses it, so the
    failure names the thing that is missing instead of appearing as a skip
    somewhere else.
    """
    assert PROVENANCE.is_file(), "third_party/PROVENANCE.json is missing"
    assert _vendored_files(), "no shape files are vendored"


@pytest.mark.parametrize("entry", _declared(), ids=lambda e: str(e["path"]))
def test_a_declared_file_is_present_and_byte_for_byte_what_was_recorded(
    entry: dict[str, object],
) -> None:
    """A digest mismatch means somebody changed somebody else's document.

    Which is the thing `NOTICE` promises did not happen. The likeliest cause is
    not an edit but a newline conversion, so the message says so: these files
    are published with CRLF endings and the repository converts everything else
    to LF.
    """
    path = VENDOR / str(entry["path"])
    assert path.is_file(), f"{entry['path']} is declared and absent"

    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == entry["sha256"], (
        f"{entry['path']} is not the file that was vendored. Either it was "
        "edited, or its line endings were converted -- check that "
        "`third_party/** -text` is still in .gitattributes."
    )
    assert len(raw) == entry["bytes"]


def test_every_vendored_file_is_declared() -> None:
    """A file nobody recorded is a file nobody can re-check or re-fetch.

    The digest test above iterates the declarations, so on its own it would pass
    happily over a fifth file that was never written down.
    """
    declared = {str(entry["path"]) for entry in _declared()}
    present = {str(p.relative_to(VENDOR)).replace("\\", "/") for p in _vendored_files()}

    assert present == declared


def test_gitattributes_keeps_the_vendored_bytes_verbatim() -> None:
    """The rule that makes `NOTICE`'s "no changes were made" survive a refresh.

    The digest test above catches a conversion after it has happened, and
    reports a hash that means nothing on its own. This asserts the rule that
    prevents it, so the failure names the cause.

    **It guards nothing today, and that is worth saying rather than dressing
    up.** All four files are published with LF endings, so the repository's
    `eol=lf` would be a no-op on them; `-text` matters only if a future refresh
    brings CRLF, which normalisation would rewrite while the file still parsed.
    An earlier version of this test asserted the opposite — that the files were
    CRLF — on a measurement taken with an empty grep pattern, which matches
    every line in any file. The rule is right; the reason first given for it was
    not.
    """
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")

    assert "third_party/** -text" in attributes, (
        "`third_party/** -text` left .gitattributes, so a refresh that brought "
        "CRLF from upstream would be normalised on the way in and NOTICE's "
        "statement that nothing was modified would stop being true"
    )


def test_every_declaration_names_where_it_came_from() -> None:
    """A URL nobody can fetch is how the README's own download block broke once."""
    for entry in _declared():
        url = str(entry["url"])
        assert url.startswith("https://")
        assert str(entry["upstream_path"]).split("/")[-1] in url.replace("%2F", "/")


# --------------------------------------------------------------------------
# The credit
# --------------------------------------------------------------------------


def test_every_vendored_file_is_credited_in_the_notice() -> None:
    """CC BY 4.0 permits redistribution only with attribution.

    So a vendored file that `NOTICE` does not name is a licence breach rather
    than an omission, and it is exactly the thing somebody adds in a hurry.
    """
    notice = NOTICE.read_text(encoding="utf-8")
    missing = [
        f"third_party/{entry['path']}"
        for entry in _declared()
        if f"third_party/{entry['path']}" not in notice
    ]

    assert not missing, "vendored but not credited in NOTICE: " + ", ".join(missing)


def test_the_notice_identifies_the_licence_and_states_that_nothing_changed() -> None:
    """The other three things CC BY 4.0 asks a redistributor to provide.

    The creator, the licence, and an indication of whether changes were made.
    The creators are checked per work below; the licence and the no-changes
    statement are here.
    """
    notice = NOTICE.read_text(encoding="utf-8")

    assert "creativecommons.org/licenses/by/4.0" in notice
    assert "NO CHANGES WERE MADE" in notice
    for work in _works():
        assert work["licence"] == EXPECTED_LICENCE
        # The work's name and its repository URL, which are tokens, rather than
        # the composed `attribution` sentence, which is prose and wraps. An
        # earlier version asserted the sentence and failed on a line break --
        # asserting on the picture of the text rather than on the thing, which
        # this project's conventions already forbid.
        assert str(work["name"]) in notice
        assert str(work["repository"]) in notice


def test_the_notice_names_this_project_and_not_a_previous_one() -> None:
    """It carried the old name for the whole life of the repository.

    `NOTICE` said `polybids` in three places, one of them a command that does
    not exist, from the initial commit until this test was written. Nothing read
    it, so nothing noticed the rename. Checked against the distribution name
    `pyproject.toml` declares, so a future rename fails here rather than ageing
    quietly in a file only a lawyer opens.
    """
    name = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["name"]
    notice = NOTICE.read_text(encoding="utf-8")

    assert notice.startswith(f"{name}\n")
    assert f"`{name} generate`" in notice


# --------------------------------------------------------------------------
# The remaining skip
# --------------------------------------------------------------------------


def test_pyshacl_is_declared_so_the_conformance_check_cannot_skip_by_accident() -> None:
    """The one skip left, and it is now unreachable by any change to this project.

    `tests/test_shacl_conformance.py` still calls `importorskip`, because
    `pyshacl` is honestly an optional dev dependency and somebody may install
    without the extra. What must not happen is for it to disappear from the
    extra and take the conformance check with it, silently. CI installs
    `--extra dev`, so with this declared the check always runs there.
    """
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dev = pyproject["project"]["optional-dependencies"]["dev"]

    assert any(requirement.startswith("pyshacl") for requirement in dev), (
        "pyshacl left the dev extra, so the HealthDCAT-AP conformance check "
        "would skip everywhere, including CI"
    )
