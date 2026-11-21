"""What the published artefacts contain, asserted on the artefacts themselves.

The one hard constraint this project does not meet is *deployable by a
stranger*: the package is not on PyPI and the repository is private, so today
only the author can install it. Publishing is an irreversible public act and
therefore a decision rather than a step. **Everything up to that step is
checkable now, and until this file existed none of it had been checked.**

Two things made it worth doing rather than deferring with the decision.

**The licence obligation is live the moment anything is distributed.** Two CC BY
4.0 works are redistributed under ``third_party/`` — HealthDCAT-AP and DCAT-AP
3.0.0 — and that licence permits redistribution only with attribution. The
source distribution carries those files, so it must carry ``NOTICE`` with them.
A build configuration change that dropped ``license-files`` would be a licence
breach that nothing would report, in an archive uploaded once and then
immutable.

**And an archive is the one artefact this project cannot take back.** Every
other output is written to a disk somebody controls. A release is published to
an index that refuses deletion as a matter of policy, so "no internal paperwork
leaked into it" has to be true the first time. ``docs/`` and ``CLAUDE.md`` are
untracked today and the build backend honours that, which is why nothing has
leaked; a guard is what keeps that an invariant rather than a coincidence of
what happens to be gitignored this week.

**Built in process, not asserted from configuration.** ``hatchling`` is the
declared build backend, so naming it in the dev extra adds no third-party
dependency and takes under a second for both artefacts. Reading
``[tool.hatch.build.targets.wheel]`` and reasoning about what it implies would
be asserting on the instruction where the artefact is the thing that ships —
and this project's conventions already forbid the inverted form of that.

Every identifier mentioned here is synthetic.
"""

from __future__ import annotations

import json
import tarfile
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DISTRIBUTION = "commissura"

# Nothing from this list may appear in either artefact. Three different reasons,
# kept in one place because the question "could this ship?" is one question:
# internal working papers (the first three), anything that could hold a secret
# or patient data (the next three), and the caches that are merely noise.
FORBIDDEN_PATHS = (
    "docs/",
    "CLAUDE.md",
    "reference/",
    "raw/",
    "dataset/",
    "corpus/",
    ".venv/",
    "htmlcov/",
    "__pycache__/",
)

FORBIDDEN_SUFFIXES = (".key", ".pem")


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """Build a wheel and a source distribution, and return their paths.

    Built into a temporary directory rather than into ``dist/``, so running the
    suite never leaves an artefact behind that somebody could publish by
    accident.
    """
    hatchling_build = pytest.importorskip("hatchling.build", reason="hatchling is a dev extra")
    out = tmp_path_factory.mktemp("dist")

    import os

    previous = Path.cwd()
    os.chdir(ROOT)
    try:
        wheel = out / str(hatchling_build.build_wheel(str(out)))
        sdist = out / str(hatchling_build.build_sdist(str(out)))
    finally:
        os.chdir(previous)
    return wheel, sdist


@pytest.fixture(scope="module")
def wheel_names(built: tuple[Path, Path]) -> list[str]:
    with zipfile.ZipFile(built[0]) as archive:
        return sorted(archive.namelist())


@pytest.fixture(scope="module")
def sdist_names(built: tuple[Path, Path]) -> list[str]:
    """Paths inside the sdist, with its single top-level directory stripped."""
    with tarfile.open(built[1]) as archive:
        members = archive.getnames()
    roots = {name.split("/")[0] for name in members}
    assert len(roots) == 1, roots
    prefix = f"{roots.pop()}/"
    return sorted(name.removeprefix(prefix) for name in members if name != prefix.rstrip("/"))


def _vendored() -> Iterator[str]:
    payload = json.loads((ROOT / "third_party" / "PROVENANCE.json").read_text(encoding="utf-8"))
    for work in payload["works"]:
        for entry in work["files"]:
            yield f"third_party/{entry['path']}"


# --------------------------------------------------------------------------
# Nothing that must not ship
# --------------------------------------------------------------------------


