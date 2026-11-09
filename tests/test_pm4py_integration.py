"""Tests of everything that goes through pm4py."""

import pandas as pd
import pytest
from conftest import make_variants

pm4py = pytest.importorskip("pm4py")

from actitrac import PetriNetMiner, cluster_traces, cluster_traces_mo, mine  # noqa: E402
from actitrac import petri  # noqa: E402


def two_groups():
    return {
        tuple("abcd"): 20, tuple("abd"): 10, tuple("acd"): 5,
        tuple("wxyz"): 15, tuple("wxz"): 8, tuple("wyz"): 2,
    }


@pytest.mark.parametrize(
    "counts",
    [
        {"abc": 1},
        {"abd": 10, "acd": 10},
        {"abcd": 10, "acbd": 10},
        {"abbc": 10, "abc": 10},
        {"abcbd": 10, "abd": 10},
        {"a": 3},
    ],
)
def test_converted_net_agrees_with_ics_on_fitting_logs(counts):
    variants = make_variants(counts)
    net = mine(variants)
    assert net.fitness(variants) == 1.0
    petri_net, initial, final = net.to_petri_net()
    assert petri.alignment_fitness(variants, petri_net, initial, final) == 1.0
    assert petri.token_fitness(variants, petri_net, initial, final) == pytest.approx(1.0)


def test_converted_net_rejects_behaviour_outside_the_model():
    net, initial, final = mine(make_variants({"abc": 5})).to_petri_net()
    outside = make_variants({"cba": 1})
    assert petri.alignment_fitness(outside, net, initial, final) < 1.0
    assert petri.token_fitness(outside, net, initial, final) < 1.0


def test_converted_net_is_precise_for_a_sequence_and_not_for_a_choice():
    sequence = make_variants({"abc": 5})
    choice = make_variants({"abd": 5, "acd": 5, "aed": 5})
    wide = mine(choice)
    assert petri.etc_precision(sequence, *mine(sequence).to_petri_net()) == pytest.approx(1.0)
    narrow = make_variants({"abd": 5})
    assert petri.etc_precision(narrow, *wide.to_petri_net()) < 1.0


def test_alignment_fitness_ignores_silent_move_cost():
    log = make_variants({"abcd": 5, "acbd": 5, "ad": 3, "abd": 2})
    net, initial, final = pm4py.discover_petri_net_inductive(petri.event_log(log))
    assert petri.alignment_fitness(log, net, initial, final) == 1.0


def test_f_score():
    assert petri.f_score(1.0, 1.0) == 1.0
    assert petri.f_score(0.0, 0.0) == 0.0
    assert petri.f_score(0.5, 1.0) == pytest.approx(2 / 3)
    assert petri.f_score(0.5, 1.0, beta=2) > petri.f_score(0.5, 1.0)


def test_pt_connectivity_of_a_sequence():
    net, _, _ = mine(make_variants({"ab": 1})).to_petri_net()
    arcs, places, transitions = len(net.arcs), len(net.places), len(net.transitions)
    assert petri.pt_connectivity(net) == pytest.approx((arcs / places + arcs / transitions) / 2)


@pytest.mark.parametrize("metric", ["alignments", "token_replay"])
def test_pm4py_miner_can_replace_the_native_one(metric):
    def discover(log):
        return pm4py.discover_petri_net_inductive(log, noise_threshold=0.3)

    result = cluster_traces(
        two_groups(), number_of_clusters=2, target_fitness=0.99,
        discover_algorithm=discover, fitness_metric=metric, window_size=0,
    )
    assert sum(c.n_cases for c in result) == 60
    assert len(result) <= 2


def test_inductive_miner_without_noise_never_fails_the_target():
    # It guarantees fitness 1, so a single model absorbs the whole log.
    result = cluster_traces(
        two_groups(), number_of_clusters=3, window_size=0,
        discover_algorithm=pm4py.discover_petri_net_inductive,
    )
    assert [c.n_cases for c in result] == [60]


def test_invalid_fitness_metric_is_rejected():
    with pytest.raises(ValueError, match="fitness_metric"):
        PetriNetMiner(pm4py.discover_petri_net_inductive, "precision")


def test_metrics_with_conformance_measures():
    metrics = cluster_traces(two_groups(), number_of_clusters=2).metrics(
        conformance=True, alignments=True
    )
    for column in ("replay_fitness", "replay_precision", "f_score", "pt_connectivity"):
        assert metrics[column].notna().all()
    average, full = metrics.iloc[-2], metrics.iloc[-1]
    assert average["replay_precision"] >= full["replay_precision"]
    assert metrics["align_fitness"].iloc[:-2].notna().all()
    # Mining two unrelated processes together yields an unsound net.
    assert pd.isna(full["align_fitness"])
    assert pd.isna(full["align_precision"])


def test_event_log_input():
    frame = pd.DataFrame(
        [(f"c{c}", a, i) for c, t in enumerate(["ab"] * 2 + ["cd"]) for i, a in enumerate(t)],
        columns=["case:concept:name", "concept:name", "time:timestamp"],
    )
    frame["time:timestamp"] = pd.to_datetime(frame["time:timestamp"], unit="s", utc=True)
    log = pm4py.convert_to_event_log(frame)
    result = cluster_traces(log, number_of_clusters=2)
    assert sum(c.n_cases for c in result) == 3


class TestMultiObjective:
    def run(self, **kwargs):
        options = dict(number_of_clusters=2, seed=1, minimal_trace_correctness=0.0,
                       minimal_correctness=0.8)
        options.update(kwargs)
        return cluster_traces_mo(two_groups(), **options)

    def test_every_case_is_assigned_once(self):
        result = self.run()
        assert sum(c.n_cases for c in result) == 60
        seen = [v.activities for c in result for v in c.variants]
        assert len(seen) == len(set(seen))

    def test_same_seed_reproduces_the_run(self):
        first = [{v.activities for v in c.variants} for c in self.run(seed=3)]
        second = [{v.activities for v in c.variants} for c in self.run(seed=3)]
        assert first == second

    def test_seeds_come_from_frequent_variants(self):
        # ceil(10% of 6) = 1, so the first seed is always the most frequent variant.
        result = self.run(number_of_clusters=1)
        assert result[0].internal[0].activities == tuple("abcd")

    def test_impossible_thresholds_leave_only_a_residual_cluster(self):
        result = self.run(maximal_complexity=0.0)
        assert len(result) == 1
        assert result[0].is_residual
        assert result[0].n_cases == 60

    def test_residual_cluster_can_be_avoided(self):
        result = self.run(cluster_remaining_traces=False, minimal_correctness=0.999,
                          minimal_trace_correctness=0.999)
        assert not any(c.is_residual for c in result)
        assert sum(c.n_cases for c in result) == 60

    def test_invalid_cluster_count_is_rejected(self):
        with pytest.raises(ValueError):
            cluster_traces_mo(two_groups(), number_of_clusters=0)


def test_f_score_skips_precision_only_when_recall_rules_out_the_floor(monkeypatch):
    from actitrac.multiobjective import _f_score

    def no_precision(*args):
        raise AssertionError("precision should not be computed")

    monkeypatch.setattr(petri, "token_fitness", lambda *args: 0.5)
    monkeypatch.setattr(petri, "etc_precision", no_precision)
    assert _f_score([], None, None, None, 1.0, floor=0.95) == pytest.approx(2 / 3)

    monkeypatch.setattr(petri, "etc_precision", lambda *args: 0.5)
    assert _f_score([], None, None, None, 1.0, floor=0.6) == pytest.approx(0.5)
