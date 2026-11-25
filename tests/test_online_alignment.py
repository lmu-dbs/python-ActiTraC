"""Tests verifying alignment with online reference implementations.

Covers:
- ActiTraC-ProM (Java plugin semantics, prom_compatible mode, and optional live
  cross-check against benchmarks/prom_emulation/Emu.java when javac is present).
- actitraceR (bupaverse R package, via benchmarks/compare_actitracer/replica.py
  when pm4py is installed, plus documented fixes over actitraceR).
- EntropicClustering (entroclus calling convention and parity).
- ActiTraC-MO (De Koninck & De Weerdt 2016 parallel F-score & connectivity rules).
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from actitrac import (
    HeuristicsSettings,
    Variant,
    cluster,
    cluster_traces,
    cluster_traces_mo,
    extract_variants,
    mine,
    osa_distance,
)
from actitrac.distance import distance_rows

REPO_ROOT = Path(__file__).resolve().parent.parent
PROM_EMU_DIR = REPO_ROOT / "benchmarks" / "prom_emulation"
ACTITRACER_DIR = REPO_ROOT / "benchmarks" / "compare_actitracer"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _multi_process_frame() -> pd.DataFrame:
    """Synthetic multi-variant event log with choices, parallelism, loops and ties."""
    traces = (
        [("a", "b", "c", "d")] * 12
        + [("a", "c", "b", "d")] * 10
        + [("a", "b", "d")] * 6
        + [("a", "c", "d")] * 6  # frequency tie with abd
        + [("w", "x", "y", "z")] * 11
        + [("w", "x", "x", "y", "z")] * 8
        + [("w", "y", "z")] * 5
        + [("p", "q", "r")] * 3
        + [("m", "n")] * 2
    )
    rows = []
    for case_idx, trace in enumerate(traces):
        for pos, act in enumerate(trace):
            rows.append(
                (
                    f"c{case_idx}",
                    act,
                    pd.Timestamp("2025-01-01", tz="UTC") + pd.Timedelta(minutes=case_idx * 10 + pos),
                    "complete",
                )
            )
    return pd.DataFrame(
        rows,
        columns=["case:concept:name", "concept:name", "time:timestamp", "lifecycle:transition"],
    )


# ---------------------------------------------------------------------------
# ActiTraC-ProM alignment
# ---------------------------------------------------------------------------


class TestActiTraCProMAlignment:
    def test_classifier_mode_matches_prom_name_plus_lifecycle(self):
        frame = pd.DataFrame(
            [
                ("c1", "a", 1, "start"),
                ("c1", "a", 2, "complete"),
                ("c1", "b", 3, "complete"),
                ("c2", "a", 1, "complete"),
                ("c2", "b", 2, "complete"),
            ],
            columns=[
                "case:concept:name",
                "concept:name",
                "time:timestamp",
                "lifecycle:transition",
            ],
        )
        # ProM's default classifier combines name + lifecycle, distinguishing c1 and c2.
        prom_variants = extract_variants(frame, lifecycle="classifier").variants
        assert len(prom_variants) == 2
        assert prom_variants[0].activities == ("a+start", "a+complete", "b+complete")
        # actitraceR filters to complete only, collapsing c1 and c2 into one variant.
        r_variants = extract_variants(frame, lifecycle="complete").variants
        assert len(r_variants) == 1
        assert r_variants[0].activities == ("a", "b")

    def test_prom_compatible_distance_mode_replays_newest_variant_first(self):
        import actitrac.clustering as module

        orders = []

        class Model:
            def fitness(self, log):
                return 1.0

            def fits(self, log, target):
                orders.append([v.activities[0] for v in log])
                return True

            def trace_fitness(self, trace):
                return 0.0

        log = {("a",): 3, ("b",): 2, ("c",): 1}
        original = module.resolve_miner
        module.resolve_miner = lambda *args: (lambda variants: Model())
        try:
            cluster_traces(
                log,
                number_of_clusters=1,
                window_size=1.0,
                distance_metric=lambda x, y: 0.0,
                cluster_remaining_traces=False,
                prom_compatible=True,
            )
            distance_orders, orders[:] = list(orders), []
            cluster_traces(
                log,
                number_of_clusters=1,
                window_size=0,
                cluster_remaining_traces=False,
                prom_compatible=True,
            )
            frequency_orders = list(orders)
        finally:
            module.resolve_miner = original
        assert distance_orders[-1] == ["c", "b", "a"]  # newest first, as ProcessModel.add
        assert frequency_orders[-1] == ["a", "b", "c"]  # log order

    def test_prom_compatible_float32_minimal_cluster_size_boundary(self):
        # Verify _size_test follows ProM's float32 multiplication and truncation rules:
        # frequency mode compares float32(size) >= float32(left) * float32(mcs),
        # distance mode compares int(size) >= int(float32(left) * float32(mcs)).
        from actitrac.clustering import _size_test

        freq_test = _size_test(left=10, minimal_cluster_size=0.25, frequency_mode=True, prom_compatible=True)
        dist_test = _size_test(left=10, minimal_cluster_size=0.25, frequency_mode=False, prom_compatible=True)
        # 10 * 0.25 = 2.5 -> frequency needs >= 2.5 (so 2 is False, 3 is True),
        # while distance truncates int(2.5) == 2 (so 2 is True).
        assert not freq_test(2)
        assert freq_test(3)
        assert dist_test(2)

    def test_prom_compatible_keeps_fixed_symmetric_mra_distances(self):
        # Unlike ProM's MaxRepeatAlphabetDistanceXLog (which reads matrix[lo][hi - lo]),
        # python-ActiTraC always keeps symmetric, exact MRA distances.
        variants = extract_variants(_multi_process_frame()).variants
        row = distance_rows("mra", variants)
        matrix = np.vstack([row(i) for i in range(len(variants))])
        assert np.allclose(matrix, matrix.T, equal_nan=True)
        assert np.all(np.diag(matrix) == 0.0)

    def test_residual_assignment_breaks_ties_for_earlier_cluster_like_prom(self):
        # ProM uses strict `>` in residual assignment, so ties stay with the earliest cluster.
        import actitrac.clustering as module

        class EqualModel:
            def __init__(self, first):
                self.first = first

            def fitness(self, variants):
                return 1.0 if len(variants) == 1 else 0.0

            def trace_fitness(self, trace):
                return 1.0 if trace[0] == self.first else 0.5

        orig = module.resolve_miner
        module.resolve_miner = lambda *args: (lambda vs: EqualModel(vs[0].activities[0]))
        try:
            result = cluster_traces(
                {("a",): 10, ("b",): 5, ("z",): 1},
                number_of_clusters=2,
                minimal_cluster_size=0.0,
                window_size=0,
                cluster_remaining_traces=False,
            )
        finally:
            module.resolve_miner = orig
        # "z" scores 0.5 on both cluster 0 and cluster 1 -> must go to cluster 0.
        assert {v.activities for v in result[0].variants} == {("a",), ("z",)}
        assert {v.activities for v in result[1].variants} == {("b",)}

    def test_heuristics_l2l_suppressed_when_l1l_present_as_in_prom(self):
        # ProM suppresses length-2 loop (a, b) if a or b has a length-1 self-loop.
        settings = HeuristicsSettings(all_tasks_connected=False)

        # Positive control: without a self-loop on a, b -> a is accepted via two-step loop.
        control = mine(
            [Variant(0, tuple("sabae"), 20), Variant(1, tuple("sae"), 20)], settings
        )
        c_idx = {a: i for i, a in enumerate(control.activities)}
        assert any(c_idx["a"] in s for s in control.outputs[c_idx["b"]])

        # With a self-loop on a, b -> a is suppressed even though a-b-a occurs 20 times.
        suppressed = mine(
            [Variant(0, tuple("saabae"), 20), Variant(1, tuple("sae"), 20)], settings
        )
        s_idx = {a: i for i, a in enumerate(suppressed.activities)}
        assert any(s_idx["a"] in s for s in suppressed.outputs[s_idx["a"]])
        assert not any(s_idx["a"] in s for s in suppressed.outputs[s_idx["b"]])

    def test_distance_selection_sums_all_cluster_members(self):
        # In ActiTraC-ProM distance mode, candidate distance is the sum of distances
        # to every variant already in the cluster (not just the seed).
        import actitrac.clustering as module

        # Seed is "a". Distances:
        #   from a: b=1, c=2, d=10
        #   from b: c=100, d=1
        # After adding b: sum to c = 102, sum to d = 11 -> d must be tried before c!
        dist_table = {
            ("a", "b"): 1.0, ("a", "c"): 2.0, ("a", "d"): 10.0,
            ("b", "c"): 100.0, ("b", "d"): 1.0,
        }

        def metric(x, y):
            if x == y:
                return 0.0
            key = tuple(sorted((x[0], y[0])))
            return dist_table.get(key, 50.0)

        tried = []

        class RecordingMiner:
            def __call__(self, vs):
                tried.append([v.activities[0] for v in vs])

                class M:
                    def fitness(self, _v):
                        return 1.0

                    def trace_fitness(self, _t):
                        return 0.0

                return M()

        orig = module.resolve_miner
        module.resolve_miner = lambda *args: RecordingMiner()
        try:
            cluster_traces(
                {("a",): 10, ("b",): 5, ("c",): 4, ("d",): 3},
                number_of_clusters=1,
                window_size=1.0,
                distance_metric=metric,
                cluster_remaining_traces=False,
            )
        finally:
            module.resolve_miner = orig
        assert tried == [["a"], ["a", "b"], ["a", "b", "d"], ["a", "b", "d", "c"]]

    @pytest.mark.skipif(
        shutil.which("javac") is None or shutil.which("java") is None,
        reason="JDK (javac + java) is required to cross-check Emu.java",
    )
    def test_matches_prom_java_emulation_exactly(self, tmp_path):
        """Cross-check python-ActiTraC directly against benchmarks/prom_emulation/Emu.java."""
        frame = _multi_process_frame()
        dump_file = tmp_path / "log.txt"
        with dump_file.open("w", encoding="utf-8") as out:
            for _, group in frame.groupby("case:concept:name", sort=False):
                events = [
                    f"{a}\x1f{lc}"
                    for a, lc in zip(group["concept:name"], group["lifecycle:transition"])
                ]
                out.write("\t".join(events) + "\n")

        subprocess.run(
            [
                "javac",
                "-nowarn",
                "-d",
                str(tmp_path),
                str(PROM_EMU_DIR / "Emu.java"),
                str(PROM_EMU_DIR / "Mra.java"),
            ],
            check=True,
        )

        def run_emu(mode: str, *flags: str) -> list[int]:
            output = subprocess.run(
                ["java", "-cp", str(tmp_path), "Emu", str(dump_file), "3", mode, *flags],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            return [int(x) for x in re.search(r"\[([\d,]*)\]", output).group(1).split(",")]

        # Default frequency mode matches Emu with ProM bugs/RNG/float disabled.
        py_freq_default = cluster_traces(
            frame, number_of_clusters=3, window_size=0, cluster_remaining_traces=False
        )
        assert [c.n_cases for c in py_freq_default] == run_emu(
            "freq", "nosticky", "nofloat", "norng"
        )

        # prom_compatible frequency mode matches Emu with ProM RNG + float enabled.
        py_freq_prom = cluster_traces(
            frame,
            number_of_clusters=3,
            window_size=0,
            cluster_remaining_traces=False,
            prom_compatible=True,
        )
        assert [c.n_cases for c in py_freq_prom] == run_emu("freq", "nosticky")

        # Distance mode with fixed MRA matches Emu with distance bugs switched off.
        py_dist_prom = cluster_traces(
            frame,
            number_of_clusters=3,
            window_size=0.25,
            cluster_remaining_traces=False,
            prom_compatible=True,
        )
        assert [c.n_cases for c in py_dist_prom] == run_emu(
            "dist", "nosticky", "lookup=ok", "exactsum", "truelen", "allstreams"
        )


# ---------------------------------------------------------------------------
# EntropicClustering (entroclus) alignment
# ---------------------------------------------------------------------------


class TestEntropicClusteringAlignment:
    def test_cluster_wrapper_matches_cluster_traces_in_both_modes(self):
        frame = _multi_process_frame()
        for variant_name, window in (("frequency", 0), ("distance", 0.25)):
            direct = cluster_traces(
                frame,
                number_of_clusters=3,
                window_size=window,
                cluster_remaining_traces=False,
            )
            wrapped_logs = cluster(
                frame,
                3,
                outputshape="log",
                variant=variant_name,
                cluster_remaining_traces=False,
            )
            wrapped_variants = cluster(
                frame,
                3,
                outputshape="variant_log",
                variant=variant_name,
                cluster_remaining_traces=False,
            )
            assert [df["case:concept:name"].nunique() for df in wrapped_logs] == [
                c.n_cases for c in direct
            ]
            assert wrapped_variants == direct.variant_logs()

    def test_cluster_wrapper_forwards_prom_compatible(self):
        frame = _multi_process_frame()
        direct = cluster_traces(
            frame,
            number_of_clusters=3,
            window_size=0,
            cluster_remaining_traces=False,
            prom_compatible=True,
        )
        wrapped = cluster(
            frame,
            3,
            outputshape="variant_log",
            variant="frequency",
            cluster_remaining_traces=False,
            prom_compatible=True,
        )
        assert wrapped == direct.variant_logs()


# ---------------------------------------------------------------------------
# actitraceR & ActiTraC-MO alignment (requires pm4py)
# ---------------------------------------------------------------------------


class TestActiTraceRAlignment:
    def test_replica_with_all_switches_matches_python_actitrac(
        self, tmp_path, monkeypatch
    ):
        """Check python-ActiTraC against the actitraceR replica with all difference flags on.

        The replica reproduced actitraceR in all 48 finished benchmark runs; here the input
        CSVs are built directly by the test rather than generated by actitraceR itself.
        """
        pm4py = pytest.importorskip("pm4py")
        replica = _load_module("actitracer_replica", ACTITRACER_DIR / "replica.py")
        agreement = _load_module("actitracer_agreement", ACTITRACER_DIR / "agreement.py")

        frame = _multi_process_frame()
        # Write the CSVs expected by replica.py (same format as make_csv.py + dump_r.R).
        csv_frame = frame.copy()
        csv_frame.columns = ["case", "activity", "timestamp", "lifecycle"]
        csv_frame["timestamp"] = csv_frame["timestamp"].astype(str).str[:19]
        csv_frame.to_csv(tmp_path / "synth.csv", index=False)

        variants = extract_variants(frame, lifecycle="complete").variants
        acts = sorted({a for v in variants for a in v.activities})
        tok_id = {a: f"[{i + 1}]" for i, a in enumerate(acts)}
        pd.DataFrame(
            [
                (
                    str(v.id),
                    v.frequency,
                    "".join(tok_id[a] for a in v.activities),
                )
                for v in variants
            ],
            columns=["trace_id", "freq", "tokens"],
        ).to_csv(tmp_path / "dump_synth_var.csv", index=False)
        pd.DataFrame(
            [(cid, str(v.id)) for v in variants for cid in v.case_ids],
            columns=["case", "trace_id"],
        ).to_csv(tmp_path / "dump_synth_case.csv", index=False)

        monkeypatch.chdir(tmp_path)
        replica_sizes = replica.main(
            "synth",
            k=2,
            target=0.99,
            mcs=0.25,
            noise=0.2,
            out=str(tmp_path / "replica_all.csv"),
            dist="act",
            fit="pkg",
            mcsmode="start",
            seed="force",
            look="always",
            order="pkg",
            resid="pkg",
            feed="pkg",
        )

        keys = dict(
            activity_key="concept:name",
            case_id_key="case:concept:name",
            timestamp_key="time:timestamp",
        )
        py_result = cluster_traces(
            frame,
            number_of_clusters=2,
            target_fitness=0.99,
            minimal_cluster_size=0.25,
            window_size=1.0,
            distance_metric="osa",
            discover_algorithm=lambda log: pm4py.discover_petri_net_inductive(
                log, noise_threshold=0.2, **keys
            ),
            fitness_metric="alignments",
            cluster_remaining_traces=False,
            lifecycle="complete",
        )

        assert [c.n_cases for c in py_result] == replica_sizes
        rep_labels = agreement.load(str(tmp_path / "replica_all.csv"))
        py_labels = pd.Series(py_result.labels)
        assert agreement.adjusted_rand_index(rep_labels, py_labels) == pytest.approx(1.0)

    def test_fixes_documented_actitracer_defects(self):
        # 1. Activity-level OSA: inserting or replacing a multi-digit activity costs 1,
        #    unlike actitraceR's character-level OSA on tokens like "[12]".
        assert osa_distance(("a1", "a2"), ("a1", "a2", "a13")) == 1
        assert osa_distance(("a1", "a2"), ("a1", "a12")) == 1

        # 2. Case-insensitive lifecycle="complete" keeps BPIC12-style "COMPLETE" events
        #    (actitraceR drops every event on raw BPIC12).
        bpic12_like = pd.DataFrame(
            [
                ("c1", "A_SUBMITTED", 1, "COMPLETE"),
                ("c1", "A_PARTLYSUBMITTED", 2, "COMPLETE"),
                ("c1", "W_Work", 3, "START"),
            ],
            columns=[
                "case:concept:name",
                "concept:name",
                "time:timestamp",
                "lifecycle:transition",
            ],
        )
        result = cluster_traces(
            bpic12_like, number_of_clusters=1, cluster_remaining_traces=False, lifecycle="complete"
        )
        assert result[0].variants[0].activities == ("A_SUBMITTED", "A_PARTLYSUBMITTED")

        # 3. window_size actually controls candidate eligibility (actitraceR ignores it).
        log = {
            ("a", "b", "d"): 20,
            ("x", "y", "z"): 15,
            ("a", "c", "d"): 2,
            ("a", "e", "d"): 1,
        }
        # Distance favors "a*d" traces; with window_size=0.33 only ("x","y","z") is in the
        # initial window (1 of 3 candidates), whereas window_size=1.0 sees ("a","c","d").
        r_small = cluster_traces(
            log,
            number_of_clusters=2,
            minimal_cluster_size=0.25,
            window_size=0.33,
            distance_metric="osa",
            cluster_remaining_traces=False,
        )
        r_full = cluster_traces(
            log,
            number_of_clusters=2,
            minimal_cluster_size=0.25,
            window_size=1.0,
            distance_metric="osa",
            cluster_remaining_traces=False,
        )
        # In r_small, ("x","y","z") is tried first after seed ("a","b","d") and stops cluster 0
        # because seed alone (20) >= 25% of 38 (9); in r_full, ("a","c","d") joins cluster 0.
        assert ("a", "c", "d") not in {v.activities for v in r_small[0].internal}
        assert ("a", "c", "d") in {v.activities for v in r_full[0].internal}


class TestActiTraCMOAlignment:
    def test_residual_ranks_by_variant_f_score_first(self):
        # Unlike ProM's ParallelClusterer (which ranks residuals by cluster F-score first,
        # sending nearly everything to one cluster), python-ActiTraC ranks by variant F-score.
        pytest.importorskip("pm4py")
        log = {
            ("a", "b", "c"): 30,
            ("x", "y", "z"): 20,
            ("x", "y", "z", "w"): 2,
        }
        # Strict thresholds force ("x","y","z","w") to become unassigned in phase 1,
        # then residual assignment must place it with ("x","y","z"), not ("a","b","c").
        result = cluster_traces_mo(
            log,
            number_of_clusters=2,
            minimal_correctness=0.99,
            minimal_trace_correctness=0.99,
            cluster_remaining_traces=False,
            seed=0,
        )
        groups = [{v.activities for v in c.variants} for c in result]
        assert {("x", "y", "z"), ("x", "y", "z", "w")} in groups
        assert {("a", "b", "c")} in groups

    def test_seed_window_widens_instead_of_looping_forever(self):
        # ProM retries the top-10% window indefinitely if those seeds fail thresholds;
        # python-ActiTraC widens the window so a qualifying less-frequent seed can be found.
        pytest.importorskip("pm4py")
        # Make top variant have a complex/low-fitness pattern under tight complexity cap
        # while a less frequent variant is a clean 1-activity trace with low P/T connectivity.
        log = {
            ("a", "b", "c", "d", "e"): 100,
            ("p", "q", "r", "s", "t"): 90,
            ("u", "v", "w", "x", "y"): 80,
            ("k",): 5,
        }
        # Single-activity Petri net ("k",) has 2 places, 1 transition, 2 arcs -> connectivity 1.5;
        # 5-activity sequence has connectivity ~1.93.
        result = cluster_traces_mo(
            log,
            number_of_clusters=1,
            minimal_correctness=0.9,
            minimal_trace_correctness=0.9,
            maximal_complexity=1.6,
            seed=0,
        )
        non_residual = [c for c in result if not c.is_residual]
        assert len(non_residual) == 1
        assert non_residual[0].internal[0].activities == ("k",)

    def test_lower_pt_connectivity_breaks_f_score_ties(self):
        # Verify the tie-breaking order (score, trace_score, -complexity) from ActiTraC-MO.
        from actitrac.multiobjective import _Candidate

        simpler = _Candidate(None, [], score=0.95, trace_score=0.95, complexity=2.0)
        complex_one = _Candidate(None, [], score=0.95, trace_score=0.95, complexity=3.5)
        assert simpler.rank() > complex_one.rank()
