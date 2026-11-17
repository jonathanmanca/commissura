"""The risk report has to hand over every quasi-identifier, not just the scored ones.

TEHDAS2 D7.2 section 4.5 (p. 41) makes two things an explicit activity for
whoever pseudonymises: "identification of quasi-identifiers and handing over
information on them to the data minimisation process", and providing
"health-data specific quasi-identifiers beyond what is in the EDPB guidelines
(e.g., dates of visits in the hospital also become quickly identifying)".
Section 3.2 (p. 17) lists "a sequence of hospital visit dates" among its own
examples of a quasi-identifier.

`risk_report.json` is that hand-over and it was under-reporting. It named the
participant columns and counted laboratory analyte rarity; it said nothing about
the day-offset sequence, which is the strongest channel in the dataset and the
one the README has described in prose since 2026-11-11. A reader taking the
machine-readable artefact at its word -- which is what a machine-readable
artefact is for -- would have generalised age and sex and shipped a dataset in
which every subject's event timeline was intact and exactly aligned.

The point these tests hold down is that **a channel with no computable k is
still a channel**. k-anonymity counts people sharing a combination of attribute
values; a sequence of offsets has no value domain, so no k describes it. Dropping
it for being unscoreable is exactly how it came to be missing.

Every identifier here is synthetic.
"""

from __future__ import annotations

import json
from pathlib import Path

from commissura import layout
from commissura.build.risk import assess, channels, write_risk_report
from commissura.build.writer import BuildSpec, build_dataset
from commissura.deident.keys import SecretKey
from commissura.generate.cohort import CohortSpec
from commissura.generate.writer import write_corpus
from commissura.read.corpus import read_corpus

KEY = SecretKey(bytes(range(32)))


def _built(tmp_path: Path, *, subjects: int = 8, seed: int = 42) -> Path:
    raw, out = tmp_path / "raw", tmp_path / "dataset"
    write_corpus(CohortSpec(subjects=subjects, seed=seed, defect_rate=0.0), raw)
    corpus = read_corpus(raw)
    spec = BuildSpec(dataset_name="d", description="d", hdab="H", publisher="P")
    build_dataset(corpus, KEY, spec, out)
    return out


def _named(report: dict[str, object]) -> dict[str, dict[str, object]]:
    found = report["quasi_identifier_channels"]
    assert isinstance(found, list)
    return {str(entry["channel"]): entry for entry in found}


# --------------------------------------------------------------------------
# The channel the report was missing
# --------------------------------------------------------------------------


def test_the_interval_sequence_is_named_as_a_quasi_identifier(tmp_path: Path) -> None:
    """The finding this file exists for.

    D7.2's own example of a health-specific quasi-identifier is a sequence of
    hospital visit dates. The dataset carries exactly that, as day offsets, and
    the hand-over artefact did not mention it.
    """
    out = _built(tmp_path)

    entry = _named(assess(out))["event interval sequence"]

    assert "day_offset" in str(entry["where"])
    assert entry["scored"] is False
    assert str(entry["why_not_scored"])
    assert str(entry["kept_because"])


def test_the_interval_channel_states_the_re_identification_route(tmp_path: Path) -> None:
    """Naming a channel without saying how it is exploited is half a hand-over.

    The route is specific and worth stating in the file: one true calendar date
    for one subject, from any other source, dates every other event in their
    record.
    """
    out = _built(tmp_path)

    risk = str(_named(assess(out))["event interval sequence"]["risk"])

    assert "exact" in risk.lower()
    assert "date" in risk.lower()


def test_a_dataset_with_no_sessions_claims_no_interval_channel(tmp_path: Path) -> None:
    """Derived, not declared: a channel is listed when the dataset carries it.

    A static list would report an interval sequence for a dataset with no
    sessions at all, where there is nothing to align -- the same mistake as the
    four fixed prose strings `residual_risk.structural` used to carry.
    """
    out = _built(tmp_path)
    for subject in out.glob(f"{layout.SUBJECT_PREFIX}*"):
        for session in subject.glob("ses-*"):
            for path in sorted(session.rglob("*"), reverse=True):
                path.unlink() if path.is_file() else path.rmdir()
            session.rmdir()

    assert "event interval sequence" not in _named(assess(out))


