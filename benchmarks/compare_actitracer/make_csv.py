"""Write NAME.csv for run_r.R, port.py and run_package.py, in the working directory.

Usage: python make_csv.py DATA_DIRECTORY NAME [NAME ...]

actitraceR keeps only events whose lifecycle is exactly "complete", and stops with an
error on a log with none. So NAME.csv changes the lifecycle where a log has none: an
upper-case COMPLETE becomes lower case and the other events stay out, as in the other
logs. Where no value means completion, as in BPIC 2013, all events count as complete.
NAME_raw.csv keeps the log's own values, to show what actitraceR does with them.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from compare_entropic import load_log  # noqa: E402

COLUMNS = ["case:concept:name", "concept:name", "time:timestamp", "lifecycle:transition"]


def refine(lifecycle):
    values = set(lifecycle.unique())
    if "complete" in values:
        return lifecycle
    if "COMPLETE" in values:
        return lifecycle.str.lower()
    return lifecycle.map(lambda _: "complete")


def main(data, names):
    for name in names:
        frame = load_log(data, name)
        if "lifecycle:transition" not in frame:
            frame["lifecycle:transition"] = "complete"
        frame = frame[COLUMNS].copy()
        frame.columns = ["case", "activity", "timestamp", "lifecycle"]
        frame["timestamp"] = frame["timestamp"].astype(str).str[:19]
        refined = frame.assign(lifecycle=refine(frame["lifecycle"].astype(str)))
        refined.to_csv(f"{name}.csv", index=False)
        print(name, len(frame), refined["lifecycle"].value_counts().to_dict())
        if not refined["lifecycle"].equals(frame["lifecycle"]):
            frame.to_csv(f"{name}_raw.csv", index=False)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
