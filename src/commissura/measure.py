"""Did the de-identification actually work? Measured against the ground truth.

The generator records every identifier it plants, with the file and the
character offsets where it wrote it. That is a ground truth almost nobody has:
real corpora are annotated by hand, partially, at great expense, and the
annotation is itself uncertain. Here the annotation is a by-product of writing
the text, so it is complete by construction.

Until now nothing compared it to anything. The project's central claim is
"rules first, **measurement always**", and the measurement half was a promise.
This module keeps it: for every planted identifier, does its text still appear
anywhere in the built dataset?

**Anywhere, not in the corresponding file.** A name that escapes from a report
into a JSON sidecar, or into another subject's directory, has leaked just as
surely. The dataset is read as one body of text and every span is looked for in
all of it.

**Three honest exclusions**, each of which would otherwise flatter or distort
the number:

* **Case is ignored.** Matching case-sensitively reported a clean sweep; the
  same corpus matched case-insensitively showed surviving clinician names. A
  name in different case is still the name, and a measurement that misses it is
  worse than none.
* **Spans shorter than :data:`MEASURABLE_LENGTH` are not counted either way.**
  A two-character fragment of a surname such as ``DE`` matches inside
  "de-identification" and would be reported as a leak that is not there.
  Counting them as removed would be the opposite lie. They are reported in
  their own bucket, with the count, so the exclusion is visible rather than
  quiet. The scrubber draws the same line for the same reason: it does not
  substitute by exact match below four characters.
* **Ages are retained on purpose** and are reported apart from the recall
  figure. An age is clinically useful and not identifying on its own below the
  ceiling, so counting a surviving age as a failure would measure the opposite
  of the intended behaviour.

**And one limit that no exclusion can fix.** This asks whether the *exact*
planted string survived. A fragment of it surviving — the tail of a truncated
institution name, say — is not a miss here, and will not be. That question is
answered by the scrubber's residual-risk list, which works the other way round:
it looks at the output for anything that smells like an identifier, without
knowing what was planted. The two measurements fail differently on purpose, and
a reader needs both.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from commissura import layout
from commissura.models import PhiCategory, PhiSpan

MEASURABLE_LENGTH: Final = 4
"""Shortest span this can honestly look for.

The same threshold the scrubber uses for exact-match substitution, and for the
same reason: below it, a string is as likely to be part of an ordinary word as
to be the identifier. Matched to the scrubber deliberately — a measurement that
demanded more than the method attempts would be scoring it against a rule it
was never given.
"""

RETAINED_BY_DESIGN: Final[frozenset[PhiCategory]] = frozenset({PhiCategory.AGE})
"""Categories the dataset is meant to keep, excluded from the recall figure.

Only ages. They are clinically useful, not identifying on their own below the
ceiling, and the build truncates the ones above it. Counting their survival as
a failure would measure the opposite of the intended behaviour -- but hiding
them would be its own dishonesty, so they are counted and reported separately.
"""

ANNOTATIONS_PATH: Final = "_generator/phi_annotations.json"
"""Where the generator writes the ground truth, relative to the corpus root."""


DECLARED_FIELDS: Final[tuple[str, ...]] = (
    "dct:title",
    "dct:description",
)
"""Top-level description fields whose text the holder typed on the command line.

Values that reach the dataset because an operator supplied them did not come
from the input corpus, so finding one is not an identifier surviving. The case
that forces this: a hospital publishing its own data names itself as the
publisher, and its name is also written across every report in the corpus. The
string genuinely appears in the output, and its being there is a disclosure the
holder chose. Reporting it as a leak would be literal and wrong.

