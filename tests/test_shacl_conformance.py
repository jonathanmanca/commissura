"""Validate the emitted description against HealthDCAT-AP's own SHACL shapes.

This is the test that turns "conformant as far as I read the specification" into
"conformant as the specification's own shapes judge it". The first time it ran it
found eleven distinct violations that the cardinality table and the health shapes
alone did not reveal: six came from the imported DCAT-AP 3.0.0 shapes and from
``range.ttl``.

**The shapes are vendored under ``third_party/``, so this runs on a clean
checkout and in CI, offline.** It used to skip unless somebody had run four
``curl`` commands on that machine, which meant the project's headline claim was
checked in one place and silently unchecked everywhere else — the failure mode
this project has recorded three times, and the one that let the README's own
download block stay broken, because a broken download produced a tidy skip
rather than an error. ``tests/test_vendored_shapes.py`` guards the vendored
copies: a digest per file, and a check that each is credited in ``NOTICE``,
since both works are CC BY 4.0 and redistribution is permitted only with
attribution.

One skip remains and is honest: ``pyshacl`` is a dev extra, so somebody who
installed without it cannot run this. That cannot happen by a change to the
project — a test asserts ``pyshacl`` is still declared in the extra, and CI
installs it.

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
# In the repository rather than downloaded, which is what removed the other and
# larger silent skip -- see this module's docstring.
SHAPES_DIR = Path(__file__).resolve().parent.parent / "third_party"
SHAPE_FILES = (
    "healthdcat-ap/non-public-shapes.ttl",
    "dcat-ap/shapes.ttl",
    "healthdcat-ap/range.ttl",
    # DCAT-AP's own class ranges, loaded by hand because HealthDCAT-AP's
    # range.ttl declares `owl:imports` of its own IRI -- a self-loop, which is a
    # no-op. Its comment says it imports these; it does not, so 84 class range
    # constraints were never checked here. Six of them failed when they were.
    "dcat-ap/range.ttl",
)
SHACL = "http://www.w3.org/ns/shacl#"
DCAT_AP_RANGE_IRI = "https://semiceu.github.io/DCAT-AP/releases/3.0.0/html/shacl/range.ttl"


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


def test_the_vendored_shapes_still_need_the_repair() -> None:
    """When a refresh brings shapes that load unmodified, this fails and the patch can go.

    **Vendoring changed what this test can see, and saying so is the point.**
    It used to read whatever had last been downloaded, so it would fire the
    first time somebody re-fetched after upstream fixed the defect. It now reads
    a pinned copy, so it reports on that copy and will pass for as long as the
    copy sits still. Pinning a dependency converts "we find out when upstream
    changes" into "we find out when somebody refreshes" — the refresh procedure
    in the README is where that now happens, and the digest in
    `third_party/PROVENANCE.json` is what makes a refresh deliberate rather than
    accidental.

    Without this, the repair in :func:`_load_shapes` would quietly outlive the
    defect it works around.
    """
    sh = rdflib.Namespace(SHACL)
    unpatched = rdflib.Graph()
    unpatched.parse(SHAPES_DIR / "healthdcat-ap/non-public-shapes.ttl", format="turtle")

    pathless = [
        prop
        for prop in set(unpatched.objects(None, sh.property))
        if (prop, sh.path, None) not in unpatched
    ]
    assert pathless, "the vendored shapes now load unmodified; delete the repair in _load_shapes"


def test_the_health_range_file_still_imports_itself() -> None:
    """While it does, DCAT-AP's ranges have to be loaded by hand.

    ``range.ttl`` declares itself as the DCAT-AP range IRI *and* ``owl:imports``
    that same IRI, so the import resolves to the file itself and brings in
    nothing. Its own comment says it imports DCAT-AP's range constraints to keep
    reused and extended constraints apart. Until that is fixed, the only way to
    check those 84 constraints is to load the file ourselves, which
    :data:`SHAPE_FILES` does -- and this fails once a refresh brings a fixed
    copy, so the workaround cannot outlive the defect it works around. Like the
    repair test above, it now reports on the pinned copy rather than on
    upstream; see that test for what vendoring costs.
    """
    owl = rdflib.Namespace("http://www.w3.org/2002/07/owl#")
    graph = rdflib.Graph()
    graph.parse(SHAPES_DIR / "healthdcat-ap/range.ttl", format="turtle")

    self_imports = [
        subject for subject, target in graph.subject_objects(owl.imports) if subject == target
    ]
    assert self_imports == [rdflib.URIRef(DCAT_AP_RANGE_IRI)], (
        "range.ttl no longer imports itself; the DCAT-AP ranges may now arrive "
        "through the import chain, so check whether loading them by hand is still needed"
    )


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
