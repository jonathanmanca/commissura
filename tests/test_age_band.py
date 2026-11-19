"""Generalising participant ages, and keeping the ceiling a separate thing.

`commissura risk` has always reported the honest number — twenty-five people
with exact ages cannot reach k=5 on age and sex — and has always said in its own
note that banding is the fix. It offered no way to apply one. The tool
diagnosed and could not treat, which is the same shape as the gap closed by
`--exclude-subjects`: `whois` derived the handle an objection points at and
`build` could not act on it.

TEHDAS2 D7.2 section 3.3.1 (p. 22) is the ask, dated 24 March 2026: age "should
only be used as an exact value when it is indispensable for the research
question and cannot be replaced by age categories". Section 3.1 (p. 18) is why
the manifest has to record the width: a holder should publish the default
minimisation rules that apply, and a dataset whose ages read ``40-44`` cannot
say on its own whether that is a five-year band or a decade starting on a
multiple of five.

**Two mechanisms, deliberately not one option.** Truncating above the age
ceiling is a de-identification invariant this tool applies to every dataset;
banding is a disclosure-control choice the holder makes per release. The
clamping test below is where they meet, and the manifest reports them under
separate keys so the first cannot read as optional.

**And one correction.** `build.writer._age_band` banded nothing — it returned
the exact age, truncated — and two entries in the manifest's per-field table
told an auditor the birth date was carried "as an age band". The misnomer had
escaped into the document written to be sent to an access body, where it
overstated a disclosure control that was not being applied.

Every identifier here is synthetic.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from commissura import layout
from commissura.build.manifest import write_manifest
from commissura.build.risk import assess, write_risk_report
from commissura.build.writer import BuildSpec, _participant_age, build_dataset
from commissura.cli import app
from commissura.deident.keys import SecretKey
from commissura.generate.cohort import CohortSpec
from commissura.generate.writer import write_corpus
from commissura.read.corpus import RawCorpus, read_corpus
from commissura.validate import validate_dataset

KEY = SecretKey(bytes(range(32)))
SPEC = BuildSpec(
    dataset_name="d",
    description="d",
    hdab="Agenzia Sintetica",
    publisher="IRCCS SINTETICO MAREBIANCO",
    contact_point="dati@irccs-sintetico.invalid",
    access_url="https://portale-sintetico.invalid/permessi",
)
WIDTH = 10

runner = CliRunner()


@pytest.fixture(scope="module")
def corpus_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The walkthrough's own cohort, which is where k=1 was first reported."""
    root = tmp_path_factory.mktemp("age-band") / "raw"
    write_corpus(CohortSpec(subjects=25, seed=42, defect_rate=0.2), root)
    return root


@pytest.fixture(scope="module")
def corpus(corpus_root: Path) -> RawCorpus:
    return read_corpus(corpus_root)


def _build(out: Path, corpus: RawCorpus, band: int | None) -> dict[str, object]:
    summary = build_dataset(corpus, KEY, SPEC, out, age_band=band)
    return write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=SPEC)


def _ages(root: Path) -> list[str]:
    rows = (root / layout.PARTICIPANTS_TSV).read_text(encoding="utf-8").splitlines()
    return [line.split("\t")[1] for line in rows[1:]]


# --------------------------------------------------------------------------
# The band
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("age", "width", "expected"),
    [
        (42, 5, "40-44"),
        (42, 10, "40-49"),
        (0, 5, "0-4"),
        (4, 5, "0-4"),
        (5, 5, "5-9"),
        (89, 5, "85-89"),
        (7, 2, "6-7"),
    ],
)
def test_a_band_is_anchored_at_zero(age: int, width: int, expected: str) -> None:
    """Which is what makes a width of ten give decades and not an offset grid."""
    assert layout.age_band(age, width) == expected


@pytest.mark.parametrize(
    ("age", "width", "expected"),
    [
        (85, 7, "84-89"),
        (89, 7, "84-89"),
        (50, 100, "0-89"),
        (85, 20, "80-89"),
    ],
)
def test_a_bands_upper_bound_never_passes_the_ceiling(age: int, width: int, expected: str) -> None:
    """Where the two mechanisms meet, and the invariant wins.

    A width of seven would otherwise place an 85-year-old in ``84-90`` and so
    state that they might be 90 — exactly what truncating at 89 exists to
    prevent. The band is clamped instead, which makes the top band uneven for
    widths that do not divide the ceiling and is the honest trade.
    """
    assert layout.age_band(age, width) == expected


@pytest.mark.parametrize("width", [2, 5, 7, 10, 20])
def test_every_age_falls_inside_the_band_it_is_given(width: int) -> None:
    """The property, rather than a handful of examples."""
    for age in range(layout.AGE_CEILING + 1):
        bounds = layout.age_bounds(layout.age_band(age, width))
        assert bounds is not None
        low, high = bounds
        assert low <= age <= high


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("42", (42, 42)),
        ("40-44", (40, 44)),
        ("0-4", (0, 4)),
        (layout.AGE_ABOVE_CEILING, None),
        (layout.NOT_APPLICABLE, None),
        ("", None),
    ],
)
def test_a_cell_is_read_as_bounds_or_as_nothing(
    value: str, expected: tuple[int, int] | None
) -> None:
    """A reader of the column cannot know which form a dataset used.

    So both are accepted, and the two cells that state no number state it by
    returning nothing rather than by raising: `90+` is not an error and neither
    is `n/a`.
    """
    assert layout.age_bounds(value) == expected


