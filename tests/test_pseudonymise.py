"""The pseudonymisation construction: keyed, domain-separated, deterministic."""

from __future__ import annotations

import re
from datetime import date
from hashlib import sha256

import pytest

from commissura.deident.keys import KEY_BYTES, SecretKey, generate_key
from commissura.deident.pseudonymise import (
    DATE_OFFSET_SPAN,
    RULE_VERSION,
    SUBJECT_ID_HEX_CHARS,
    UID_ROOT,
    Pseudonymiser,
)

KEY = SecretKey(bytes(range(KEY_BYTES)))
CF = "RSSMRA80A01H501U"
OTHER_CF = "DLCFRN62S44X217T"


def _fresh() -> Pseudonymiser:
    return Pseudonymiser(KEY)


# --------------------------------------------------------------------------
# Determinism, which is what makes a multimodal dataset possible
# --------------------------------------------------------------------------


def test_the_same_key_and_input_always_give_the_same_label() -> None:
    """Three separate exports are linked only by deriving the same pseudonym."""
    assert _fresh().subject_label(CF) == _fresh().subject_label(CF)


def test_a_different_key_gives_a_different_label() -> None:
    assert _fresh().subject_label(CF) != Pseudonymiser(generate_key()).subject_label(CF)


def test_different_inputs_give_different_labels() -> None:
    assert _fresh().subject_label(CF) != _fresh().subject_label(OTHER_CF)


def test_repeated_calls_within_one_instance_are_cached_consistently() -> None:
    pseudonymiser = _fresh()
    first = pseudonymiser.subject_label(CF)
    for _ in range(10):
        assert pseudonymiser.subject_label(CF) == first
    assert pseudonymiser.issued_subject_count() == 1


# --------------------------------------------------------------------------
# Keyed, not a plain hash
# --------------------------------------------------------------------------


def test_the_label_is_not_a_plain_digest_of_the_input() -> None:
    """The decisive property.

    A codice fiscale is drawn from a space small enough to enumerate: the format
    encodes a name, a birth date, a sex and a place of birth. A plain
    ``sha256(national_id)`` would let anyone with a candidate list reverse the
    whole dataset without the key.
    """
    label = _fresh().subject_label(CF)
    assert label != sha256(CF.encode()).hexdigest()[:SUBJECT_ID_HEX_CHARS]
    assert label not in sha256(CF.encode()).hexdigest()


def test_the_key_is_not_recoverable_from_the_outputs() -> None:
    """A weak check, but it pins the obvious mistake of emitting key material."""
    pseudonymiser = _fresh()
    outputs = [
        pseudonymiser.subject_label(CF),
        pseudonymiser.uid("1.2.840.10008.1.2.1"),
        pseudonymiser.accession("LAB24031801"),
        pseudonymiser.key_fingerprint,
    ]
    hex_key = KEY.material.hex()
    for output in outputs:
        assert hex_key not in output
        assert output not in hex_key


# --------------------------------------------------------------------------
# Domain separation
# --------------------------------------------------------------------------


def test_the_same_string_in_different_roles_derives_differently() -> None:
    """Without domain separation, a value observed in one role could be replayed."""
    pseudonymiser = _fresh()
    shared = "0048812"
    derived = {
        pseudonymiser.subject_label(shared),
        pseudonymiser.accession(shared),
        pseudonymiser.uid(shared),
    }
    assert len(derived) == 3


def test_a_label_and_its_offset_are_independent_derivations() -> None:
    pseudonymiser = _fresh()
    label = pseudonymiser.subject_label(CF)
    assert str(pseudonymiser.date_offset(label)) not in label


# --------------------------------------------------------------------------
# Shape of the outputs
# --------------------------------------------------------------------------


def test_a_label_is_twelve_lowercase_hex_characters() -> None:
    assert re.fullmatch(r"[0-9a-f]{12}", _fresh().subject_label(CF))


def test_the_directory_name_carries_the_bids_prefix_and_the_label_does_not() -> None:
    """The prefix belongs to the filename grammar, not to the identifier."""
    pseudonymiser = _fresh()
    label = pseudonymiser.subject_label(CF)
    assert pseudonymiser.subject_directory(CF) == f"sub-{label}"
    assert not label.startswith("sub-")


def test_labels_are_spread_across_the_space() -> None:
    """A derivation bug that produced a constant or near-constant would show here."""
    pseudonymiser = _fresh()
    labels = {pseudonymiser.subject_label(f"TEST{n:012d}") for n in range(500)}
    assert len(labels) == 500


