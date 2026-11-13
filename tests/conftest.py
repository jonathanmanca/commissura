"""Fixtures shared across the test suite.

Test modules must not import from each other: a helper reached through
``from tests.test_labs import _person`` couples two files that should be free to
change independently, and it breaks the moment one of them is renamed or run in
isolation. pytest's answer is this file, which it discovers automatically.

The dataset builder below is the other reason this file exists, and it carries
more weight than a test helper usually does. ``build`` does not exist yet, so
this is currently the only executable statement of what a conformant dataset
looks like — written against :mod:`commissura.layout` so that the validator and
the thing it validates are both derived from the same schema. When ``build``
arrives, its output has to match what this produces, and the tests here are what
will say whether it does.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from commissura import layout
from commissura.models import Person, Sex

PersonFactory = Callable[..., Person]
DatasetFactory = Callable[..., Path]

TAB = "\t"


# --------------------------------------------------------------------------
# Synthetic people
# --------------------------------------------------------------------------


@pytest.fixture
def make_person() -> PersonFactory:
    """Return a factory for synthetic people, overridable field by field.

    A factory rather than a fixed instance because tests need to vary one
    attribute at a time — sex drives reference intervals, the MRN drives the
    padding-drift defect — while leaving everything else at a known value. The
    defaults are the same shape the generator produces: an unassignable place
    code in the codice fiscale, an undiallable telephone number, an ``.invalid``
    email domain.

    Returns:
        A callable taking any :class:`~commissura.models.Person` field as a
        keyword argument.
    """

    def _make(**overrides: object) -> Person:
        defaults: dict[str, object] = {
            "family_name": "DE LUCA",
            "given_name": "FRANCESCA",
            "sex": Sex.FEMALE,
            "birth_date": date(1962, 11, 4),
            "codice_fiscale": "DLCFRN62S44X217H",
            "mrn": "0048812",
            "street": "Via dei Tigli 7",
            "city": "Bologna",
            "province": "BO",
            "postal_code": "40121",
            "phone": "+39 051 0442913",
            "email": "f.deluca@posta.invalid",
        }
        return Person(**{**defaults, **overrides})

    return _make


@pytest.fixture
def person(make_person: PersonFactory) -> Person:
    """Return one synthetic person, for tests that do not need to vary anything."""
    return make_person()


# --------------------------------------------------------------------------
# Conformant datasets
# --------------------------------------------------------------------------


def write_text(path: Path, content: str) -> None:
    """Write text with no newline translation, creating parent directories.

    ``newline=""`` for the same reason the corpus writer uses it: translation
    would change the bytes on disk, and several rules here count characters.

    Args:
        path: Destination.
        content: Exact characters to write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="")


def write_json(path: Path, payload: object) -> None:
    """Write pretty-printed UTF-8 JSON with no newline translation."""
    write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def write_tsv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    """Write a tab-separated file with a header row.

    Args:
        path: Destination.
        header: Column names.
        rows: Data rows, each already the same length as the header.
    """
    lines = [TAB.join(header), *(TAB.join(row) for row in rows)]
    write_text(path, "\n".join(lines) + "\n")


SUBJECT_LABELS = ("a3f9c21b4e07", "b7e21d4409aa", "c1d8ff3027be", "d409ab17c355")
"""Labels shaped like the pseudonymisation design's output: truncated HMAC hex.

Using realistic labels rather than ``01`` and ``02`` means the tests exercise
the label grammar against what ``build`` will actually produce.
"""


