"""A build publishes exactly what it produced, or it changes nothing.

The audit of 2026-11-13 withdrew one imaging study from a corpus, rebuilt into
the same directory, and got ``Validation: conforms — 0 error(s), 0 warning(s)``
with a zero exit code while the withdrawn study was still in the dataset,
digested into the new manifest and certified ``INTACT`` by ``commissura
verify``. A data holder acting on a patient's objection had not acted on it.

These tests are that scenario and its neighbours. The withdrawal cases are the
contract; the refusal cases are what stops the fix from becoming a way to lose
somebody's files.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from commissura import layout
from commissura.build.publish import (
    MARKER_NAME,
    OUTGOING_PREFIX,
    WORKING_PREFIX,
    PublicationError,
    Staged,
    abandon,
    begin,
    looks_like_our_dataset,
    publish,
)
from commissura.cli import app

runner = CliRunner()

KEY_HEX = bytes(range(32)).hex()


def _key(tmp_path: Path) -> Path:
    path = tmp_path / "test.key"
    path.write_text(KEY_HEX, encoding="utf-8")
    return path


def _corpus(tmp_path: Path, *, subjects: int = 4, seed: int = 11) -> Path:
    root = tmp_path / "raw"
    result = runner.invoke(
        app,
        [
            "generate",
            "--subjects",
            str(subjects),
            "--seed",
            str(seed),
            "--defect-rate",
            "0",
            "--out",
            str(root),
        ],
    )
    assert result.exit_code == 0, result.output
    return root


def _build(tmp_path: Path, corpus: Path, out: Path) -> object:
    return runner.invoke(
        app,
        [
            "build",
            str(corpus),
            "--out",
            str(out),
            "--key-file",
            str(_key(tmp_path)),
            "--hdab",
            "Agenzia Sintetica",
            "--publisher",
            "IRCCS SINTETICO MAREBIANCO",
            "--contact-point",
            "dati@irccs-sintetico.invalid",
            "--access-url",
            "https://portale-sintetico.invalid/permessi",
        ],
    )


def _build_argv(tmp_path: Path, corpus: Path, out: Path) -> list[str]:
    """Return the argument list for a minimal build, for tests that drive failures."""
    return [
        "build",
        str(corpus),
        "--out",
        str(out),
        "--key-file",
        str(_key(tmp_path)),
        "--hdab",
        "H",
        "--publisher",
        "P",
    ]


def _tree(root: Path) -> dict[str, str]:
    """Return every file under ``root`` by relative path, with its contents."""
    return {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# --------------------------------------------------------------------------
# Withdrawal: the audit scenario
# --------------------------------------------------------------------------


def test_a_withdrawn_imaging_study_does_not_survive_a_rebuild(tmp_path: Path) -> None:
    """The audit's finding 3, in the form that reported success.

    One study removed from the corpus, rebuilt into the same directory. Before
    this change the build said ``conforms``, exited 0, and the withdrawn
    study's pseudonymised metadata was still in ``derivatives/``.
    """
    corpus = _corpus(tmp_path)
    out = tmp_path / "dataset"
    assert _build(tmp_path, corpus, out).exit_code == 0  # type: ignore[attr-defined]
    before = sorted((out / "derivatives").rglob("*.json"))
    assert len(before) >= 2, "this corpus should produce imaging metadata to withdraw"

    withdrawn = sorted(corpus.glob("imaging/*.json"))[0]
    withdrawn.unlink()
    result = _build(tmp_path, corpus, out)

    assert result.exit_code == 0, result.output  # type: ignore[attr-defined]
    after = sorted((out / "derivatives").rglob("*.json"))
    assert len(after) == len(before) - 1


def test_a_rebuild_matches_a_clean_build_of_the_same_corpus(tmp_path: Path) -> None:
    """The contract, stated as an equality.

    A successful build publishes exactly what the current corpus produced, so a
    rebuild over a previous dataset and a first build into an empty directory
    are the same dataset. Only the manifest differs, and only in the fields that
    legitimately do.
    """
    corpus = _corpus(tmp_path)
    # Same leaf name in different parents. ``dct:identifier`` is
    # ``urn:commissura:<directory name>``, so a build into ``a`` and one into
    # ``b`` legitimately differ in exactly one file -- the trap recorded in the
    # decision log of 2026-11-13, which this test would otherwise walk into.
    (tmp_path / "one").mkdir()
    (tmp_path / "two").mkdir()
    rebuilt, fresh = tmp_path / "one" / "dataset", tmp_path / "two" / "dataset"
    assert _build(tmp_path, corpus, rebuilt).exit_code == 0  # type: ignore[attr-defined]
    sorted(corpus.glob("imaging/*.json"))[0].unlink()
    sorted(corpus.glob("reports/*.txt"))[0].unlink()

    assert _build(tmp_path, corpus, rebuilt).exit_code == 0  # type: ignore[attr-defined]
    assert _build(tmp_path, corpus, fresh).exit_code == 0  # type: ignore[attr-defined]

    manifest = f"{layout.DEIDENT_DIR}/{layout.MANIFEST_JSON}"
    rebuilt_tree, fresh_tree = _tree(rebuilt), _tree(fresh)
    assert sorted(rebuilt_tree) == sorted(fresh_tree)
    for name in rebuilt_tree:
        if name == manifest:
            # `generated_at` is a timestamp and the digest list covers the rest.
            continue
        assert rebuilt_tree[name] == fresh_tree[name], name
    assert (
        json.loads(rebuilt_tree[manifest])["integrity"]["files"]
        == (json.loads(fresh_tree[manifest])["integrity"]["files"])
    )


def test_a_withdrawn_participant_leaves_no_directory_behind(tmp_path: Path) -> None:
    """A whole person removed, not just one of their records.

    The validator caught this case before, through PT006, because the subject
    directory was no longer in ``participants.tsv``. Catching it is not the same
    as not producing it: the dataset still held that person's records, and the
    manifest still authenticated them.
    """
    corpus = _corpus(tmp_path)
    out = tmp_path / "dataset"
    assert _build(tmp_path, corpus, out).exit_code == 0  # type: ignore[attr-defined]
    before = {p.name for p in out.glob("sub-*")}

    victim = sorted(corpus.glob("lab/*.hl7"))[0].name.split("_")[0]
    for path in list(corpus.rglob(f"{victim}_*")):
        path.unlink()
    result = _build(tmp_path, corpus, out)

    assert result.exit_code == 0, result.output  # type: ignore[attr-defined]
    after = {p.name for p in out.glob("sub-*")}
    assert len(after) == len(before) - 1
    assert after < before


def test_the_manifest_does_not_reference_a_withdrawn_record(tmp_path: Path) -> None:
    """The integrity list is the dataset's inventory, so it must shrink too."""
    corpus = _corpus(tmp_path)
    out = tmp_path / "dataset"
    assert _build(tmp_path, corpus, out).exit_code == 0  # type: ignore[attr-defined]
    recorded = json.loads(
        (out / layout.DEIDENT_DIR / layout.MANIFEST_JSON).read_text(encoding="utf-8")
    )["integrity"]["files"]
    derivatives = [name for name in recorded if name.startswith("derivatives/")]
    assert derivatives

    sorted(corpus.glob("imaging/*.json"))[0].unlink()
    assert _build(tmp_path, corpus, out).exit_code == 0  # type: ignore[attr-defined]

    after = json.loads(
        (out / layout.DEIDENT_DIR / layout.MANIFEST_JSON).read_text(encoding="utf-8")
    )["integrity"]["files"]
    assert len([n for n in after if n.startswith("derivatives/")]) == len(derivatives) - 1
    assert set(after) < set(recorded) or sorted(after) != sorted(recorded)