# --------------------------------------------------------------------------
# The channels that were already there
# --------------------------------------------------------------------------


def test_the_scored_channels_say_that_they_were_scored(tmp_path: Path) -> None:
    """So a reader can tell a measured channel from a merely named one."""
    out = _built(tmp_path)

    found = _named(assess(out))

    assert found["participant demographics"]["scored"] is True
    assert found["laboratory measurement values"]["scored"] is True


def test_the_demographic_channel_names_the_mitigation_the_guideline_asks_for(
    tmp_path: Path,
) -> None:
    """D7.2 section 3.3.1 (p. 22) names generalisation for age specifically.

    Which this tool does not apply, and the entry says so rather than implying
    the channel is handled. The ceiling at 89 is the half that *is* applied.
    """
    out = _built(tmp_path)

    mitigation = str(_named(assess(out))["participant demographics"]["mitigation_available"])

    assert "89" in mitigation
    assert "not implemented" in mitigation


def test_every_channel_either_is_scored_or_says_why_not(tmp_path: Path) -> None:
    """The invariant, over whatever channels a dataset turns out to carry.

    An unscored entry with no reason is how an unscoreable channel becomes an
    omitted one, which is the defect this whole file is about.
    """
    out = _built(tmp_path)

    for name, entry in _named(assess(out)).items():
        if entry["scored"] is False:
            assert str(entry.get("why_not_scored", "")), name
        else:
            assert entry["scored"] is True, name
        assert str(entry["where"]), name
        assert str(entry["risk"]), name


def test_the_imaging_channel_points_at_the_pixel_warning(tmp_path: Path) -> None:
    """The one channel this tool cannot inspect at all.

    Metadata is read; pixels never are. A study whose own metadata reports
    burned-in annotation is reported by rule DI009 and is not fixed, so the
    hand-over has to say where that warning comes from.
    """
    out = _built(tmp_path)

    entry = _named(assess(out))["imaging acquisition metadata"]

    assert "DI009" in str(entry["risk"])
    assert entry["scored"] is False


# --------------------------------------------------------------------------
# Through the written report
# --------------------------------------------------------------------------


def test_the_written_report_carries_the_channels(tmp_path: Path) -> None:
    """It is the file the next step reads, so the list has to be in it."""
    out = _built(tmp_path)

    write_risk_report(out)

    payload = json.loads(
        (out / layout.DEIDENT_DIR / layout.RISK_REPORT_JSON).read_text(encoding="utf-8")
    )
    assert "event interval sequence" in _named(payload)


def test_a_table_without_quasi_identifier_columns_still_reports_channels(
    tmp_path: Path,
) -> None:
    """The early-return branch had to grow the field too.

    A participants table carrying none of the recommended columns means no k can
    be computed over demographics -- and says nothing at all about the intervals,
    the laboratory values or the imaging metadata, which are still there.
    """
    out = _built(tmp_path)
    table = out / layout.PARTICIPANTS_TSV
    rows = table.read_text(encoding="utf-8").splitlines()
    with table.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("participant_id\n")
        for row in rows[1:]:
            handle.write(row.split("\t")[0] + "\n")

    report = assess(out)

    assert report["quasi_identifiers"] == []
    found = _named(report)
    assert "event interval sequence" in found
    assert "participant demographics" not in found


def test_channels_takes_the_scored_columns_as_given(tmp_path: Path) -> None:
    """So the entry cannot claim a measurement that was skipped."""
    out = _built(tmp_path)

    assert "participant demographics" not in {
        str(entry["channel"]) for entry in channels(out, scored=())
    }
    assert "participant demographics" in {
        str(entry["channel"]) for entry in channels(out, scored=("age", "sex"))
    }
