"""The two defects that make the identity-conflict paths reachable from a corpus.

Those paths existed from 2026-11-13 and were exercised by unit tests and by
nothing else: every generated corpus reported zero conflicts, because the
generator could not produce one. That is the third time this project has found a
path no corpus reaches — after the shape of the linkage issues, wrong from the
day it was written and never surfaced because every corpus had zero issues, and
the institution address that hid behind a cohort size.

It mattered more here than the count of untested branches suggests, because the
first thing these defects did on a real corpus was expose a manifest that
claimed 32 records were missing from a dataset holding all but 3 of them.

Every identifier here is synthetic.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pytest

from commissura.build.manifest import write_manifest
from commissura.build.writer import BuildSpec, build_dataset
from commissura.deident.keys import SecretKey
from commissura.generate.cohort import CohortSpec
from commissura.generate.defects import BY_ID, DefectClass, Modality
from commissura.generate.writer import write_corpus
from commissura.measure import measure
from commissura.read.corpus import read_corpus
from commissura.read.identity import REASON_KEEPS_RECORD, RefusalReason

KEY = SecretKey(bytes(range(32)))

LAB_CONFLICT = "lab.conflicting_identity"
REPORT_NAME = "reports.wrong_patient_name"


def _corpus(tmp_path: Path, *, rate: float, subjects: int = 25, seed: int = 42) -> Path:
    root = tmp_path / f"raw-{rate}"
    write_corpus(CohortSpec(subjects=subjects, seed=seed, defect_rate=rate), root)
    return root


def _applied(root: Path) -> Counter[str]:
    """Return how many of each defect the generation manifest records."""
    manifest = json.loads(
        (root / "_generator" / "generation_manifest.json").read_text(encoding="utf-8")
    )
    return Counter(entry["defect_id"] for entry in manifest["defects"])


def _paths_for(root: Path, defect_id: str) -> list[str]:
    """Return the corpus files a defect landed in, as the manifest records them."""
    manifest = json.loads(
        (root / "_generator" / "generation_manifest.json").read_text(encoding="utf-8")
    )
    return [e["path"] for e in manifest["defects"] if e["defect_id"] == defect_id]


# --------------------------------------------------------------------------
# The catalogue
# --------------------------------------------------------------------------


@pytest.mark.parametrize("defect_id", [LAB_CONFLICT, REPORT_NAME])
def test_both_defects_are_catalogued_with_a_real_cause(defect_id: str) -> None:
    """The same shape as every other entry, including why it happens.

    ``why_it_happens`` is what keeps the catalogue honest about being drawn from
    practice rather than invented, so a new entry without one is not an entry.
    """
    defect = BY_ID[defect_id]

    assert defect.summary.endswith(".")
    assert len(defect.why_it_happens) > 60
    assert defect.modality in {Modality.LAB, Modality.REPORTS}


def test_the_report_defect_is_classed_as_privacy() -> None:
    """The damage is a name in a document it does not belong to.

    Which is a second patient's identifier sitting in the first one's record —
    not a linkage failure, because the document links perfectly well. It links
    to the wrong person.
    """
    assert BY_ID[REPORT_NAME].defect_class is DefectClass.PRIVACY


def test_the_lab_defect_is_classed_as_linkage() -> None:
    """Each message is internally consistent and they disagree with each other."""
    assert BY_ID[LAB_CONFLICT].defect_class is DefectClass.LINKAGE


# --------------------------------------------------------------------------
# Injection
# --------------------------------------------------------------------------


def test_a_clean_corpus_produces_neither(tmp_path: Path) -> None:
    """``--defect-rate 0`` means a clean corpus, and these are no exception."""
    applied = _applied(_corpus(tmp_path, rate=0.0, subjects=8))

    assert applied[LAB_CONFLICT] == 0
    assert applied[REPORT_NAME] == 0


def test_both_fire_at_the_walkthrough_rate(tmp_path: Path) -> None:
    """The point of the exercise: a path a corpus reaches.

    Pinned at "some" rather than at a number. The count depends on the cohort's
    shape and on the random stream, and a test that pinned it would fail for
    every unrelated change to either.
    """
    applied = _applied(_corpus(tmp_path, rate=0.2))

    assert applied[LAB_CONFLICT] > 0
    assert applied[REPORT_NAME] > 0


def test_each_is_recorded_against_the_file_it_landed_in(tmp_path: Path) -> None:
    """A defect log that does not name the file is not a log.

    It is what turns validator development into a measurable exercise: run the
    reader over the corpus, compare what it reported against what was injected.
    """
    root = _corpus(tmp_path, rate=0.5, subjects=12)

    for defect_id, prefix in ((LAB_CONFLICT, "lab/"), (REPORT_NAME, "reports/")):
        paths = _paths_for(root, defect_id)
        assert paths, defect_id
        assert all(path.startswith(prefix) for path in paths)
        assert all((root / path).is_file() for path in paths)


def test_the_lab_defect_never_lands_on_a_subjects_only_message(tmp_path: Path) -> None:
    """A conflicting identity is a property of a pair, not of either message.

    So the first message a subject has is not an opportunity for one: there is
    nothing for it to disagree with. Checked by confirming every affected file
    belongs to a subject with more than one laboratory message.
    """
    root = _corpus(tmp_path, rate=1.0, subjects=10)
    affected = _paths_for(root, LAB_CONFLICT)
    assert affected

    for path in affected:
        record_number = Path(path).name.split("_")[0]
        siblings = list(root.glob(f"lab/{record_number}_*.hl7"))
        assert len(siblings) > 1, f"{path} is its subject's only message"


def test_the_planted_name_enters_the_ground_truth(tmp_path: Path) -> None:
    """Which is the whole reason the substitution happens before rendering.

    A name planted in a document it does not belong to is a person's identifier
    where it should not be, so ``measure`` has to be able to check that it was
    removed — and that needs its exact character offsets, not a search.
    """
    root = _corpus(tmp_path, rate=1.0, subjects=10)
    annotations = json.loads(
        (root / "_generator" / "phi_annotations.json").read_text(encoding="utf-8")
    )
    affected = set(_paths_for(root, REPORT_NAME))
    assert affected

    names_in_affected = {
        span["text"]
        for span in annotations["spans"]
        if span["path"] in affected and span["category"] == "person_name"
    }
    assert names_in_affected, "the substituted name is not in the ground truth"


# --------------------------------------------------------------------------
# What the reader makes of them
# --------------------------------------------------------------------------


def test_the_reader_reports_both_conflicts(tmp_path: Path) -> None:
    """The quarantine, reached from a generated corpus for the first time."""
    corpus = read_corpus(_corpus(tmp_path, rate=0.2))
    reasons = Counter(issue.reason for issue in corpus.issues)

    assert reasons[RefusalReason.CONFLICTING_IDENTITY.value] > 0
    assert reasons[RefusalReason.CONFLICTING_REPORT_NAME.value] > 0


def test_no_planted_name_survives_anywhere(tmp_path: Path) -> None:
    """Text, manifest and HTML report, measured against the ground truth.

    The HTML report is included because it is the one output that holds
    unredacted material by design, and the question is whether the *redacted*
    half of its comparison is actually redacted.
    """
    from commissura.build.manifest import write_healthdcat_description
    from commissura.build.report import write_report
    from commissura.build.risk import write_risk_report

    raw = _corpus(tmp_path, rate=0.5, subjects=12)
    out = tmp_path / "dataset"
    corpus = read_corpus(raw)
    spec = BuildSpec(dataset_name="d", description="d", hdab="H", publisher="P")
    summary = build_dataset(corpus, KEY, spec, out)
    write_healthdcat_description(out, spec=spec, summary=summary)
    risk = write_risk_report(out)
    manifest = write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=spec, risk=risk)
    page = write_report(
        tmp_path / "review.html",
        corpus=corpus,
        summary=summary,
        manifest=manifest,
        risk=risk,
        destination=out,
    )

    report = measure(raw, out)
    assert report.recall == 1.0, [miss.text for miss in report.misses]

    # The manifest and the page are outside what `measure` walks, so they are
    # checked directly against the same ground truth.
    annotations = json.loads(
        (raw / "_generator" / "phi_annotations.json").read_text(encoding="utf-8")
    )
    planted = {
        span["text"]
        for span in annotations["spans"]
        if span["category"] == "person_name" and len(span["text"]) >= 4
    }
    assert planted
    manifest_text = (out / ".deident" / "manifest.json").read_text(encoding="utf-8")
    # The page holds the unredacted half by design -- that is why it is refused
    # inside the dataset -- so only the <pre class="after"> blocks are checked.
    after_blocks = " ".join(
        re.findall(r'<pre class="after">(.*?)</pre>', page.read_text(encoding="utf-8"), re.S)
    )
    assert after_blocks, "the page produced no after half to check"
    for name in planted:
        assert name.lower() not in manifest_text.lower(), f"{name} in the manifest"
        assert name.lower() not in after_blocks.lower(), f"{name} in the page's after half"


# --------------------------------------------------------------------------
# The count the defects exposed
# --------------------------------------------------------------------------


def test_every_reason_declares_whether_its_record_reached_the_dataset() -> None:
    """Looked up without a default, so a new reason must say which side it is on.

    A manifest that guessed would be worse than a build that stopped, and the
    guess would be in the one document written to be believed.
    """
    assert set(REASON_KEEPS_RECORD) == set(RefusalReason)


def test_a_flagged_record_is_not_counted_as_absent(tmp_path: Path) -> None:
    """The defect these two defects exposed on their first real corpus.

    ``records_not_in_dataset`` counted every linkage issue plus every dropped
    record, on the premise that a linkage issue means a record that could not be
    attached. Three reasons added since attach the record and merely flag it, so
    the number claimed 32 records absent from a dataset holding all but 3.
    """
    raw = _corpus(tmp_path, rate=0.3, subjects=20)
    out = tmp_path / "dataset"
    corpus = read_corpus(raw)
    spec = BuildSpec(dataset_name="d", description="d", hdab="H", publisher="P")
    summary = build_dataset(corpus, KEY, spec, out)
    manifest = write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=spec)
    source = manifest["source"]
    assert isinstance(source, dict)

    flagged = sum(1 for issue in corpus.issues if REASON_KEEPS_RECORD[RefusalReason(issue.reason)])
    refused = len(corpus.issues) - flagged

    assert flagged > 0, "this corpus should produce a flagged record"
    assert source["records_flagged_in_dataset"] == flagged
    assert source["records_not_in_dataset"] == refused + len(summary.dropped)


def test_a_flagged_report_is_published_rather_than_dropped(tmp_path: Path) -> None:
    """Counted and checked rather than asserted: the records really are there.

    Reports are one-to-one between corpus and dataset, unlike laboratory
    messages which collapse into one table per session, so this is the modality
    where the arithmetic can be done directly.
    """
    raw = _corpus(tmp_path, rate=0.5, subjects=12)
    out = tmp_path / "dataset"
    corpus = read_corpus(raw)
    summary = build_dataset(
        corpus,
        KEY,
        BuildSpec(dataset_name="d", description="d", hdab="H", publisher="P"),
        out,
    )

    in_corpus = len(list(raw.glob("reports/*.txt")))
    in_dataset = len(list(out.rglob("*_report.txt")))
    dropped_reports = sum(1 for record in summary.dropped if record.path.startswith("reports/"))

    assert in_dataset == in_corpus - dropped_reports