def test_verifying_an_old_manifest_proves_nothing_about_a_withdrawal(tmp_path: Path) -> None:
    """Integrity, authenticity, completeness and correctness are four claims.

    This is the one that was conflated. An authentic manifest says the files
    match the digests it records — it says nothing about whether the dataset
    contains a record that should have been withdrawn, because the manifest was
    written when it was still supposed to be there. The test keeps the old
    dataset and its old manifest, verifies it, and shows that verification is
    perfectly happy with a dataset holding a withdrawn record.
    """
    corpus = _corpus(tmp_path)
    out = tmp_path / "dataset"
    assert _build(tmp_path, corpus, out).exit_code == 0  # type: ignore[attr-defined]

    # The holder withdraws a record from the corpus and does not rebuild.
    sorted(corpus.glob("imaging/*.json"))[0].unlink()

    verified = runner.invoke(app, ["verify", str(out), "--key-file", str(_key(tmp_path))])

    assert verified.exit_code == 0
    assert "INTACT" in verified.output
    # And that is correct: the bytes have not changed. The dataset is still
    # wrong, and no amount of verifying it will say so.
    assert "does not prove" in verified.output or "completeness" in verified.output


# --------------------------------------------------------------------------
# Refusing, and never destroying
# --------------------------------------------------------------------------


