"""Residual-risk detection, which must not depend on how this generator writes names.

The audit of 2026-11-13 found the detector matching ``[A-Z]{4,}`` and nothing
else. It reported ``FRANCESCA FONTANA`` and said nothing at all about
``Francesca Fontana`` — so a real hospital's title-case template would have left
a leaked name completely silent. The decision log already named
``_REPORT_LABELS`` as *the* obstacle to using this tool on real data because it
is written against the generator's own conventions; the detector had the same
dependency, unrecorded, and failed silently rather than loudly.

Three layers now, and these tests pin each one separately because they answer
different questions and only the first is certain.

Every identifier here is synthetic.
"""

from __future__ import annotations

from datetime import date

import pytest

from commissura.build.scrub import KnownIdentifiers, assess_residual_risk
from commissura.identifiers import codice_fiscale
from commissura.models import Sex
from commissura.read.corpus import Identity

FONTANA = Identity(
    national_id=codice_fiscale("FONTANA", "FRANCESCA", date(1954, 4, 16), Sex.FEMALE, "X300"),
    mrn="5534585",
    family_name="FONTANA",
    given_name="FRANCESCA",
    sex=Sex.FEMALE,
    birth_date=date(1954, 4, 16),
)

KNOWN = KnownIdentifiers(
    identities=(FONTANA,),
    providers=frozenset({"MORETTI GIULIA", "MORETTI"}),
    institutions=frozenset({"OSPEDALE SINTETICO DI COLLEVERDE"}),
)

CLEAN = (
    # Copied from a real build's output rather than invented. An earlier version
    # of this fixture left a bare `OSPEDALE` outside the placeholder and the
    # unanticipated-token layer reported it — correctly, because the real
    # scrubber redacts an institution's name whole and collapses the run. A
    # fixture that is not what the tool produces tests the fixture.
    "[INSTITUTION]\n[ADDRESS] - [ADDRESS]\n\n"
    "REFERTO DI DIAGNOSTICA PER IMMAGINI\n"
    "===================================\n\n"
    "Paziente: [NAME]\n"
    "Nato/a il: [BIRTH-DATE]   Eta: 59 anni\n"
    "Codice fiscale: [NATIONAL-ID]\n"
    "Numero nosografico: [PATIENT-ID]\n"
    "Data del referto: [day_offset:12]\n\n"
    "QUESITO CLINICO\nStadiazione di neoplasia polmonare nota.\n\n"
    "REPERTI\nNon si apprezzano lesioni focali a carico del parenchima.\n"
    "Si confronta con il precedente esame eseguito 42 giorni prima.\n\n"
    "CONCLUSIONI\nQuadro sostanzialmente stabile.\n"
    "Il medico refertante: [PROVIDER]\n"
)


def _risks(text: str, *, known: KnownIdentifiers = KNOWN) -> list[str]:
    return assess_residual_risk(text, known=known)


# --------------------------------------------------------------------------
# What the audit required, case by case
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "written",
    [
        "FRANCESCA FONTANA",
        "Francesca Fontana",
        "francesca fontana",
        "FONTANA FRANCESCA",
        "Francesca FONTANA",
        "Francesca Fontanà",
        "FRANCESCA  FONTANA",
    ],
)
def test_a_surviving_patient_name_is_reported_however_it_is_written(written: str) -> None:
    """The exact list the audit asked for, and the reason the detector was rewritten.

    ``Francesca Fontanà`` works through NFKD: decomposition puts the base letter
    first and the combining accent after it, so the folded needle is still a
    substring of the folded text. Accent insensitivity comes free from the
    normalisation rather than from a table of equivalences.
    """
    risks = _risks(f"REFERTO\n\nPaziente: {written}\n\nREPERTI\nNulla da segnalare.\n")

    assert risks, f"{written!r} was not reported"


def test_a_name_in_an_ordinary_sentence_is_reported() -> None:
    """Not in a labelled field, so only the declared-value layer can see it.

    This is the layer that has no false positives available to it: the string
    was handed to the scrubber by name.
    """
    risks = _risks("REPERTI\nLa paziente Francesca Fontana presenta un addensamento basale.\n")

    assert any("declared are still present" in risk for risk in risks)


def test_a_clinician_name_after_a_title_is_reported_in_title_case() -> None:
    """``Dott. Bianchi`` was invisible: the old pattern needed four capitals."""
    risks = _risks("CONCLUSIONI\nQuadro stabile.\nSi firma Dott. Bianchi.\n")

    assert any("declare a person's name" in risk for risk in risks)


def test_a_surviving_identifier_is_reported_whatever_its_case() -> None:
    """A codice fiscale written in lower case is still a codice fiscale."""
    risks = _risks(f"REFERTO\nCodice fiscale: {FONTANA.national_id.lower()}\n")

    assert any("declared are still present" in risk for risk in risks)


