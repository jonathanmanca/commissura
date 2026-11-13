"""Read the dataset once, so that every rule sees the same thing.

Twenty-odd rules each inspecting the filesystem on their own would read
``participants.tsv`` twenty times, parse it twenty ways, and handle a malformed
file twenty places. Worse, two rules could reach different conclusions about the
same file, and the report would contradict itself.

So the context reads and parses eagerly on first access, caches the result, and
hands rules a view of it. Rules never touch the filesystem.

**Parse failure is data, not an exception.** A malformed ``dataset_description``
must be *reported*, which means the thing that failed to parse has to survive as
a value a rule can inspect — hence :class:`JsonFile` and :class:`TsvFile`
carrying an ``error`` alongside the data. If parsing raised, the rule that cares
about "is this file valid JSON" would have to catch, and every other rule would
have to guard against a half-built context.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from commissura import layout
from commissura.read.corpus import read_exact


@dataclass(frozen=True, slots=True)
class JsonFile:
    """A JSON file that may be absent, unreadable or malformed.

    Attributes:
        relative: Dataset-relative path, for use in findings.
        exists: Whether the file is present.
        data: The parsed object, or ``None`` if absent or unparseable.
        error: Why parsing failed, if it did.
    """

    relative: str
    exists: bool
    data: dict[str, object] | None = None
    error: str | None = None

    @property
    def is_object(self) -> bool:
        """Return whether the file parsed to a JSON object rather than something else."""
        return isinstance(self.data, dict)


@dataclass(frozen=True, slots=True)
class TsvFile:
    """A tab-separated file that may be absent, unreadable or malformed.

    Attributes:
        relative: Dataset-relative path, for use in findings.
        exists: Whether the file is present.
        header: The column names, empty if the file could not be read.
        rows: The data rows, exactly as read, without padding short rows.
            Padding would hide the ragged-row problem this validator reports.
        error: Why reading failed, if it did.
    """

    relative: str
    exists: bool
    header: tuple[str, ...] = ()
    rows: tuple[tuple[str, ...], ...] = ()
    error: str | None = None

    def column(self, name: str) -> tuple[str, ...]:
        """Return one column's values, skipping rows too short to have it.

        Args:
            name: Column name.

        Returns:
            The values, or an empty tuple if the column is absent.
        """
        if name not in self.header:
            return ()
        index = self.header.index(name)
        return tuple(row[index] for row in self.rows if len(row) > index)


@dataclass(frozen=True, slots=True)
class DataFile:
    """One file inside a datatype directory, with the context it sits in.

    Attributes:
        relative: Dataset-relative path.
        path: Absolute path.
        subject: The ``sub-<label>`` directory name it lives under.
        session: The ``ses-<label>`` directory name, or ``None`` when the
            dataset has no session level.
        datatype: The datatype directory name, such as ``lab``.
        name: The parsed BIDS filename, or ``None`` if it does not follow the
            grammar.
    """

    relative: str
    path: Path
    subject: str
    session: str | None
    datatype: str
    name: layout.BidsName | None


@dataclass(frozen=True, slots=True)
class DatatypeDir:
    """One datatype directory and the files in it."""

    relative: str
    subject: str
    session: str | None
    datatype: str
    files: tuple[DataFile, ...] = field(default_factory=tuple)


class DatasetContext:
    """A parsed, cached view of one dataset directory.

    Construction does no work; every property reads on first access. That keeps
    a context cheap to build in a test that only exercises one rule.
    """

    def __init__(self, root: Path) -> None:
        """Point the context at a dataset directory.

        Args:
            root: The dataset root. It need not exist; ``root_exists`` reports
                that, so a rule can say so rather than the validator crashing.
        """
        self.root = root.resolve()

    # --- Filesystem basics -------------------------------------------------

    @cached_property
    def root_exists(self) -> bool:
        """Return whether the dataset root is an existing directory."""
        return self.root.is_dir()

    @cached_property
    def top_level_entries(self) -> tuple[str, ...]:
        """Return the names of entries at the dataset root, sorted."""
        if not self.root_exists:
            return ()
        return tuple(sorted(entry.name for entry in self.root.iterdir()))

    def relative_of(self, path: Path) -> str:
        """Return a path relative to the dataset root, with forward slashes.

        Forward slashes unconditionally, so that a report generated on Windows
        and one generated on Linux can be compared.

        Args:
            path: An absolute path inside the dataset.

        Returns:
            The dataset-relative path.
        """
        return path.relative_to(self.root).as_posix()

    # --- Parsing helpers ---------------------------------------------------

    def read_json(self, relative: str) -> JsonFile:
        """Read and parse one JSON file by its dataset-relative path."""
        path = self.root / relative
        if not path.is_file():
            return JsonFile(relative=relative, exists=False)
        try:
            data = json.loads(read_exact(path))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return JsonFile(relative=relative, exists=True, error=str(exc))
        if not isinstance(data, dict):
            return JsonFile(
                relative=relative,
                exists=True,
                error=f"expected a JSON object, found {type(data).__name__}",
            )
        return JsonFile(relative=relative, exists=True, data=data)

    def read_tsv(self, relative: str) -> TsvFile:
        """Read one tab-separated file by its dataset-relative path.

        Rows are returned exactly as found, without padding short ones, because
        a ragged row is a problem to report rather than to repair silently.
        """
        path = self.root / relative
        if not path.is_file():
            return TsvFile(relative=relative, exists=False)
        try:
            with path.open(encoding="utf-8", newline="") as handle:
                rows = [tuple(row) for row in csv.reader(handle, delimiter="\t")]
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            return TsvFile(relative=relative, exists=True, error=str(exc))

        # Trailing blank lines are an artefact of text editors, not data.
        while rows and rows[-1] in ((), ("",)):
            rows.pop()
        if not rows:
            return TsvFile(relative=relative, exists=True, error="file is empty")
        return TsvFile(relative=relative, exists=True, header=rows[0], rows=tuple(rows[1:]))

    # --- The dataset's own files -------------------------------------------

    @cached_property
    def description(self) -> JsonFile:
        """Return ``dataset_description.json``."""
        return self.read_json(layout.DATASET_DESCRIPTION)

    @cached_property
    def participants(self) -> TsvFile:
        """Return ``participants.tsv``."""
        return self.read_tsv(layout.PARTICIPANTS_TSV)

    @cached_property
    def manifest(self) -> JsonFile:
        """Return ``.deident/manifest.json``."""
        return self.read_json(f"{layout.DEIDENT_DIR}/{layout.MANIFEST_JSON}")

    @cached_property
    def risk_report(self) -> JsonFile:
        """Return ``.deident/risk_report.json``."""
        return self.read_json(f"{layout.DEIDENT_DIR}/{layout.RISK_REPORT_JSON}")

    # --- Subjects, sessions, datatypes -------------------------------------

    def imaging_metadata(self) -> tuple[tuple[str, dict[str, object]], ...]:
        """Return the pseudonymised imaging metadata this dataset carries.

        Lives here rather than in the rule that needs it, like every other read
        in this class, so that two rules asking the same question cannot reach
        different conclusions about the same files.

        Returns:
            One ``(relative path, payload)`` pair per readable JSON object
            under ``derivatives/imaging-metadata/``. A file that does not parse is
            left out: reporting that is the job of :class:`JsonFile` through the rules
            that already do that, and a rule about pixel data has nothing to
            say about malformed JSON.
        """
        found: list[tuple[str, dict[str, object]]] = []
        directory = self.root / "derivatives" / "imaging-metadata"
        if not directory.is_dir():
            return ()
        for path in sorted(directory.glob("*.json")):
            relative = self.relative_of(path)
            parsed = self.read_json(relative)
            if parsed.is_object and isinstance(parsed.data, dict):
                found.append((relative, parsed.data))
        return tuple(found)

    @cached_property
    def subject_dirs(self) -> tuple[str, ...]:
        """Return the ``sub-*`` directory names, sorted."""
        if not self.root_exists:
            return ()
        return tuple(
            sorted(
                entry.name
                for entry in self.root.iterdir()
                if entry.is_dir() and entry.name.startswith(layout.SUBJECT_PREFIX)
            )
        )

    @cached_property
    def datatype_dirs(self) -> tuple[DatatypeDir, ...]:
        """Return every datatype directory found, with its files.

        Handles both layouts BIDS allows: sessions present
        (``sub-x/ses-1/lab/``) and sessions absent (``sub-x/lab/``). A dataset
        that mixes the two is a problem for a rule to report, not for this
        method to resolve.
        """
        found: list[DatatypeDir] = []
        for subject in self.subject_dirs:
            subject_path = self.root / subject
            for entry in sorted(subject_path.iterdir()):
                if not entry.is_dir():
                    continue
                if entry.name.startswith(layout.SESSION_PREFIX):
                    for datatype_entry in sorted(entry.iterdir()):
                        if datatype_entry.is_dir():
                            found.append(self._datatype_dir(subject, entry.name, datatype_entry))
                else:
                    found.append(self._datatype_dir(subject, None, entry))
        return tuple(found)

    def _datatype_dir(self, subject: str, session: str | None, path: Path) -> DatatypeDir:
        """Build one :class:`DatatypeDir` from a directory on disk."""
        files = tuple(
            DataFile(
                relative=self.relative_of(entry),
                path=entry,
                subject=subject,
                session=session,
                datatype=path.name,
                name=layout.parse_bids_name(entry.name),
            )
            for entry in sorted(path.iterdir())
            if entry.is_file()
        )
        return DatatypeDir(
            relative=self.relative_of(path),
            subject=subject,
            session=session,
            datatype=path.name,
            files=files,
        )

    @cached_property
    def data_files(self) -> tuple[DataFile, ...]:
        """Return every file inside every datatype directory."""
        return tuple(file for directory in self.datatype_dirs for file in directory.files)

    def files_of_datatype(self, datatype: str) -> tuple[DataFile, ...]:
        """Return every file inside directories of one datatype.

        Args:
            datatype: The datatype directory name, such as ``lab``.

        Returns:
            The matching files.
        """
        return tuple(file for file in self.data_files if file.datatype == datatype)