def test_a_destination_that_is_not_our_output_is_refused(tmp_path: Path) -> None:
    """The guard between a mistyped --out and somebody's files."""
    destination = tmp_path / "documents"
    destination.mkdir()
    (destination / "thesis.tex").write_text("years of work", encoding="utf-8")

    with pytest.raises(PublicationError, match="does not look like a commissura dataset"):
        begin(destination)

    assert (destination / "thesis.tex").read_text(encoding="utf-8") == "years of work"


def test_there_is_no_flag_that_overrides_the_refusal() -> None:
    """Deliberately no --force: the flag would exist to defeat this check.

    Asserted on the declared interface rather than on help text, per the
    convention adopted after the rendered-output incident of 2026-11-12.
    """
    from typer.main import get_command

    build = get_command(app).commands["build"]  # type: ignore[attr-defined]
    names = {name for param in build.params for name in param.opts}

    assert "--force" not in names
    assert "-f" not in names


def test_an_empty_destination_is_accepted(tmp_path: Path) -> None:
    """Nothing to protect, so nothing to refuse."""
    destination = tmp_path / "empty"
    destination.mkdir()

    staged = begin(destination)

    assert staged.destination == destination.resolve()
    assert staged.root.is_dir()
    assert WORKING_PREFIX in staged.holding.name


def test_a_missing_destination_is_accepted(tmp_path: Path) -> None:
    staged = begin(tmp_path / "not-there-yet")

    assert staged.root.is_dir()
    assert not staged.destination.exists()


def test_a_destination_that_is_a_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "dataset"
    path.write_text("a file, not a directory", encoding="utf-8")

    with pytest.raises(PublicationError, match="not a directory"):
        begin(path)


def test_our_own_dataset_is_recognised_by_its_manifest(tmp_path: Path) -> None:
    """Narrow on purpose: the question is "did we write this", not "is this datasetish"."""
    root = tmp_path / "d"
    (root / layout.DEIDENT_DIR).mkdir(parents=True)
    assert not looks_like_our_dataset(root)

    (root / layout.DEIDENT_DIR / layout.MANIFEST_JSON).write_text("{}", encoding="utf-8")
    assert looks_like_our_dataset(root)


def test_a_dataset_from_before_the_manifest_existed_is_still_recognised(
    tmp_path: Path,
) -> None:
    root = tmp_path / "d"
    root.mkdir()
    (root / layout.DATASET_DESCRIPTION).write_text("{}", encoding="utf-8")

    assert looks_like_our_dataset(root)


# --------------------------------------------------------------------------
# Publishing and abandoning
# --------------------------------------------------------------------------