@pytest.mark.parametrize("artefact", ["wheel", "sdist"])
def test_no_internal_paperwork_or_secret_is_packaged(
    artefact: str, wheel_names: list[str], sdist_names: list[str]
) -> None:
    """The guard that has to hold the first time, because a release is immutable.

    `docs/` and `CLAUDE.md` are untracked and the build backend honours the
    ignore file, so they are absent by consequence rather than by decision.
    This makes it a decision. `*.key` is in the list for the same reason
    `.gitignore` excludes it: a key inside a published archive is a key in
    every download, permanently.
    """
    names = wheel_names if artefact == "wheel" else sdist_names

    offending = [
        name
        for name in names
        if any(part in name for part in FORBIDDEN_PATHS) or name.endswith(FORBIDDEN_SUFFIXES)
    ]

    assert not offending, f"{artefact} would publish: {offending}"


def test_the_wheel_carries_no_tests_and_no_vendored_shapes(wheel_names: list[str]) -> None:
    """An installable wheel is the package and nothing else.

    The vendored shapes are read only by the conformance test, which does not
    ship, and `pyshacl` is deliberately a dev extra so that `pip install
    commissura` stays light. Shipping 80 KB of somebody else's Turtle to every
    installation would also put the CC BY material where `NOTICE` says it is
    not.
    """
    assert not [name for name in wheel_names if name.startswith("tests/")]
    assert not [name for name in wheel_names if "third_party" in name]


# --------------------------------------------------------------------------
# Everything that must
# --------------------------------------------------------------------------


def test_the_wheel_is_the_package_and_declares_its_types(wheel_names: list[str]) -> None:
    """`Typing :: Typed` is claimed in the classifiers, so the marker has to be there.

    Without `py.typed` a downstream type checker ignores every annotation in
    this package, and the classifier would be advertising something no tool
    could use.
    """
    assert f"{DISTRIBUTION}/__init__.py" in wheel_names
    assert f"{DISTRIBUTION}/py.typed" in wheel_names
    assert f"{DISTRIBUTION}/cli.py" in wheel_names


def test_the_console_script_points_at_the_application(built: tuple[Path, Path]) -> None:
    """Which is the difference between an installed library and an installed tool."""
    with zipfile.ZipFile(built[0]) as archive:
        entry = next(n for n in archive.namelist() if n.endswith("entry_points.txt"))
        text = archive.read(entry).decode("utf-8")

    assert "[console_scripts]" in text
    assert f"{DISTRIBUTION} = {DISTRIBUTION}.cli:app" in text


@pytest.mark.parametrize("artefact", ["wheel", "sdist"])
def test_both_artefacts_carry_the_licence_and_the_notice(
    artefact: str, wheel_names: list[str], sdist_names: list[str]
) -> None:
    """Apache-2.0 section 4(d) requires the notice to travel with the work.

    And CC BY 4.0 requires attribution to travel with the material it credits,
    which is why this matters more for the sdist: that archive carries the
    vendored shapes, so losing the notice would turn a compliant redistribution
    into a breach, silently.

    **What the declaration is actually worth, measured rather than assumed.**
    Deleting `license-files` from `pyproject.toml` changes nothing: hatchling
    falls back to a default glob that already matches `LICENSE*` and `NOTICE*`,
    and the artefact still carries both. So that line documents intent and does
    not cause the inclusion — a sabotage that removed it was no defect and this
    test rightly passed. **Narrowing it is the reachable mistake**:
    `license-files = ["LICENSE"]` silently drops the notice, and that is what
    this catches.
    """
    if artefact == "wheel":
        assert any(name.endswith(".dist-info/licenses/LICENSE") for name in wheel_names)
        assert any(name.endswith(".dist-info/licenses/NOTICE") for name in wheel_names)
    else:
        assert "LICENSE" in sdist_names
        assert "NOTICE" in sdist_names


def test_the_sdist_carries_every_vendored_file_it_credits(sdist_names: list[str]) -> None:
    """Read from the provenance, so a fifth vendored file cannot be left behind.

    The sdist is where the CC BY material is actually redistributed. A file
    credited in `NOTICE` and missing from the archive is the mirror image of the
    breach `tests/test_vendored_shapes.py` guards against, and neither direction
    is caught by the other.
    """
    declared = sorted(_vendored())
    assert declared

    missing = [name for name in declared if name not in sdist_names]
    assert not missing, f"credited in NOTICE and absent from the sdist: {missing}"


