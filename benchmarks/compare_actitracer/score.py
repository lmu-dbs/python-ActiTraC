"""Score run_docker.sh's and run_docker_rest.sh's clusters with the paper's metrics.

Usage: PYTHONHASHSEED=0 python score.py DATA_DIRECTORY RESULT_DIRECTORY OUT.json

Run on the benchmark image, so the metrics use the same pm4py as compare_entropic.py.
It also describes the logs and clusters them with python-ActiTraC's defaults, to compare
those clusters with actitraceR's. As in compare_entropic.py, the metrics use all events
of a log, BPIC12 and BPIC15 skip alignments, and BPIC15 scores with the original case IDs.
A run with no labels, such as one that hit the time limit, is listed under "missing".
"""
import json
import os
import sys
from multiprocessing import Pool

import pandas as pd
import pm4py

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from actitrac import cluster_traces  # noqa: E402
from agreement import adjusted_rand_index, load  # noqa: E402
from compare_entropic import (  # noqa: E402
    ACTIVITY, CASE, LOGS, NO_ALIGNMENTS, ORIGINAL_CASE, TIME, evaluate, load_log, weighted_average,
)

LABELS = {
    "Helpdesk": ["r_w25", "r_t1", "pyactitrac_w25", "pyactitrac_w1", "pyactitrac_t1_w25", "pyactitrac_t1_w1"],
    "Sepsis": ["r_sep_t99", "r_sep_t1", "pyactitrac_sep_t99_w25", "pyactitrac_sep_t1_w25"],
}
REST = ["BPIC13_closedproblems", "BPIC13_incidents", "RTFM", "Hospital_Billing", "BPIC12", "BPIC15"]
for _name in REST:
    LABELS[_name] = [f"{tool}_{_name}_{target}{suffix}" for target in ("t10", "t099")
                     for tool, suffix in (("r", ""), ("replica", ""), ("pyactitrac", "_w25"), ("pyactitrac", "_w1"))]
# The label file each log's native clusters are compared with, at target 1.00.
TARGET_ONE = {"Helpdesk": "r_t1", "Sepsis": "r_sep_t1", **{name: f"r_{name}_t10" for name in REST}}
SEEDS = (0, 1)
NATIVE = {
    "frequency, default": (0, False),
    "frequency, prom_compatible": (0, True),
    "distance, default": (0.25, False),
    "distance, prom_compatible": (0.25, True),
}


def score(frame, labels, alignments):
    events = frame[[CASE, ACTIVITY, TIME]]
    scored = events.assign(**{CASE: frame[ORIGINAL_CASE]}) if ORIGINAL_CASE in frame else events
    groups = [group for _, group in scored.groupby(events[CASE].map(labels))]
    sizes = [group[CASE].nunique() for group in groups]
    return sizes, weighted_average([evaluate(group, alignments) for group in groups], sizes)


def has_labels(path):
    # A run with no traces, such as actitraceR's on a raw log, writes a file without the columns.
    return os.path.exists(path) and "case" in pd.read_csv(path, nrows=0).columns and len(load(path)) > 0


def score_run(job):
    data, directory, name, tag, seed = job
    sizes, metrics = score(load_log(data, name), load(os.path.join(directory, f"{tag}_s{seed}.csv")), name not in NO_ALIGNMENTS)
    return {"log": name, "tag": tag, "seed": seed, "sizes": sizes, "metrics": metrics}


def native_run(job):
    data, directory, name, mode = job
    window, compatible = NATIVE[mode]
    frame = load_log(data, name)
    result = cluster_traces(
        frame, number_of_clusters=LOGS[name], target_fitness=1.0, minimal_cluster_size=0.25,
        window_size=window, cluster_remaining_traces=False, prom_compatible=compatible,
    )
    labels = pd.Series(result.labels)
    path = os.path.join(directory, f"{TARGET_ONE[name]}_s0.csv")
    return {
        "log": name, "mode": mode, "sizes": [c.n_cases for c in result],
        "ari_against_actitraceR": adjusted_rand_index(labels, load(path)) if has_labels(path) else None,
    }


def describe(job):
    data, name = job
    frame = load_log(data, name)
    if name == "BPIC15":
        lifecycle = pm4py.read_xes(os.path.join(data, "BPIC15_1.xes"))["lifecycle:transition"]
    else:
        lifecycle = frame["lifecycle:transition"] if "lifecycle:transition" in frame else None
    traces = frame.sort_values([CASE, TIME], kind="stable").groupby(CASE, sort=False)[ACTIVITY].agg(tuple)
    return {
        "log": name, "k": LOGS[name], "cases": int(traces.size), "events": len(frame),
        "variants": int(traces.nunique()), "activities": int(frame[ACTIVITY].nunique()),
        "lifecycle": None if lifecycle is None else {str(k): int(v) for k, v in lifecycle.value_counts().items()},
    }


def main(data, directory, out):
    runs = [(n, t, s) for n, tags in LABELS.items() for t in tags for s in SEEDS]
    present = [run for run in runs if has_labels(os.path.join(directory, f"{run[1]}_s{run[2]}.csv"))]
    with Pool(int(os.environ.get("JOBS", 16))) as pool:
        output = {
            "logs": pool.map(describe, [(data, name) for name in LOGS], 1),
            "native": pool.map(native_run, [(data, directory, n, m) for n in LABELS for m in NATIVE], 1),
            "scores": pool.map(score_run, [(data, directory, *run) for run in present], 1),
            "missing": [{"log": n, "tag": t, "seed": s} for n, t, s in runs if (n, t, s) not in present],
        }
    with open(out, "w") as file:
        json.dump(output, file, indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:])