def test_publishing_replaces_the_destination_wholesale(tmp_path: Path) -> None:
    """Not a merge. The stale file is the whole reason this module exists."""
    destination = tmp_path / "dataset"
    (destination / layout.DEIDENT_DIR).mkdir(parents=True)
    (destination / layout.DEIDENT_DIR / layout.MANIFEST_JSON).write_text("{}", encoding="utf-8")
    (destination / "stale.txt").write_text("from a previous build", encoding="utf-8")

    staged = begin(destination)
    (staged.root / "fresh.txt").write_text("from this build", encoding="utf-8")
    published = publish(staged)

    assert published == destination.resolve()
    assert sorted(p.name for p in published.iterdir()) == ["fresh.txt"]
    assert not staged.root.exists()


def test_publishing_leaves_no_working_directories_behind(tmp_path: Path) -> None:
    """A staging or previous directory left in place would be published next time."""
    destination = tmp_path / "dataset"
    staged = begin(destination)
    (staged.root / "x.txt").write_text("x", encoding="utf-8")
    publish(staged)

    siblings = [p.name for p in tmp_path.iterdir()]

    assert not [n for n in siblings if WORKING_PREFIX in n or OUTGOING_PREFIX in n]


def test_abandoning_a_build_leaves_the_destination_exactly_as_it_was(
    tmp_path: Path,
) -> None:
    """The other half of the contract: a failed build changes nothing."""
    destination = tmp_path / "dataset"
    (destination / layout.DEIDENT_DIR).mkdir(parents=True)
    (destination / layout.DEIDENT_DIR / layout.MANIFEST_JSON).write_text("{}", encoding="utf-8")
    (destination / "previous.txt").write_text("still here", encoding="utf-8")
    before = _tree(destination)

    staged = begin(destination)
    (staged.root / "half-written.txt").write_text("incomplete", encoding="utf-8")
    abandon(staged)

    assert _tree(destination) == before
    assert not staged.root.exists()


def test_an_interrupted_build_publishes_nothing(tmp_path: Path) -> None:
    """A crash partway through must not leave a mixture at the destination.

    Driven through the command line, because the ordering that makes this true
    lives there: everything is written into the staging tree and the destination
    is not touched until the build has finished.
    """
    corpus = _corpus(tmp_path)
    out = tmp_path / "dataset"
    assert _build(tmp_path, corpus, out).exit_code == 0  # type: ignore[attr-defined]
    before = _tree(out)

    # A report path inside the dataset is refused *after* the build has run and
    # before anything is published, which is the window this test is about.
    result = runner.invoke(
        app,
        [
            "build",
            str(corpus),
            "--out",
            str(out),
            "--key-file",
            str(_key(tmp_path)),
            "--hdab",
            "H",
            "--publisher",
            "P",
            "--report",
            str(out / "review.html"),
        ],
    )

    assert result.exit_code == 1
    assert _tree(out) == before
    assert not [p for p in tmp_path.iterdir() if WORKING_PREFIX in p.name]


