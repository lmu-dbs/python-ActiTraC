"""Compare this package with the ProM ActiTraC results of Peeperkorn et al.

Reruns the experiment of "Model-driven Stochastic Trace Clustering"
(https://arxiv.org/abs/2506.23776) with this package in place of ProM, and prints
the differences from the results published in
https://github.com/jaripeeperkorn/EntropicClustering.

    pip install "pm4py==2.7.8.4"
    python benchmarks/compare_entropic.py --data logs/ \
        --results EntropicClustering/experiment/experimental_results_one_cluster_size/results

Use the pm4py version above, the one the paper used. The Inductive Miner metrics
differ considerably between pm4py versions, even on the full log.

``--data`` holds the logs from 4TU.ResearchData, named as the keys of ``LOGS``:
Helpdesk.csv, BPIC15_1.xes to BPIC15_5.xes, and <name>.xes.gz for the others.
"""

from __future__ import annotations

import argparse
import math
import os
import time
from collections import Counter, defaultdict

import numpy as np
import pandas as pd
import pm4py

from actitrac import cluster_traces

CASE, ACTIVITY, TIME, LIFECYCLE = (
    "case:concept:name",
    "concept:name",
    "time:timestamp",
    "lifecycle:transition",
)
PM4PY_KEYS = {"activity_key": ACTIVITY, "case_id_key": CASE, "timestamp_key": TIME}

# Table 1 of the paper: number of clusters. Alignments did not finish on the last two.
LOGS = {
    "Helpdesk": 4,
    "RTFM": 4,
    "BPIC13_incidents": 5,
    "BPIC13_closedproblems": 5,
    "Hospital_Billing": 5,
    "Sepsis": 6,
    "BPIC12": 4,
    "BPIC15": 4,
}
NO_ALIGNMENTS = {"BPIC12", "BPIC15"}
MODES = {"actitrac_freq": 0, "actitrac_dist": 0.25}
METRICS = [
    "replay_fitness",
    "replay_precision",
    "align_fitness",
    "align_precision",
    "simplicity",
    "ER",
    "graph_density",
    "graph_entropy",
]
LOWER_IS_BETTER = {"ER", "graph_density", "graph_entropy"}
ER_FLOOR = 1e-10
ORIGINAL_CASE = "original_case"


def load_log(data: str, name: str) -> pd.DataFrame:
    if name == "Helpdesk":
        frame = pd.read_csv(
            os.path.join(data, "Helpdesk.csv"),
            usecols=["Case ID", "Activity", "Complete Timestamp"],
        )
        frame.columns = [CASE, ACTIVITY, TIME]
        frame[TIME] = pd.to_datetime(frame[TIME])
    elif name == "BPIC15":
        frame = _prepare_bpic15(data)
    else:
        frame = pm4py.read_xes(os.path.join(data, f"{name}.xes.gz"))
    frame[CASE] = frame[CASE].astype(str)
    return frame


def _prepare_bpic15(data: str) -> pd.DataFrame:
    """Rebuild the paper's merged log, which is not published.

    Each municipality's log keeps its case order and gets the same preparation:
    the first two parts of each activity code, direct repeats collapsed, and start
    and end events. This gives Table 1's statistics for this log, ProM's cluster
    sizes, and with case IDs merged its DFG (density 0.308).

    Two case IDs occur in two municipalities. ProM treats them as separate traces,
    while pm4py, which scored the paper's clusters, merges them. So clustering uses
    a case ID that is unique per municipality, and scoring uses ``ORIGINAL_CASE``.
    """
    parts = []
    for i in range(1, 6):
        part = pm4py.read_xes(os.path.join(data, f"BPIC15_{i}.xes"))[[CASE, ACTIVITY, TIME]]
        part[CASE] = part[CASE].astype(str)
        part[ACTIVITY] = part[ACTIVITY].astype(str).str.split("_").str[:2].str.join("_")
        order = {case: rank for rank, case in enumerate(part[CASE].drop_duplicates())}
        part = part.sort_values(TIME, kind="stable")
        part = part[part[ACTIVITY] != part.groupby(CASE)[ACTIVITY].shift()]
        times = part.groupby(CASE, sort=False)[TIME]
        start = times.min().reset_index().assign(**{ACTIVITY: "START"})
        start[TIME] -= pd.Timedelta(seconds=1)
        end = times.max().reset_index().assign(**{ACTIVITY: "END"})
        end[TIME] += pd.Timedelta(seconds=1)
        part = pd.concat([start, part, end], ignore_index=True)
        part["rank"] = part[CASE].map(order)
        part = part.sort_values(["rank", TIME], kind="stable").drop(columns="rank")
        part[ORIGINAL_CASE] = part[CASE]
        part[CASE] = f"{i}:" + part[CASE]
        parts.append(part)
    return pd.concat(parts, ignore_index=True)


def dfg_metrics(frame: pd.DataFrame) -> dict[str, float]:
    """Entropic relevance (Algorithm 1 of the paper), graph density and entropy."""
    variants = pm4py.stats.get_variants_as_tuples(frame)
    nodes: Counter = Counter()
    edges: Counter = Counter()
    for trace, count in variants.items():
        path = ("BOS", *trace, "EOS")
        for a, b in zip(path, path[1:]):
            nodes[a] += count
            edges[a, b] += count
        nodes["EOS"] += count

    total = 0.0
    for trace, count in variants.items():
        path = ("BOS", *trace, "EOS")
        probability = math.prod(edges[a, b] / nodes[a] for a, b in zip(path, path[1:]))
        total -= math.log2(max(probability, ER_FLOOR)) * count

    outgoing: defaultdict = defaultdict(int)
    for (a, _), count in edges.items():
        outgoing[a] += count
    return {
        "ER": total / sum(variants.values()),
        "graph_density": len(edges) / (len(nodes) * (len(nodes) - 1)),
        "graph_entropy": -sum(
            count / outgoing[a] * math.log2(count / outgoing[a])
            for (a, _), count in edges.items()
        ),
    }


