"""The documentation requirements of TEHDAS2 D7.2 section 5.5.1, p. 50-51.

That section enumerates what the documentation of a de-identification should
carry, and three of its clauses are testable properties of this project's
output rather than of its prose:

- **Traceability across updates.** "Appropriate mechanisms shall be in place to
  maintain traceability across documentation updates, enabling verification of
  how the documentation has evolved over time." A rebuild replaced the manifest
  and left no trace that a previous dataset existed -- which is the withdrawal
  case of 2026-11-13 seen from the documentation side.
- **Anonymity of documentation.** "The documentation shall not contain personal
  or identifying information relating to the data subjects." This project found
  four violations of that clause the hard way before reading it, so the guard
  here is class-level and covers the sections added since.
- **Structured and machine-readable**, which the manifest already is, and which
  the same section says has no standard: "Standard structure for anonymised or
  synthetic data documentation is currently not existing and should be
  developed."

Also here: the two recommended HealthDCAT-AP age properties, which D7.2 section
3.1 (p. 18) asks a holder to publish so an applicant can tell whether they need
exact ages before applying for them.

Every identifier here is synthetic.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from commissura import layout
from commissura.build.manifest import (
    predecessor_of,
    write_healthdcat_description,
    write_manifest,
)
from commissura.build.risk import write_risk_report
from commissura.build.writer import BuildSpec, build_dataset
from commissura.deident.keys import SecretKey
from commissura.generate.cohort import CohortSpec
from commissura.generate.writer import write_corpus
from commissura.read.corpus import read_corpus

KEY = SecretKey(bytes(range(32)))
HMAC_FIELD = "manifest_hmac"


def _spec() -> BuildSpec:
    return BuildSpec(
        dataset_name="Synthetic dataset",
        description="For testing the documentation requirements against.",
        hdab="Agenzia Sintetica",
        publisher="IRCCS SINTETICO MAREBIANCO",
        contact_point="dati@irccs-sintetico.invalid",
        access_url="https://portale-sintetico.invalid/permessi",
    )


def _built(  # type: ignore[no-untyped-def]
    tmp_path: Path,
    *,
    subjects: int = 6,
    seed: int = 42,
    defect_rate: float = 0.0,
    cda: bool = False,
):
    raw, out = tmp_path / "raw", tmp_path / "dataset"
    write_corpus(CohortSpec(subjects=subjects, seed=seed, defect_rate=defect_rate, cda=cda), raw)
    corpus = read_corpus(raw)
    spec = _spec()
    summary = build_dataset(corpus, KEY, spec, out)
    return raw, out, corpus, summary, spec


_WORD = r"[^\W_]"
"""A letter or a digit, Unicode-aware, and deliberately not an underscore.

