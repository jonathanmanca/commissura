"""What a report's header declares about identity, and whether it is redacted.

Only laboratory messages produced an :class:`Identity`, so ``observe()`` was
called for them and for nothing else. A report's ``full_name`` therefore never
entered the material redaction is built from, and a report whose header named a
different person — a mis-filed document, which happens in any real export —
had that name published in the dataset. The subject's *own* name was removed
correctly, which is exactly what made it hard to see.

The scrubber's positional layer did warn about it, which is the detector added
on 2026-11-13 earning itself a second time. But a warning is not a redaction,
and the name was still in the released dataset.

Every identifier here is synthetic, built from an unassigned ``X`` place code.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from commissura.build.writer import BuildSpec, build_dataset
from commissura.deident.keys import SecretKey
from commissura.identifiers import codice_fiscale
from commissura.models import Sex
from commissura.read.corpus import DeclaredIdentity, read_corpus
from commissura.read.identity import report_name_conflicts

CR = "\r"
KEY = SecretKey(bytes(range(32)))

ROSSI = codice_fiscale("ROSSI", "MARIO", date(1980, 1, 1), Sex.MALE, "X001")
ESPOSITO = codice_fiscale("ESPOSITO", "GIOVANNA", date(1975, 6, 12), Sex.FEMALE, "X002")


def _write(path: Path, text: str) -> None:
    """Write exact characters: HL7 terminates segments with a bare CR."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def _lab(
    root: Path,
    name: str,
    *,
    national_id: str = ROSSI,
    family: str = "ROSSI",
    given: str = "MARIO",
    mrn: str = "0012345",
) -> None:
    _write(
        root / "lab" / f"{name}.hl7",
        CR.join(
            [
                "MSH|^~\\&|LIS|OSPEDALE SINTETICO|COMMISSURA|RESEARCH|20240301090000"
                "||ORU^R01|M1|P|2.5.1",
                f"PID|1||{mrn}^^^OSPEDALE SINTETICO^MR~{national_id}^^^MINSAL^NNITA"
                f"||{family}^{given}||19800101|M",
                "OBR|1|ACC1^LIS|ACC1^LAB|INFL^Indici^L|||20240301090000",
                "OBX|1|NM|718-7^Emoglobina||13.0|g/dL|12.0-16.0|N|||F",
            ]
        )
        + CR,
    )


def _report(
    root: Path,
    name: str,
    *,
    patient: str,
    national_id: str = ROSSI,
    mrn: str = "0012345",
    body: str = "Nessuna alterazione di rilievo.",
) -> None:
    _write(
        root / "reports" / f"{name}.txt",
        "OSPEDALE SINTETICO\nVia dei Tigli 40 - Milano\n\n"
        "REFERTO\n\n"
        f"Paziente: {patient}\n"
        f"Codice fiscale: {national_id}\n"
        f"Numero nosografico: {mrn}\n"
        "Data del referto: 02/03/2024\n\n"
        f"REPERTI\n{body}\n",
    )


def _built(tmp_path: Path):  # type: ignore[no-untyped-def]
    """Read and build, returning the corpus and the summary."""
    corpus = read_corpus(tmp_path / "raw")
    summary = build_dataset(
        corpus,
        KEY,
        BuildSpec(dataset_name="d", description="d", hdab="H", publisher="P"),
        tmp_path / "dataset",
    )
    return corpus, summary


def _published(root: Path) -> str:
    """Return every published file's text, joined, for leak assertions."""
    return "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


def _reasons(corpus: object) -> list[str]:
    return sorted(issue.reason for issue in corpus.issues)  # type: ignore[attr-defined]


# --------------------------------------------------------------------------
# The leak, exactly as reported
# --------------------------------------------------------------------------


def test_a_name_declared_only_by_a_report_header_is_redacted(tmp_path: Path) -> None:
    """The reproduced case: a report filed against the wrong patient.

    Linked by codice fiscale to ROSSI, header naming ESPOSITO. Before this, the
    dataset carried ``Paziente: GIOVANNA ESPOSITO`` in plain text while ROSSI's
    own name was removed — selective redaction that looked like success.
    """
    root = tmp_path / "raw"
    _lab(root, "a")
    _report(root, "r", patient="GIOVANNA ESPOSITO")

    corpus, summary = _built(tmp_path)
    published = _published(summary.root)

    for leaked in ("GIOVANNA", "ESPOSITO", "MARIO", "ROSSI"):
        assert leaked not in published, f"{leaked} survived"
    assert _reasons(corpus) == ["conflicting_report_name"]


