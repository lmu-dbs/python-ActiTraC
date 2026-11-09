import pandas as pd
import pytest

from actitrac import HeuristicsSettings, cluster, cluster_traces
from actitrac.clustering import _select
from conftest import make_variants


def sizes(result):
    return [c.n_cases for c in result]


def variant_sets(result):
    return [{"".join(v.activities) for v in c.variants} for c in result]


def two_groups():
    return {
        tuple("abcd"): 20, tuple("abd"): 10, tuple("acd"): 5,
        tuple("wxyz"): 15, tuple("wxz"): 8, tuple("wyz"): 2,
    }


def test_each_case_lands_in_exactly_one_cluster():
    result = cluster_traces(two_groups(), number_of_clusters=3)
    assert sum(sizes(result)) == 60
    seen = [v.activities for c in result for v in c.variants]
    assert len(seen) == len(set(seen)) == 6


def test_disjoint_processes_are_separated():
    result = cluster_traces(two_groups(), number_of_clusters=2, cluster_remaining_traces=False)
    groups = variant_sets(result)
    assert {"abcd", "abd", "acd"} in groups
    assert {"wxyz", "wxz", "wyz"} in groups


def test_number_of_clusters_includes_the_residual_cluster():
    # Five disjoint variants that a single model can never combine.
    log = {(chr(97 + i),): 10 - i for i in range(5)}
    result = cluster_traces(log, number_of_clusters=3, minimal_cluster_size=0.0)
    assert len(result) == 3
    assert result[-1].is_residual
    assert not result[0].is_residual


def test_residual_assignment_keeps_exactly_k_clusters(fitting_miner):
    log = make_variants({"ab": 10, "cd": 5, "ef": 1})
    result = cluster_traces(
        {v.activities: v.frequency for v in log},
        number_of_clusters=2,
        minimal_cluster_size=0.0,
        cluster_remaining_traces=False,
        discover_algorithm=None,
    )
    assert len(result) == 2
    assert sum(sizes(result)) == 16
    assert not any(c.is_residual for c in result)


def run_with(miner, counts, **kwargs):
    import actitrac.clustering as module

    original = module.resolve_miner
    module.resolve_miner = lambda *args: miner
    try:
        return cluster_traces({tuple(k): v for k, v in counts.items()}, **kwargs)
    finally:
        module.resolve_miner = original


def test_minimal_size_skips_non_fitting_variants_until_reached(fitting_miner):
    # Below 25% of 20 cases, a misfit is ignored and the search goes on.
    result = run_with(
        fitting_miner, {"a1": 4, "b1": 4, "a2": 3, "b2": 3, "a3": 3, "b3": 3},
        window_size=0, number_of_clusters=2, cluster_remaining_traces=False,
    )
    assert variant_sets(result)[0] >= {"a1", "a2", "a3"}


def trained_sets(miner):
    return [["".join(trace) for trace in call] for call in miner.calls]


def prefer_b(a, b):
    """A distance that makes b-variants nearest, so they are tried first."""
    return 0.0 if b[0] == "b" else 1.0


def test_frequency_mode_does_not_count_the_seed(fitting_miner):
    # The seed has 10 of 12 cases, yet the size stays below 25% of 12, so the
    # misfit b1 is skipped and a2 is still tried and trained on.
    result = run_with(
        fitting_miner, {"a1": 10, "b1": 1, "a2": 1},
        window_size=0, number_of_clusters=2, cluster_remaining_traces=False,
    )
    assert ["a1", "a2"] in trained_sets(fitting_miner)
    assert [v.activities for v in result[0].internal] == [tuple("a1"), tuple("a2")]


def test_distance_mode_counts_the_seed_and_stops_at_minimal_size(fitting_miner):
    # Size 10 meets 25% of 12 cases, so the first misfit ends phase 1.
    run_with(
        fitting_miner, {"a1": 10, "b1": 1, "a2": 1},
        window_size=1.0, distance_metric=prefer_b,
        number_of_clusters=1, cluster_remaining_traces=False,
    )
    assert ["a1", "a2"] not in trained_sets(fitting_miner)


