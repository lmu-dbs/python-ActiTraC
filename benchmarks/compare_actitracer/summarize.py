"""Tables from the output of run_docker.sh and run_docker_rest.sh.

Usage: python summarize.py RESULT_DIRECTORY
"""
import os
import re
import sys

import pandas as pd

from agreement import adjusted_rand_index, load

SEEDS = (0, 1, 2, 3)
HELPDESK_FLAGS = ("look", "dist", "mcs", "fit", "feed", "order", "resid", "seed", "all")
# Setting: (actitraceR tag, port tag, package tag at window 0.25, at window 1).
SETTINGS = {
    "Target 0.99, mcs 0.25": ("w25", "base", "w25", "w1"),
    "Target 0.95, mcs 0.25": ("t95", "t95", "t95_w25", "t95_w1"),
    "Target 0.99, mcs 0.60": ("mcs60", "mcs60", "mcs60_w25", "mcs60_w1"),
    "Target 1.00, mcs 0.25": ("t1", "t1", "t1_w25", "t1_w1"),
    "Target 1.00, mcs 0.25, noise 0": ("noise0", "noise0", "noise0_w25", "noise0_w1"),
}
SEPSIS = {
    "Target 0.99": ("sep_t99", "sep_t99", "sep_t99_w25", "sep_t99_w1"),
    "Target 1.00": ("sep_t1", "sep_t1", "sep_t1_w25", "sep_t1_w1"),
}
REST = ("BPIC13_closedproblems", "BPIC13_incidents", "RTFM", "Hospital_Billing", "BPIC12", "BPIC15")


def path(directory, tool, tag, seed):
    return os.path.join(directory, f"{tool}_{tag}_s{seed}.csv")


def labels(directory, tool, tag, seed):
    file = path(directory, tool, tag, seed)
    # A run with no traces writes a file without the columns.
    if not os.path.exists(file) or "case" not in pd.read_csv(file, nrows=0).columns:
        return None
    return load(file)


def sizes(series):
    if series is None:
        return "none"
    return ", ".join(str(n) for n in series.value_counts().sort_index())


def ari(a, b):
    return "n/a" if a is None or b is None else f"{adjusted_rand_index(a, b):.3f}"


def log_times(directory, tool, tag, seed):
    file = os.path.join(directory, f"{tool}_{tag}_s{seed}.log")
    if not os.path.exists(file):
        return {}
    text = open(file, errors="replace").read()
    times = {}
    for key, pattern in (("clustering", r"labels:.*seconds:\s*([\d.]+)"), ("total", r"sizes:.*seconds:\s*([\d.]+)"),
                         ("python", r"(\d+)s\s*$")):
        match = re.search(pattern, text, re.M)
        if match:
            times[key] = float(match.group(1))
    # The status is the last line, though a progress bar cut off by the time limit can share it.
    status = re.search(r"status (\d+)\s*\Z", text)
    times["status"] = int(status.group(1)) if status else None
    return times


