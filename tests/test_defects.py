"""The defect catalogue and the injector's contract.

Integration through corpus generation already executes the happy path of this
module. What it cannot reach is the refusal behaviour — the injector rejecting a
bad rate or an identifier that is not in the catalogue — and that is precisely
the behaviour a caller depends on, because it is what turns a typo in a defect
id into an immediate failure rather than a defect that silently never fires.
"""

from __future__ import annotations

from random import Random

import pytest

from commissura.generate.defects import (
    BY_ID,
    CATALOGUE,
    DefectClass,
    DefectInjector,
    Modality,
    defects_for,
)


def test_catalogue_ids_are_unique() -> None:
    ids = [defect.defect_id for defect in CATALOGUE]
    assert len(set(ids)) == len(ids)
    assert len(BY_ID) == len(CATALOGUE)


def test_catalogue_ids_are_namespaced_by_modality() -> None:
    """``lab.missing_unit`` reads unambiguously in a manifest; ``missing_unit`` does not."""
    for defect in CATALOGUE:
        assert defect.defect_id.startswith(f"{defect.modality.value}."), defect.defect_id


def test_every_defect_records_why_it_happens() -> None:
    """A defect with no stated cause is an invention, not an observation."""
    for defect in CATALOGUE:
        assert len(defect.why_it_happens) > 40, defect.defect_id
        assert defect.summary.endswith("."), defect.defect_id


def test_defects_for_partitions_the_catalogue() -> None:
    grouped = [defect for modality in Modality for defect in defects_for(modality)]
    assert sorted(d.defect_id for d in grouped) == sorted(d.defect_id for d in CATALOGUE)


def test_every_modality_has_defects() -> None:
    for modality in Modality:
        assert defects_for(modality), modality


def test_every_defect_class_is_represented() -> None:
    """Each class has a different owner, so an empty one is a blind spot."""
    present = {defect.defect_class for defect in CATALOGUE}
    assert present == set(DefectClass)


@pytest.mark.parametrize("rate", [-0.01, 1.01, 2.0, -5.0])
def test_injector_rejects_a_rate_outside_the_unit_interval(rate: float) -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        DefectInjector(Random(0), rate)


@pytest.mark.parametrize("rate", [0.0, 0.5, 1.0])
def test_injector_accepts_the_boundaries(rate: float) -> None:
    assert DefectInjector(Random(0), rate).rate == rate


def test_should_apply_rejects_an_unknown_id() -> None:
    """A typo must fail loudly, not become a defect that never fires."""
    injector = DefectInjector(Random(0), 1.0)
    with pytest.raises(KeyError, match="unknown defect id"):
        injector.should_apply("lab.no_such_defect")


def test_record_rejects_an_unknown_id() -> None:
    injector = DefectInjector(Random(0), 1.0)
    with pytest.raises(KeyError, match="unknown defect id"):
        injector.record("imaging.no_such_defect", "imaging/x.json", "detail")


def test_apply_rejects_an_unknown_id() -> None:
    injector = DefectInjector(Random(0), 1.0)
    with pytest.raises(KeyError, match="unknown defect id"):
        injector.apply("reports.no_such_defect", "reports/x.txt", "detail")


def test_rate_zero_never_fires_and_rate_one_always_does() -> None:
    never = DefectInjector(Random(1), 0.0)
    always = DefectInjector(Random(1), 1.0)
    for _ in range(50):
        assert not never.should_apply("lab.missing_unit")
        assert always.should_apply("lab.missing_unit")


def test_nothing_is_logged_unless_a_defect_fires() -> None:
    injector = DefectInjector(Random(1), 0.0)
    for _ in range(20):
        assert not injector.apply("lab.missing_unit", "lab/x.hl7", "detail")
    assert injector.applied() == ()


def test_applied_preserves_order_and_detail() -> None:
    injector = DefectInjector(Random(1), 1.0)
    injector.apply("lab.missing_unit", "lab/a.hl7", "first")
    injector.apply("imaging.burned_in_annotation", "imaging/b.json", "second")

    applied = injector.applied()
    assert [a.defect_id for a in applied] == ["lab.missing_unit", "imaging.burned_in_annotation"]
    assert [a.detail for a in applied] == ["first", "second"]
    assert [a.path for a in applied] == ["lab/a.hl7", "imaging/b.json"]


def test_applied_returns_a_snapshot_not_a_live_view() -> None:
    """A caller holding the log must not see it change underneath them."""
    injector = DefectInjector(Random(1), 1.0)
    injector.apply("lab.missing_unit", "lab/a.hl7", "first")
    snapshot = injector.applied()
    injector.apply("lab.missing_unit", "lab/b.hl7", "second")
    assert len(snapshot) == 1


class _CountingRandom(Random):
    """A random source that reports how many draws it has served."""

    def __init__(self, seed: int) -> None:
        """Seed the generator and start the draw counter at zero."""
        super().__init__(seed)
        self.draws = 0

    def random(self) -> float:
        """Serve one value and count it."""
        self.draws += 1
        return super().random()


@pytest.mark.parametrize("rate", [0.0, 0.5, 1.0])
def test_a_decision_costs_one_draw_whatever_the_rate_is(rate: float) -> None:
    """Changing the rate must not shift the rest of the random stream.

    Two corpora generated at different rates have to stay comparable, which
    means a defect decision has to consume the same amount of randomness even
    when it cannot possibly fire. Short-circuiting on ``rate == 0`` would make
    every later value in the run different.
    """
    source = _CountingRandom(42)
    injector = DefectInjector(source, rate)
    for _ in range(10):
        injector.should_apply("lab.missing_unit")
    assert source.draws == 10