def test_look_ahead_adds_without_retraining(fitting_miner):
    result = run_with(
        fitting_miner, {"a1": 10, "b1": 1, "a2": 1},
        window_size=1.0, distance_metric=prefer_b,
        number_of_clusters=2, cluster_remaining_traces=False,
    )
    first = result[0]
    assert [v.activities for v in first.internal] == [tuple("a1")]
    assert [v.activities for v in first.external] == [tuple("a2")]


def test_distance_mode_stops_when_the_seed_itself_misses_the_target():
    class Bad:
        def fitness(self, variants):
            return 0.0

        def trace_fitness(self, trace):
            return 0.0

    calls = []

    def miner(variants):
        calls.append(len(variants))
        return Bad()

    run_with(
        miner, {"a": 2, "b": 1}, window_size=1.0, distance_metric="osa",
        number_of_clusters=1, cluster_remaining_traces=False,
    )
    assert calls == [1]


def test_look_ahead_requires_perfect_fit_even_with_a_lower_target():
    class Model:
        def fitness(self, variants):
            return 1.0

        def trace_fitness(self, trace):
            return 0.95

    def miner(variants):
        return Model()

    # The grown model passes the target, so phase 1 takes everything; a stopped
    # cluster must not pull in the 0.95-fit rest through look-ahead.
    class StoppingModel(Model):
        def fitness(self, variants):
            return 1.0 if len(variants) == 1 else 0.5

    result = run_with(
        lambda variants: StoppingModel(), {"a": 10, "b": 1},
        target_fitness=0.9, window_size=0, number_of_clusters=1,
        cluster_remaining_traces=True,
    )
    assert variant_sets(result) == [{"a"}, {"b"}]


def test_unfit_seed_still_forms_a_cluster():
    class Bad:
        def fitness(self, variants):
            return 0.0

        def trace_fitness(self, trace):
            return 0.0

    result = run_with(
        lambda variants: Bad(), {"a": 2, "b": 1},
        window_size=0, number_of_clusters=3, cluster_remaining_traces=False,
    )
    assert variant_sets(result) == [{"a"}, {"b"}]


def test_residual_goes_to_best_fitting_cluster():
    class Model:
        def __init__(self, name):
            self.name = name

        def fitness(self, variants):
            return 1.0 if len(variants) == 1 else 0.0

        def trace_fitness(self, trace):
            return {("a", "x"): 0.1, ("b", "x"): 0.9}.get((self.name, trace[0]), 0.0)

    result = run_with(
        lambda variants: Model(variants[0].activities[0]), {"a": 5, "b": 3, "x": 1},
        window_size=0, number_of_clusters=2, cluster_remaining_traces=False,
        minimal_cluster_size=0.0,
    )
    assert variant_sets(result) == [{"a"}, {"b", "x"}]
    assert [v.activities for v in result[1].external] == [("x",)]


def test_stop_percentage_replaces_the_cluster_count(fitting_miner):
    counts = {"a1": 50, "b1": 30, "c1": 15, "d1": 5}
    result = run_with(
        fitting_miner, counts, window_size=0, stop_percentage=75,
        number_of_clusters=99, minimal_cluster_size=0.0,
    )
    # a=50% is below 75%, a+b=80% stops; c and d form the residual cluster.
    assert sizes(result) == [50, 30, 20]
    assert result[-1].is_residual


class TestWindow:
    variants = make_variants({"a": 10, "b": 5, "c": 5, "d": 2, "e": 1})
    distances = [9.0, 3.0, 1.0, 0.0, 0.0]

    def select(self, window_size, candidates=(0, 1, 2, 3, 4)):
        import numpy as np

        return _select(list(candidates), self.variants, np.array(self.distances), window_size)

    def test_window_is_a_share_of_remaining_variants_not_of_cases(self):
        # int(5 * 0.4) = 2 candidates; the second has frequency 5, and c ties it.
        assert self.select(0.4) == 2

    def test_small_window_keeps_only_the_most_frequent(self):
        assert self.select(0.1) == 0

    def test_full_window_sees_every_variant(self):
        assert self.select(1.0) == 3

    def test_distance_ties_prefer_the_more_frequent_variant(self):
        assert self.select(1.0, (3, 4)) == 3

    def test_no_distances_means_strict_frequency_order(self):
        assert _select([3, 4], self.variants, None, 0.5) == 3


