"""This package in actitraceR's configuration: Inductive Miner, alignments, OSA.

Usage: python run_package.py NAME K TARGET MCS WINDOW NOISE OUT.csv

The R wrapper pins pm4py 2.7.2, so run this on that version. Results depend on
PYTHONHASHSEED, because pm4py's Inductive Miner does.
"""
import sys
import time
import warnings

warnings.filterwarnings("ignore")
import pandas as pd
import pm4py

from actitrac import cluster_traces

KEYS = dict(activity_key="concept:name", case_id_key="case:concept:name", timestamp_key="time:timestamp")


def main(name, k, target, mcs, window, noise, out):
    frame = pd.read_csv(f"{name}.csv", keep_default_na=False, dtype={"case": str})
    frame.columns = ["case:concept:name", "concept:name", "time:timestamp", "lifecycle:transition"]
    frame["time:timestamp"] = pd.to_datetime(frame["time:timestamp"])
    start = time.time()
    result = cluster_traces(
        frame, number_of_clusters=int(k), target_fitness=float(target),
        minimal_cluster_size=float(mcs), window_size=float(window), distance_metric="osa",
        discover_algorithm=lambda log: pm4py.discover_petri_net_inductive(log, noise_threshold=float(noise), **KEYS),
        fitness_metric="alignments", cluster_remaining_traces=False, lifecycle="complete",
    )
    print([c.n_cases for c in result], f"{time.time() - start:.0f}s")
    pd.Series(result.labels, name="cluster").rename_axis("case").reset_index().to_csv(out, index=False)


if __name__ == "__main__":
    main(*sys.argv[1:])