# --------------------------------------------------------------------------
# Nothing can publish by accident
# --------------------------------------------------------------------------

WORKFLOWS = ROOT / ".github" / "workflows"

AUTOMATIC_TRIGGERS = frozenset(
    {"push", "pull_request", "schedule", "release", "create", "repository_dispatch"}
)
"""Events nobody has to decide on, so a workflow carrying one can fire itself."""

PUBLISHING_ACTIONS = ("gh-action-pypi-publish", "twine upload")


def _workflow(path: Path) -> dict[object, object]:
    """Parse a workflow, working around YAML 1.1's view of the word ``on``.

    ``yaml.safe_load`` reads the bare key ``on`` as the boolean ``True``,
    because YAML 1.1 lists it among the ways to spell one. So the triggers
    arrive under ``True`` rather than under ``"on"``, and a test that looked
    only for the string would find nothing and conclude a workflow had no
    triggers at all — which is the shape that passes while checking nothing.
    """
    import yaml

    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _triggers(document: dict[object, object]) -> set[str]:
    section = document.get(True, document.get("on"))
    if isinstance(section, str):
        return {section}
    if isinstance(section, list):
        return {str(item) for item in section}
    if isinstance(section, dict):
        return {str(key) for key in section}
    return set()


def test_no_workflow_can_publish_without_somebody_starting_it() -> None:
    """The guard on the one act this project cannot take back.

    PyPI refuses to re-upload a filename it has already accepted and a yanked
    release stays downloadable by exact version, so a publication is permanent
    in a way nothing else here is. A workflow triggered by `push: tags:` turns
    `git push --tags` into a release, which is far more consequence than that
    command carries in anybody's head.

    Asserted on the parsed triggers rather than on the file's text: GitHub reads
    these as YAML, so `on: [workflow_dispatch, push]` is an automatic trigger
    however it is spelled, and a text search for `push:` would miss it.
    """
    publishing = [
        path
        for path in sorted(WORKFLOWS.glob("*.yml"))
        if any(marker in path.read_text(encoding="utf-8") for marker in PUBLISHING_ACTIONS)
    ]

    assert publishing, "no workflow publishes anything; delete this test or find out why"

    for path in publishing:
        triggers = _triggers(_workflow(path))
        assert triggers, f"{path.name} declares no trigger at all"
        assert not (triggers & AUTOMATIC_TRIGGERS), (
            f"{path.name} can publish to an index without anybody deciding to: "
            f"{sorted(triggers & AUTOMATIC_TRIGGERS)}"
        )


def test_the_publishing_workflow_asks_for_no_more_permission_than_it_needs() -> None:
    """Trusted publishing is why no API token is stored in this repository.

    `id-token: write` is what exchanges a short-lived OIDC identity for an
    upload token at the moment of upload, and it is the only permission any job
    here is granted. A workflow that instead carried a stored token would put a
    credential able to publish under this name into the repository's secrets,
    which is the same class of mistake as a key on a command line.
    """
    document = _workflow(WORKFLOWS / "publish.yml")
    jobs = document["jobs"]
    assert isinstance(jobs, dict)

    granted = {
        name: job.get("permissions", {})
        for name, job in jobs.items()
        if isinstance(job, dict) and job.get("permissions")
    }

    assert granted == {"publish": {"id-token": "write"}}, granted
    assert "secrets." not in (WORKFLOWS / "publish.yml").read_text(encoding="utf-8")


def test_the_sdist_can_run_its_own_test_suite(sdist_names: list[str]) -> None:
    """Which is what lets a distribution packager check the claims before shipping.

    An sdist with the tests and without the shapes would make the conformance
    check fail rather than skip — correct behaviour and a useless experience for
    somebody who only wanted to build a package. Both halves travel, so the
    headline claim is verifiable from the archive alone.
    """
    assert "tests/test_shacl_conformance.py" in sdist_names
    assert "tests/test_vendored_shapes.py" in sdist_names
    assert "third_party/PROVENANCE.json" in sdist_names
    assert "pyproject.toml" in sdist_names
    assert "uv.lock" in sdist_names
