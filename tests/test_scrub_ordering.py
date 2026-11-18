"""A short word inside a declared name must not survive its redaction.

Found by reviewing the CDA work on 2026-11-17, and present in the walkthrough
corpus the README documents: twenty-two occurrences of
``[INSTITUTION] DI [INSTITUTION]`` in a dataset built from seed 42 at the
walkthrough's own defect rate.

**The mechanism.** :func:`commissura.build.writer._known_identifiers` puts a
declared value *and its individual words* into one flat set, keeping only words
of four characters or more — the scrubber's minimum redactable length. So
``OSPEDALE SINTETICO DI COLLEVERDE`` contributes the whole string plus
``OSPEDALE``, ``SINTETICO`` and ``COLLEVERDE``, and **not** ``DI``. Substituted
in alphabetical order, ``COLLEVERDE`` fires before the whole string, the whole
string no longer matches, and the three long words each become a placeholder
with the short one left standing between them.

**Two things leak, and the second is the one with a decision behind it.** The
word itself survives, which tells a reader the institution was an "X DI Y". And
the number of placeholders tells them how many words its name had — which is
exactly what the decision of 2026-11-07 added ``_collapse_runs`` to prevent.
That guarantee silently fails whenever an excluded short word sits *between* two
redacted parts, because the placeholders are then not consecutive. Italian
institution and clinician names are full of such words: ``DI``, ``DE``, ``SAN``,
``DEI``.

**Why no instrument caught it.** ``commissura measure`` asks whether an exact
planted string survived, and counts neither way anything under four characters —
the exclusion recorded on 2026-11-12 that keeps the recall figure honest. ``DI``
is two characters, so the one tool that would have seen this was excluded from
seeing it by design. The residual-risk detector looks for tokens of four
characters or more, so it was equally blind.

Every identifier here is synthetic.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from commissura.build.scrub import (
    PLACEHOLDER_INSTITUTION,
    PLACEHOLDER_PROVIDER,
    _longest_first,
    _replace_all,
)
from commissura.build.writer import BuildSpec, build_dataset
from commissura.deident.keys import SecretKey
from commissura.generate.cohort import CohortSpec
from commissura.generate.writer import write_corpus
from commissura.read.corpus import read_corpus

KEY = SecretKey(bytes(range(32)))

# A placeholder, a word of one to three characters, then another placeholder.
# The signature of a name redacted around a word too short to redact.
STRANDED_WORD = re.compile(
    r"\[(?:INSTITUTION|PROVIDER|NAME|ADDRESS)\]\s+\w{1,3}\s+\[(?:INSTITUTION|PROVIDER|NAME|ADDRESS)\]"
)


def _declared_set(value: str) -> set[str]:
    """Return the set a build would hold for one declared value.

    Mirrors `_known_identifiers`: the whole value, plus every word of at least
    four characters. Written out rather than imported because the point of the
    test is that these two things have to agree, and a test that called the
    same helper could not tell if the helper changed.
    """
    return {value} | {word for word in value.split() if len(word) >= 4}


# --------------------------------------------------------------------------
# The ordering itself
# --------------------------------------------------------------------------


def test_longest_first_puts_the_whole_value_before_its_words() -> None:
    """The property the substitution pass depends on."""
    ordered = _longest_first(_declared_set("OSPEDALE SINTETICO DI COLLEVERDE"))

    assert ordered[0] == "OSPEDALE SINTETICO DI COLLEVERDE"


def test_longest_first_is_deterministic_for_equal_lengths() -> None:
    """Two corpora with the same declared values must plan the same way.

    A build that reordered its substitutions between runs would produce a
    different replacement report from the same input, and the manifest's counts
    would stop being comparable.
    """
    values = {"ROSSI", "VERDI", "BIANCHI"}

    assert _longest_first(values) == _longest_first(sorted(values, reverse=True))
    assert _longest_first(values) == ["BIANCHI", "ROSSI", "VERDI"]


@pytest.mark.parametrize(
    "declared",
    [
        "OSPEDALE SINTETICO DI COLLEVERDE",
        "ISTITUTO DEI TUMORI SINTETICO",
        "PRESIDIO SAN SINTETICO MAREBIANCO",
    ],
)
def test_a_declared_name_with_a_short_word_is_redacted_whole(declared: str) -> None:
    """The leak, in isolation, for three shapes of Italian institution name."""
    text = f"Paziente trasferito presso {declared} per approfondimenti."

    scrubbed = text
    for needle in _longest_first(_declared_set(declared)):
        scrubbed, _ = _replace_all(scrubbed, needle, PLACEHOLDER_INSTITUTION)

    assert scrubbed == f"Paziente trasferito presso {PLACEHOLDER_INSTITUTION} per approfondimenti."
    assert not STRANDED_WORD.search(scrubbed)
    for word in declared.split():
        assert word not in scrubbed


def test_alphabetical_order_is_what_left_the_word_behind() -> None:
    """The counterfactual, so the fix is tied to the defect it closes.

    Not a test of current behaviour: it demonstrates that the *old* order
    produced the leak, which is what makes the assertion above meaningful
    rather than a restatement of whatever the code happens to do.
    """
    declared = "OSPEDALE SINTETICO DI COLLEVERDE"
    text = f"eseguito presso {declared}."

    scrubbed = text
    for needle in sorted(_declared_set(declared)):
        scrubbed, _ = _replace_all(scrubbed, needle, PLACEHOLDER_INSTITUTION)

    assert " DI " in scrubbed
    assert STRANDED_WORD.search(scrubbed)


def test_a_clinician_name_with_a_short_particle_is_redacted_whole() -> None:
    """The generator emits `DE LUCA CLAUDIO`, so this is not hypothetical."""
    declared = "DE LUCA CLAUDIO"
    text = f"Come concordato con il collega {declared}, si rimanda."

    scrubbed = text
    for needle in _longest_first(_declared_set(declared)):
        scrubbed, _ = _replace_all(scrubbed, needle, PLACEHOLDER_PROVIDER)

    assert scrubbed == f"Come concordato con il collega {PLACEHOLDER_PROVIDER}, si rimanda."


# --------------------------------------------------------------------------
# End to end, on the corpus the README documents
# --------------------------------------------------------------------------


def test_no_short_word_is_stranded_in_the_walkthrough_dataset(tmp_path: Path) -> None:
    """The corpus where this was measured: seed 42, the walkthrough's rate.

    Twenty-two occurrences before the fix. Pinned here rather than in a unit
    test alone, because the unit tests above would pass on a build that never
    put a short word in a declared value, and this one proves the generator
    does — which is what makes the path covered rather than merely tested.
    """
    raw, out = tmp_path / "raw", tmp_path / "dataset"
    write_corpus(CohortSpec(subjects=25, seed=42, defect_rate=0.2), raw)
    corpus = read_corpus(raw)
    build_dataset(
        corpus, KEY, BuildSpec(dataset_name="d", description="d", hdab="H", publisher="P"), out
    )

    stranded: list[str] = []
    for path in sorted(out.rglob("*_report.txt")):
        text = path.read_text(encoding="utf-8")
        stranded += [f"{path.name}: {match.group(0)!r}" for match in STRANDED_WORD.finditer(text)]

    assert not stranded, (
        "a word too short to redact survived inside a redacted name:\n" + "\n".join(stranded[:10])
    )


def test_the_generator_still_emits_a_name_with_a_short_word(tmp_path: Path) -> None:
    """Otherwise the test above passes over a corpus that cannot exercise it.

    The fifth time this project has guarded against that shape: an empty
    collection is not evidence that what fills it is safe, and a path no corpus
    reaches is not covered whatever the percentage says.
    """
    raw = tmp_path / "raw"
    write_corpus(CohortSpec(subjects=25, seed=42, defect_rate=0.2), raw)
    corpus = read_corpus(raw)

    declared = {
        value
        for subject in corpus.subjects
        for lab in subject.labs
        for value in (lab.sending_facility, lab.ordering_provider)
        if value
    }
    with_short_word = {value for value in declared if any(len(word) < 4 for word in value.split())}

    assert with_short_word, "no declared value carries a word too short to redact"
