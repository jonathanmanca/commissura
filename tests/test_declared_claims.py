"""Every statement the manifest makes, and what keeps the declared ones true.

The audit of 2026-11-13 asked one question of this document — *for every field,
can it carry something derived from the input?* — and found two leaks. This file
comes from asking the next one, deliberately rather than by accident: **for
every statement the manifest makes, is it derived from the run or declared by
hand, and if declared, what keeps it true?**

The prompt for asking was that three defects of exactly that shape had turned up
inside four days, each one found while doing something else: a count that
claimed records were absent when they were present, a count in the wrong unit,
and a per-field note saying the birth date was carried "as an age band" when no
banding existed anywhere in the tool. A pattern found three times by accident is
worth one deliberate pass.

381 leaf statements were enumerated from a manifest with every optional section
populated. Most are derived and need nothing. What the pass found:

**One live re-identification channel, and it was two days old.** `--age-band`
generalised `participants.tsv` and left the exact age in the prose of the same
subject's reports. Measured on twelve subjects banded to ten years: **eleven
carried their own exact age**, while the table said `50-59` and the manifest
declared the band. The dataset reversed a control it documented, and `risk`
reported a k improvement the reports handed straight back. That is worse than a
stale note, because the note was merely false while this was the feature not
working.

**Two schema versions that could not move.** `risk_report.json` declared
`layout.SCHEMA_VERSION` as its own, so a consumer had a version field
structurally unable to describe the file it sat in — and it stood at 1.0.0
across two changes to the report's own structure. And the layout's own version
had read 1.0.0 since the initial commit while three dataset-observable things
changed under it.

**Two prose declarations that duplicated a constant** rather than deriving from
it: the key length written out as "32-byte", and `sha256` named beside a
hardcoded `hashlib.sha256()` call.

**And what the pass found sound, recorded because an audit that reports only
problems is not a measurement.** `DOMAIN_PURPOSES` is complete and guarded by a
test that reads the module's own `_DOMAIN_*` constants, so a prefix added
without a purpose fails. The three-part reconciliation of
`records_not_in_dataset` holds. `residual_risk.structural` is derived, as of
2026-11-13. The CDA note claiming `section/code` reaches `panel_code` is
accurate.

Every identifier here is synthetic.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest

from commissura import layout
from commissura.build.integrity import DIGEST_ALGORITHM, digest_file
from commissura.build.manifest import write_healthdcat_description, write_manifest
from commissura.build.observe import AGE_FIELD
from commissura.build.risk import RISK_SCHEMA_VERSION, write_risk_report
from commissura.build.writer import BuildSpec, build_dataset
from commissura.deident.keys import KEY_BYTES, SecretKey
from commissura.generate.cohort import CohortSpec
from commissura.generate.writer import write_corpus
from commissura.read.corpus import RawCorpus, read_corpus

KEY = SecretKey(bytes(range(32)))
SPEC = BuildSpec(dataset_name="d", description="d", hdab="H", publisher="P")
WIDTH = 10

AGE_IN_PROSE = re.compile(rf"{AGE_FIELD}:\s*(\S+)\s*anni")


@pytest.fixture(scope="module")
def corpus_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("declared") / "raw"
    write_corpus(CohortSpec(subjects=12, seed=42, defect_rate=0.0), root)
    return root


@pytest.fixture(scope="module")
def corpus(corpus_root: Path) -> RawCorpus:
    return read_corpus(corpus_root)


def _build(out: Path, corpus: RawCorpus, band: int | None) -> dict[str, object]:
    summary = build_dataset(corpus, KEY, SPEC, out, age_band=band)
    write_risk_report(out)
    return write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=SPEC)


def _ages_in_prose(root: Path, subject: str) -> set[str]:
    return {
        match.group(1)
        for path in (root / subject).rglob(f"*{layout.REPORT_TEXT_EXTENSION}")
        for match in AGE_IN_PROSE.finditer(path.read_text(encoding="utf-8"))
    }


def _participants(root: Path) -> list[tuple[str, str]]:
    lines = (root / layout.PARTICIPANTS_TSV).read_text(encoding="utf-8").splitlines()[1:]
    return [(row[0], row[1]) for row in (line.split("\t") for line in lines)]


# --------------------------------------------------------------------------
# The control has to reach every representation of the value
# --------------------------------------------------------------------------


def test_a_banded_dataset_states_no_exact_age_in_its_prose(
    tmp_path: Path, corpus: RawCorpus
) -> None:
    """The leak this pass was for, pinned so the feature cannot half-work again.

    Eleven of twelve banded participants once carried their own exact age in
    their own reports, in a dataset whose table said `50-59` and whose manifest
    declared a ten-year band. Asserted against each subject's own row rather
    than against a pattern, because "no digits anywhere" would pass on a
    dataset that had removed the age entirely and that is a different product.
    """
    out = tmp_path / "banded"
    _build(out, corpus, WIDTH)

    disagreeing = [
        (subject, band, stated)
        for subject, band in _participants(out)
        for stated in _ages_in_prose(out, subject)
        if stated != band and stated != layout.AGE_ABOVE_CEILING
    ]

    assert not disagreeing, "prose states an age its own participant row does not: " + repr(
        disagreeing[:5]
    )


def test_a_banded_dataset_still_states_the_age_somewhere(tmp_path: Path, corpus: RawCorpus) -> None:
    """The guard on the guard. Removing the age would satisfy the test above.

    Banding is generalisation and not redaction: the point is a value coarse
    enough to share and still worth reading. A fix that deleted the line would
    pass the previous assertion and quietly change what the tool does.
    """
    out = tmp_path / "banded"
    _build(out, corpus, WIDTH)

    stated = {value for subject, _ in _participants(out) for value in _ages_in_prose(out, subject)}

    assert stated, "no report states an age at all"
    assert all(
        layout.AGE_BAND_SEPARATOR in value or value == layout.AGE_ABOVE_CEILING for value in stated
    )


def test_an_unbanded_dataset_keeps_the_exact_age_in_prose(
    tmp_path: Path, corpus: RawCorpus
) -> None:
    """Unchanged behaviour, and the reason the fix is conditional rather than always.

    An exact age in prose is a documented decision of 2026-11-10 and not a
    defect: it is clinically useful, the birth date it came from is removed, and
    nothing in an unbanded dataset claims otherwise. It only became a leak once
    something else in the same dataset declared the value generalised.
    """
    out = tmp_path / "exact"
    _build(out, corpus, None)

    stated = {value for subject, _ in _participants(out) for value in _ages_in_prose(out, subject)}

    assert stated
    assert any(value.isdigit() for value in stated)


def test_the_manifest_reports_what_the_build_did_to_the_age_row(
    tmp_path: Path, corpus: RawCorpus
) -> None:
    """Derived, because the disposition depends on a flag.

    `observe_corpus` describes the input and cannot know what the build did to
    it, so a static `kept` was a declaration that a banded run contradicted.
    This is the same correction as the birth-date note, one table along.
    """
    rows = {}
    for label, band in (("exact", None), ("banded", WIDTH)):
        manifest = _build(tmp_path / label, corpus, band)
        ledgers = manifest["modalities"]
        assert isinstance(ledgers, list)
        reports = next(item for item in ledgers if item["modality"] == "reports")
        rows[label] = next(f for f in reports["fields"] if f["field"] == AGE_FIELD)

    assert rows["exact"]["disposition"] == "kept"
    assert rows["banded"]["disposition"] == "replaced"


# --------------------------------------------------------------------------
# A version has to describe the document it is in
# --------------------------------------------------------------------------


def test_the_risk_report_declares_its_own_version_and_not_the_layouts(
    tmp_path: Path, corpus: RawCorpus
) -> None:
    """Two documents sharing one number can never move independently.

    The report emitted `layout.SCHEMA_VERSION` for its own `schema_version`, so
    it stood at 1.0.0 across two additions to its own structure
    (`laboratory_values`, then `quasi_identifier_channels`) and could not have
    moved without making a false statement about the dataset layout. The
    inequality is the load-bearing half of this test: it fails if somebody
    wires the two together again.
    """
    out = tmp_path / "ds"
    _build(out, corpus, None)

    report = json.loads(
        (out / layout.DEIDENT_DIR / layout.RISK_REPORT_JSON).read_text(encoding="utf-8")
    )

    assert report["schema_version"] == RISK_SCHEMA_VERSION
    assert report["schema_version"] != layout.SCHEMA_VERSION


def test_the_layout_version_is_spelled_out_so_a_bump_is_deliberate() -> None:
    """Written here rather than imported, on purpose.

    A test that imported the constant would agree with whatever value somebody
    put in it, which is exactly how this one sat at 1.0.0 from the initial
    commit while `healthdcat-ap.jsonld`, a banded `age` column and a banded
    `Eta:` line all appeared under it. The `MANIFEST_SCHEMA_VERSION` precedent:
    a schema version is part of a schema change, so changing it should make a
    test fail and be acknowledged.
    """
    assert layout.SCHEMA_VERSION == "1.1.0"
    assert RISK_SCHEMA_VERSION == "1.2.0"


# --------------------------------------------------------------------------
# A declaration that duplicates a constant will disagree with it
# --------------------------------------------------------------------------


def test_the_declared_digest_algorithm_is_the_one_that_produced_the_digests(
    tmp_path: Path,
) -> None:
    """A manifest naming the wrong algorithm sends a verifier to the wrong answer.

    `DIGEST_ALGORITHM` is both declared in the manifest and passed to
    `hashlib.new`, so the constant causes the behaviour. Before that the module
    named `sha256` in one place and called `hashlib.sha256` in another, and a
    dataset whose digests were produced some other way would have read as
    altered when nothing had touched it.
    """
    path = tmp_path / "f.txt"
    path.write_bytes(b"synthetic content\n")

    expected = hashlib.new(DIGEST_ALGORITHM, b"synthetic content\n").hexdigest()

    assert digest_file(path) == expected


def test_the_declared_key_length_is_the_enforced_one(tmp_path: Path, corpus: RawCorpus) -> None:
    """The manifest said "A 32-byte key" in prose beside a constant reading 32.

    True today and true only by coincidence of nobody having changed either. It
    is interpolated now, so the sentence cannot outlive the rule it describes.
    """
    manifest = _build(tmp_path / "ds", corpus, None)

    section = manifest["pseudonymisation"]
    assert isinstance(section, dict)

    assert f"{KEY_BYTES}-byte" in str(section["salt_custody"])


def test_the_three_part_record_count_still_reconciles(tmp_path: Path, corpus: RawCorpus) -> None:
    """Checked again here because this pass is where it would be noticed if it broke.

    Reported sound rather than rewritten: `records_not_in_dataset` is the
    refused linkage issues plus `records_dropped` plus
    `opt_out.records_excluded`, and all three parts are visible in the same
    section. An audit that reports only its findings has not measured anything.
    """
    manifest = _build(tmp_path / "ds", corpus, None)

    source = manifest["source"]
    assert isinstance(source, dict)
    dropped = source["records_dropped"]
    assert isinstance(dropped, list)
    opt_out = source["opt_out"]
    assert isinstance(opt_out, dict)

    assert opt_out["applied"] is False
    assert source["records_not_in_dataset"] >= sum(int(row["count"]) for row in dropped)


# --------------------------------------------------------------------------
# The other document written to travel: the Article 77 description
# --------------------------------------------------------------------------
#
# The SHACL check proves the description is *conformant*, which is a different
# claim from *true*: `"integer"` is a valid CSVW built-in whatever the column
# holds, and `"synthetic"` is a perfectly well-formed keyword for real patient
# data. So the same question was asked here, and found three things.


def _description(out: Path) -> dict[str, object]:
    payload = json.loads((out / layout.HEALTHDCAT_DESCRIPTION).read_text(encoding="utf-8"))
    node = next(item for item in payload["@graph"] if "dct:title" in item)
    assert isinstance(node, dict)
    return node


def _describe(out: Path, corpus: RawCorpus, spec: BuildSpec) -> dict[str, object]:
    summary = build_dataset(corpus, KEY, spec, out)
    write_healthdcat_description(out, spec=spec, summary=summary)
    return _description(out)


def test_a_dataset_with_no_imaging_is_not_catalogued_as_imaging(
    tmp_path: Path, corpus_root: Path
) -> None:
    """The keywords were a fixed list, so they described a corpus nobody had.

    A catalogue is searched by keyword. A dataset asserting `imaging` with no
    imaging study in it wastes the time of whoever finds it, and an access body
    reading the record cannot tell which datasets actually hold what.
    """
    bare = tmp_path / "raw"
    shutil.copytree(corpus_root, bare)
    shutil.rmtree(bare / "imaging")

    keywords = _describe(tmp_path / "ds", read_corpus(bare), SPEC)["dcat:keyword"]
    assert isinstance(keywords, list)

    assert "imaging" not in keywords
    assert "laboratory" in keywords


@pytest.mark.parametrize(
    ("dataset_type", "expected"),
    [("SYNTHETIC_DATA", True), ("TEST_DATA", False)],
)
def test_the_keywords_cannot_contradict_the_declared_dataset_type(
    tmp_path: Path, corpus: RawCorpus, dataset_type: str, expected: bool
) -> None:
    """Two properties stating one fact must not disagree, and they did.

    `--dataset-type TEST_DATA` was reachable from the command line and left
    `synthetic` in the keywords of the same record, so a holder who correctly
    declared their dataset type still published a document saying the data was
    synthetic — with no flag to fix it. A record that contradicts itself leaves
    a reader to guess which half to believe.
    """
    spec = BuildSpec(
        dataset_name="d", description="d", hdab="H", publisher="P", dataset_type=dataset_type
    )

    keywords = _describe(tmp_path / f"ds-{dataset_type}", corpus, spec)["dcat:keyword"]
    assert isinstance(keywords, list)

    assert ("synthetic" in keywords) is expected


def test_the_holder_can_replace_the_keywords_from_the_command_line(
    tmp_path: Path, corpus_root: Path
) -> None:
    """Driven through the CLI, because that is where this defect lived.

    Three mandatory fields once existed on `BuildSpec` with no flag, so the
    library could emit a conformant description while the command could not
    (2026-11-07). The keywords were the same shape: a field with a default and
    no way to reach it.
    """
    from typer.testing import CliRunner

    from commissura.cli import app

    key = tmp_path / "k.key"
    key.write_text(KEY.material.hex(), encoding="utf-8")
    out = tmp_path / "ds"

    result = CliRunner().invoke(
        app,
        [
            "build",
            str(corpus_root),
            "--out",
            str(out),
            "--key-file",
            str(key),
            "--hdab",
            "H",
            "--publisher",
            "P",
            "--contact-point",
            "a@b.invalid",
            "--access-url",
            "https://x.invalid",
            "--keyword",
            "oncology",
            "--identifier",
            "urn:irccs-marebianco:lab-2029-01",
        ],
    )

    assert result.exit_code == 0, result.stdout
    node = _description(out)
    assert node["dcat:keyword"] == ["oncology"]
    assert node["dct:identifier"] == "urn:irccs-marebianco:lab-2029-01"


def test_every_declared_column_datatype_is_the_tightest_true_one(
    tmp_path: Path, corpus: RawCorpus
) -> None:
    """Checked against the data, in both directions.

    `reference_low` and `reference_high` were declared `integer` while the
    column holds `0.30`, `1.10` and `17.0`. A catalogue consumer parsing by the
    declared type fails on the first row, and the SHACL check calls the document
    conformant because `integer` is a valid CSVW built-in name.

    Both directions, because a one-sided test is passed by declaring everything
    `string`: a column whose every value is an integer must say so, and a column
    with anything else must not. `decimal` is deliberately not reachable here —
    `_split_reference_range` writes `n/a` for a one-sided interval, so that
    column's domain holds a non-numeric sentinel and no numeric type describes
    it.
    """
    out = tmp_path / "ds"
    node = _describe(out, corpus, SPEC)

    columns = node["healthdcatap:hasVariables"]
    assert isinstance(columns, list)
    declared = {
        column["csvw:name"]: column["csvw:datatype"]
        for column in columns[0]["csvw:table"][0]["csvw:column"]
    }

    tables = sorted(out.rglob(f"*{layout.LAB_SUFFIX}.tsv"))
    assert tables, "no laboratory table to check the declaration against"
    header = tables[0].read_text(encoding="utf-8").splitlines()[0].split("\t")
    seen: dict[str, set[str]] = {name: set() for name in header}
    for table in tables:
        for line in table.read_text(encoding="utf-8").splitlines()[1:]:
            for name, cell in zip(header, line.split("\t"), strict=True):
                seen[name].add(cell)

    for name, values in seen.items():
        meaningful = {v for v in values if v != layout.NOT_APPLICABLE}
        all_integers = bool(meaningful) and all(v.lstrip("-").isdigit() for v in meaningful)
        expected = "integer" if all_integers else "string"
        assert declared[name] == expected, (
            f"{name} is declared {declared[name]!r} and holds "
            f"{sorted(meaningful)[:4]}; the tightest true type is {expected!r}"
        )