def test_a_failed_publication_puts_the_previous_dataset_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The window the module docstring describes, and what it recovers to.

    Publication is two renames and the destination does not exist between them.
    If the second fails, leaving it that way would turn a failed rebuild into a
    lost dataset — so the previous one goes back. Driven by making the second
    rename fail, because this is the path that runs least and matters most.
    """
    destination = tmp_path / "dataset"
    (destination / layout.DEIDENT_DIR).mkdir(parents=True)
    (destination / layout.DEIDENT_DIR / layout.MANIFEST_JSON).write_text("{}", encoding="utf-8")
    (destination / "precious.txt").write_text("the only copy", encoding="utf-8")

    staged = begin(destination)
    (staged.root / "new.txt").write_text("the new build", encoding="utf-8")

    real_replace = Path.replace
    calls: list[Path] = []

    def failing(self: Path, target: object) -> Path:
        calls.append(self)
        if self == staged.root:
            raise OSError("the filesystem said no")
        return real_replace(self, target)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "replace", failing)

    with pytest.raises(PublicationError, match="could not publish"):
        publish(staged)

    monkeypatch.undo()
    assert (destination / "precious.txt").read_text(encoding="utf-8") == "the only copy"
    assert not [p for p in tmp_path.iterdir() if OUTGOING_PREFIX in p.name]


def test_a_failed_publication_says_where_the_finished_build_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """By then the staged tree may be the only copy of an expensive build."""
    staged = begin(tmp_path / "dataset")
    (staged.root / "x.txt").write_text("x", encoding="utf-8")

    def failing(self: Path, target: object) -> Path:
        raise OSError("nope")

    monkeypatch.setattr(Path, "replace", failing)

    with pytest.raises(PublicationError, match=r"complete at .*commissura-staging"):
        publish(staged)


def test_a_build_that_raises_partway_through_abandons_its_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash inside the pipeline must leave neither a staging tree nor a dataset."""
    corpus = _corpus(tmp_path, subjects=2)
    import commissura.cli as cli_module

    def exploding(*args: object, **kwargs: object) -> None:
        raise RuntimeError("the disk filled up")

    monkeypatch.setattr(cli_module, "write_risk_report", exploding)

    result = runner.invoke(app, _build_argv(tmp_path, corpus, tmp_path / "dataset"))

    assert result.exit_code != 0
    assert not (tmp_path / "dataset").exists()
    assert not [p for p in tmp_path.iterdir() if WORKING_PREFIX in p.name]


def test_a_publication_failure_at_the_command_line_exits_non_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """And says why, rather than reporting a build that did not land."""
    corpus = _corpus(tmp_path, subjects=2)
    import commissura.cli as cli_module

    def refusing(staged: object) -> Path:
        raise PublicationError("the destination is on a read-only share")

    monkeypatch.setattr(cli_module, "publish", refusing)

    result = runner.invoke(app, _build_argv(tmp_path, corpus, tmp_path / "dataset"))

    assert result.exit_code == 1
    assert "read-only share" in (result.stderr or result.output)


# --------------------------------------------------------------------------
# Ownership is a marker, not a name
# --------------------------------------------------------------------------


def test_the_old_predictable_staging_path_is_never_touched(tmp_path: Path) -> None:
    """The defect this redesign removes, pinned as a regression.

    The first version named its working directory
    ``<destination>.commissura-staging-<pid>`` and removed whatever sat there
    with :func:`shutil.rmtree`. Process ids are small and reused, so an
    unrelated directory could occupy that path — and the removal established
    ownership from the name alone, which is not evidence of anything. Working
    directories are created with :func:`tempfile.mkdtemp` now, so the branch
    does not exist to be guarded.
    """
    destination = tmp_path / "dataset"
    squatter = tmp_path / f"dataset.commissura-staging-{os.getpid()}"
    squatter.mkdir()
    (squatter / "somebody-elses-work.txt").write_text("precious", encoding="utf-8")

    staged = begin(destination)
    (staged.root / "x.txt").write_text("x", encoding="utf-8")
    publish(staged)

    assert (squatter / "somebody-elses-work.txt").read_text(encoding="utf-8") == "precious"


def test_a_working_directory_with_no_marker_is_refused(tmp_path: Path) -> None:
    """Every removal in this module proves ownership first."""
    staged = begin(tmp_path / "dataset")
    (staged.holding / MARKER_NAME).unlink()

    with pytest.raises(PublicationError, match="no readable"):
        publish(staged)

    assert staged.root.is_dir(), "a refusal must change nothing"


def test_a_marker_naming_another_destination_is_refused(tmp_path: Path) -> None:
    """A working directory for one dataset must not be used for another."""
    staged = begin(tmp_path / "dataset")
    (staged.holding / MARKER_NAME).write_text(
        json.dumps({"destination": str(tmp_path / "elsewhere")}), encoding="utf-8"
    )

    with pytest.raises(PublicationError, match="does not name"):
        publish(staged)


