"""Validate the emitted description against HealthDCAT-AP's own SHACL shapes.

This is the test that turns "conformant as far as I read the specification" into
"conformant as the specification's own shapes judge it". The first time it ran it
found eleven distinct violations that the cardinality table and the health shapes
alone did not reveal: six came from the imported DCAT-AP 3.0.0 shapes and from
``range.ttl``.

It skips unless both `pyshacl` and the downloaded shapes are present. The shapes
are somebody else's documents, fetched on demand into a gitignored directory,
and a suite that failed on a clean checkout would be a suite people stop
trusting. The README says how to fetch them.

The shapes are not loaded as published: Release 8 puts an ``sh:or`` inside the
``sh:property`` list with no ``sh:path``, which is not a well-formed SHACL
property shape, and a strict engine refuses the whole file. :func:`_load_shapes`
re-attaches it to the node shape, where it was plainly meant to go.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from commissura import layout
from commissura.build.manifest import write_healthdcat_description, write_manifest
from commissura.build.writer import BuildSpec, build_dataset
from commissura.deident.keys import SecretKey
from commissura.generate.cohort import CohortSpec
from commissura.generate.writer import write_corpus
from commissura.read.corpus import read_corpus

pyshacl = pytest.importorskip("pyshacl", reason="pyshacl is a dev extra")
rdflib = pytest.importorskip("rdflib")

# Relative to this file, not to the working directory: a relative path made
# the whole conformance check skip silently when pytest ran from elsewhere.
SHAPES_DIR = Path(__file__).resolve().parent.parent / "reference" / "healthdcat-ap"
SHAPE_FILES = ("non-public-shapes.ttl", "dcat-ap-3.0.0-shapes.ttl", "range.ttl")
SHACL = "http://www.w3.org/ns/shacl#"

pytestmark = pytest.mark.skipif(
    not all((SHAPES_DIR / name).is_file() for name in SHAPE_FILES),
    reason=f"HealthDCAT-AP shapes not downloaded into {SHAPES_DIR}",
)


def _load_shapes() -> Any:  # rdflib arrives through importorskip, so Any is honest
    """Load the three shape graphs, repairing one malformed shape on the way in.

    shortcut: patches a defect in HealthDCAT-AP Release 8 rather than waiting
    for upstream — remove this once the published shapes load unmodified.
    """
    sh = rdflib.Namespace(SHACL)
    shapes = rdflib.Graph()
    for name in SHAPE_FILES:
        shapes.parse(SHAPES_DIR / name, format="turtle")

    for prop in set(shapes.objects(None, sh.property)):
        if (prop, sh.path, None) in shapes:
            continue
        for alternative in list(shapes.objects(prop, sh["or"])):
            for owner in list(shapes.subjects(sh.property, prop)):
                shapes.remove((owner, sh.property, prop))
                shapes.add((owner, sh["or"], alternative))
    return shapes


def _build_description(tmp_path: Path) -> Path:
    """Build a dataset with everything a holder must supply, and return its root."""
    raw, out = tmp_path / "raw", tmp_path / "dataset"
    shutil.rmtree(out, ignore_errors=True)
    write_corpus(CohortSpec(subjects=4, seed=31, defect_rate=0.0), raw)
    corpus = read_corpus(raw)

    spec = BuildSpec(
        dataset_name="Synthetic multimodal clinical dataset",
        description="Laboratory results, reports and imaging metadata, de-identified.",
        hdab="Agenzia Nazionale Sintetica per i Dati Sanitari",
        publisher="IRCCS SINTETICO MAREBIANCO",
        contact_point="dati@irccs-sintetico.invalid",
        access_url="https://portale-hdab-sintetico.invalid/permessi",
    )
    key = SecretKey(bytes(range(32)))
    summary = build_dataset(corpus, key, spec, out)
    write_manifest(out, corpus=corpus, summary=summary, key=key, spec=spec)
    write_healthdcat_description(out, spec=spec, summary=summary)
    assert summary.missing_for_conformance == (), summary.missing_for_conformance
    return out


def test_the_description_conforms_to_the_profiles_own_shapes(tmp_path: Path) -> None:
    """The claim this project makes, judged by the specification rather than by us."""
    out = _build_description(tmp_path)

    data = rdflib.Graph()
    data.parse(out / layout.HEALTHDCAT_DESCRIPTION, format="json-ld")

    conforms, _, text = pyshacl.validate(
        data, shacl_graph=_load_shapes(), advanced=True, inference="none"
    )
    assert conforms, text


def test_the_published_shapes_still_need_the_repair() -> None:
    """When upstream fixes its own shapes, this fails and the patch can go.

    Without this, the repair in :func:`_load_shapes` would quietly outlive the
    defect it works around.
    """
    sh = rdflib.Namespace(SHACL)
    unpatched = rdflib.Graph()
    unpatched.parse(SHAPES_DIR / "non-public-shapes.ttl", format="turtle")

    pathless = [
        prop
        for prop in set(unpatched.objects(None, sh.property))
        if (prop, sh.path, None) not in unpatched
    ]
    assert pathless, "the published shapes now load unmodified; delete the repair in _load_shapes"


def test_a_description_missing_what_the_holder_must_supply_does_not_conform(
    tmp_path: Path,
) -> None:
    """The counterpart: the check has to be capable of failing.

    A conformance test that passes on an incomplete document is measuring
    nothing, so this builds one without the holder-supplied fields and confirms
    the shapes reject it.
    """
    raw, out = tmp_path / "raw", tmp_path / "bare"
    write_corpus(CohortSpec(subjects=2, seed=31, defect_rate=0.0), raw)
    corpus = read_corpus(raw)

    spec = BuildSpec(dataset_name="Bare", description="No holder fields supplied.")
    key = SecretKey(bytes(range(32)))
    summary = build_dataset(corpus, key, spec, out)
    write_healthdcat_description(out, spec=spec, summary=summary)
    assert summary.missing_for_conformance

    data = rdflib.Graph()
    data.parse(out / layout.HEALTHDCAT_DESCRIPTION, format="json-ld")
    conforms, _, _ = pyshacl.validate(
        data, shacl_graph=_load_shapes(), advanced=True, inference="none"
    )
    assert not conforms


def test_the_command_line_can_produce_a_conformant_description(tmp_path: Path) -> None:
    """Drives the CLI, not BuildSpec.

    The test above constructs BuildSpec directly, so it proved the library
    conformed while the command could not: three mandatory fields had no flag.
    This one goes through `commissura build` exactly as the README tells a user
    to, which is the claim that actually matters.
    """
    from typer.testing import CliRunner

    from commissura.cli import app

    runner = CliRunner()
    raw, out, key = tmp_path / "raw", tmp_path / "dataset", tmp_path / "k.key"
    write_corpus(CohortSpec(subjects=3, seed=31, defect_rate=0.0), raw)
    assert runner.invoke(app, ["keygen", "--out", str(key)]).exit_code == 0

    result = runner.invoke(
        app,
        [
            "build",
            str(raw),
            "--out",
            str(out),
            "--key-file",
            str(key),
            "--hdab",
            "Agenzia Nazionale Sintetica per i Dati Sanitari",
            "--publisher",
            "IRCCS SINTETICO MAREBIANCO",
            "--contact-point",
            "dati@irccs-sintetico.invalid",
            "--access-url",
            "https://portale-hdab-sintetico.invalid/permessi",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "Not yet conformant" not in result.stdout

    data = rdflib.Graph()
    data.parse(out / layout.HEALTHDCAT_DESCRIPTION, format="json-ld")
    conforms, _, text = pyshacl.validate(
        data, shacl_graph=_load_shapes(), advanced=True, inference="none"
    )
    assert conforms, text
