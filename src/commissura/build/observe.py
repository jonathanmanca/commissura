"""What the input actually contained, field by field, and what became of it.

The manifest used to answer *what was removed from each modality* from a static
table. That table stated the **intent** of the rules: it said PID-5 was removed
whether or not any message carried a PID-5, and it could not say how many did.
Intent and reality had also already drifted apart in two places. The table
claimed PID-3 was *replaced* by the subject label, and that the laboratory
accession was pseudonymised; in fact the medical record number is read for
linkage and then dropped, and the laboratory accession never reaches the dataset
at all.

This module derives the answer, and the shape of the pipeline is what makes that
possible. **The build carries a whitelist, not a blacklist.** The laboratory
branch writes nine columns, the imaging branch seven keys, and everything else
in the input is dropped by never being copied. So a field's disposition follows
from one short declaration -- which input fields are carried, and whether they
pass through the pseudonymiser -- joined to an observation of which fields the
input actually held:

* observed, and not carried, means **removed**;
* carried through the pseudonymiser means **replaced**;
* carried verbatim means **kept**.

Nothing has to be listed in order to be reported as removed, which is the part a
static table cannot get right: it can only account for what somebody remembered
to write down. Here a field nobody anticipated appears in the manifest as
removed, with a count, because it was in the input.

Free text is the exception and is treated as one. A report has labelled headers,
which are fields and are observed here, and a body, which is not. What happened
to the body is measured by the scrubber, per document and per category, and the
manifest records those counts beside this table rather than paraphrasing them.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from commissura.read.corpus import RAW_SOURCES, read_exact
from commissura.read.hl7 import parse_message

Disposition = Literal["removed", "replaced", "kept"]
"""What became of one input field.

Three values and no fourth. A fourth such as "transformed" would hide the
distinction an auditor needs: a replaced value is still derived from the
original and is relinkable by whoever holds the key, while a kept value *is* the
original.
"""


@dataclass(frozen=True, slots=True)
class Carried:
    """One input field that the build carries into the dataset.

    Attributes:
        disposition: ``replaced`` if the value passes through the pseudonymiser,
            ``kept`` if it reaches the dataset as it was.
        note: Where it lands and in what form, for whoever reads the manifest.
    """

    disposition: Disposition
    note: str


CARRIED_FIELDS: Final[dict[str, dict[str, Carried]]] = {
    "lab": {
        "PID-7": Carried(
            "replaced",
            "date of birth, as an age band in participants.tsv truncated at the age ceiling",
        ),
        "PID-8": Carried("kept", "administrative sex, in participants.tsv"),
        "PID-19": Carried(
            "replaced",
            "national identifier, as the HMAC-derived subject label; the key "
            "never enters the dataset",
        ),
        "OBR-4": Carried("kept", "panel code, in the lab table's panel_code column"),
        "OBR-7": Carried(
            "replaced",
            "collection timestamp, as day_offset from the subject's baseline",
        ),
        "OBX-3": Carried("kept", "LOINC code and display name"),
        "OBX-5": Carried("kept", "the measured value as the laboratory reported it"),
        "OBX-6": Carried("kept", "units"),
        "OBX-7": Carried("kept", "reference range, split into low and high"),
        "OBX-8": Carried("kept", "abnormal flag"),
    },
    "reports": {
        "Data del referto": Carried(
            "replaced", "report date, as day_offset from the subject's baseline"
        ),
        "Eta": Carried(
            "kept",
            "age in years, clinically useful and not identifying on its own; the "
            "date of birth it was computed from is removed",
        ),
    },
    # The notes here do not repeat the tag's keyword, which ``name`` already
    # carries: a value printed twice in one row is a value that can disagree
    # with itself.
    "imaging": {
        "00080020": Carried("replaced", "as day_offset from the subject's baseline"),
        "00080050": Carried("replaced", "as an HMAC-derived value"),
        "00080060": Carried("kept", "describes the study, not the person"),
        "0020000D": Carried("replaced", "as an HMAC-derived UID under the 2.25 arc"),
        "0020000E": Carried("replaced", "as an HMAC-derived UID under the 2.25 arc"),
        "00280301": Carried("kept", "so a reader knows the pixels were not inspected"),
    },
}
"""Every input field the build carries, and nothing else.

Short by design, and short because the pipeline is a whitelist. It is declared
rather than observed for one reason: whether a carried value passed through the
pseudonymiser is a fact about the code, not about the data. Two values can look
equally unlike their originals and only one of them be relinkable.

