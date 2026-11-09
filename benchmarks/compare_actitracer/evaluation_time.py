"""Time the steps of actitraceR's final evaluation, in its order, to find the slow one.

Usage: python evaluation_time.py NAME LABELS.csv NOISE clusters|whole

"clusters" times fitness and precision for each cluster's model at the noise threshold.
"whole" times the model of the whole log, which actitraceR mines without a threshold.
"""
import sys
import time
import warnings

warnings.filterwarnings("ignore")
import pandas as pd
import pm4py

from agreement import load

KEYS = dict(activity_key="concept:name", case_id_key="case:concept:name", timestamp_key="time:timestamp")


def timed(label, function):
    start = time.time()
    print(f"start {label}", flush=True)
    value = function()
    print(f"done {label}: {time.time() - start:.1f} s", flush=True)
    return value


def main(name, labels, noise, stage):
    frame = pd.read_csv(f"{name}.csv", keep_default_na=False, dtype={"case": str})
    frame.columns = ["case:concept:name", "concept:name", "time:timestamp", "lifecycle:transition"]
    frame["time:timestamp"] = pd.to_datetime(frame["time:timestamp"])
    frame = frame[frame["lifecycle:transition"] == "complete"]
    if stage == "whole":
        groups = [("whole log", frame, 0.0)]
    else:
        cluster = frame["case:concept:name"].map(load(labels))
        groups = [(f"cluster {i}", group, float(noise)) for i, group in frame.groupby(cluster)]
    models = [(label, group, pm4py.discover_petri_net_inductive(group, noise_threshold=n, **KEYS)) for label, group, n in groups]
    for label, group, model in models:
        print(label, "places", len(model[0].places), "transitions", len(model[0].transitions), flush=True)
        timed(f"{label} fitness", lambda: pm4py.fitness_alignments(group, *model, **KEYS))
    for label, group, model in models:
        timed(f"{label} precision", lambda: pm4py.precision_alignments(group, *model, **KEYS))


if __name__ == "__main__":
    main(*sys.argv[1:])
