r"""Write a generated corpus to disk, with its manifest and ground truth.

The corpus is laid out as three separate exports:

    raw/
      lab/         ORU^R01 messages
      reports/     free text
      imaging/     DICOM JSON Model metadata
      _generator/
        generation_manifest.json
        phi_annotations.json

That shape is a claim about the problem, not a filing convenience. Clinical data
arrives as separate per-modality dumps from separate systems, with no shared
subject key and no guarantee the three agree about who the patient is. Laying
the corpus out per subject would quietly do the hard part — linkage — before the
tool under test gets a chance to.

**One platform trap, disarmed here.** Python's text mode translates ``\n`` to
``\r\n`` on Windows. For this project that is not a cosmetic difference: it
would shift every character offset after the first newline, so every recorded
PHI span would point at the wrong text, and the corpus would score a perfect
de-identifier as broken. It would also corrupt the HL7 messages, whose segments
are already terminated with a bare ``\r``. Every write here therefore passes
``newline=""`` to disable translation, and the test suite re-reads the files from
disk and re-checks the spans, so the protection cannot rot unnoticed.
"""

from __future__ import annotations

import json
import platform
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from random import Random

from commissura import __version__
from commissura.annotate import check_spans
from commissura.generate import vocabulary
from commissura.generate.cda import render_lab_cda
from commissura.generate.cohort import CohortSpec, PlannedSubject, build_cohort, child_seed
from commissura.generate.defects import DefectInjector
from commissura.generate.imaging import render_study
from commissura.generate.labs import render_panel
from commissura.generate.reports import render_report
from commissura.models import (
    AppliedDefect,
    GenerationManifest,
    ModalityCounts,
    Person,
    PhiSpan,
    ReportKind,
    Sex,
)
from commissura.read.corpus import read_exact

ANNOTATION_SCHEMA_VERSION = "1.0.0"
"""Schema version of ``phi_annotations.json``.

Separate from the manifest's own version because the two files will not change
together, and a consumer needs to know which one it is reading.
"""


@dataclass(frozen=True, slots=True)
class CorpusSummary:
    """What a generation run produced."""

    root: Path
    manifest: GenerationManifest
    spans: tuple[PhiSpan, ...]

    @property
    def file_count(self) -> int:
        """Return the number of clinical files written, excluding metadata."""
        counts = self.manifest.files
        return counts.lab + counts.cda + counts.reports + counts.imaging


def _another_name(rng: Random, person: Person, *, surname_only: bool = False) -> Person:
    """Return the same person with somebody else's name on them.

    Everything that identifies the record is kept — the codice fiscale, the
    record number, the address, the birth date — so the document still links to
    the subject it was always about. Only the name differs, which is what makes
    this a *conflict* rather than an unrelated document: two sources agreeing on
    the identifier and disagreeing on the person.

    The substituted name goes through the same :class:`~commissura.annotate.Phi`
    wrapping as any other, so it lands in the ground truth automatically. That
    is the point of doing it this way rather than editing the rendered text: a
    name planted in a document it does not belong to is a person's identifier
    where it should not be, and ``commissura measure`` has to be able to check
    that it was removed.

    Args:
        rng: Seeded random source.
        person: The subject the document belongs to.
        surname_only: Replace the family name alone, which is the shape a
            mistyped codice fiscale takes — the given name is usually right
            because whoever typed it was looking at the right patient.

    Returns:
        A copy with a different name and every identifier unchanged.
    """
    family = rng.choice([n for n in vocabulary.FAMILY_NAMES if n != person.family_name])
    if surname_only:
        return person.model_copy(update={"family_name": family})
    pool = (
        vocabulary.GIVEN_NAMES_FEMALE if person.sex is Sex.FEMALE else vocabulary.GIVEN_NAMES_MALE
    )
    given = rng.choice([n for n in pool if n != person.given_name])
    return person.model_copy(update={"family_name": family, "given_name": given})


def _another_clinician(rng: Random, besides: str) -> str:
    """Return a clinician name that is not the one given.

    A CDA document names the clinician who created it and the clinician who
    legally signed it, in two different elements, and the signer is the one a
    plain-text report declares nowhere except its signature line. If the two
    coincided, a corpus could not show whether the reader found the second
    element at all — the same reasoning that gave one generated site a legacy
    PID-19 interface.

    Args:
        rng: Seeded random source.
        besides: The name to avoid.

    Returns:
        A different name, in the same ``FAMILY GIVEN`` form.
    """
    family = rng.choice([n for n in vocabulary.FAMILY_NAMES if not besides.startswith(n)])
    given = rng.choice(vocabulary.GIVEN_NAMES_MALE + vocabulary.GIVEN_NAMES_FEMALE)
    return f"{family} {given}"