``PID-3`` is deliberately absent. The medical record number is what links an
imaging study to a person; it is read for exactly that and then dropped, so it
is removed rather than replaced. ``00100020`` PatientID is absent for the same
reason. Both were described the other way round in the static table this
replaces.
"""

_HEADER_LABEL: Final = re.compile(r"(?:^|(?<=  ))([A-Za-z][\w/ ]{0,28}?):[ \t]", re.MULTILINE)
"""A labelled field in a free-text report, such as ``Paziente:``.

Matched generically rather than against a list of expected labels, so that a
label the rules do not govern still appears in the manifest as removed. A list
would only ever report the labels somebody had already thought of, which is the
failure this module exists to end.

Two labels can share a line -- the generated reports write ``Nato/a il:`` and
``Eta:`` side by side -- so a label may begin either at the start of a line or
after the run of spaces that separates it from the previous value. Anchoring on
line starts alone found the first of that pair and missed the second, which this
module reported honestly as a field carried in zero files, and which is how the
omission was noticed.
"""

_REDACTED_REPORT_LABELS: Final[frozenset[str]] = frozenset(
    {"Paziente", "Codice fiscale", "Numero nosografico", "Nato/a il"}
)
"""Report labels this project knows and removes, so they can be named.

Together with the carried labels these are the headers the pipeline actually
understands. Naming them is safe because they are the *label*, chosen by this
project's own template, and not the value beside it. Anything else is counted
under :data:`UNDECLARED_LABELS` rather than printed, because in free text a
"label" can be a person's name.

Listed here rather than read from `read.corpus._REPORT_LABELS` because that
table maps labels to the fields linkage needs, while this is the set the field
table may print. They overlap today and need not: a label can be understood and
removed without being something linkage uses.
"""

_EXTENSION_OF: Final[dict[str, str]] = {
    "lab": "HL7 v2 field",
    "reports": "report header label",
    "imaging": "DICOM tag",
}
"""What a key means in each modality, so the manifest can say so."""

DICOM_KEYWORDS: Final[dict[str, str]] = {
    "00080020": "StudyDate",
    "00080030": "StudyTime",
    "00080050": "AccessionNumber",
    "00080060": "Modality",
    "00080070": "Manufacturer",
    "00080080": "InstitutionName",
    "00080081": "InstitutionAddress",
    "00080090": "ReferringPhysicianName",
    "0008103E": "SeriesDescription",
    "00081010": "StationName",
    "00081030": "StudyDescription",
    "00081050": "PerformingPhysicianName",
    "00081090": "ManufacturerModelName",
    "00100010": "PatientName",
    "00100020": "PatientID",
    "00100030": "PatientBirthDate",
    "00100040": "PatientSex",
    "00101010": "PatientAge",
    "00180015": "BodyPartExamined",
    "00181000": "DeviceSerialNumber",
    "00181030": "ProtocolName",
    "0020000D": "StudyInstanceUID",
    "0020000E": "SeriesInstanceUID",
    "00200011": "SeriesNumber",
    "00201209": "NumberOfSeriesRelatedInstances",
    "00280301": "BurnedInAnnotation",
}
"""Keywords for the DICOM tags this project knows, so the manifest reads.

A tag number alone is unreadable, and losing the keyword would make this table
worse than the static one it replaces for the only person who will read it. But
a full data dictionary is not the answer either: the point of observing is to
report tags nobody anticipated, and those have no entry here. So a known tag is
named and an unknown one is reported by its number, which is still enough to
look it up. An odd group number -- ``0029`` here -- marks a private tag, whose
meaning is the vendor's and not in any dictionary at all.
"""


@dataclass(frozen=True, slots=True)
class FieldOutcome:
    """One input field, joined to what the build did with it.

    Attributes:
        key: The field as its own source names it: ``PID-5``, a DICOM tag such
            as ``00100010``, or a report's header label.
        name: The readable name of that key where this project knows one, and an
            empty string where it does not.
        disposition: What became of it.
        note: Where it landed; empty for a removed field, which by definition
            landed nowhere.
        files_present: How many of that modality's files carried it. Zero means
            the build declares it carries the field but this corpus never
            exercised that, which is worth seeing rather than hiding.
    """

    key: str
    name: str
    disposition: Disposition
    note: str
    files_present: int


@dataclass(frozen=True, slots=True)
class ModalityLedger:
    """What one modality's input held, and what became of every field in it.

    Attributes:
        modality: The modality name.
        key_kind: What a key in ``fields`` denotes.
        files_read: How many files were parsed successfully.
        unreadable: One entry per file that could not be parsed, with the
            reason. Named rather than skipped: a file whose fields were never
            seen is a file this table cannot vouch for.
        fields: Every field observed in the input, plus any declared as carried
            that the input did not hold, sorted by key.
    """

    modality: str
    key_kind: str
    files_read: int
    unreadable: tuple[str, ...]
    fields: tuple[FieldOutcome, ...]

    def count(self, disposition: Disposition) -> int:
        """Return how many observed fields had this disposition.

        Args:
            disposition: The disposition to count.

        Returns:
            The number of fields that were present in at least one file. A field
            declared as carried but absent from the corpus is not counted, since
            nothing happened to it here.
        """
        return sum(
            1 for item in self.fields if item.disposition == disposition and item.files_present
        )


def lab_fields(path: Path) -> set[str]:
    """Return the populated field keys of one HL7 message.

    Args:
        path: The message file.

    Returns:
        Keys such as ``PID-5``, one per populated field. Repeats collapse: a
        message with twelve OBX segments contributes ``OBX-5`` once, because the
        unit of the count is files, not occurrences.
    """
    message = parse_message(read_exact(path))
    return {
        f"{segment.name}-{index}"
        for segment in message.segments
        for index in range(1, len(segment.fields))
        if segment.fields[index].strip()
    }


def imaging_fields(path: Path) -> set[str]:
    """Return the populated tag keys of one DICOM JSON Model sidecar.

    Args:
        path: The sidecar file.

    Returns:
        Bare eight-character tag keys, across every series object in the file.
        A tag present with an empty ``Value`` list does not count as populated.
    """
    payload = json.loads(read_exact(path))
    series_objects = payload if isinstance(payload, list) else []
    return {
        tag
        for series in series_objects
        if isinstance(series, dict)
        for tag, entry in series.items()
        if isinstance(entry, dict) and entry.get("Value")
    }


UNDECLARED_LABELS: Final = "other labelled lines"
"""The one row that stands for every label this project did not declare.