def build_dataset(
    root: Path,
    *,
    subjects: int = 2,
    sessions: int = 1,
    with_sessions: bool = True,
) -> Path:
    """Write a dataset that satisfies every rule, and return its root.

    Every value here is chosen to pass a specific rule, which makes this
    function the readable form of the schema: provenance keys in the
    description, ``n/a`` rather than blanks, ages truncated at the ceiling, no
    absolute date anywhere, a hex key fingerprint and no secret beside it.

    Args:
        root: Directory to create.
        subjects: How many subjects, up to the number of available labels.
        sessions: How many sessions per subject.
        with_sessions: Whether to use a session directory level. BIDS allows
            either, and NM006 requires that one dataset not mix the two.

    Returns:
        The dataset root.
    """
    labels = SUBJECT_LABELS[:subjects]

    write_json(
        root / layout.DATASET_DESCRIPTION,
        {
            "Name": "Synthetic multimodal clinical dataset",
            "BIDSVersion": layout.BIDS_VERSION,
            "DatasetType": "raw",
            "License": "CC0-1.0",
            "Authors": ["Commissura test fixture"],
            "GeneratedBy": [{"Name": "commissura", "Version": "0.1.0"}],
            "CommissuraSchemaVersion": layout.SCHEMA_VERSION,
        },
    )

    write_tsv(
        root / layout.PARTICIPANTS_TSV,
        [layout.PARTICIPANT_ID_COLUMN, "age", "sex"],
        [
            [f"{layout.SUBJECT_PREFIX}{label}", age, sex]
            for label, age, sex in zip(
                labels,
                ["64", "71", layout.AGE_ABOVE_CEILING, layout.NOT_APPLICABLE],
                ["F", "M", "F", "M"],
                strict=False,
            )
        ],
    )

    for label in labels:
        subject = f"{layout.SUBJECT_PREFIX}{label}"
        for session_number in range(1, sessions + 1):
            if with_sessions:
                session = f"{layout.SESSION_PREFIX}{session_number:02d}"
                base = root / subject / session
                stem = f"{subject}_{session}"
            else:
                base = root / subject
                stem = subject

            write_tsv(
                base / "lab" / f"{stem}_{layout.LAB_SUFFIX}.tsv",
                [*layout.LAB_REQUIRED_COLUMNS, *layout.LAB_RECOMMENDED_COLUMNS],
                [
                    ["0", "718-7", "14.1", "g/dL", "Hemoglobin", "12.0", "15.5", "N", "CBC"],
                    ["0", "777-3", "535", "10*3/uL", "Platelets", "150", "400", "H", "CBC"],
                    ["86", "2345-7", "92", "mg/dL", "Glucose", "70", "100", "N", "CHEM7"],
                ],
            )
            write_json(
                base / "lab" / f"{stem}_{layout.LAB_SUFFIX}.json",
                {
                    "day_offset": {"Description": "Days from the subject's own baseline."},
                    "loinc_code": {"Description": "LOINC code of the analyte."},
                },
            )

            report_stem = f"{stem}_run-01_{layout.REPORT_SUFFIX}"
            write_text(
                base / "reports" / f"{report_stem}{layout.REPORT_TEXT_EXTENSION}",
                "REFERTO DI DIAGNOSTICA PER IMMAGINI\n\n"
                "QUESITO CLINICO\nStadiazione di neoplasia polmonare nota.\n\n"
                "REPERTI\nNon si apprezzano lesioni focali a carico del parenchima polmonare.\n"
                "Si confronta con il precedente esame eseguito 42 giorni prima.\n\n"
                "CONCLUSIONI\nQuadro sostanzialmente stabile.\n",
            )
            write_json(
                base / "reports" / f"{report_stem}{layout.REPORT_SIDECAR_EXTENSION}",
                {"kind": "radiology", "day_offset": 0, "Modality": "CT"},
            )

            write_text(base / "anat" / f"{stem}_T1w.nii.gz", "not a real nifti")
            write_json(base / "anat" / f"{stem}_T1w.json", {"EchoTime": 0.003})

    write_json(
        root / layout.DEIDENT_DIR / layout.MANIFEST_JSON,
        {
            "schema_version": layout.SCHEMA_VERSION,
            "deidentification_rule_version": "1.0.0",
            "key_fingerprint": "9f2c41ab77de0315",
            "tool_versions": {"commissura": "0.1.0", "python": "3.11.16"},
            # The shape build emits: one observed ledger per modality, each
            # field counted against the files that carried it. Kept in step with
            # commissura.build.observe so that a fixture cannot describe a
            # manifest the tool no longer writes.
            "modalities": [
                {
                    "modality": "lab",
                    "key_kind": "HL7 v2 field",
                    "files_read": 2,
                    "unreadable": 0,
                    "fields_observed": {"removed": 1, "replaced": 1, "kept": 1},
                    "fields": [
                        {
                            "field": "OBX-5",
                            "disposition": "kept",
                            "files_present": 2,
                            "note": "value",
                        },
                        {"field": "PID-5", "disposition": "removed", "files_present": 2},
                        {
                            "field": "PID-19",
                            "disposition": "replaced",
                            "files_present": 2,
                            "note": "subject label",
                        },
                    ],
                }
            ],
        },
    )
    write_json(
        root / layout.DEIDENT_DIR / layout.RISK_REPORT_JSON,
        {
            "schema_version": layout.SCHEMA_VERSION,
            "quasi_identifiers": ["age", "sex"],
            "minimum_k": 2,
            "combinations_below_threshold": [],
        },
    )

    return root


@pytest.fixture
def make_dataset(tmp_path: Path) -> DatasetFactory:
    """Return a factory that writes a conformant dataset under ``tmp_path``.

    Returns:
        A callable taking ``name`` plus any keyword accepted by
        :func:`build_dataset`.
    """

    def _make(name: str = "dataset", **kwargs: object) -> Path:
        return build_dataset(tmp_path / name, **kwargs)  # type: ignore[arg-type]

    return _make


@pytest.fixture
def dataset(make_dataset: DatasetFactory) -> Path:
    """Return a conformant two-subject, one-session dataset."""
    return make_dataset()
