"""The measurement the project's central claim rests on.

"Rules first, measurement always" was half a promise until something compared
the generator's ground truth against the built dataset. These tests pin the
number and, more importantly, pin that the number can move: a measurement that
cannot report a failure is not measuring.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from commissura import layout
from commissura.build.manifest import write_healthdcat_description, write_manifest
from commissura.build.risk import write_risk_report
from commissura.build.writer import BuildSpec, build_dataset
from commissura.deident.keys import SecretKey
from commissura.generate.cohort import CohortSpec
from commissura.generate.writer import write_corpus
from commissura.measure import (
    ANNOTATIONS_PATH,
    MEASURABLE_LENGTH,
    RETAINED_BY_DESIGN,
    CategoryResult,
    MeasureReport,
    declared_values,
    excluded_record_count,
    measure,
    read_annotations,
)
from commissura.models import PhiCategory
from commissura.read.corpus import read_corpus

KEY = SecretKey(bytes(range(32)))

MINIMUM_RECALL = 1.0
"""Every measurable planted identifier must be removed. No allowance.

Set at the number a real run produces rather than below it. A threshold with
slack in it is a threshold that absorbs the first regression silently, and the
first regression is the one worth catching -- by the time recall has drifted
far enough to cross a lenient bar, nobody knows which change did it.
"""


def corpus_and_dataset(
    tmp_path: Path, *, defect_rate: float = 0.0, seed: int = 23
) -> tuple[Path, Path]:
    """Generate a corpus and build a dataset from it, as the command line does."""
    raw, out = tmp_path / "raw", tmp_path / "dataset"
    write_corpus(CohortSpec(subjects=5, seed=seed, defect_rate=defect_rate), raw)
    parsed = read_corpus(raw)
    spec = BuildSpec(
        dataset_name="Synthetic dataset",
        description="For measuring.",
        hdab="Agenzia Nazionale Sintetica per i Dati Sanitari",
        publisher="IRCCS SINTETICO MAREBIANCO",
        contact_point="dati@irccs-sintetico.invalid",
        access_url="https://portale-hdab-sintetico.invalid/permessi",
    )
    summary = build_dataset(parsed, KEY, spec, out)
    write_healthdcat_description(out, spec=spec, summary=summary)
    write_risk_report(out)
    write_manifest(out, corpus=parsed, summary=summary, key=KEY, spec=spec)
    return raw, out


def test_every_measurable_identifier_is_removed(tmp_path: Path) -> None:
    """The headline number, and the threshold a regression has to cross."""
    raw, out = corpus_and_dataset(tmp_path)

    report = measure(raw, out)

    assert report.recall is not None
    assert report.recall >= MINIMUM_RECALL, [
        (m.category.value, m.text, m.found_in) for m in report.misses
    ]
    assert report.measurable > 0, "a corpus with nothing to measure would pass vacuously"
    assert report.survived == 0


DEFECTIVE_CORPUS_FLOOR = 0.95
"""Lower than the clean floor, on purpose, and the gap is the finding.

A defective corpus scores **below 100% and is supposed to**. The combination
that does it is `reports.missing_author`, which removes a report's signature
block, with `reports.identifier_in_prose`, which names a colleague mid-sentence.
The signature is the only structured source for that clinician, so removing it
leaves a name in the body that nothing declared — and targeted redaction cannot
reach a name nobody declared. That limit is stated in `scrub.py`'s own module
docstring and in the README; this is the number attached to it.