def test_the_declared_name_is_redacted_from_the_body_as_well(tmp_path: Path) -> None:
    """A header writes both names and the prose below writes only the surname.

    So the whole string is not enough: replacing only ``GIOVANNA ESPOSITO``
    leaves the ``ESPOSITO`` in the sentence. The words go in too, which is the
    treatment institution names already had.
    """
    root = tmp_path / "raw"
    _lab(root, "a")
    _report(
        root,
        "r",
        patient="GIOVANNA ESPOSITO",
        body="La paziente ESPOSITO non presenta alterazioni focali.",
    )

    _, summary = _built(tmp_path)

    assert "ESPOSITO" not in _published(summary.root)


def test_a_declared_record_number_the_subject_does_not_carry_is_redacted(
    tmp_path: Path,
) -> None:
    """A report linked by codice fiscale may carry another institution's number.

    That number is in no laboratory message for this subject, so nothing knew
    to remove it. It is a patient identifier and it was being published.
    """
    root = tmp_path / "raw"
    _lab(root, "a", mrn="0012345")
    _report(root, "r", patient="MARIO ROSSI", mrn="9988776")

    _, summary = _built(tmp_path)

    assert "9988776" not in _published(summary.root)


def test_measure_finds_nothing_surviving_on_a_generated_corpus(tmp_path: Path) -> None:
    """The ground-truth check, which is the one that cannot be argued with.

    Verified with the same instrument the project uses for the claim: every
    measurable planted identifier removed, on a corpus the generator produced.
    """
    from commissura.build.manifest import write_healthdcat_description, write_manifest
    from commissura.build.risk import write_risk_report
    from commissura.generate.cohort import CohortSpec
    from commissura.generate.writer import write_corpus
    from commissura.measure import measure

    raw, out = tmp_path / "raw", tmp_path / "dataset"
    write_corpus(CohortSpec(subjects=8, seed=42, defect_rate=0.0), raw)
    corpus = read_corpus(raw)
    spec = BuildSpec(
        dataset_name="d",
        description="d",
        hdab="Agenzia Sintetica",
        publisher="IRCCS SINTETICO MAREBIANCO",
        contact_point="dati@irccs-sintetico.invalid",
    )
    summary = build_dataset(corpus, KEY, spec, out)
    write_healthdcat_description(out, spec=spec, summary=summary)
    write_risk_report(out)
    write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=spec)

    report = measure(raw, out)

    assert report.recall == 1.0, [miss.text for miss in report.misses]


# --------------------------------------------------------------------------
# The conflict policy
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("declared", "known", "label"),
    [
        ("MARIO ROSSI", "MARIO ROSSI", "identical"),
        ("ROSSI MARIO", "MARIO ROSSI", "the other way round"),
        ("mario rossi", "MARIO ROSSI", "lower case"),
        ("MARIO  ROSSI", "MARIO ROSSI", "doubled space"),
        ("MARIO ROSSÌ", "MARIO ROSSI", "a combining accent"),
        ("M. ROSSI", "MARIO ROSSI", "an abbreviated given name"),
        ("MARIA LUISA DE LUCA", "DE LUCA MARIA LUISA", "a compound name, reversed"),
        ("MARIO ROSSI BIANCHI", "MARIO ROSSI", "a second surname"),
        ("MARIA DELUCA", "MARIA DE LUCA", "a surname with and without its space"),
        ("GIOVANNA ESPOSITO", "GIOVANNI ESPOSITO", "one character of difference"),
        ("ESPOSITO", "GIOVANNA ESPOSITO", "the surname alone"),
        ("", "MARIO ROSSI", "a report with no name"),
        ("LI BO", "MARIO ROSSI", "names too short to compare"),
    ],
)
def test_these_are_not_conflicts(declared: str, known: str, label: str) -> None:
    """Crying wolf on any of these would bury the case the check exists for.

    Each is one person recorded twice far more often than two people confused.
    The comparison is on the *set* of folded words, so order never matters, and
    sharing one redactable word is enough to stay quiet.
    """
    assert not report_name_conflicts(declared, [known]), label