def test_a_marker_that_is_not_json_is_refused(tmp_path: Path) -> None:
    """A corrupt marker is not a licence to delete a directory."""
    staged = begin(tmp_path / "dataset")
    (staged.holding / MARKER_NAME).write_text("not json at all", encoding="utf-8")

    with pytest.raises(PublicationError, match="no readable"):
        publish(staged)


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs elevation on Windows")
def test_a_working_directory_that_is_a_symlink_is_refused(tmp_path: Path) -> None:
    """A marker read through a link says nothing about what removal would reach."""
    destination = (tmp_path / "dataset").resolve()
    real = tmp_path / "real"
    real.mkdir()
    (real / MARKER_NAME).write_text(json.dumps({"destination": str(destination)}), encoding="utf-8")
    (real / "payload").mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)

    staged = Staged(root=link / "payload", holding=link, destination=destination)

    with pytest.raises(PublicationError, match="symbolic link"):
        publish(staged)

    assert (real / MARKER_NAME).is_file(), "the real directory must be untouched"


def test_the_marker_never_reaches_the_published_dataset(tmp_path: Path) -> None:
    """Which is why the dataset is built in a subdirectory of the working one.

    Putting the marker inside the tree being published and deleting it just
    before the rename would also work, and would be one more thing to get wrong.
    """
    staged = begin(tmp_path / "dataset")
    (staged.root / "x.txt").write_text("x", encoding="utf-8")

    published = publish(staged)

    assert sorted(p.name for p in published.rglob("*")) == ["x.txt"]
    assert not list(published.rglob(MARKER_NAME))


def test_a_working_directory_cannot_collide_with_another(tmp_path: Path) -> None:
    """``mkdtemp`` is atomic and random, so two builds never share one."""
    destination = tmp_path / "dataset"

    first, second = begin(destination), begin(destination)

    assert first.holding != second.holding
    assert first.root.is_dir()
    assert second.root.is_dir()


# --------------------------------------------------------------------------
# Two builds at once
# --------------------------------------------------------------------------


def test_two_concurrent_builds_leave_one_complete_dataset(tmp_path: Path) -> None:
    """Which one wins is undefined; a mixture of the two is impossible.

    Each rename is atomic and each build has its own working directory, so the
    destination always holds one complete dataset. Serialising them would need
    a lock, and the expected load is one person running a command-line tool.
    """
    destination = tmp_path / "dataset"
    first, second = begin(destination), begin(destination)
    (first.root / "from-first.txt").write_text("1", encoding="utf-8")
    (second.root / "from-second.txt").write_text("2", encoding="utf-8")

    publish(first)
    publish(second)

    names = sorted(p.name for p in destination.iterdir())
    assert names in (["from-first.txt"], ["from-second.txt"])
    assert not [p for p in tmp_path.iterdir() if WORKING_PREFIX in p.name]
    assert not [p for p in tmp_path.iterdir() if OUTGOING_PREFIX in p.name]


def test_a_destination_published_by_another_build_first_is_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The loser of the race finds the destination gone between check and rename.

    Nothing is lost — the destination holds a complete dataset either way — and
    this build still has its own to put there. Handled as an ordinary
    publication rather than raised as a traceback.
    """
    destination = tmp_path / "dataset"
    (destination / layout.DEIDENT_DIR).mkdir(parents=True)
    (destination / layout.DEIDENT_DIR / layout.MANIFEST_JSON).write_text("{}", encoding="utf-8")
    staged = begin(destination)
    (staged.root / "mine.txt").write_text("mine", encoding="utf-8")

    real_replace = Path.replace
    raced = {"done": False}

    def racing(self: Path, target: object) -> Path:
        if self == destination.resolve() and not raced["done"]:
            raced["done"] = True
            shutil.rmtree(destination)
            raise FileNotFoundError(destination)
        return real_replace(self, target)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "replace", racing)
    published = publish(staged)
    monkeypatch.undo()

    assert sorted(p.name for p in published.iterdir()) == ["mine.txt"]
    assert not [p for p in tmp_path.iterdir() if OUTGOING_PREFIX in p.name]


# --------------------------------------------------------------------------
# Failing, and recovering
# --------------------------------------------------------------------------


def test_a_failure_moving_the_old_dataset_aside_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first of the two renames, which the earlier tests did not reach."""
    destination = tmp_path / "dataset"
    (destination / layout.DEIDENT_DIR).mkdir(parents=True)
    (destination / layout.DEIDENT_DIR / layout.MANIFEST_JSON).write_text("{}", encoding="utf-8")
    (destination / "previous.txt").write_text("still here", encoding="utf-8")
    staged = begin(destination)
    (staged.root / "new.txt").write_text("new", encoding="utf-8")

    def refusing(self: Path, target: object) -> Path:
        raise PermissionError("the share is read-only")

    monkeypatch.setattr(Path, "replace", refusing)

    with pytest.raises(PublicationError, match="aside"):
        publish(staged)

    monkeypatch.undo()
    assert (destination / "previous.txt").read_text(encoding="utf-8") == "still here"
    assert not [p for p in tmp_path.iterdir() if OUTGOING_PREFIX in p.name]


