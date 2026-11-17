"""This repository must not claim a conformance it cannot support.

Four claims are out of bounds:

- that `commissura` is **EHDS-conformant**. The Regulation's implementing acts
  for Articles 77 and 78 are due March 2027 and do not exist; Italy has not
  designated a health data access body; and nobody has assessed this tool.
- that it is **GDPR-compliant**. Compliance is a property of a controller's
  whole processing operation, not of a program.
- that it is a **certified secure processing environment**. It is a local CLI,
  and seventeen of the eighteen EHDS-derived SPE requirements belong to other
  roles.
- that it **anonymises**. It pseudonymises. D7.2 section 5.5.4 (p. 53) makes
  anonymisation require that direct identifiers *and pseudonyms* be removed, and
  this tool keeps pseudonyms on purpose. Pseudonymised data is still personal
  data under the GDPR, which is the entire legal weight of the word.

The one conformance claim that *is* allowed is HealthDCAT-AP conformance of the
emitted description, because it is mechanically checked against the profile's own
SHACL by ``tests/test_shacl_conformance.py`` -- a claim about one file, with a
test behind it.

**Why a test and not a convention.** The decision log of 2026-11-16 records a
reason that sounded like a security reason surviving two readings before anybody
checked it, and concludes that "a reason that sounds like a security reason gets
less scrutiny than one that does not". A compliance claim has the same shape. A
test fails on the sentence; a convention relies on the next reader's restraint.

**And why this guard is structural rather than semantic, which is the part worth
reading.** The first version searched every text file for the claim phrases and
failed immediately -- on this project's own disclaimers. "Nothing here should be
quoted as evidence that `commissura` is EHDS-conformant, GDPR-compliant, a
certified anonymisation tool, or a secure processing environment" contains all
four phrases and asserts none of them. Teaching a regular expression to tell a
claim from a denial across a line-wrapped Markdown paragraph is precisely the
mistake this project's own convention names: asserting on the picture of the
prose instead of on the thing. Either the pattern leaks, which is the dangerous
direction, or it cries wolf and gets deleted.

So the guard asks two structural questions instead:

1. **The claim phrases must not appear at all** in the surfaces where a claim
   reaches somebody who is relying on it -- the README, the command-line
   interface's own declared text, and the note strings the build writes into
   `.deident/manifest.json` and `.deident/risk_report.json`, which travel to an
   access body. None of those has any business even discussing certification, so
   in them a mention *is* the defect, framing irrelevant.
2. **Anywhere else they appear, the file must carry the disclaimer.** A document
   under `docs/` may analyse compliance at length, provided it opens by saying it
   is not a statement of conformance. That turns "do not overclaim" from a
   convention into something a test can check.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.main import get_command

from commissura.build.manifest import write_manifest
from commissura.build.risk import write_risk_report
from commissura.build.writer import BuildSpec, build_dataset
from commissura.cli import app
from commissura.deident.keys import SecretKey
from commissura.generate.cohort import CohortSpec
from commissura.generate.writer import write_corpus
from commissura.read.corpus import read_corpus

ROOT = Path(__file__).resolve().parent.parent
KEY = SecretKey(bytes(range(32)))

# Phrases, not words. "GDPR" alone is fine and appears throughout; the project
# could not discuss what it does without it.
CLAIMS: dict[str, re.Pattern[str]] = {
    "EHDS conformance": re.compile(r"ehds[\s-]*(compliant|conformant)", re.IGNORECASE),
    "GDPR compliance": re.compile(r"gdpr[\s-]*(compliant|conformant)", re.IGNORECASE),
    "SPE certification": re.compile(
        r"certified\s+(secure\s+processing\s+environment|spe)", re.IGNORECASE
    ),
    "certified anonymisation": re.compile(r"certified\s+anonymis(ation|er|ing)", re.IGNORECASE),
    "anonymising our output": re.compile(
        r"(commissura|this tool|the tool)\s+anonymises"
        r"|(produces|emits|writes|yields)\s+(an?\s+)?anonymised\s+dataset",
        re.IGNORECASE,
    ),
}

# What a document has to say about itself before it may discuss compliance.
DISCLAIMER = re.compile(
    r"does not declare conformance|is not a (statement of )?conformance|"
    r"not a declaration of compliance|should not be quoted as evidence",
    re.IGNORECASE,
)

SEARCHED_SUFFIXES = {".md", ".py", ".toml", ".yml", ".yaml", ".cfg", ".txt"}
SKIPPED_DIRS = {
    ".git",
    ".venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "reference",
    "raw",
    "dataset",
    "htmlcov",
}


def _searched_files() -> list[Path]:
    """Return every text file in the repository worth searching."""
    found: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SEARCHED_SUFFIXES:
            continue
        if any(part in SKIPPED_DIRS for part in path.relative_to(ROOT).parts):
            continue
        if path.name == Path(__file__).name:
            # This file holds the patterns themselves.
            continue
        found.append(path)
    return found


def _hits(text: str, pattern: re.Pattern[str]) -> list[str]:
    """Return every match, with its line number."""
    return [
        f"line {text.count(chr(10), 0, match.start()) + 1}: {match.group(0)!r}"
        for match in pattern.finditer(text)
    ]


# --------------------------------------------------------------------------
# A guard on the guard
# --------------------------------------------------------------------------


def test_there_is_something_to_search() -> None:
    """An empty file list would make every assertion below pass over nothing.

    Which is the shape of failure this project has now found five times: an
    empty collection is not evidence that what fills it is safe.
    """
    names = {path.name for path in _searched_files()}

    assert len(_searched_files()) > 40
    assert {"README.md", "cli.py", "TEHDAS2_GAP_ANALYSIS.md"} <= names


def test_the_patterns_catch_the_sentences_they_are_for() -> None:
    """Checked by sabotage, which is this project's rule for a new guard.

    These are the sentences somebody would actually write. A guard nobody has
    watched fail is a guard nobody has tested.
    """
    samples = {
        "EHDS conformance": "commissura is EHDS-compliant out of the box.",
        "GDPR compliance": "The output is GDPR-compliant.",
        "SPE certification": "Deployed as a certified secure processing environment.",
        "certified anonymisation": "A certified anonymisation tool for clinical data.",
        "anonymising our output": "commissura anonymises the corpus.",
    }

    assert set(samples) == set(CLAIMS)
    for claim, sentence in samples.items():
        assert CLAIMS[claim].search(sentence), claim


def test_the_patterns_allow_what_this_project_actually_says() -> None:
    """The other half, and the one that stops the guard being a nuisance.

    This project discusses the GDPR, the EHDS and anonymisation constantly, and
    makes one mechanically checked conformance claim. A pattern that caught those
    would be deleted within a week, and then nothing would be checked at all.
    """
    allowed = [
        "commissura emits HealthDCAT-AP-conformant dataset descriptions.",
        "Pseudonymised data is still personal data under the GDPR.",
        "commissura pseudonymises; it does not anonymise, and must never imply it does.",
        "The access body may anonymise the data it receives.",
        "EHDS Regulation 2025/327 makes secondary use a legal obligation.",
        "k-anonymity over participant attributes, flagging k below 5.",
        "This is not a certificate of anonymity.",
        "Anonymisation and synthetic data generation are the access body's duty.",
        "A dataset in an anonymised statistical format answers a data request.",
    ]

    for sentence in allowed:
        for claim, pattern in CLAIMS.items():
            assert not pattern.search(sentence), f"{claim} matched: {sentence!r}"


# --------------------------------------------------------------------------
# 1. The surfaces where a claim reaches somebody relying on it
# --------------------------------------------------------------------------


@pytest.mark.parametrize("claim", sorted(CLAIMS))
def test_the_readme_makes_no_conformance_claim(claim: str) -> None:
    """The README is read by somebody deciding whether to use this on health data.

    It is the document with the most to lose from a sentence like that, and it
    has no reason to mention certification at all, so a mention is the defect
    whatever frame it sits in.
    """
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert not _hits(text, CLAIMS[claim]), f"{claim} in README.md"


@pytest.mark.parametrize("claim", sorted(CLAIMS))
def test_the_command_line_interface_makes_no_conformance_claim(claim: str) -> None:
    """Asked of click rather than of rendered help, as this project's rule says.

    A test that reads `--help` is testing the renderer: rich styles the tokens,
    so a negative substring assertion against that output passes no matter what.
    That failure mode cost this project a security guard that was green in CI for
    weeks while checking nothing.
    """
    command = get_command(app)
    declared: list[str] = [command.help or ""]
    for name, sub in command.commands.items():  # type: ignore[attr-defined]
        declared.append(f"{name}: {sub.help or ''}")
        for param in sub.params:
            declared.append(str(getattr(param, "help", "") or ""))

    assert not _hits("\n".join(declared), CLAIMS[claim]), f"{claim} in the CLI's own text"


@pytest.mark.parametrize("claim", sorted(CLAIMS))
def test_the_documents_the_build_writes_make_no_conformance_claim(
    claim: str, tmp_path: Path
) -> None:
    """These two travel to an access body, which is the reader that matters.

    Built rather than read off the source, because the note strings are assembled
    at run time from the dataset -- the whole point of deriving them -- so the
    only way to see what a reader gets is to produce one.
    """
    raw, out = tmp_path / "raw", tmp_path / "dataset"
    write_corpus(CohortSpec(subjects=4, seed=42, defect_rate=0.0), raw)
    corpus = read_corpus(raw)
    spec = BuildSpec(dataset_name="d", description="d", hdab="H", publisher="P")
    summary = build_dataset(corpus, KEY, spec, out)
    risk = write_risk_report(out)
    manifest = write_manifest(
        out,
        corpus=corpus,
        summary=summary,
        key=KEY,
        spec=spec,
        risk=risk,
        permit_reference="IT-HDAB-2029-00417",
        root_fingerprint=KEY.fingerprint,
    )

    for name, payload in (("manifest", manifest), ("risk report", risk)):
        assert not _hits(json.dumps(payload), CLAIMS[claim]), f"{claim} in the {name}"


def test_the_manifest_states_what_it_is_not() -> None:
    """The positive counterpart, so the guard is not only a prohibition.

    A guard that only forbids something passes on a document that says nothing at
    all, which is the defect recorded on 2026-11-12 about the `--key` tests.
    """
    from commissura.deident.pseudonymise import declare

    note = str(declare(KEY)["reversibility_note"]).lower()

    assert "irreversible" in note
    assert "no mapping" in note


def test_the_risk_report_refuses_to_be_read_as_a_clearance(tmp_path: Path) -> None:
    """Pinned here as well as in the risk module's own tests, deliberately.

    This is the file somebody would quote, and the sentence is the whole reason
    the report is safe to publish.
    """
    raw, out = tmp_path / "raw", tmp_path / "dataset"
    write_corpus(CohortSpec(subjects=4, seed=42, defect_rate=0.0), raw)
    corpus = read_corpus(raw)
    build_dataset(
        corpus, KEY, BuildSpec(dataset_name="d", description="d", hdab="H", publisher="P"), out
    )

    text = json.dumps(write_risk_report(out)).lower()

    assert "not a certificate of anonymity" in text


# --------------------------------------------------------------------------
# 2. Anywhere else, the file must say what it is not
# --------------------------------------------------------------------------


@pytest.mark.parametrize("claim", sorted(CLAIMS))
def test_a_file_discussing_a_claim_carries_the_disclaimer(claim: str) -> None:
    """A document may analyse compliance if it opens by saying it is not one.

    This is the structural answer to a problem a regular expression cannot
    solve: the four phrases appear in this project's own disclaimers, in a
    negative frame no pattern can reliably detect across a wrapped paragraph. So
    rather than guessing at the frame, the guard requires the *document* to
    declare itself -- which is a property a test can check and a reader can see.
    """
    offences: list[str] = []
    for path in _searched_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        hits = _hits(text, CLAIMS[claim])
        if hits and not DISCLAIMER.search(text):
            offences.append(f"{path.relative_to(ROOT)}: {hits[0]}")

    assert not offences, f"{claim} discussed without a disclaimer:\n" + "\n".join(offences)


def test_every_tehdas2_document_declares_what_it_is_not() -> None:
    """Risk R-10's mitigation, asserted rather than trusted.

    Six documents with TEHDAS2 in their names are exactly the thing a reader
    would mistake for an assessment against the Regulation. "Aligned with
    TEHDAS2" becomes "EHDS-ready" in a README and then "compliant" in a
    conversation, and nothing in the repository would contradict it.
    """
    documents = sorted((ROOT / "docs").glob("*.md"))

    assert len(documents) >= 5
    for path in documents:
        text = path.read_text(encoding="utf-8")
        assert DISCLAIMER.search(text) or "does not declare" in text, path.name


def test_the_disclaimer_pattern_is_not_satisfied_by_silence() -> None:
    """Otherwise the check above would pass on an empty document."""
    assert not DISCLAIMER.search("A perfectly ordinary paragraph about datasets.")
    assert DISCLAIMER.search("This document does not declare conformance.")