@pytest.mark.parametrize(
    ("declared", "known", "label"),
    [
        ("GIOVANNA ESPOSITO", "MARIO ROSSI", "two different people"),
        ("ROSSI GIOVANNA", "ROSSINI MARIO", "similar surnames that are not the same"),
    ],
)
def test_these_are_conflicts(declared: str, known: str, label: str) -> None:
    """Nothing shared, so the document may belong to somebody else.

    ``ROSSI`` and ``ROSSINI`` are different families, and matching on substrings
    so that one covered the other would quietly stop reporting the case this
    exists for.
    """
    assert report_name_conflicts(declared, [known]), label


def test_a_second_identity_matching_is_enough_to_stay_quiet() -> None:
    """A subject assembled from two institutions has two names on record."""
    assert not report_name_conflicts("GIOVANNA ESPOSITO", ["MARIO ROSSI", "GIOVANNA ESPOSITO"])


def test_two_patients_with_similar_names_are_not_confused(tmp_path: Path) -> None:
    """Two subjects, two reports, one surname between them.

    The risk of putting a report's name into the redaction material is
    over-redaction: a name removed from a document it does not belong to. Each
    subject's declared names are gathered per subject, so one patient's name
    cannot reach the other's report — and both are removed from their own.
    """
    root = tmp_path / "raw"
    _lab(root, "a", national_id=ROSSI, family="ROSSI", given="MARIO", mrn="111")
    _lab(root, "b", national_id=ESPOSITO, family="ROSSI", given="GIOVANNA", mrn="222")
    _report(root, "ra", patient="MARIO ROSSI", national_id=ROSSI, mrn="111")
    _report(root, "rb", patient="GIOVANNA ROSSI", national_id=ESPOSITO, mrn="222")

    corpus, summary = _built(tmp_path)
    published = _published(summary.root)

    assert len(corpus.subjects) == 2
    assert corpus.issues == ()
    for leaked in ("MARIO", "GIOVANNA", "ROSSI"):
        assert leaked not in published


def test_a_compound_name_is_redacted_whole_and_in_parts(tmp_path: Path) -> None:
    """``MARIA LUISA DE LUCA`` in the header, ``DE LUCA`` in the prose."""
    root = tmp_path / "raw"
    _lab(root, "a", family="DE LUCA", given="MARIA LUISA")
    _report(
        root,
        "r",
        patient="MARIA LUISA DE LUCA",
        body="La signora DE LUCA riferisce benessere.",
    )

    corpus, summary = _built(tmp_path)
    published = _published(summary.root)

    assert corpus.issues == ()
    for leaked in ("MARIA", "LUISA", "LUCA"):
        assert leaked not in published


@pytest.mark.parametrize(
    "written",
    ["MARIO ROSSI", "mario rossi", "ROSSI MARIO", "MARIO  ROSSI", "Mario Rossi"],
)
def test_case_space_and_unicode_variants_raise_no_conflict(tmp_path: Path, written: str) -> None:
    """The header's spelling is the template's choice, not a fact about identity."""
    root = tmp_path / "raw"
    _lab(root, "a")
    _report(root, "r", patient=written)

    corpus, summary = _built(tmp_path)

    assert corpus.issues == ()
    assert "ROSSI" not in _published(summary.root)


def test_a_report_with_no_name_in_its_header_is_not_a_conflict(tmp_path: Path) -> None:
    """Absence is not disagreement, and the report still links on its identifiers."""
    root = tmp_path / "raw"
    _lab(root, "a")
    _report(root, "r", patient="")

    corpus, _ = _built(tmp_path)

    assert corpus.issues == ()
    assert len(corpus.subjects[0].reports) == 1


# --------------------------------------------------------------------------
# The model
# --------------------------------------------------------------------------


def test_a_declared_name_is_never_split_into_given_and_family() -> None:
    """A report writes one line and does not say which part is which.

    Splitting would be a guess, and a guess here puts a surname in the
    given-name field of the document an auditor reads. So the name is one
    opaque string, and only its words are derived from it.
    """
    declared = DeclaredIdentity(full_name="GIOVANNA ESPOSITO", national_id="X", mrn="1")

    assert not hasattr(declared, "family_name")
    assert not hasattr(declared, "given_name")
    assert declared.words() == {"GIOVANNA", "ESPOSITO"}


def test_short_words_of_a_declared_name_are_left_alone() -> None:
    """``DE`` matches inside ordinary words, and the scrubber refuses it anyway."""
    assert DeclaredIdentity(full_name="MARIA DE LUCA", national_id="", mrn="").words() == {
        "MARIA",
        "LUCA",
    }