def comparison(directory, settings, seeds):
    for name, (r_tag, port_tag, package_quarter, package_one) in settings.items():
        print(f"\n### {name}\n")
        print("| Seed | actitraceR | Port | ARI R, port | Package w=0.25 | ARI | Package w=1 | ARI |")
        print("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for seed in seeds:
            r = labels(directory, "r", r_tag, seed)
            port = labels(directory, "port", port_tag, seed)
            quarter = labels(directory, "package", package_quarter, seed)
            one = labels(directory, "package", package_one, seed)
            print(f"| {seed} | {sizes(r)} | {sizes(port)} | {ari(r, port)} | {sizes(quarter)} | {ari(r, quarter)} "
                  f"| {sizes(one)} | {ari(r, one)} |")


def self_agreement(directory, tool, tag, seeds):
    runs = {seed: labels(directory, tool, tag, seed) for seed in seeds}
    found = [seed for seed in seeds if runs[seed] is not None]
    outcomes = {}
    for seed in found:
        outcomes.setdefault(sizes(runs[seed]), []).append(seed)
    return outcomes, min((adjusted_rand_index(runs[a], runs[b]) for a in found for b in found if a < b), default=None)


def main(directory):
    print("## Helpdesk")
    comparison(directory, SETTINGS, SEEDS)

    print("\n## actitraceR at three windows (target 0.99, mcs 0.25)\n")
    print("| Seed | w=0 | w=0.25 | w=1 | ARI w=0, w=0.25 | ARI w=0.25, w=1 |")
    print("| --- | --- | --- | --- | --- | --- |")
    for seed in SEEDS:
        a, b, c = (labels(directory, "r", t, seed) for t in ("w0", "w25", "w1"))
        print(f"| {seed} | {sizes(a)} | {sizes(b)} | {sizes(c)} | {ari(a, b)} | {ari(b, c)} |")

    print("\n## Port against actitraceR, any seed (best ARI)\n")
    print("| Setting | R seed | Best port seed | ARI |")
    print("| --- | --- | --- | --- |")
    for name, (r_tag, port_tag, _, _) in SETTINGS.items():
        for seed in SEEDS:
            r = labels(directory, "r", r_tag, seed)
            scores = {s: labels(directory, "port", port_tag, s) for s in SEEDS}
            scores = {s: adjusted_rand_index(r, v) for s, v in scores.items() if v is not None and r is not None}
            if scores:
                best = max(scores, key=scores.get)
                print(f"| {name} | {seed} | {best} | {scores[best]:.3f} |")

    print("\n## One difference at a time, from actitraceR's behaviour in the port\n")
    print("| Change | Seed | Sizes | ARI against port base, same seed |")
    print("| --- | --- | --- | --- |")
    for flag in HELPDESK_FLAGS:
        for seed in SEEDS:
            run = labels(directory, "port", flag, seed)
            print(f"| {flag} | {seed} | {sizes(run)} | {ari(run, labels(directory, 'port', 'base', seed))} |")

    print("\n## All differences on, against this package at window 1\n")
    print("| Seed | Port, all on | Package | ARI |")
    print("| --- | --- | --- | --- |")
    for seed in SEEDS:
        a, b = labels(directory, "port", "all", seed), labels(directory, "package", "w1", seed)
        print(f"| {seed} | {sizes(a)} | {sizes(b)} | {ari(a, b)} |")

    print("\n## Hash-seed variation (ARI is the lowest between seeds)\n")
    print("| Tool | Setting | Outcomes and seeds | Lowest ARI |")
    print("| --- | --- | --- | --- |")
    for tool, tags in (("r", ("w25", "t95", "mcs60", "t1", "noise0")), ("port", ("base", "t95", "mcs60", "t1", "noise0")),
                       ("package", ("w25", "w1", "t95_w25", "mcs60_w25", "t1_w25", "noise0_w25"))):
        for tag in tags:
            outcomes, low = self_agreement(directory, tool, tag, SEEDS)
            shown = "; ".join(f"{k} ({','.join(map(str, v))})" for k, v in outcomes.items())
            print(f"| {tool} | {tag} | {shown} | {'n/a' if low is None else f'{low:.3f}'} |")

    print("\n## Sepsis")
    comparison(directory, SEPSIS, (0, 1))

    for name in REST:
        print(f"\n## {name}")
        comparison(directory, {
            "Target 1.00": (f"{name}_t10", f"{name}_t10", f"{name}_t10_w25", f"{name}_t10_w1"),
            "Target 0.99": (f"{name}_t099", f"{name}_t099", f"{name}_t099_w25", f"{name}_t099_w1"),
        }, (0, 1))

    print("\n## Times and exit status\n")
    print("| File | Status | Clustering s | Total s |")
    print("| --- | --- | --- | --- |")
    for file in sorted(f for f in os.listdir(directory) if re.match(r"(r|port|package)_.*\.log$", f)):
        tool, tag, seed = re.match(r"(r|port|package)_(.*)_s(\d+)\.log$", file).groups()
        t = log_times(directory, tool, tag, seed)
        clustering = t.get("clustering", t.get("python", ""))
        print(f"| {file[:-4]} | {t.get('status')} | {clustering} | {t.get('total', t.get('python', ''))} |")


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    main(sys.argv[1])