def _write_text(path: Path, content: str) -> None:
    """Write text with no newline translation, creating parent directories.

    Args:
        path: Destination.
        content: Exact characters to write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # newline="" is load-bearing: see this module's docstring.
    path.write_text(content, encoding="utf-8", newline="")


def _write_json(path: Path, payload: object) -> None:
    """Write pretty-printed UTF-8 JSON with no newline translation.

    ``ensure_ascii=False`` keeps accented characters as themselves rather than
    as escapes, which matters because the offsets recorded elsewhere are
    character offsets into the decoded text.

    Args:
        path: Destination.
        payload: Any JSON-serialisable object.
    """
    _write_text(path, json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n")


def _render_subject(
    planned: PlannedSubject,
    *,
    root: Path,
    spec: CohortSpec,
) -> tuple[list[PhiSpan], list[AppliedDefect], ModalityCounts]:
    """Render and write every file for one subject.

    The subject gets its own defect injector, seeded from the master seed and
    the subject index. That is what keeps subject *n* independent of how many
    subjects were requested: a shared injector would couple them through its
    random stream.

    Args:
        planned: The subject and its rendering context.
        root: Corpus root directory.
        spec: The cohort specification.

    Returns:
        The spans recorded, the defects injected, and the per-modality counts.
    """
    person = planned.subject.person
    injector = DefectInjector(
        Random(child_seed(spec.seed, f"defects|{planned.index}")),
        spec.defect_rate,
    )
    render_rng = Random(child_seed(spec.seed, f"render|{planned.index}"))

    spans: list[PhiSpan] = []
    counts = {"lab": 0, "cda": 0, "imaging": 0, "reports": 0}
    study_dates = sorted(study.study_date for study in planned.subject.studies)

    # --- Laboratory ---
    for position, panel in enumerate(planned.subject.panels):
        source = "cda" if spec.cda else "lab"
        extension = "xml" if spec.cda else "hl7"
        relative = f"{source}/{person.mrn}_{panel.accession}.{extension}"
        # A conflicting identity is a property of a *pair* of messages, not of
        # either one alone, so the first message is not an opportunity for one:
        # there is nothing for it to disagree with. The draw still happens for
        # every panel, which keeps the random stream stable against the shape
        # of a cohort, and only a draw that is actually used is recorded.
        speaking_for = person
        if injector.should_apply("lab.conflicting_identity") and position > 0:
            speaking_for = _another_name(render_rng, person, surname_only=True)
            injector.record(
                "lab.conflicting_identity",
                relative,
                f"PID-5 family name replaced with {speaking_for.family_name!r}: "
                "this message and the subject's others claim one codice fiscale "
                "for two people",
            )
        control_id = (
            planned.control_ids[position]
            if position < len(planned.control_ids)
            else f"MSG{planned.index:05d}{position:04d}"
        )
        if spec.cda:
            # A CDA document may cite an earlier examination, the same way a
            # radiology report does. Only one that actually precedes it: a
            # comparison the generator invented would make the corpus
            # internally inconsistent in a way nothing records.
            earlier_studies = [moment for moment in study_dates if moment < panel.collected_at]
            content, panel_spans = render_lab_cda(
                panel,
                person=speaking_for,
                site=planned.site,
                path=relative,
                document_id=control_id,
                signed_by=_another_clinician(render_rng, panel.ordering_provider),
                injector=injector,
                previous_study_date=earlier_studies[-1] if earlier_studies else None,
                previous_site=planned.previous_site if earlier_studies else None,
            )
        else:
            content, panel_spans = render_panel(
                panel,
                person=speaking_for,
                site=planned.site,
                path=relative,
                control_id=control_id,
                injector=injector,
            )
        _write_text(root / relative, content)
        spans.extend(panel_spans)
        counts[source] += 1

        # A retried interface delivers the same message twice. In an export that
        # shows up as a second file with the same accession number.
        if injector.should_apply("lab.duplicate_message"):
            duplicate = f"{source}/{person.mrn}_{panel.accession}_2.{extension}"
            injector.record(
                "lab.duplicate_message",
                duplicate,
                f"byte-identical copy of {relative}, same accession {panel.accession}",
            )
            _write_text(root / duplicate, content)
            spans.extend(span.model_copy(update={"path": duplicate}) for span in panel_spans)
            counts[source] += 1

    # --- Imaging ---
    for study in planned.subject.studies:
        relative = f"imaging/{person.mrn}_{study.accession}.json"
        content, study_spans = render_study(study, person=person, path=relative, injector=injector)
        _write_text(root / relative, content)
        spans.extend(study_spans)
        counts["imaging"] += 1

    # --- Reports ---
    for position, report in enumerate(planned.subject.reports, start=1):
        kind = "rad" if report.kind is ReportKind.RADIOLOGY else "dim"
        relative = f"reports/{person.mrn}_{kind}_{position}.txt"
        # A report can refer in prose to an earlier study, but only if one
        # actually precedes it. Inventing a comparison that never happened would
        # make the corpus internally inconsistent in a way nothing records.
        earlier = [moment for moment in study_dates if moment < report.authored_at]
        named_in_header = person
        if injector.apply(
            "reports.wrong_patient_name",
            relative,
            "the Paziente header names somebody other than the subject this "
            "document links to by codice fiscale and record number",
        ):
            named_in_header = _another_name(render_rng, person)
        content, report_spans = render_report(
            report,
            person=named_in_header,
            site=planned.site,
            path=relative,
            rng=render_rng,
            injector=injector,
            previous_study_date=earlier[-1] if earlier else None,
            previous_site=planned.previous_site if earlier else None,
        )
        _write_text(root / relative, content)
        spans.extend(report_spans)
        counts["reports"] += 1

    return (
        spans,
        list(injector.applied()),
        ModalityCounts(
            lab=counts["lab"],
            cda=counts["cda"],
            reports=counts["reports"],
            imaging=counts["imaging"],
        ),
    )


def write_corpus(spec: CohortSpec, root: Path) -> CorpusSummary:
    """Generate a corpus and write it, with its manifest and ground truth.

    Args:
        spec: What to generate.
        root: Directory to write into. Created if absent.

    Returns:
        A summary of what was written.
    """
    root = root.resolve()
    planned = build_cohort(spec)

    all_spans: list[PhiSpan] = []
    all_defects: list[AppliedDefect] = []
    totals = {"lab": 0, "cda": 0, "reports": 0, "imaging": 0}

    for subject in planned:
        spans, defects, counts = _render_subject(subject, root=root, spec=spec)
        all_spans.extend(spans)
        all_defects.extend(defects)
        totals["lab"] += counts.lab
        totals["cda"] += counts.cda
        totals["reports"] += counts.reports
        totals["imaging"] += counts.imaging

    manifest = GenerationManifest(
        tool_version=__version__,
        python_version=f"{platform.python_implementation()} {sys.version.split()[0]}",
        generated_at=datetime.now(UTC),
        seed=spec.seed,
        subject_count=spec.subjects,
        files=ModalityCounts(
            lab=totals["lab"],
            cda=totals["cda"],
            reports=totals["reports"],
            imaging=totals["imaging"],
        ),
        phi_span_count=len(all_spans),
        defects=tuple(all_defects),
    )

    metadata = root / "_generator"
    _write_json(metadata / "generation_manifest.json", manifest.model_dump(mode="json"))
    _write_json(
        metadata / "phi_annotations.json",
        {
            "schema_version": ANNOTATION_SCHEMA_VERSION,
            "note": (
                "Ground truth for de-identification scoring. Offsets are character "
                "positions into the UTF-8 decoded file, half-open, so "
                "text == content[start:end]."
            ),
            "spans": [span.model_dump(mode="json") for span in all_spans],
        },
    )

    return CorpusSummary(root=root, manifest=manifest, spans=tuple(all_spans))


def verify_corpus(summary: CorpusSummary) -> None:
    """Re-read every annotated file and confirm the spans still match.

    Checking against the files rather than against the in-memory text is the
    point: it catches newline translation, encoding mistakes and anything else
    that happens between rendering and disk — the failures that would silently
    invalidate every measurement made on this corpus.

    Args:
        summary: The result of :func:`write_corpus`.

    Raises:
        AssertionError: If any span no longer quotes the text it points at.
    """
    by_path: dict[str, list[PhiSpan]] = {}
    for span in summary.spans:
        by_path.setdefault(span.path, []).append(span)

    for relative, spans in by_path.items():
        content = read_exact(summary.root / relative)
        check_spans(content, tuple(spans))