Agent names are collected separately, from ``foaf:name`` wherever it appears,
because the publisher and the HDAB are nested nodes rather than top-level
fields.
"""


def excluded_record_count(dataset: Path) -> int:
    """Return how many input records the dataset says it did not include.

    A record that was never written removes its identifiers by not existing,
    which is no evidence that redaction works. In the degenerate case, a build
    that dropped everything would score a perfect recall for having produced
    nothing, so the number belongs beside the recall figure.

    A count and not a list of paths, because the manifest no longer carries the
    paths: an export names its files after the record they hold, so they were
    patient identifiers in a document written to travel. That is also why this
    is a caveat on the whole report rather than an exclusion applied span by
    span — attributing it per span would need exactly the paths that had to go.

    Args:
        dataset: The dataset root.

    Returns:
        The count, or zero when there is no manifest to read.
    """
    path = dataset / layout.DEIDENT_DIR / layout.MANIFEST_JSON
    if not path.is_file():
        return 0
    try:
        source = json.loads(path.read_text(encoding="utf-8")).get("source", {})
    except (OSError, json.JSONDecodeError):
        return 0
    count = source.get("records_not_in_dataset", 0)
    return count if isinstance(count, int) else 0


@dataclass(frozen=True, slots=True)
class Miss:
    """One planted identifier whose text survived into the dataset.

    Attributes:
        path: The corpus file it was planted in.
        start: Character offset of the span in that file.
        end: End offset, half-open.
        text: The identifier itself.
        category: What kind of identifier it is.
        found_in: A dataset file the text was found in, relative to the dataset
            root. One example and not all of them: the first is what somebody
            opens, and a name that leaked into thirty files leaked once.
    """

    path: str
    start: int
    end: int
    text: str
    category: PhiCategory
    found_in: str


@dataclass(frozen=True, slots=True)
class CategoryResult:
    """What became of one category of planted identifier."""

    category: PhiCategory
    planted: int
    measurable: int
    removed: int
    survived: int
    too_short: int
    declared: int

    @property
    def recall(self) -> float | None:
        """Return the share of measurable spans removed, or None if there were none.

        ``None`` rather than 1.0 for an empty category: a rule that was never
        exercised has not earned a perfect score, and printing 100% for it is
        how a corpus that tests nothing comes to look like a corpus that passes.
        """
        if not self.measurable:
            return None
        return self.removed / self.measurable


@dataclass(frozen=True, slots=True)
class MeasureReport:
    """The whole comparison of a corpus's ground truth against a dataset."""

    categories: tuple[CategoryResult, ...]
    misses: tuple[Miss, ...]
    dataset_files: int
    records_not_in_dataset: int = 0

    @property
    def scored(self) -> tuple[CategoryResult, ...]:
        """Return the categories that count toward recall."""
        return tuple(c for c in self.categories if c.category not in RETAINED_BY_DESIGN)

    @property
    def measurable(self) -> int:
        """Return how many spans were both scored and long enough to look for."""
        return sum(c.measurable for c in self.scored)

    @property
    def removed(self) -> int:
        """Return how many scored spans were removed."""
        return sum(c.removed for c in self.scored)

    @property
    def survived(self) -> int:
        """Return how many scored spans survived."""
        return sum(c.survived for c in self.scored)

    @property
    def too_short(self) -> int:
        """Return how many spans were below the measurable length."""
        return sum(c.too_short for c in self.categories)

    @property
    def declared(self) -> int:
        """Return how many spans matched a value the data holder supplied."""
        return sum(c.declared for c in self.categories)

    @property
    def recall(self) -> float | None:
        """Return overall recall over the scored, measurable spans."""
        if not self.measurable:
            return None
        return self.removed / self.measurable