``\\w`` would include it, which would let a planted value sit inside a
snake_case token unnoticed. A leak guard takes the strict side: a false positive
costs somebody a glance, a false negative ships an identifier.
"""


def _standalone(value: str) -> re.Pattern[str]:
    r"""Match a value only where it is a token and not part of a longer one.

    ``\b`` cannot do this job directly. It is defined against word characters,
    so a value that begins with ``+`` or ends with ``.`` gets the boundary test
    applied to the wrong side and the pattern means the opposite of what it
    reads as. The lookarounds are therefore added only on the edges that are
    alphanumeric.

    Args:
        value: The planted identifier, already lowercased.

    Returns:
        The pattern.
    """
    head = rf"(?<!{_WORD})" if value[:1].isalnum() else ""
    tail = rf"(?!{_WORD})" if value[-1:].isalnum() else ""
    return re.compile(head + re.escape(value) + tail)


# --------------------------------------------------------------------------
# Traceability across updates
# --------------------------------------------------------------------------


def test_a_first_build_records_no_predecessor(tmp_path: Path) -> None:
    """Absent and unknown are different facts, so `None` is written not omitted."""
    _, out, corpus, summary, spec = _built(tmp_path)

    manifest = write_manifest(
        out,
        corpus=corpus,
        summary=summary,
        key=KEY,
        spec=spec,
        predecessor=predecessor_of(tmp_path / "nowhere"),
    )

    assert "predecessor" in manifest
    assert manifest["predecessor"] is None


def test_a_rebuild_names_the_manifest_it_replaced(tmp_path: Path) -> None:
    """The requirement itself: a chain of rebuilds has to be followable.

    Three fields and no counts. The predecessor's numbers describe data this
    dataset may no longer hold, and shipping them inside the new manifest would
    put a stale claim in the file written to be believed.
    """
    _, out, corpus, summary, spec = _built(tmp_path)
    first = write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=spec)

    found = predecessor_of(out)

    assert found is not None
    assert found["generated_at"] == first["generated_at"]
    assert found[HMAC_FIELD] == first[HMAC_FIELD]
    assert found["schema_version"] == first["schema_version"]
    assert set(found) == {"generated_at", HMAC_FIELD, "schema_version"}


def test_the_predecessor_link_survives_a_real_rebuild(tmp_path: Path) -> None:
    """Through the command line, where staging is what makes it possible.

    The predecessor has to be read while the destination still holds the
    previous build. After `publish` it is gone, so this is the one fact only the
    publication layer can supply.
    """
    from typer.testing import CliRunner

    from commissura.cli import app

    runner = CliRunner()
    raw = tmp_path / "raw"
    write_corpus(CohortSpec(subjects=6, seed=11, defect_rate=0.0), raw)
    key_file = tmp_path / "k.key"
    key_file.write_text(KEY.material.hex(), encoding="utf-8")
    out = tmp_path / "dataset"
    argv = [
        "build",
        str(raw),
        "--out",
        str(out),
        "--key-file",
        str(key_file),
        "--hdab",
        "H",
        "--publisher",
        "P",
    ]
    assert runner.invoke(app, argv).exit_code == 0
    path = out / layout.DEIDENT_DIR / layout.MANIFEST_JSON
    first = json.loads(path.read_text(encoding="utf-8"))
    assert first["predecessor"] is None

    assert runner.invoke(app, argv).exit_code == 0

    second = json.loads(path.read_text(encoding="utf-8"))
    assert second["predecessor"] is not None
    assert second["predecessor"][HMAC_FIELD] == first[HMAC_FIELD]
    assert second[HMAC_FIELD] != first[HMAC_FIELD]


def test_an_unreadable_destination_manifest_is_treated_as_absent(tmp_path: Path) -> None:
    """A malformed manifest in the destination must not fail a sound build.

    And recording "there was something here but we could not read it" would be a
    field nobody can act on.
    """
    destination = tmp_path / "dataset"
    (destination / layout.DEIDENT_DIR).mkdir(parents=True)
    (destination / layout.DEIDENT_DIR / layout.MANIFEST_JSON).write_text("{ not", encoding="utf-8")

    assert predecessor_of(destination) is None


def test_a_destination_manifest_that_is_not_an_object_is_absent(tmp_path: Path) -> None:
    """Valid JSON is not the same as a manifest."""
    destination = tmp_path / "dataset"
    (destination / layout.DEIDENT_DIR).mkdir(parents=True)
    (destination / layout.DEIDENT_DIR / layout.MANIFEST_JSON).write_text("[]", encoding="utf-8")

    assert predecessor_of(destination) is None


# --------------------------------------------------------------------------
# Anonymity of documentation, over the sections added this round
# --------------------------------------------------------------------------


@pytest.mark.parametrize("cda", [False, True])
@pytest.mark.parametrize("seed", [7, 42])
def test_no_planted_identifier_reaches_the_new_manifest_sections(
    tmp_path: Path, seed: int, cda: bool
) -> None:
    """Class-level, as the audit of 2026-11-13 established it must be.

    A test naming the fields it checks passes on the next field somebody adds,
    which is how `linkage_issues` carried a codice fiscale for months. So this
    reads every planted identifier out of the ground truth and asserts none of
    them is anywhere in the document -- including `pseudonymisation` and
    `predecessor`, which are new.

    **Matched on word boundaries, and that is a correction to this test rather
    than a refinement.** It compared substrings, so it reported `ANNA` -- a
    clinician's given name -- because the manifest transcribes the DICOM
    keywords `ReferringPhysicianName` and `PerformingPhysicianName` and `ANNA`
    sits inside "Physici**anNa**me". A collision with this project's own
    vocabulary, not a leak.

    It was recorded on 2026-11-17 as seed- and modality-dependent, which
    understated it: measuring the grid showed the collision at seeds 5, 6 and 42
    for a plain corpus as well as for every CDA one, and seed 7 without CDA --
    the single combination this test ran -- is the only cell of eight where it
    does not fire. The green was a coincidence, not a property of the modality.
    So the rule is now a boundary match and the grid is parametrised, because a
    guard that holds in one cell is a guard nobody has measured.
    """
    raw, out, corpus, summary, spec = _built(
        tmp_path, subjects=10, defect_rate=0.5, seed=seed, cda=cda
    )
    risk = write_risk_report(out)
    write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=spec, risk=risk)
    write_manifest(
        out,
        corpus=corpus,
        summary=summary,
        key=KEY,
        spec=spec,
        risk=risk,
        permit_reference="IT-HDAB-2029-00417",
        root_fingerprint=KEY.fingerprint,
        predecessor=predecessor_of(out),
    )
    text = (out / layout.DEIDENT_DIR / layout.MANIFEST_JSON).read_text(encoding="utf-8").lower()
    planted = {
        span["text"]
        for span in json.loads(
            (raw / "_generator" / "phi_annotations.json").read_text(encoding="utf-8")
        )["spans"]
        if len(span["text"]) >= 4
    }

    assert planted
    for value in planted:
        assert not _standalone(value.lower()).search(text), value


def test_the_pseudonymisation_section_is_present_and_machine_readable(tmp_path: Path) -> None:
    """D7.2 section 5.5.1: structured, and preferably machine-readable.

    Which is also the section saying no standard structure for this exists -- the
    citation behind this project's decision of 2026-11-07 that the manifest
    schema is its own.
    """
    _, out, corpus, summary, spec = _built(tmp_path)

    manifest = write_manifest(out, corpus=corpus, summary=summary, key=KEY, spec=spec)

    section = manifest["pseudonymisation"]
    assert isinstance(section, dict)
    assert section["algorithm"] == "HMAC-SHA256"
    assert isinstance(section["domains"], dict)
    # Round-trips, which is what machine-readable has to mean in practice.
    reread = json.loads(
        (out / layout.DEIDENT_DIR / layout.MANIFEST_JSON).read_text(encoding="utf-8")
    )
    assert reread["pseudonymisation"] == section


# --------------------------------------------------------------------------
# The age range in the Article 77 description
# --------------------------------------------------------------------------


def _dataset_node(payload: dict[str, object]) -> dict[str, object]:
    """Return the ``dcat:Dataset`` node out of the emitted JSON-LD."""
    graph = payload["@graph"]
    assert isinstance(graph, list)
    node = next(n for n in graph if isinstance(n, dict) and n.get("@type") == "dcat:Dataset")
    assert isinstance(node, dict)
    return node


def _published_ages(out: Path) -> list[int]:
    """Return the integer ages in the published participants table."""
    lines = (out / layout.PARTICIPANTS_TSV).read_text(encoding="utf-8").splitlines()
    index = lines[0].split("\t").index("age")
    values = [row.split("\t")[index] for row in lines[1:] if row]
    return [int(value) for value in values if value.isdigit()]


def test_the_description_publishes_the_cohorts_age_range(tmp_path: Path) -> None:
    """Derived from the published table, so it cannot disagree with the data."""
    _, out, _, summary, spec = _built(tmp_path, subjects=10)

    node = _dataset_node(write_healthdcat_description(out, spec=spec, summary=summary))

    low = node["healthdcatap:minTypicalAge"]
    high = node["healthdcatap:maxTypicalAge"]
    assert isinstance(low, dict) and isinstance(high, dict)
    # xsd:nonNegativeInteger and not a bare JSON number, which JSON-LD reads as
    # xsd:integer -- a different datatype, and the profile's own value
    # constraint asks for this one.
    assert low["@type"] == "xsd:nonNegativeInteger"
    assert high["@type"] == "xsd:nonNegativeInteger"
    ages = _published_ages(out)
    assert ages
    assert int(low["@value"]) == min(ages)
    assert int(high["@value"]) == max(ages)


def test_a_cohort_with_no_numeric_age_claims_no_range(tmp_path: Path) -> None:
    """Both properties are recommended, so absence is silence and 0 is a lie.

    Ages above the ceiling are carried as `90+`, which is not a number. A
    cohort of nothing but those has no range to publish, and a `maxTypicalAge`
    of 0 would be a false statement where saying nothing is accurate.
    """
    _, out, _, summary, spec = _built(tmp_path, subjects=4)
    table = out / layout.PARTICIPANTS_TSV
    lines = table.read_text(encoding="utf-8").splitlines()
    header, rows = lines[0], lines[1:]
    columns = header.split("\t")
    age = columns.index("age")
    rewritten = [header]
    for row in rows:
        cells = row.split("\t")
        cells[age] = layout.AGE_ABOVE_CEILING
        rewritten.append("\t".join(cells))
    with table.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(rewritten) + "\n")

    node = _dataset_node(write_healthdcat_description(out, spec=spec, summary=summary))

    assert not _published_ages(out)
    assert "healthdcatap:minTypicalAge" not in node
    assert "healthdcatap:maxTypicalAge" not in node