def test_a_uid_is_under_the_registration_free_arc_and_fits_the_limit() -> None:
    uid = _fresh().uid("1.2.840.113619.2.55.3.604688.1234567890")
    assert uid.startswith(f"{UID_ROOT}.")
    assert re.fullmatch(r"2\.25\.\d+", uid)
    assert len(uid) <= 64


def test_uids_are_unique_across_many_inputs() -> None:
    pseudonymiser = _fresh()
    uids = {pseudonymiser.uid(f"1.2.840.{n}") for n in range(500)}
    assert len(uids) == 500


def test_an_accession_is_sixteen_hex_characters() -> None:
    assert re.fullmatch(r"[0-9a-f]{16}", _fresh().accession("LAB24031801"))


# --------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------


def test_the_offset_is_inside_the_declared_window() -> None:
    pseudonymiser = _fresh()
    half = DATE_OFFSET_SPAN // 2
    for n in range(500):
        offset = pseudonymiser.date_offset(pseudonymiser.subject_label(f"TEST{n:012d}"))
        assert -half <= offset < half


def test_the_offset_is_stable_for_a_subject() -> None:
    pseudonymiser = _fresh()
    label = pseudonymiser.subject_label(CF)
    assert pseudonymiser.date_offset(label) == _fresh().date_offset(label)


def test_offsets_differ_between_subjects() -> None:
    """A single cohort-wide offset would let one known date unshift everybody."""
    pseudonymiser = _fresh()
    offsets = {
        pseudonymiser.date_offset(pseudonymiser.subject_label(f"TEST{n:012d}")) for n in range(200)
    }
    assert len(offsets) > 100


def test_shifting_preserves_intervals_exactly() -> None:
    """The property that makes a shifted date usable for research at all."""
    pseudonymiser = _fresh()
    label = pseudonymiser.subject_label(CF)
    first, second = date(2024, 3, 18), date(2024, 5, 7)

    shifted_first = pseudonymiser.shift_date(label, first)
    shifted_second = pseudonymiser.shift_date(label, second)

    assert (shifted_second - shifted_first).days == (second - first).days
    assert shifted_first != first


def test_shifting_moves_every_date_for_a_subject_by_the_same_amount() -> None:
    pseudonymiser = _fresh()
    label = pseudonymiser.subject_label(CF)
    dates = [date(2020, 1, 1), date(2022, 6, 15), date(2024, 12, 31)]
    deltas = {(pseudonymiser.shift_date(label, d) - d).days for d in dates}
    assert len(deltas) == 1


def test_day_offset_is_a_plain_subtraction_and_needs_no_key() -> None:
    """What the dataset actually stores, and why it needs no secret.

    Expressing time as a distance from the subject's own first event removes the
    calendar without any key being involved.
    """
    pseudonymiser = _fresh()
    baseline = date(2024, 3, 18)
    assert pseudonymiser.day_offset(baseline, date(2024, 5, 7)) == 50
    assert pseudonymiser.day_offset(baseline, baseline) == 0
    assert pseudonymiser.day_offset(baseline, date(2024, 3, 1)) == -17


def test_day_offset_does_not_depend_on_the_key() -> None:
    baseline, moment = date(2024, 1, 1), date(2024, 3, 1)
    assert _fresh().day_offset(baseline, moment) == Pseudonymiser(generate_key()).day_offset(
        baseline, moment
    )


# --------------------------------------------------------------------------
# Collisions and provenance
# --------------------------------------------------------------------------


def test_a_truncation_collision_raises_instead_of_merging_two_people() -> None:
    """Forced by pre-seeding the issued map, since 48 bits will not collide on demand.

    The guard matters more than its likelihood: a handled collision is a
    curiosity, an unhandled one puts two patients' data in one record.
    """
    pseudonymiser = _fresh()
    label = _fresh().subject_label(CF)
    pseudonymiser._issued_subjects[label] = "A DIFFERENT PERSON"

    with pytest.raises(ValueError, match="truncation collision"):
        pseudonymiser.subject_label(CF)


def test_the_fingerprint_comes_from_the_key() -> None:
    assert _fresh().key_fingerprint == KEY.fingerprint


def test_the_rule_version_is_reported_for_the_manifest() -> None:
    """Two datasets built from one key under different rules are not linkable."""
    assert _fresh().rule_version == RULE_VERSION
    assert re.fullmatch(r"\d+\.\d+\.\d+", RULE_VERSION)


def test_the_rule_version_can_be_pinned_explicitly() -> None:
    assert Pseudonymiser(KEY, rule_version="2.1.0").rule_version == "2.1.0"