A patient's name is not allowed to become a field name, and that is what the
alternative did. The header pattern matches "word, colon, space", and ordinary
clinical prose matches it too: a line reading ``Rossi Mario: paziente noto
per...`` yields the label ``Rossi Mario``, and ``Dott Bianchi Anna: concorda``
yields a clinician. Both were then published in the manifest's field table —
the same names the scrubber had just removed from the body of that report, in
the document written to be sent to an access body.

So an unrecognised label is counted under this name and never quoted. The count
still does the job the generic matching was for: it tells a reader that the
template carries labelled lines this build did not understand, and `--report`
or the file itself is where to go and look at them.
"""


def report_fields(path: Path) -> set[str]:
    """Return the labelled headers one free-text report carries.

    Args:
        path: The report file.

    Returns:
        The declared labels the document carries, plus
        :data:`UNDECLARED_LABELS` standing for any others. The body is not a
        field and is not described here; the scrubber measures what became of
        it.
    """
    declared = set(CARRIED_FIELDS["reports"]) | _REDACTED_REPORT_LABELS
    found: set[str] = set()
    for label in _HEADER_LABEL.findall(read_exact(path)):
        stripped = label.strip()
        found.add(stripped if stripped in declared else UNDECLARED_LABELS)
    return found


_EXTRACTORS: Final[dict[str, Callable[[Path], set[str]]]] = {
    "lab": lab_fields,
    "reports": report_fields,
    "imaging": imaging_fields,
}


def observe_modality(root: Path, modality: str) -> ModalityLedger:
    """Walk one modality's input and account for every field it held.

    Args:
        root: The corpus root.
        modality: A key of :data:`commissura.read.corpus.RAW_SOURCES`.

    Returns:
        The ledger for that modality.
    """
    extract = _EXTRACTORS[modality]
    carried = CARRIED_FIELDS[modality]
    present: Counter[str] = Counter()
    unreadable: list[str] = []
    files_read = 0

    for path in sorted(root.glob(RAW_SOURCES[modality])):
        try:
            keys = extract(path)
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            unreadable.append(f"{path.relative_to(root).as_posix()}: {exc}")
            continue
        files_read += 1
        present.update(keys)

    return ModalityLedger(
        modality=modality,
        key_kind=_EXTENSION_OF[modality],
        files_read=files_read,
        unreadable=tuple(unreadable),
        fields=tuple(
            FieldOutcome(
                key=key,
                name=DICOM_KEYWORDS.get(key, "") if modality == "imaging" else "",
                disposition=carried[key].disposition if key in carried else "removed",
                note=carried[key].note if key in carried else "",
                files_present=present.get(key, 0),
            )
            for key in sorted(set(present) | set(carried))
        ),
    )


def observe_corpus(root: Path) -> tuple[ModalityLedger, ...]:
    """Account for every field in every modality of a raw corpus.

    Args:
        root: The corpus root, holding ``lab/``, ``reports/`` and ``imaging/``.

    Returns:
        One ledger per modality, in the order the modalities are declared.
    """
    return tuple(observe_modality(root, modality) for modality in RAW_SOURCES)