@pytest.mark.parametrize("kwargs", [{"number_of_clusters": 0}, {"window_size": 1.5}])
def test_invalid_parameters_are_rejected(kwargs):
    with pytest.raises(ValueError):
        cluster_traces({("a",): 1}, **kwargs)


def test_empty_log_is_rejected():
    with pytest.raises(ValueError, match="no traces"):
        cluster_traces({})


def test_settings_require_the_native_miner():
    with pytest.raises(ValueError, match="native"):
        cluster_traces({("a",): 1}, settings=HeuristicsSettings(), discover_algorithm=print)


def test_run_is_deterministic():
    first = cluster_traces(two_groups(), number_of_clusters=3)
    second = cluster_traces(two_groups(), number_of_clusters=3)
    assert variant_sets(first) == variant_sets(second)


def event_frame():
    rows = []
    for case, trace in enumerate(["abd"] * 3 + ["acd"] * 2 + ["xyz"] * 4):
        for position, activity in enumerate(trace):
            rows.append((f"c{case}", activity, position, "complete"))
        rows.append((f"c{case}", trace[0], -1, "start"))
    return pd.DataFrame(
        rows,
        columns=["case:concept:name", "concept:name", "time:timestamp", "lifecycle:transition"],
    )


class TestResult:
    def test_labels_cover_every_case(self):
        result = cluster_traces(event_frame(), number_of_clusters=2)
        assert set(result.labels) == {f"c{i}" for i in range(9)}

    def test_augment_keeps_all_lifecycle_events(self):
        log = event_frame()
        augmented = cluster_traces(log, number_of_clusters=2).augment()
        assert len(augmented) == len(log)
        assert augmented.groupby("case:concept:name")["cluster"].nunique().max() == 1

    def test_logs_partition_the_original_log(self):
        log = event_frame()
        logs = cluster_traces(log, number_of_clusters=2).logs()
        assert sum(len(part) for part in logs) == len(log)

    def test_select_cluster(self):
        result = cluster_traces(event_frame(), number_of_clusters=2)
        assert result.select_cluster(0).equals(result.logs()[0])
        with pytest.raises(IndexError, match="only 2 clusters"):
            result.select_cluster(2)

    def test_group_by_cluster(self):
        result = cluster_traces(event_frame(), number_of_clusters=2)
        assert result.group_by_cluster().ngroups == len(result)

    def test_variant_dict_input_has_no_event_log(self):
        result = cluster_traces(two_groups(), number_of_clusters=2)
        assert sum(sum(log.values()) for log in result.variant_logs()) == 60
        with pytest.raises(ValueError, match="no event log"):
            result.logs()

    def test_metrics_report_clusters_average_and_full_log(self):
        metrics = cluster_traces(two_groups(), number_of_clusters=2).metrics()
        assert metrics["cluster"].tolist()[-2:] == ["weighted_average", "full_log"]
        assert metrics.iloc[-1]["cases"] == 60
        assert metrics.iloc[-2]["cases"] == 60
        assert metrics.iloc[-2]["ics_fitness"] >= metrics.iloc[-1]["ics_fitness"]

    def test_str_lists_cluster_sizes(self):
        result = cluster_traces(two_groups(), number_of_clusters=2)
        assert str(result).startswith("Trace clustering with 2 clusters of sizes ")


class TestEntroclusConvention:
    def test_variant_log_output(self):
        clusters = cluster(two_groups(), 2, outputshape="variant_log")
        assert sum(sum(c.values()) for c in clusters) == 60
        assert all(isinstance(c, dict) for c in clusters)

    def test_log_output(self):
        log = event_frame()
        clusters = cluster(log, 2, variant="frequency")
        assert sum(len(part) for part in clusters) == len(log)

    def test_variant_dict_requires_variant_log_output(self):
        with pytest.raises(ValueError, match="variant_log"):
            cluster(two_groups(), 2)

    @pytest.mark.parametrize("kwargs", [{"variant": "x"}, {"outputshape": "x"}])
    def test_invalid_options_are_rejected(self, kwargs):
        with pytest.raises(ValueError):
            cluster(event_frame(), 2, **kwargs)
