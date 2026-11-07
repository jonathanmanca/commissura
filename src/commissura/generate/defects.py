"""The catalogue of defects the generator can inject, and the injector itself.

A generator that only produces clean data is of limited use. Real exports
arrive broken in specific, recurring ways, and a validator that has never seen
those ways will pass them. This module enumerates the breakage so that
``commissura validate`` can be developed against it.

The design point worth noticing: injection is **recorded, not random in
effect**. Every defect the injector applies is appended to a log naming the
defect and the file it landed in. That log goes into the generation manifest,
which turns validator development into a measurable exercise — run the
validator over a corpus, compare what it reported against what was injected,
and read off the misses directly. Without the log you are left inspecting output
by hand and hoping.

Defects are grouped by the kind of damage they do, because that is what
determines who has to deal with them:

- **Structural** breakage violates the format. A parser can refuse the file.
- **Semantic** breakage parses cleanly but means something wrong. Only a domain
  rule catches it.
- **Linkage** breakage is the expensive one: each modality is internally
  consistent, and they disagree with each other. This is the class of problem
  that makes multimodal datasets hard, and the reason this project exists.
- **Privacy** breakage puts an identifier somewhere a scrubber is unlikely to
  look. These are the defects that make the ground-truth annotations earn their
  keep.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from random import Random

from commissura.models import AppliedDefect


class DefectClass(StrEnum):
    """What kind of damage a defect does."""

    STRUCTURAL = "structural"
    SEMANTIC = "semantic"
    LINKAGE = "linkage"
    PRIVACY = "privacy"


class Modality(StrEnum):
    """Which modality a defect applies to."""

    LAB = "lab"
    REPORTS = "reports"
    IMAGING = "imaging"


@dataclass(frozen=True, slots=True)
class Defect:
    """One named, documented way that clinical data arrives broken.

    Attributes:
        defect_id: Stable identifier. Referenced from manifests and from tests,
            so it must not change once released.
        modality: Where the defect can occur.
        defect_class: The kind of damage done.
        summary: One line, written for whoever has to fix the data.
        why_it_happens: The real-world cause. This is the part that justifies
            including the defect at all, and keeps the catalogue honest about
            being drawn from practice rather than invented.
    """

    defect_id: str
    modality: Modality
    defect_class: DefectClass
    summary: str
    why_it_happens: str


CATALOGUE: tuple[Defect, ...] = (
    # ----- Laboratory -----
    Defect(
        "lab.missing_unit",
        Modality.LAB,
        DefectClass.SEMANTIC,
        "OBX-6 is empty: a numeric result arrives with no unit of measure.",
        "Legacy analysers report into fields the interface was never configured "
        "to populate. The number is right and completely unusable.",
    ),
    Defect(
        "lab.missing_reference_range",
        Modality.LAB,
        DefectClass.SEMANTIC,
        "OBX-7 is empty: no reference interval, so the result cannot be interpreted.",
        "Reference intervals are often held in the analyser rather than the LIS "
        "and are dropped at the interface boundary.",
    ),
    Defect(
        "lab.nonstandard_date_format",
        Modality.LAB,
        DefectClass.STRUCTURAL,
        "A timestamp uses DD/MM/YYYY where HL7 requires YYYYMMDDHHMMSS.",
        "Hand-built interfaces format dates for human readers. Parsers that "
        "accept it silently guess at the day and month.",
    ),
    Defect(
        "lab.impossible_value",
        Modality.LAB,
        DefectClass.SEMANTIC,
        "A result is physiologically impossible, such as a negative haemoglobin.",
        "Unit confusion, a misplaced decimal, or a sentinel value like -999 used "
        "to mean 'not measured' and never translated.",
    ),
    Defect(
        "lab.duplicate_message",
        Modality.LAB,
        DefectClass.STRUCTURAL,
        "The same result message appears twice with the same accession number.",
        "Interface retries after a timeout. The receiver acknowledged but the "
        "acknowledgement was lost, so the sender sent it again.",
    ),
    Defect(
        "lab.missing_segment",
        Modality.LAB,
        DefectClass.STRUCTURAL,
        "The PV1 visit segment is absent, so the result has no encounter context.",
        "Outpatient orders placed outside the admission workflow never acquire a "
        "visit record to point at.",
    ),
    Defect(
        "lab.unknown_code",
        Modality.LAB,
        DefectClass.SEMANTIC,
        "The observation is identified by a local code with no LOINC mapping.",
        "Local codes outnumber mapped ones in most laboratories. Unmapped "
        "analytes are invisible to any cross-site query.",
    ),
    # ----- Reports -----
    Defect(
        "reports.truncated",
        Modality.REPORTS,
        DefectClass.STRUCTURAL,
        "The report text stops mid-sentence.",
        "A fixed-width database column, or an export that counted bytes while "
        "the text was multi-byte UTF-8.",
    ),
    Defect(
        "reports.identifier_in_prose",
        Modality.REPORTS,
        DefectClass.PRIVACY,
        "An identifier is written inside a clinical sentence, not in a header field.",
        "Dictation. 'Confronto con l'esame del 12/03/2023 eseguito presso...' is "
        "normal clinical writing, and field-based scrubbing never sees it.",
    ),
    Defect(
        "reports.missing_author",
        Modality.REPORTS,
        DefectClass.STRUCTURAL,
        "The report has no signing clinician.",
        "Unsigned preliminary reports get exported alongside final ones.",
    ),
    # ----- Imaging -----
    Defect(
        "imaging.phi_in_series_description",
        Modality.IMAGING,
        DefectClass.PRIVACY,
        "The patient name is embedded in SeriesDescription (0008,103E).",
        "A technologist typed the name into a free-text protocol field at the "
        "console. The field is not on anyone's list of identifiers to remove.",
    ),
    Defect(
        "imaging.phi_in_private_tag",
        Modality.IMAGING,
        DefectClass.PRIVACY,
        "An identifier sits in a vendor private tag.",
        "The single most commonly missed hiding place. Private blocks are "
        "undocumented, vendor-specific, and routinely retained because removing "
        "them can break the vendor's own post-processing.",
    ),
    Defect(
        "imaging.burned_in_annotation",
        Modality.IMAGING,
        DefectClass.PRIVACY,
        "BurnedInAnnotation is YES: identifiers are rendered into the pixels.",
        "Screen captures, dose reports and ultrasound frames carry the name in "
        "the image itself. No header-level scrubber can reach it; this requires "
        "pixel inspection, and for head imaging, defacing.",
    ),
    Defect(
        "imaging.mrn_format_drift",
        Modality.IMAGING,
        DefectClass.LINKAGE,
        "PatientID drops the zero padding used by the laboratory export.",
        "The RIS and the LIS store the same number with different padding. "
        "A naive join loses every affected subject without reporting an error.",
    ),
    Defect(
        "imaging.name_mismatch",
        Modality.IMAGING,
        DefectClass.LINKAGE,
        "The patient name is spelled differently from the laboratory export.",
        "Manual re-entry at the modality console: an abbreviated given name, a "
        "missing accent, a transposed pair of letters.",
    ),
    Defect(
        "imaging.missing_study_description",
        Modality.IMAGING,
        DefectClass.SEMANTIC,
        "StudyDescription is empty, so the study cannot be classified.",
        "Studies started from a blank protocol rather than a scheduled order.",
    ),
)

BY_ID: dict[str, Defect] = {defect.defect_id: defect for defect in CATALOGUE}
"""Index for looking a defect up by identifier."""


def defects_for(modality: Modality) -> tuple[Defect, ...]:
    """Return every catalogued defect that applies to ``modality``."""
    return tuple(d for d in CATALOGUE if d.modality is modality)


class DefectInjector:
    """Decides which defects to apply, and records every decision.

    One injector is shared across a whole generation run so that the log is
    complete and the random draws come from a single seeded stream.

    The rate is expressed per *opportunity*, not per file: each defect is
    considered independently wherever it could apply. A rate of ``0.0`` produces
    a clean corpus, which is the right default for a first look at the output,
    and ``1.0`` produces a corpus that is maximally hostile to a validator,
    which is the right input for testing one.
    """

    __slots__ = ("_applied", "_rate", "_rng")

    def __init__(self, rng: Random, rate: float) -> None:
        """Create an injector.

        Args:
            rng: Seeded random source, shared with the rest of the run.
            rate: Probability in ``[0.0, 1.0]`` that any given opportunity is
                taken.

        Raises:
            ValueError: If ``rate`` lies outside the unit interval.
        """
        if not 0.0 <= rate <= 1.0:
            raise ValueError(f"defect rate must be between 0 and 1, got {rate}")
        self._rng = rng
        self._rate = rate
        self._applied: list[AppliedDefect] = []

    @property
    def rate(self) -> float:
        """Return the configured per-opportunity injection rate."""
        return self._rate

    def should_apply(self, defect_id: str) -> bool:
        """Draw once to decide whether a defect fires at this opportunity.

        The draw happens even when the rate is zero, so that changing the rate
        does not shift every later random value and invalidate a corpus
        generated from the same seed. Keeping the random stream stable against
        configuration changes is what makes two runs comparable.

        Args:
            defect_id: Catalogue identifier, validated to catch typos early.

        Returns:
            Whether the caller should apply the defect.

        Raises:
            KeyError: If ``defect_id`` is not in the catalogue.
        """
        if defect_id not in BY_ID:
            raise KeyError(f"unknown defect id: {defect_id!r}")
        return self._rng.random() < self._rate

    def record(self, defect_id: str, path: str, detail: str) -> None:
        """Log that a defect was applied to a file.

        Args:
            defect_id: Catalogue identifier.
            path: Corpus-relative path of the affected file.
            detail: What was actually done, specific enough to verify by hand.

        Raises:
            KeyError: If ``defect_id`` is not in the catalogue.
        """
        if defect_id not in BY_ID:
            raise KeyError(f"unknown defect id: {defect_id!r}")
        self._applied.append(AppliedDefect(defect_id=defect_id, path=path, detail=detail))

    def apply(self, defect_id: str, path: str, detail: str) -> bool:
        """Draw, and record the defect if it fires.

        Convenience for the common case where the caller wants to branch on the
        outcome and log at the same time::

            if injector.apply("lab.missing_unit", path, "OBX-6 cleared"):
                unit = ""

        Args:
            defect_id: Catalogue identifier.
            path: Corpus-relative path of the affected file.
            detail: What was done.

        Returns:
            Whether the defect fired.
        """
        if self.should_apply(defect_id):
            self.record(defect_id, path, detail)
            return True
        return False

    def applied(self) -> tuple[AppliedDefect, ...]:
        """Return everything injected so far, in order of application."""
        return tuple(self._applied)