def test_a_surviving_institution_is_reported() -> None:
    """Institutions are declared per corpus, so they go through the same layer."""
    risks = _risks("REFERTI\nEseguito presso Ospedale Sintetico Di Colleverde.\n")

    assert any("declared are still present" in risk for risk in risks)


def test_a_name_in_a_filename_is_measured_against_the_ground_truth(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Filenames are searched by ``measure``, not by this heuristic.

    A dataset's filenames are composed from pseudonymous labels, so an
    identifier cannot reach one by design — which is exactly what was said about
    the manifest's ``records_dropped`` field before it was found carrying paths
    named after medical record numbers. ``measure`` now prepends each file's
    path to its contents, so ground truth covers the name as well as the bytes.
    """
    from commissura.measure import _dataset_text

    root = tmp_path / "dataset"
    (root / "sub-a3f9c21b4e07").mkdir(parents=True)
    (root / "sub-a3f9c21b4e07" / "FONTANA_report.txt").write_text("clean", encoding="utf-8")

    haystack = _dataset_text(root)

    assert "FONTANA" in "\n".join(haystack.values())


# --------------------------------------------------------------------------
# Not crying wolf
# --------------------------------------------------------------------------


def test_a_properly_redacted_report_reports_nothing() -> None:
    """The detector must stay usable, which means staying quiet when it should.

    A detector that fires on every document trains people to ignore it, and an
    ignored warning is worse than none. Every placeholder, every section
    heading and every day offset in a real redacted report is here.
    """
    assert _risks(CLEAN) == []


def test_a_clean_dataset_does_not_produce_a_flood(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Measured rather than asserted in prose: a real build, counted.

    On the twenty-five-subject walkthrough the three layers together report the
    same two truncation fragments the single-layer version did, and nothing
    else. The bound here is loose on purpose — the number is a property of the
    corpus — but a regression that made the detector noisy would blow past it.
    """
    from commissura.build.writer import BuildSpec, build_dataset
    from commissura.deident.keys import SecretKey
    from commissura.generate.cohort import CohortSpec
    from commissura.generate.writer import write_corpus
    from commissura.read.corpus import read_corpus

    raw = tmp_path / "raw"
    write_corpus(CohortSpec(subjects=8, seed=42, defect_rate=0.0), raw)
    corpus = read_corpus(raw)
    summary = build_dataset(
        corpus,
        SecretKey(bytes(range(32))),
        BuildSpec(dataset_name="d", description="d", hdab="H", publisher="P"),
        tmp_path / "dataset",
    )

    risks = list(summary.residual_risks())

    assert len(risks) <= 3, risks
    # And none of them may be the layer that cannot produce a false positive.
    assert not [r for r in risks if "declared are still present" in r]


def test_a_placeholder_in_a_name_field_is_not_a_residue() -> None:
    """``Paziente: [NAME]`` is what success looks like."""
    assert _risks("REFERTO\nPaziente: [NAME]\n") == []


def test_a_day_offset_in_a_name_field_is_not_a_residue() -> None:
    """A rewritten date next to a redacted name must not read as a surviving one."""
    assert _risks("REFERTO\nPaziente: [NAME]\nMedico: [PROVIDER] [day_offset:-3]\n") == []


def test_a_short_token_in_a_name_field_is_not_reported() -> None:
    """Below the floor the scrubber refuses to replace at.

    Measuring against a stricter rule than the method was given would be
    scoring it on a different exam — the same reasoning
    ``commissura measure`` uses for its own four-character threshold.
    """
    assert _risks("REFERTO\nPaziente: AB\n") == []


def test_the_detector_never_quotes_what_it_found() -> None:
    """Every layer counts; none hands over the strings it is warning about.

    The residual-risk list is written into ``.deident/manifest.json``, which is
    the document sent to an access body. A report that quoted the values it
    could not remove would hand them to the same reader — found by
    ``commissura measure`` on 2026-11-12, and the guard has to cover the two
    new layers as well as the old one.
    """
    text = (
        "REFERTO\nPaziente: Francesca Fontana\n"
        f"Codice fiscale: {FONTANA.national_id}\n"
        "Numero nosografico: 5534585\nMedico: Dott. Moretti\n"
    )

    risks = _risks(text)

    assert len(risks) >= 2
    joined = " ".join(risks)
    for secret in (
        "Francesca",
        "Fontana",
        "FONTANA",
        FONTANA.national_id,
        "5534585",
        "Moretti",
    ):
        assert secret not in joined, f"the detector quoted {secret!r}"


def test_the_note_never_reads_as_a_clearance() -> None:
    """A heuristic that found nothing has found nothing, not established safety.

    Pinned because this is the one way the section could do harm: being read as
    a clearance by somebody deciding whether a dataset may be released.
    """
    assert assess_residual_risk.__doc__ is not None
    assert "measurement, not a clearance" in assess_residual_risk.__doc__
