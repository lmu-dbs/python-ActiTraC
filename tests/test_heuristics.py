import pytest
from conftest import make_variants

from actitrac import HeuristicsSettings, mine
from actitrac.heuristics import HeuristicsNet, Replay


def sets(net, activity, side):
    index = {a: i for i, a in enumerate(net.activities)}
    groups = getattr(net, side)[index[activity]]
    return {frozenset(net.activities[i] for i in group) for group in groups}


def test_sequence_replays_perfectly():
    variants = make_variants({"abc": 1})
    net = mine(variants)
    assert net.replay("abc") == Replay(parsed=3, missing=0, extra=0)
    assert net.fitness(variants) == 1.0


def test_exclusive_choice_is_one_xor_set():
    variants = make_variants({"abd": 10, "acd": 10})
    net = mine(variants)
    assert sets(net, "a", "outputs") == {frozenset("bc")}
    assert sets(net, "d", "inputs") == {frozenset("bc")}
    assert net.fitness(variants) == 1.0


def test_parallel_branches_are_separate_sets():
    variants = make_variants({"abcd": 10, "acbd": 10})
    net = mine(variants)
    assert sets(net, "a", "outputs") == {frozenset("b"), frozenset("c")}
    assert sets(net, "d", "inputs") == {frozenset("b"), frozenset("c")}
    assert net.fitness(variants) == 1.0


def test_self_loop_replays_perfectly():
    variants = make_variants({"abbc": 10, "abc": 10})
    assert mine(variants).fitness(variants) == 1.0


def test_rare_self_loop_stays_below_the_threshold():
    # 5 / (5 + 1) is below ProM's L1L threshold of 0.9.
    variants = make_variants({"abbc": 5, "abc": 5})
    assert mine(variants).fitness(variants) < 1.0


def test_two_step_loop_replays_perfectly():
    variants = make_variants({"abcbd": 10, "abd": 10})
    assert mine(variants).fitness(variants) == 1.0


def test_skipped_activity_counts_missing_and_extra_tokens():
    net = mine(make_variants({"abc": 1}))
    # c lacks b's token, and a's unconsumed token stays behind.
    assert net.replay("ac") == Replay(parsed=1, missing=1, extra=1)
    assert net.trace_fitness("ac") == pytest.approx((1 - 1 - 1) / 2)


def test_unknown_activity_counts_as_missing_token():
    net = mine(make_variants({"ab": 1}))
    assert net.replay("axb") == Replay(parsed=2, missing=1, extra=0)


def test_ics_formula_on_hand_computed_log():
    net = mine(make_variants({"abc": 1}))
    log = make_variants({"abc": 1, "ac": 1})
    # parsed=3+1, missing=1 over 1 case, extra=1 over 1 case, 5 events, 2 cases:
    # (4 - (1/(2-1+1) + 1/(2-1+1))) / 5
    assert net.fitness(log) == pytest.approx(3 / 5)


def test_ics_weights_by_frequency():
    net = mine(make_variants({"abc": 1}))
    log = make_variants({"abc": 3, "ac": 1})
    # parsed=9+1, missing=1 and extra=1 over denominators 4-1+1: (10 - 2/4) / 11
    assert net.fitness(log) == pytest.approx(9.5 / 11)


def test_ics_can_be_negative():
    net = mine(make_variants({"abc": 1}))
    assert net.trace_fitness("c") < 0


def test_trace_starting_without_the_start_activity_keeps_start_token():
    net = mine(make_variants({"abc": 1}))
    # b lacks a's token, and the source token stays behind.
    assert net.replay("bc") == Replay(parsed=1, missing=1, extra=1)


def test_all_tasks_connected_keeps_infrequent_activity_connected():
    variants = make_variants({"abd": 100, "acd": 1})
    net = mine(variants)
    assert net.fitness(variants) == 1.0
    disconnected = mine(variants, HeuristicsSettings(all_tasks_connected=False))
    assert sets(disconnected, "c", "inputs") == set()


def test_small_logs_lower_unreachable_thresholds():
    settings = HeuristicsSettings().for_log_size(1)
    assert settings.dependency_threshold == pytest.approx(0.49)
    assert settings.l1l_threshold == pytest.approx(0.49)
    assert settings.l2l_threshold == pytest.approx(0.49)
    assert HeuristicsSettings().for_log_size(100).dependency_threshold == 0.9
    fixed = HeuristicsSettings(adapt_to_log_size=False).for_log_size(1)
    assert fixed.dependency_threshold == 0.9


def test_conflicting_or_join_consumes_the_smallest_cover():
    net = HeuristicsNet(
        ("a", "b", "c", "d"),
        inputs=(
            (),
            (frozenset({0}),),
            (frozenset({0}),),
            (frozenset({1, 2}), frozenset({1})),
        ),
        outputs=(
            (frozenset({1}), frozenset({2})),
            (frozenset({3}),),
            (frozenset({3}),),
            (),
        ),
    )
    # b alone covers both input sets of d, so c's token is the only one left over.
    assert net.replay("abcd") == Replay(parsed=4, missing=0, extra=1)