Fixing it would mean named entity recognition, which this project rejects on
the evidence that general-purpose tools miss over half of clinical PHI. So the
floor sits below the measured value with room for seed variation, and the test
below additionally pins *what* leaks — a bound alone would pass while the
failure changed character.
"""


def test_a_defective_corpus_leaks_only_things_nothing_declared(tmp_path: Path) -> None:
    """Injected defects are where de-identification is supposed to get harder.

    Not a 100% test, because the honest answer is not 100%. What is pinned is
    the *shape* of the failure: every survivor is a name written in running
    prose that no structured field declared — a colleague mentioned
    mid-sentence, or the site of a previous study cited after "presso". That is
    the one class targeted redaction is documented as unable to reach, and the
    scrubber's residual-risk list already warns about both. An identifier of
    any other kind surviving — a national identifier, an accession, a date —
    would be a defect rather than a limit, and this would catch it.

    The seed is load-bearing and that is worth knowing rather than discovering.
    Seed 23 stopped leaking when `reports.unreadable_date` was added, because
    the new defect drops the very reports that used to leak: an identifier in a
    document that is not in the dataset is not in the dataset. That is the
    degenerate effect `records_not_in_dataset` exists to make visible, and it
    is why this test fixes a seed that still exercises the limit.
    """
    raw, out = corpus_and_dataset(tmp_path, defect_rate=0.4, seed=5)

    report = measure(raw, out)

    assert report.recall is not None
    assert report.recall >= DEFECTIVE_CORPUS_FLOOR, [
        (m.category.value, m.text, m.found_in) for m in report.misses
    ]
    assert report.survived > 0, (
        "this seed exercises the documented limit; if it no longer leaks, find "
        "out whether the method improved or the records were merely dropped"
    )
    undeclarable = {
        PhiCategory.PERSON_NAME,
        PhiCategory.PROVIDER_NAME,
        PhiCategory.INSTITUTION,
    }
    for miss in report.misses:
        assert miss.category in undeclarable, miss
        assert layout.REPORT_TEXT_EXTENSION in miss.found_in, miss


def test_nothing_leaks_into_the_documents_that_travel(tmp_path: Path) -> None:
    """The manifest and the descriptions are read by outsiders by design.

    `measure` found a patient surname in `.deident/manifest.json`: the
    residual-risk list quoted the all-capitals tokens it was warning about, so
    the document that says "I could not remove these" handed them over. Now it
    reports a count and a length range. Pinned here because the whole point of
    that file is that somebody outside reads it.
    """
    raw, out = corpus_and_dataset(tmp_path, defect_rate=0.6)

    report = measure(raw, out)
    travelling = {
        f"{layout.DEIDENT_DIR}/{layout.MANIFEST_JSON}",
        layout.HEALTHDCAT_DESCRIPTION,
        layout.DATASET_DESCRIPTION,
    }

    assert not [m for m in report.misses if m.found_in in travelling], [
        (m.category.value, m.text, m.found_in) for m in report.misses
    ]


def test_the_measurement_can_fail(tmp_path: Path) -> None:
    """Otherwise the number above means nothing.

    A name is pasted back into a built report, exactly as somebody correcting a
    document by hand might, and the measurement has to find it and say where.
    """
    raw, out = corpus_and_dataset(tmp_path)
    leaked = next(
        span
        for span in read_annotations(raw)
        if span.category is PhiCategory.PERSON_NAME and len(span.text) >= MEASURABLE_LENGTH
    )
    document = sorted(out.rglob(f"*{layout.REPORT_TEXT_EXTENSION}"))[0]
    document.write_text(
        document.read_text(encoding="utf-8") + f"Firmato: {leaked.text}\n", encoding="utf-8"
    )

    report = measure(raw, out)

    assert report.survived >= 1
    assert report.recall is not None and report.recall < 1.0
    miss = next(m for m in report.misses if m.text == leaked.text)
    # The point of recording offsets: the miss names where it was planted, not
    # only that something leaked.
    assert miss.path == leaked.path
    assert (miss.start, miss.end) == (leaked.start, leaked.end)
    assert miss.found_in == document.relative_to(out).as_posix()


def test_a_name_in_different_case_is_still_found(tmp_path: Path) -> None:
    """Matching case-sensitively reported a clean sweep on a corpus that was not.

    This is the test for the decision, not for the regex: a measurement that a
    change of case defeats would have been quietly useless.
    """
    raw, out = corpus_and_dataset(tmp_path)
    leaked = next(
        span
        for span in read_annotations(raw)
        if span.category is PhiCategory.PERSON_NAME and len(span.text) >= MEASURABLE_LENGTH
    )
    document = sorted(out.rglob(f"*{layout.REPORT_TEXT_EXTENSION}"))[0]
    document.write_text(
        document.read_text(encoding="utf-8") + f"Firmato: {leaked.text.title()}\n",
        encoding="utf-8",
    )

    assert any(m.text == leaked.text for m in measure(raw, out).misses)


def test_a_fragment_of_a_name_is_not_a_miss(tmp_path: Path) -> None:
    """The limit, pinned so that nobody reads the recall as more than it is.

    Half an institution name surviving is a real hazard and this measurement
    will not see it. The scrubber's residual-risk list is the other half of the
    picture, and the README says to read both.
    """
    raw, out = corpus_and_dataset(tmp_path)
    leaked = next(
        span
        for span in read_annotations(raw)
        if span.category is PhiCategory.INSTITUTION and len(span.text) > 12
    )
    document = sorted(out.rglob(f"*{layout.REPORT_TEXT_EXTENSION}"))[0]
    document.write_text(
        document.read_text(encoding="utf-8") + f"{leaked.text[:8]}\n", encoding="utf-8"
    )

    assert measure(raw, out).survived == 0


def test_a_short_span_is_counted_neither_way(tmp_path: Path) -> None:
    """A two-letter name fragment matches inside ordinary words.

    Counting it as survived invents a leak; counting it as removed invents a
    success. It goes in its own bucket and the total says so.
    """
    raw, out = corpus_and_dataset(tmp_path)

    report = measure(raw, out)

    assert report.too_short > 0, "this corpus should contain some short spans"
    for item in report.categories:
        assert item.measurable + item.too_short + item.declared == item.planted
        assert item.removed + item.survived == item.measurable


def test_ages_are_reported_apart_from_the_recall_figure(tmp_path: Path) -> None:
    """They are kept on purpose, so scoring them would measure the opposite."""
    raw, out = corpus_and_dataset(tmp_path)

    report = measure(raw, out)

    assert PhiCategory.AGE in RETAINED_BY_DESIGN
    assert all(item.category is not PhiCategory.AGE for item in report.scored)
    assert any(item.category is PhiCategory.AGE for item in report.categories)


def test_an_empty_category_has_no_recall_rather_than_a_perfect_one(tmp_path: Path) -> None:
    """A rule never exercised has not earned 100%."""
    raw, out = corpus_and_dataset(tmp_path)
    report = measure(raw, out)
    empty = [item for item in report.categories if item.measurable == 0]

    for item in empty:
        assert item.recall is None


def test_a_corpus_without_ground_truth_says_so(tmp_path: Path) -> None:
    """`measure` compares against annotations only this generator writes."""
    (tmp_path / "raw").mkdir()
    (tmp_path / "dataset").mkdir()

    with pytest.raises(FileNotFoundError, match="no ground truth"):
        measure(tmp_path / "raw", tmp_path / "dataset")


def test_the_annotations_are_where_the_generator_puts_them(tmp_path: Path) -> None:
    """Pinned because the two modules agree by convention and not by import."""
    raw, _ = corpus_and_dataset(tmp_path)

    assert (raw / ANNOTATIONS_PATH).is_file()
    assert read_annotations(raw)


def test_the_manifest_carries_no_absolute_path(tmp_path: Path) -> None:
    """Found by measure on its first run, and worth a test of its own.

    The manifest recorded the corpus's full path, which on any ordinary machine
    contains the operator's account name — shipped inside the one document
    written to be read by an access body. A generated clinician called JONATHAN
    is what made it visible.
    """
    _, out = corpus_and_dataset(tmp_path)
    text = (out / layout.DEIDENT_DIR / layout.MANIFEST_JSON).read_text(encoding="utf-8")
    source = json.loads(text)["source"]

    assert source["root_name"] == "raw"
    assert "root" not in source
    assert str(tmp_path) not in text
    assert str(tmp_path).replace("\\", "\\\\") not in text


def test_a_dropped_record_is_counted_apart_from_the_recall(tmp_path: Path) -> None:
    """A record that was never written removes its identifiers by not existing.

    That is no evidence about redaction, and in the degenerate case a build
    that dropped everything would score a perfect recall for producing nothing.
    So the count sits beside the figure rather than inside it.
    """
    raw, out = corpus_and_dataset(tmp_path, defect_rate=0.6, seed=31)

    report = measure(raw, out)

    assert report.records_not_in_dataset > 0, (
        "this seed should trip reports.unreadable_date; without a dropped "
        "record the caveat is untested"
    )


def test_the_caveat_is_zero_when_nothing_was_left_out(tmp_path: Path) -> None:
    raw, out = corpus_and_dataset(tmp_path)

    assert measure(raw, out).records_not_in_dataset == 0


def test_the_caveat_is_zero_without_a_manifest(tmp_path: Path) -> None:
    """`measure` works on a dataset built by an older version, or half-built."""
    raw, out = corpus_and_dataset(tmp_path)
    (out / layout.DEIDENT_DIR / layout.MANIFEST_JSON).unlink()

    assert excluded_record_count(out) == 0
    assert measure(raw, out).records_not_in_dataset == 0


def test_a_damaged_manifest_does_not_stop_the_measurement(tmp_path: Path) -> None:
    """The caveat is a courtesy; losing it must not cost the recall figure."""
    raw, out = corpus_and_dataset(tmp_path)
    (out / layout.DEIDENT_DIR / layout.MANIFEST_JSON).write_text("{ not json", encoding="utf-8")

    assert excluded_record_count(out) == 0
    assert measure(raw, out).recall == 1.0


def test_a_non_numeric_count_is_ignored(tmp_path: Path) -> None:
    """A hand-edited manifest should not make the caveat nonsense."""
    _, out = corpus_and_dataset(tmp_path)
    path = out / layout.DEIDENT_DIR / layout.MANIFEST_JSON
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["source"]["records_not_in_dataset"] = "lots"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert excluded_record_count(out) == 0


def test_declared_values_survives_a_missing_or_damaged_description(tmp_path: Path) -> None:
    """Same reasoning: an exclusion that cannot be read excludes nothing."""
    raw, out = corpus_and_dataset(tmp_path)
    description = out / layout.HEALTHDCAT_DESCRIPTION
    description.write_text("{ not json", encoding="utf-8")

    assert declared_values(out) == frozenset()

    description.unlink()
    assert declared_values(out) == frozenset()
    assert measure(raw, out).recall is not None


def test_a_category_with_nothing_measurable_scores_none_not_perfect() -> None:
    """A rule that was never exercised has not earned 100%.

    The only way to report a perfect score for an empty category is to compute
    ``removed / measurable`` and call ``0 / 0`` a win. Printing 100% there is
    how a corpus that tests nothing comes to look like a corpus that passes,
    which is the opposite of what this command is for.
    """
    empty = CategoryResult(
        category=PhiCategory.CONTACT,
        planted=0,
        measurable=0,
        removed=0,
        survived=0,
        too_short=0,
        declared=0,
    )

    assert empty.recall is None
    assert MeasureReport(categories=(empty,), misses=(), dataset_files=0).recall is None