def test_an_interruption_before_the_rename_leaves_the_destination_alone(
    tmp_path: Path,
) -> None:
    """Killed mid-build: the previous dataset is still where it was."""
    destination = tmp_path / "dataset"
    (destination / layout.DEIDENT_DIR).mkdir(parents=True)
    (destination / layout.DEIDENT_DIR / layout.MANIFEST_JSON).write_text("{}", encoding="utf-8")
    before = _tree(destination)

    staged = begin(destination)
    (staged.root / "half.txt").write_text("incomplete", encoding="utf-8")
    # The process dies here: nothing calls publish or abandon.

    assert _tree(destination) == before
    assert staged.holding.is_dir()


def test_an_interruption_after_the_rename_leaves_a_recoverable_previous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The window the module documents, and what it leaves behind.

    Between the two renames the destination does not exist. A process killed
    there leaves the previous dataset in a working directory whose marker names
    where it came from, which is what makes it recoverable by hand rather than
    merely still present somewhere.
    """
    destination = tmp_path / "dataset"
    (destination / layout.DEIDENT_DIR).mkdir(parents=True)
    (destination / layout.DEIDENT_DIR / layout.MANIFEST_JSON).write_text("{}", encoding="utf-8")
    (destination / "precious.txt").write_text("the only copy", encoding="utf-8")
    staged = begin(destination)
    (staged.root / "new.txt").write_text("new", encoding="utf-8")

    real_replace = Path.replace

    def dying(self: Path, target: object) -> Path:
        if self == staged.root:
            raise KeyboardInterrupt
        return real_replace(self, target)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "replace", dying)
    with pytest.raises(KeyboardInterrupt):
        publish(staged)
    monkeypatch.undo()

    assert not destination.exists(), "this is the documented window"
    outgoing = [p for p in tmp_path.iterdir() if OUTGOING_PREFIX in p.name]
    assert len(outgoing) == 1
    recorded = json.loads((outgoing[0] / MARKER_NAME).read_text(encoding="utf-8"))
    assert recorded["destination"] == str(destination.resolve())
    assert (outgoing[0] / "payload" / "precious.txt").read_text(encoding="utf-8") == (
        "the only copy"
    )


def test_abandon_never_raises_over_a_failed_build(tmp_path: Path) -> None:
    """It runs on the way out of a failure and must not replace it with its own.

    A working directory left behind is visible, named, and carries a marker
    saying what it was for.
    """
    staged = begin(tmp_path / "dataset")
    (staged.holding / MARKER_NAME).unlink()

    abandon(staged)

    assert staged.holding.is_dir(), "refused, and left alone"


def test_a_destination_whose_parent_cannot_be_written_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A clear message rather than an OSError from the middle of the build."""

    def refusing(*args: object, **kwargs: object) -> str:
        raise PermissionError("read-only filesystem")

    monkeypatch.setattr(tempfile, "mkdtemp", refusing)

    with pytest.raises(PublicationError, match="working directory"):
        begin(tmp_path / "dataset")
