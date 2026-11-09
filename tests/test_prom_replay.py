import numpy as np
import pytest

from actitrac import HeuristicsNet, HeuristicsSettings, Variant, cluster_traces, mine
from actitrac.prom_replay import JavaRandom, prom_input_sets

PROM = HeuristicsSettings(prom_replay=True)


def test_random_matches_java():
    # From java.util.Random(Long.MAX_VALUE) on OpenJDK 8.
    random = JavaRandom()
    bounds = [1, 2, 3, 5, 7, 1, 10, 16, 3, 1000000007]
    assert [random.next_int(b) for b in bounds] == [0, 0, 0, 4, 6, 0, 7, 6, 1, 121412731]


def test_skip_equals_drawing():
    drawn, skipped = JavaRandom(), JavaRandom()
    for _ in range(1000):
        drawn.next_int(1)
    skipped.skip(1000)
    assert [drawn.next_int(7) for _ in range(5)] == [skipped.next_int(7) for _ in range(5)]
    assert drawn.draws == skipped.draws


def test_input_sets_keep_insertion_order_and_duplicates():
    # Everything is welcome, so one set grows to hold all members.
    assert prom_input_sets(9, [3, 1, 2], lambda *_: 0.0, 0.1) == ((1, 2, 3),)
    # Nothing is welcome, so each member gets its own set, sorted.
    assert prom_input_sets(9, [3, 1, 2], lambda *_: 1.0, 0.1) == ((1,), (2,), (3,))


def choice_net(**kwargs):
    """Task d takes its one input from a or b, and a and b both have tokens after s."""
    activities = ("a", "b", "d", "s")
    inputs = ((frozenset({3}),), (frozenset({3}),), (frozenset({0, 1}),), ())
    outputs = ((frozenset({2}),), (frozenset({2}),), (), (frozenset({0}), frozenset({1})))
    return HeuristicsNet(activities, inputs, outputs, **kwargs)


def test_default_replay_is_unchanged_and_exact():
    net = choice_net()
    assert net.prom_inputs is None
    assert net.replay("sabd") == (4, 0, 1)
    assert net.fits([Variant(0, tuple("sabd"), 1)], 1.0) is False


def test_seeded_replay_gives_the_same_counts_when_the_choice_does_not_matter():
    inputs = (((3,),), ((3,),), ((0, 1),), ())
    net = choice_net(prom_inputs=inputs)
    assert net.replay("sabd") == (4, 0, 1)


def test_seeded_token_choice_depends_on_the_draw():
    # Two tasks hold tokens for d. Which one fires decides whether a later e parses.
    activities = ("a", "b", "d", "e", "s")
    outputs = (
        (frozenset({2, 3}),),
        (frozenset({2}),),
        (),
        (),
        (frozenset({0}), frozenset({1})),
    )
    inputs = (
        (frozenset({4}),),
        (frozenset({4}),),
        (frozenset({0, 1}),),
        (frozenset({0}),),
        (),
    )
    seeded = (((4,),), ((4,),), ((0, 1),), ((0,),), ())
    net = HeuristicsNet(activities, inputs, outputs, prom_inputs=seeded)
    # a and b draw once each with one option, then d draws between a and b. Taking
    # a's token leaves e without one.
    random = JavaRandom()
    random.next_int(1), random.next_int(1)
    expected_missing = 1 if random.next_int(2) == 0 else 0
    assert net.replay("sabde").missing == expected_missing
    # The native default always takes the lowest task, a.
    assert HeuristicsNet(activities, inputs, outputs).replay("sabde").missing == 1


def test_fits_rounds_fitness_to_float_but_exact_comparison_does_not():
    # a splits into b and c, which d joins. One case in many never reaches d, so it
    # leaves tokens behind, which costs less than a float can show.
    activities = tuple("abcd")
    inputs = ((), (frozenset({0}),), (frozenset({0}),), (frozenset({1}), frozenset({2})))
    outputs = ((frozenset({1}), frozenset({2})), (frozenset({3}),), (frozenset({3}),), ())
    seeded = HeuristicsNet(
        activities, inputs, outputs, prom_inputs=((), ((0,),), ((0,),), ((1,), (2,)))
    )
    exact = HeuristicsNet(activities, inputs, outputs)
    variants = [Variant(0, tuple("abcd"), 1_000_000), Variant(1, tuple("abc"), 1)]

    assert seeded.fitness(variants) == exact.fitness(variants) < 1.0
    assert np.float32(seeded.fitness(variants)) == 1.0
    assert seeded.fits(variants, 1.0)
    assert not exact.fits(variants, 1.0)


def test_seeded_replay_jumps_over_repeated_cases_correctly():
    many = [Variant(0, tuple("abcd"), 500), Variant(1, tuple("acbd"), 300)]
    one_by_one = [Variant(i, v.activities, 1) for v in many for i in range(v.frequency)]
    net = mine(many, PROM)
    assert net.fitness(many) == pytest.approx(net.fitness(one_by_one), abs=0)


def test_option_needs_the_native_miner():
    with pytest.raises(ValueError, match="native Heuristics Miner"):
        cluster_traces({("a", "b"): 1}, discover_algorithm=lambda log: None, prom_compatible=True)


def test_option_keeps_user_settings():
    log = {tuple("abc"): 5, tuple("abd"): 3, tuple("xyz"): 2}
    settings = HeuristicsSettings(dependency_threshold=0.5)
    result = cluster_traces(log, 2, settings=settings, prom_compatible=True)
    assert sum(c.n_cases for c in result) == 10
    assert result[0].model.prom_inputs is not None


def test_option_runs_in_both_modes_and_keeps_all_cases():
    log = {tuple("abcd"): 50, tuple("acbd"): 30, tuple("abd"): 10, tuple("xyz"): 8, tuple("xz"): 2}
    for window in (0, 0.25):
        result = cluster_traces(
            log, 2, window_size=window, cluster_remaining_traces=False, prom_compatible=True
        )
        assert sum(c.n_cases for c in result) == 100