def test_the_ceiling_outranks_the_band(the_very_old: date = date(1900, 3, 2)) -> None:
    """An age above the ceiling is the marker, banded or not.

    Driven through the build's own helper rather than through a cohort, because
    the generator produces nobody over 89 — and a test that depended on it
    would be a test that passed for the wrong reason.
    """
    reference = date(2024, 6, 1)

    assert _participant_age(the_very_old, reference, None) == layout.AGE_ABOVE_CEILING
    assert _participant_age(the_very_old, reference, WIDTH) == layout.AGE_ABOVE_CEILING
    assert _participant_age(None, reference, WIDTH) == layout.NOT_APPLICABLE


# --------------------------------------------------------------------------
# Through the build
# --------------------------------------------------------------------------


def test_without_the_option_the_table_is_what_it_always_was(
    tmp_path: Path, corpus: RawCorpus
) -> None:
    """Opt-in, so no existing dataset moves and no captured number does either."""
    plain, again = tmp_path / "plain", tmp_path / "again"
    _build(plain, corpus, None)
    _build(again, corpus, None)

    digest = hashlib.sha256((plain / layout.PARTICIPANTS_TSV).read_bytes()).hexdigest()
    assert hashlib.sha256((again / layout.PARTICIPANTS_TSV).read_bytes()).hexdigest() == digest
    assert all(value.isdigit() or value in {layout.NOT_APPLICABLE} for value in _ages(plain))


def test_a_banded_table_states_bands_and_never_a_bare_age(
    tmp_path: Path, corpus: RawCorpus
) -> None:
    """One exact age left among the bands would be the one re-identifiable row."""
    out = tmp_path / "banded"
    _build(out, corpus, WIDTH)

    values = _ages(out)
    assert values
    for value in values:
        if value in {layout.NOT_APPLICABLE, layout.AGE_ABOVE_CEILING}:
            continue
        assert layout.AGE_BAND_SEPARATOR in value, value
        bounds = layout.age_bounds(value)
        assert bounds is not None
        low, high = bounds
        assert low % WIDTH == 0
        assert high in {low + WIDTH - 1, layout.AGE_CEILING}


def test_a_banded_dataset_still_conforms(tmp_path: Path, corpus: RawCorpus) -> None:
    """A band must not read to the validator as a surviving calendar date.

    It cannot — every bound is at most two digits because ages stop at the
    ceiling — but that is a property of the ceiling rather than of the band
    format, so it is worth a check rather than an argument.
    """
    out = tmp_path / "banded"
    _build(out, corpus, WIDTH)
    write_risk_report(out)

    report = validate_dataset(out)

    assert report.is_conformant, [f.format_line() for f in report.errors]


# --------------------------------------------------------------------------
# What it buys, measured
# --------------------------------------------------------------------------


def test_banding_reduces_the_combinations_below_the_threshold(
    tmp_path: Path, corpus: RawCorpus
) -> None:
    """The reason the option exists, as a number rather than as a claim.

    Not an assertion that k reaches five: on twenty-five people it does not, and
    `risk` says so. What banding buys is fewer rows alone in their own
    combination, and that is what is measured.
    """
    plain, banded = tmp_path / "plain", tmp_path / "banded"
    _build(plain, corpus, None)
    _build(banded, corpus, WIDTH)

    before = assess(plain)
    after = assess(banded)

    assert len(after["combinations_below_threshold"]) < len(  # type: ignore[arg-type]
        before["combinations_below_threshold"]  # type: ignore[arg-type]
    )


def test_risk_measures_the_values_the_dataset_holds(tmp_path: Path, corpus: RawCorpus) -> None:
    """Not the ages they came from, which would describe a dataset nobody has.

    It needs no code of its own to do this — `risk` reads `participants.tsv` —
    and that is precisely why it is worth pinning: a future change that banded
    somewhere other than at write time would silently make the report describe
    the wrong values.
    """
    out = tmp_path / "banded"
    _build(out, corpus, WIDTH)

    report = assess(out)

    combinations = report["combinations_below_threshold"]
    assert isinstance(combinations, list)
    assert combinations
    for entry in combinations:
        age = entry["values"]["age"]
        assert layout.AGE_BAND_SEPARATOR in age or age in {
            layout.NOT_APPLICABLE,
            layout.AGE_ABOVE_CEILING,
        }, age