def petri_net_metrics(frame: pd.DataFrame, alignments: bool) -> dict[str, float]:
    from pm4py.algo.evaluation.simplicity import algorithm as simplicity

    net, initial, final = pm4py.discover_petri_net_inductive(
        frame, noise_threshold=0.2, **PM4PY_KEYS
    )
    replay = pm4py.fitness_token_based_replay(frame, net, initial, final, **PM4PY_KEYS)
    metrics = {
        "simplicity": simplicity.apply(net),
        "replay_fitness": replay["log_fitness"],
        "replay_precision": pm4py.precision_token_based_replay(
            frame, net, initial, final, **PM4PY_KEYS
        ),
    }
    if alignments:
        fitness = pm4py.fitness_alignments(frame, net, initial, final, **PM4PY_KEYS)
        metrics["align_fitness"] = fitness["log_fitness"]
        metrics["align_precision"] = pm4py.precision_alignments(
            frame, net, initial, final, **PM4PY_KEYS
        )
    return metrics


def evaluate(frame: pd.DataFrame, alignments: bool) -> dict[str, float]:
    return {**dfg_metrics(frame), **petri_net_metrics(frame, alignments)}


def weighted_average(rows: list[dict[str, float]], sizes: list[int]) -> dict[str, float]:
    return {key: float(np.average([r[key] for r in rows], weights=sizes)) for key in rows[0]}


def published_rows(results: str, name: str) -> tuple[pd.DataFrame, dict[str, list[int]]]:
    """Return one row per method and ProM's cluster sizes, keeping cluster order."""
    table = pd.read_csv(os.path.join(results, f"{name}_results.csv"))
    cluster = table["cluster"].astype(str)
    summary = table[(table["method"] == "full_log") | (cluster == "average")]
    sizes = {
        mode: table[(table["method"] == mode) & (cluster != "average")]["num_traces"]
        .astype(int)
        .tolist()
        for mode in MODES
    }
    return summary.set_index("method"), sizes


def rank(value: float, others: pd.Series, metric: str) -> int:
    others = others[others > -1]  # -999 marks metrics that did not finish
    better = others < value if metric in LOWER_IS_BETTER else others > value
    return 1 + int(better.sum())


def compare_log(
    data: str, results: str, name: str, ranks: dict, prom_compatible: bool = False
) -> None:
    frame = load_log(data, name)
    alignments = name not in NO_ALIGNMENTS
    # ProM's classifier joins activity and lifecycle, while the metrics use the
    # activity alone, as pm4py's defaults do in the paper.
    events = frame[[CASE, ACTIVITY, TIME]]
    scored = events.assign(**{CASE: frame[ORIGINAL_CASE]}) if ORIGINAL_CASE in frame else events
    table, prom_sizes = published_rows(results, name)

    def show(label: str, mine: dict, published: pd.Series) -> None:
        cells = [
            f"{metric}={mine[metric]:.3f}/{published[metric]:.3f}"
            for metric in METRICS
            if metric in mine
        ]
        print(f"  {label:6s} " + " ".join(cells), flush=True)

    print(f"\n{name}  (metrics are this package/ProM)")
    show("full", evaluate(scored, alignments), table.loc["full_log"])

    for mode, window in MODES.items():
        started = time.time()
        result = cluster_traces(
            frame,
            number_of_clusters=LOGS[name],
            target_fitness=1.0,
            minimal_cluster_size=0.25,
            window_size=window,
            cluster_remaining_traces=False,
            prom_compatible=prom_compatible,
        )
        seconds = time.time() - started
        groups = [group for _, group in scored.groupby(events[CASE].map(result.labels))]
        sizes = [group[CASE].nunique() for group in groups]
        prom = prom_sizes[mode]
        padded = sizes + [0] * (len(prom) - len(sizes))
        differ = sum(abs(a - b) for a, b in zip(padded, prom)) / 2 / max(sum(sizes), sum(prom))
        print(f"  {mode[9:]}: {sizes} ProM {prom}, differ {differ:.1%}, {seconds:.1f}s")

        rows = [evaluate(group, alignments) for group in groups]
        mine = weighted_average(rows, sizes)
        show(mode[9:], mine, table.loc[mode])
        for metric in mine:
            if table.loc[mode, metric] <= -1:
                continue
            others = table.drop(index=mode)[metric].astype(float)
            ranks[mode, metric].append(
                (rank(mine[metric], others, metric), rank(table.loc[mode, metric], others, metric))
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", required=True, help="directory with the event logs")
    parser.add_argument("--results", required=True, help="EntropicClustering results directory")
    parser.add_argument("--logs", nargs="*", default=list(LOGS), choices=list(LOGS))
    parser.add_argument("--prom-compatible", action="store_true", help="use prom_compatible=True")
    args = parser.parse_args()

    ranks: defaultdict = defaultdict(list)
    for name in args.logs:
        compare_log(args.data, args.results, name, ranks, args.prom_compatible)

    print("\nAverage rank among the paper's 12 methods, this package/ProM")
    for (mode, metric), values in sorted(ranks.items()):
        mine, prom = zip(*values)
        print(f"  {mode:14s} {metric:17s} {np.mean(mine):5.2f} {np.mean(prom):5.2f}  n={len(values)}")


if __name__ == "__main__":
    main()