def read_annotations(corpus: Path) -> tuple[PhiSpan, ...]:
    """Load the generator's ground truth for a corpus.

    Args:
        corpus: The raw corpus root.

    Returns:
        Every recorded span.

    Raises:
        FileNotFoundError: If the corpus carries no annotations, which means it
            was not written by this generator and there is nothing to measure
            against.
    """
    path = corpus / ANNOTATIONS_PATH
    if not path.is_file():
        raise FileNotFoundError(
            f"no ground truth at {path}. `measure` compares a dataset against the "
            "annotations `generate` records; a corpus from anywhere else has none."
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    return tuple(PhiSpan.model_validate(span) for span in payload["spans"])


def _pattern(text: str) -> re.Pattern[str]:
    r"""Return a case-insensitive pattern for one identifier.

    Bounded by non-alphanumerics where the text begins or ends with one, so a
    surname does not match inside a longer word. Punctuation-led text, such as a
    leading ``+`` on a telephone number, needs no boundary and must not be given
    one: ``\b`` before ``+`` never matches.

    Args:
        text: The identifier as planted.

    Returns:
        The compiled pattern.
    """
    body = re.escape(text)
    prefix = r"(?<![0-9A-Za-z])" if text[:1].isalnum() else ""
    suffix = r"(?![0-9A-Za-z])" if text[-1:].isalnum() else ""
    return re.compile(prefix + body + suffix, re.IGNORECASE)


def declared_values(dataset: Path) -> frozenset[str]:
    """Return the strings the data holder supplied, folded to lower case.

    Read from the dataset's own Article 77 description, which is where those
    values land, so the dataset says which strings were typed rather than
    derived. Absent description, nothing is excluded.

    Args:
        dataset: The dataset root.

    Returns:
        The declared strings, lower-cased for comparison.
    """
    path = dataset / layout.HEALTHDCAT_DESCRIPTION
    if not path.is_file():
        return frozenset()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return frozenset()

    found: set[str] = set()

    def walk(node: object, key: str = "") -> None:
        if isinstance(node, dict):
            for name, value in node.items():
                walk(value, name)
        elif isinstance(node, list):
            for value in node:
                walk(value, key)
        elif isinstance(node, str) and (key in DECLARED_FIELDS or key == "foaf:name"):
            found.add(node.strip().lower())

    walk(payload)
    return frozenset(value for value in found if value)


def _dataset_text(dataset: Path) -> dict[str, str]:
    """Read every file in the dataset as text, keyed by relative path.

    Args:
        dataset: The dataset root.

    Returns:
        Path to content. Undecodable bytes are replaced rather than skipped: a
        file this cannot read is still a file an identifier could be hiding in,
        and dropping it would quietly shrink the haystack.
    """
    return {
        path.relative_to(dataset).as_posix(): path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(dataset.rglob("*"))
        if path.is_file()
    }


def measure(corpus: Path, dataset: Path) -> MeasureReport:
    """Compare a corpus's planted identifiers against the dataset built from it.

    Args:
        corpus: The raw corpus root, holding the generator's annotations.
        dataset: The built dataset root.

    Returns:
        The report, with one row per category and a miss for every identifier
        whose text survived.

    Raises:
        FileNotFoundError: If the corpus carries no ground truth.
    """
    spans = read_annotations(corpus)
    contents = _dataset_text(dataset)
    holder_declared = declared_values(dataset)
    records_not_in_dataset = excluded_record_count(dataset)

    planted: Counter[PhiCategory] = Counter()
    short: Counter[PhiCategory] = Counter()
    declared: Counter[PhiCategory] = Counter()
    survived: Counter[PhiCategory] = Counter()
    misses: list[Miss] = []

    # The whole dataset as one string, searched once per *distinct* identifier.
    #
    # Searching every span against every file made the work grow with the
    # square of the cohort: spans grow with it and so do files. Measured on
    # eight subjects, 91,519 searches and 2.0 seconds; on sixty, 3,891,711 and
    # 60.4 seconds. Seven times the subjects, thirty times the time, which puts
    # a few hundred subjects out of reach — on the command that carries this
    # project's central claim, and so the one somebody would actually run on a
    # real cohort.
    #
    # Two changes, both resting on the same fact: almost nothing is found,
    # because that is what success looks like here. The joined text answers
    # "does this survive anywhere" in one search instead of one per file, and
    # the per-file scan below runs only for the rare span that *is* found, to
    # say which file. The cache collapses repeats: one institution name is
    # planted 170 times in a corpus and searching for it once is enough. Sixty
    # subjects: 1,794 searches and 13.9 seconds, same answer.
    joined = "\n".join(contents.values())
    seen: dict[str, bool] = {}

    for span in spans:
        planted[span.category] += 1
        if len(span.text) < MEASURABLE_LENGTH:
            short[span.category] += 1
            continue
        if span.text.strip().lower() in holder_declared:
            declared[span.category] += 1
            continue
        if span.text not in seen:
            seen[span.text] = _pattern(span.text).search(joined) is not None
        if not seen[span.text]:
            continue
        pattern = _pattern(span.text)
        found = next((name for name, text in contents.items() if pattern.search(text)), None)
        if found is None:  # pragma: no cover - the joined text said it is there
            continue
        survived[span.category] += 1
        misses.append(
            Miss(
                path=span.path,
                start=span.start,
                end=span.end,
                text=span.text,
                category=span.category,
                found_in=found,
            )
        )

    categories = []
    for category in sorted(planted, key=lambda c: c.value):
        total = planted[category]
        too_short = short[category]
        holder = declared[category]
        measurable = total - too_short - holder
        categories.append(
            CategoryResult(
                category=category,
                planted=total,
                measurable=measurable,
                removed=measurable - survived[category],
                survived=survived[category],
                too_short=too_short,
                declared=holder,
            )
        )

    return MeasureReport(
        categories=tuple(categories),
        misses=tuple(misses),
        dataset_files=len(contents),
        records_not_in_dataset=records_not_in_dataset,
    )