def test_the_description_reports_the_range_the_dataset_states(
    tmp_path: Path, corpus: RawCorpus
) -> None:
    """Both bounds of a band, not just its lower one.

    `minTypicalAge` and `maxTypicalAge` exist so an applicant can tell whether
    they need exact ages before applying for them. Reading only the first number
    of `80-89` would understate the maximum by almost a whole band; parsing with
    `int()`, which is what the code did before bands existed, would skip the row
    entirely and report no range at all for a banded dataset.
    """
    from commissura.build.manifest import _typical_age_range

    plain, banded = tmp_path / "plain", tmp_path / "banded"
    _build(plain, corpus, None)
    _build(banded, corpus, WIDTH)

    exact = _typical_age_range(plain)
    ranged = _typical_age_range(banded)

    assert exact and ranged, "a banded dataset must still publish a range"
    assert int(ranged["healthdcatap:maxTypicalAge"]["@value"]) >= int(  # type: ignore[index]
        exact["healthdcatap:maxTypicalAge"]["@value"]  # type: ignore[index]
    )
    assert int(ranged["healthdcatap:minTypicalAge"]["@value"]) <= int(  # type: ignore[index]
        exact["healthdcatap:minTypicalAge"]["@value"]  # type: ignore[index]
    )


# --------------------------------------------------------------------------
# What the manifest says
# --------------------------------------------------------------------------


def test_the_manifest_states_the_width_that_was_applied(tmp_path: Path, corpus: RawCorpus) -> None:
    """A dataset whose ages read 40-49 is not self-describing without it."""
    manifest = _build(tmp_path / "banded", corpus, WIDTH)

    section = manifest["generalisation"]
    assert isinstance(section, dict)
    age = section["age"]
    assert isinstance(age, dict)
    assert age["banded"] is True
    assert age["band_years"] == WIDTH


def test_the_manifest_says_ages_are_exact_when_they_are(tmp_path: Path, corpus: RawCorpus) -> None:
    """Said rather than left out, so a reader can tell a decision from a silence."""
    manifest = _build(tmp_path / "plain", corpus, None)

    section = manifest["generalisation"]
    assert isinstance(section, dict)
    age = section["age"]
    assert isinstance(age, dict)
    assert age["banded"] is False
    assert "band_years" not in age


def test_the_ceiling_is_reported_apart_from_the_band(tmp_path: Path, corpus: RawCorpus) -> None:
    """One field for both would make an invariant look like a choice."""
    for band in (None, WIDTH):
        manifest = _build(tmp_path / f"ds-{band}", corpus, band)
        section = manifest["generalisation"]
        assert isinstance(section, dict)
        age = section["age"]
        assert isinstance(age, dict)
        assert age["ceiling_years"] == layout.AGE_CEILING
        assert age["above_ceiling"] == layout.AGE_ABOVE_CEILING


def test_the_manifest_no_longer_claims_a_band_it_did_not_apply(
    tmp_path: Path, corpus: RawCorpus
) -> None:
    """The misstatement this task found, pinned so it cannot come back.

    Two entries in the per-field table said the birth date was carried "as an
    age band" whatever the build did, because the helper producing the value
    was named `_age_band` and banded nothing. An auditor reading the one
    document written to travel would have believed ages were generalised when
    they were exact.
    """
    out = tmp_path / "plain"
    _build(out, corpus, None)

    text = (out / layout.DEIDENT_DIR / layout.MANIFEST_JSON).read_text(encoding="utf-8")

    assert "as an age band" not in text
    assert "generalisation" in text


# --------------------------------------------------------------------------
# Through the command
# --------------------------------------------------------------------------


def _key_file(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "k.key"
    path.write_text(KEY.material.hex(), encoding="utf-8")
    return path


def _invoke(tmp_path: Path, raw: Path, *extra: str):  # type: ignore[no-untyped-def]
    return runner.invoke(
        app,
        [
            "build",
            str(raw),
            "--out",
            str(tmp_path / "ds"),
            "--key-file",
            str(_key_file(tmp_path)),
            "--hdab",
            "H",
            "--publisher",
            "P",
            *extra,
        ],
    )


def test_the_command_refuses_a_width_of_one(tmp_path: Path, corpus_root: Path) -> None:
    """Which is the exact age, and is what omitting the option already gives.

    Accepting it would write `42-42` into the dataset and declare a band width
    of one in the manifest — a true statement about nothing, which a reader
    would have to decode before concluding that nothing had been generalised.
    """
    result = _invoke(tmp_path, corpus_root, "--age-band", "1")

    assert result.exit_code == 2


def test_the_command_reports_which_of_the_two_it_did(tmp_path: Path, corpus_root: Path) -> None:
    """On the terminal and in the JSON, because it changes what the data means."""
    banded = _invoke(tmp_path / "a", corpus_root, "--age-band", str(WIDTH), "--json")
    plain = _invoke(tmp_path / "b", corpus_root, "--json")

    assert banded.exit_code == 0
    assert plain.exit_code == 0
    assert json.loads(banded.stdout)["age_band_years"] == WIDTH
    assert json.loads(plain.stdout)["age_band_years"] is None
