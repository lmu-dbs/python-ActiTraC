"""Turn the Docker outputs into the CSV files behind the comparison page.

    python docs/comparison/build_data.py BENCH_OUT R_OUT [DEST]

BENCH_OUT is /data/out from benchmarks/docker/run.sh. R_OUT is /data/r_out from
benchmarks/compare_actitracer/run_docker.sh and run_docker_rest.sh, with the output of
score.py saved there as score.json. Logs of runs that were repeated with a longer limit
go in R_OUT/timeout_12h/. DEST defaults to docs/comparison/data.
"""

import csv
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT, ROUT = sys.argv[1], sys.argv[2]
DASH = sys.argv[3] if len(sys.argv) > 3 else os.path.join(HERE, "data")
sys.path.insert(0, os.path.join(HERE, "..", "..", "benchmarks", "compare_actitracer"))
import pandas as pd  # noqa: E402

from agreement import adjusted_rand_index, load  # noqa: E402

LOGS = [
    "Helpdesk",
    "RTFM",
    "BPIC13_incidents",
    "BPIC13_closedproblems",
    "Hospital_Billing",
    "Sepsis",
    "BPIC12",
    "BPIC15",
]
NAMES = {
    "Helpdesk": "Helpdesk",
    "RTFM": "RTFM",
    "BPIC13_incidents": "BPIC13 incidents",
    "BPIC13_closedproblems": "BPIC13 closed problems",
    "Hospital_Billing": "Hospital Billing",
    "Sepsis": "Sepsis",
    "BPIC12": "BPIC12",
    "BPIC15": "BPIC15",
}
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
score = json.load(open(f"{ROUT}/score.json"))


def write(name, rows, columns):
    with open(f"{DASH}/{name}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, columns)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in columns})
    print(name, len(rows))


def parse(mode, log):
    text = open(f"{OUT}/{mode}/{log}.out", errors="replace").read().replace("\r", "\n")
    res = {}
    for key in ("full", "freq", "dist"):
        line = re.search(rf"^  {key}\s+(replay.*)$", text, re.M)[1]
        pairs = re.findall(r"(\w+)=(-?[\d.]+)/(-?[\d.]+)", line)
        res[key] = {"mine": {k: a for k, a, _ in pairs}, "prom": {k: b for k, _, b in pairs}}
    for key in ("freq", "dist"):
        m = re.search(rf"^  {key}: \[(.*?)\] ProM \[(.*?)\], differ ([\d.]+)%, ([\d.]+)s", text, re.M)
        res[key].update(sizes=m[1], prom_sizes=m[2], gap=m[3], seconds=m[4])
    return res


default = {log_name: parse("default", log_name) for log_name in LOGS}
option = {log_name: parse("prom_compatible", log_name) for log_name in LOGS}

# logs
facts = {x["log"]: x for x in score["logs"]}
logs = []
for log_name in LOGS:
    f = facts[log_name]
    lc = f["lifecycle"]
    if log_name == "Helpdesk":
        note = "no lifecycle column"
    elif log_name == "BPIC15":
        note = (
            "first municipality's log has lifecycle complete on all events"
            if set(lc) == {"complete"}
            else "mixed lifecycle"
        )
    elif set(lc) == {"complete"}:
        note = "all events marked complete"
    elif "complete" not in lc:
        upper = lc.get("COMPLETE")
        note = f"no events marked complete; {upper:,} marked COMPLETE" if upper else "no events marked complete"
    else:
        note = f"{lc['complete']:,} events marked complete"
    logs.append(
        {
            "log": NAMES[log_name],
            "k": f["k"],
            "cases": f["cases"],
            "events": f["events"],
            "variants": f["variants"],
            "activities": f["activities"],
            "lifecycle": note,
        }
    )
write("logs", logs, ["log", "k", "cases", "events", "variants", "activities", "lifecycle"])

# gaps
gaps = [
    {
        "log": NAMES[log_name],
        "freq_default": default[log_name]["freq"]["gap"],
        "freq_prom_compatible": option[log_name]["freq"]["gap"],
        "dist_default": default[log_name]["dist"]["gap"],
        "dist_prom_compatible": option[log_name]["dist"]["gap"],
        "freq_default_s": default[log_name]["freq"]["seconds"],
        "freq_prom_compatible_s": option[log_name]["freq"]["seconds"],
        "dist_default_s": default[log_name]["dist"]["seconds"],
        "dist_prom_compatible_s": option[log_name]["dist"]["seconds"],
    }
    for log_name in LOGS
]
write("gaps", gaps, list(gaps[0]))

# results: one row per implementation, log and setting
rows = []


def log_text(base):
    p = f"{ROUT}/{base}.log"
    return open(p, errors="replace").read().replace("\r", "\n") if os.path.exists(p) else None


def run_state(base, seed):
    """What happened to a run with no labels."""
    text = log_text(f"{base}_s{seed}")
    if text is None:
        return "Not run"
    status = re.search(r"status (\d+)\s*\Z", text)
    if status is None:
        return "Unfinished"
    return "Time limit" if status[1] == "124" else f"Error (status {status[1]})"


def add(log_name, group, impl, sizes, metrics, seed="", show=True):
    row = {
        "row": f"{NAMES[log_name]} | {group} | {impl}" + (f" | seed {seed}" if seed != "" else ""),
        "log": NAMES[log_name],
        "group": group,
        "implementation": impl,
        "seed": seed,
        "sizes": sizes,
        "chart": "yes" if show else "no",
    }
    row.update({m: metrics.get(m, "") for m in METRICS})
    rows.append(row)


TAGS = {
    "Helpdesk": [
        ("r_t1", "actitraceR, target 1.00"),
        ("pyactitrac_t1_w25", "python-ActiTraC, target 1.00, window 0.25"),
        ("pyactitrac_t1_w1", "python-ActiTraC, target 1.00, window 1"),
        ("r_w25", "actitraceR, target 0.99"),
        ("pyactitrac_w25", "python-ActiTraC, target 0.99, window 0.25"),
        ("pyactitrac_w1", "python-ActiTraC, target 0.99, window 1"),
    ],
    "Sepsis": [
        ("r_sep_t1", "actitraceR, target 1.00"),
        ("pyactitrac_sep_t1_w25", "python-ActiTraC, target 1.00, window 0.25"),
        ("r_sep_t99", "actitraceR, target 0.99"),
        ("pyactitrac_sep_t99_w25", "python-ActiTraC, target 0.99, window 0.25"),
    ],
}
REST = ["BPIC13_closedproblems", "BPIC13_incidents", "RTFM", "Hospital_Billing", "BPIC12", "BPIC15"]
TARGETS = (("t10", "1.00"), ("t099", "0.99"))
for n in REST:
    TAGS[n] = [
        (f"{tool}_{n}_{t}{suffix}", f"{label}, target {tl}{extra}")
        for t, tl in TARGETS
        for tool, suffix, label, extra in (
            ("r", "", "actitraceR", ""),
            ("replica", "", "actitraceR replica", ""),
            ("pyactitrac", "_w25", "python-ActiTraC", ", window 0.25"),
            ("pyactitrac", "_w1", "python-ActiTraC", ", window 1"),
        )
    ]
scores = {(x["log"], x["tag"], x["seed"]): x for x in score["scores"]}
for log_name in LOGS:
    d, o = default[log_name], option[log_name]
    add(log_name, "Whole log", "Published", "", d["full"]["prom"], show=False)
    add(log_name, "Whole log", "Recomputed", "", d["full"]["mine"], show=False)
    for key, group in (("freq", "Frequency mode"), ("dist", "Distance mode")):
        add(log_name, group, "ActiTraC-ProM, published results", d[key]["prom_sizes"], d[key]["prom"])
        add(log_name, group, "python-ActiTraC · default", d[key]["sizes"], d[key]["mine"])
        add(log_name, group, "python-ActiTraC · prom_compatible", o[key]["sizes"], o[key]["mine"])
    for tag, impl in TAGS.get(log_name, []):
        for seed in (0, 1):
            x = scores.get((log_name, tag, seed))
            # The replica is shown only where actitraceR has no clusters, since elsewhere they match.
            if tag.startswith("replica_") and (log_name, "r_" + tag[8:], seed) in scores:
                continue
            if x is None:
                add(log_name, "Inductive Miner setup", impl, run_state(tag, seed), {}, seed, show=False)
                continue
            add(
                log_name,
                "Inductive Miner setup",
                impl,
                ", ".join(map(str, x["sizes"])),
                {k: f"{v:.3f}" for k, v in x["metrics"].items()},
                seed,
                show=seed == 0,
            )
write("results", rows, ["row", "log", "group", "implementation", "seed", "sizes", "chart"] + METRICS)

# ranks
text = {m: "" for m in ("default", "prom_compatible")}
ranks = {}
for m in text:
    acc = {}
    for log_name in LOGS:
        t = open(f"{OUT}/{m}/{log_name}.out", errors="replace").read().replace("\r", "\n")
        for x in re.finditer(r"^\s+actitrac_(freq|dist)\s+(\w+)\s+([\d.]+)\s+([\d.]+)\s+n=1", t, re.M):
            acc.setdefault((x[1], x[2]), []).append((float(x[3]), float(x[4])))
    ranks[m] = acc
avg = lambda v, i: f"{sum(a[i] for a in v) / len(v):.2f}"  # noqa: E731
rank_rows = [
    {
        "metric": k,
        "logs": len(ranks["default"][("freq", k)]),
        "freq_default": avg(ranks["default"][("freq", k)], 0),
        "freq_prom_compatible": avg(ranks["prom_compatible"][("freq", k)], 0),
        "freq_actitrac_prom": avg(ranks["prom_compatible"][("freq", k)], 1),
        "dist_default": avg(ranks["default"][("dist", k)], 0),
        "dist_prom_compatible": avg(ranks["prom_compatible"][("dist", k)], 0),
        "dist_actitrac_prom": avg(ranks["prom_compatible"][("dist", k)], 1),
    }
    for k in METRICS
]
write("ranks", rank_rows, list(rank_rows[0]))


# actitraceR agreement
def lab(tool, tag, seed):
    p = f"{ROUT}/{tool}_{tag}_s{seed}.csv"
    return load(p) if os.path.exists(p) and "case" in pd.read_csv(p, nrows=0).columns else None


def sz(s, tool=None, tag=None, seed=None):
    if s is None:
        return "" if tool is None else run_state(f"{tool}_{tag}", seed)
    return ", ".join(str(n) for n in s.value_counts().sort_index())


def ari(a, b):
    return "" if a is None or b is None else f"{adjusted_rand_index(a, b):.3f}"


SET = [
    ("Helpdesk", "Target 0.99, mcs 0.25, noise 0.2", "w25", "base", "w25", "w1", (0, 1, 2, 3)),
    ("Helpdesk", "Target 0.95, mcs 0.25, noise 0.2", "t95", "t95", "t95_w25", "t95_w1", (0, 1, 2, 3)),
    ("Helpdesk", "Target 0.99, mcs 0.60, noise 0.2", "mcs60", "mcs60", "mcs60_w25", "mcs60_w1", (0, 1, 2, 3)),
    ("Helpdesk", "Target 1.00, mcs 0.25, noise 0.2", "t1", "t1", "t1_w25", "t1_w1", (0, 1, 2, 3)),
    ("Helpdesk", "Target 1.00, mcs 0.25, noise 0", "noise0", "noise0", "noise0_w25", "noise0_w1", (0, 1, 2, 3)),
    ("Sepsis", "Target 0.99, mcs 0.25, noise 0.2", "sep_t99", "sep_t99", "sep_t99_w25", "sep_t99_w1", (0, 1)),
    ("Sepsis", "Target 1.00, mcs 0.25, noise 0.2", "sep_t1", "sep_t1", "sep_t1_w25", "sep_t1_w1", (0, 1)),
]
SET += [
    (NAMES[n], f"Target {tl}, mcs 0.25, noise 0.2", f"{n}_{t}", f"{n}_{t}", f"{n}_{t}_w25", f"{n}_{t}_w1", (0, 1))
    for n in REST
    for t, tl in TARGETS
]
agree = []
for log, setting, rt, pt, q, one, seeds in SET:
    for seed in seeds:
        r, p = lab("r", rt, seed), lab("replica", pt, seed)
        a, b = lab("pyactitrac", q, seed), lab("pyactitrac", one, seed)
        agree.append(
            {
                "run": f"{log} | {setting} | seed {seed}",
                "log": log,
                "setting": setting,
                "seed": seed,
                "actitracer": sz(r, "r", rt, seed),
                "replica": sz(p, "replica", pt, seed),
                "ari_replica": ari(r, p),
                "pyactitrac_w025": sz(a, "pyactitrac", q, seed),
                "ari_pyactitrac_w025": ari(r, a),
                "pyactitrac_w1": sz(b, "pyactitrac", one, seed),
                "ari_pyactitrac_w1": ari(r, b),
                "noise": "0" if setting.endswith("noise 0") else "0.2",
            }
        )
write("agreement", agree, list(agree[0]))

native = [
    {
        "row": f"{x['log']} | {x['mode']}",
        "log": NAMES[x["log"]],
        "mode": x["mode"],
        "sizes": ", ".join(map(str, x["sizes"])),
        "ari_actitracer": "" if x["ari_against_actitraceR"] is None else f"{x['ari_against_actitraceR']:.3f}",
    }
    for x in score["native"]
]
write("native", native, ["row", "log", "mode", "sizes", "ari_actitracer"])

# One difference at a time
NAMES_C = [
    ("look", "Look-ahead always, at perfect fit"),
    ("dist", "Edit distance over activities"),
    ("mcs", "Minimal size against cases at the start"),
    ("fit", "Fitness without the silent-move cost"),
    ("feed", "Miner input in cluster order"),
    ("order", "Frequency ties in log order"),
    ("resid", "Residuals against the model before look-ahead"),
    ("seed", "Seed always joins"),
    ("all", "All eight together"),
]
causes = []
for flag, name in NAMES_C:
    for seed in (0, 1, 2, 3):
        # The replica's base run equals actitraceR's clusters on every seed.
        run, base = lab("replica", flag, seed), lab("replica", "base", seed)
        causes.append(
            {
                "row": f"{name} | seed {seed}",
                "change": name,
                "seed": seed,
                "sizes": sz(run),
                "ari_actitracer": ari(run, base),
                "ari_pyactitrac_w1": ari(run, lab("pyactitrac", "w1", seed)) if flag == "all" else "",
            }
        )
write("causes", causes, list(causes[0]))

# Run times from the logs


def seconds(tool, tag, seed):
    """Clustering and total seconds, None where the run has no such time."""
    t = log_text(f"{tool}_{tag}_s{seed}") or ""
    if tool == "r":
        c = re.search(r"labels:.*seconds:\s*([\d.]+)", t)
        f = re.search(r"sizes:.*seconds:\s*([\d.]+)", t)
        return (float(c[1]) if c else None), (float(f[1]) if f else None)
    m = re.search(r"(\d+)s\s*$", t.replace("status 0", "").strip(), re.M)
    return (float(m[1]), float(m[1])) if m else (None, None)


TIME = [
    ("Helpdesk", "Target 0.99, mcs 0.25", "w25", "base", "w25", (0, 1, 2, 3)),
    ("Helpdesk", "Target 0.95, mcs 0.25", "t95", "t95", "t95_w25", (0, 1, 2, 3)),
    ("Helpdesk", "Target 0.99, mcs 0.60", "mcs60", "mcs60", "mcs60_w25", (0, 1, 2, 3)),
    ("Helpdesk", "Target 1.00, mcs 0.25", "t1", "t1", "t1_w25", (0, 1, 2, 3)),
    ("Sepsis", "Target 0.99, mcs 0.25", "sep_t99", "sep_t99", "sep_t99_w25", (0, 1)),
    ("Sepsis", "Target 1.00, mcs 0.25", "sep_t1", "sep_t1", "sep_t1_w25", (0, 1)),
]
TIME += [
    (NAMES[n], f"Target {tl}, mcs 0.25", f"{n}_{t}", f"{n}_{t}", f"{n}_{t}_w25", (0, 1))
    for n in REST
    for t, tl in TARGETS
]
times = []


def span(values, limit):
    done = [v for v in values if v is not None]
    if not done:
        return f"Unfinished at {limit}"
    text = f"{min(done):.0f}" if round(min(done)) == round(max(done)) else f"{min(done):.0f} to {max(done):.0f}"
    return text + (f" ({len(values) - len(done)} unfinished at {limit})" if len(done) < len(values) else "")


# Runs that reached the 12-hour limit and ran again with a 48-hour limit, 15 at once.
# Their 12-hour logs were moved to timeout_12h/ before the rerun.
RERUN = {f[:-4] for f in os.listdir(f"{ROUT}/timeout_12h")} if os.path.isdir(f"{ROUT}/timeout_12h") else set()
for log, setting, rt, pt, q, seeds in TIME:
    second = log not in ("Helpdesk", "Sepsis")
    rerun = any(f"{tool}_{tag}_s{s}" in RERUN for tool, tag in (("r", rt), ("replica", pt), ("pyactitrac", q)) for s in seeds)
    limit = 172800 if rerun else 43200 if second else 10800
    r = [seconds("r", rt, s) for s in seeds]
    times.append(
        {
            "run": f"{log} | {setting}",
            "log": log,
            "setting": setting,
            "jobs": "32, rerun 15" if rerun else "32" if second else "16",
            "actitracer_clustering": span([x[0] for x in r], limit),
            "actitracer_total": "Not run (evaluation left out)" if second else span([x[1] for x in r], limit),
            "replica": span([seconds("replica", pt, s)[0] for s in seeds], limit),
            "pyactitrac_w025": span([seconds("pyactitrac", q, s)[0] for s in seeds], limit),
        }
    )
write("times", times, list(times[0]))

# The doc's four extra logs, from the earlier run
extra = [
    ("MCRM", "frequency", "0.5", "742, 143, 24, 47", "0.292", "-0.128"),
    ("MCRM", "distance", "0.5", "462, 210, 237, 47", "0.714", "-0.128"),
    ("KIM", "frequency", "2.8", "18962, 3171, 1343, 1294", "0.837", "0.791"),
    ("KIM", "distance", "6.4", "14201, 4061, 2519, 3989", "0.831", "0.791"),
    ("TSL", "frequency", "1.0", "9583, 7660, 308, 261", "-1.170", "-1.414"),
    ("TSL", "distance", "26.5", "8494, 5865, 2148, 1305", "-1.149", "-1.414"),
    ("ICP", "frequency", "12.7", "9047, 2412, 314, 618", "-0.515", "-0.776"),
    ("ICP", "distance", "16.7", "5425, 2755, 2907, 1304", "0.372", "-0.776"),
]
write(
    "extra",
    [
        {"row": f"{a} | {b}", "log": a, "mode": b, "seconds": c, "sizes": d, "weighted_ics": e, "full_log_ics": f}
        for a, b, c, d, e, f in extra
    ],
    ["row", "log", "mode", "seconds", "sizes", "weighted_ics", "full_log_ics"],
)

# Which implementation ran where. "Run, refined" marks the logs whose lifecycle had to be
# changed for actitraceR, and where actitraceR's empty clusters had to be dropped.
REFINED = {"BPIC13_closedproblems", "BPIC13_incidents", "BPIC12"}


def coverage(tool, log, tags):
    found = [lab(tool, t, s) is not None for t in tags for s in (0, 1)]
    if all(found):
        return "Run, refined" if log in REFINED else "Run"
    if any(found):
        return "Partly run, refined" if log in REFINED else "Partly run"
    return "Time limit"


def rest(tool, n, suffixes):
    return {n: coverage(tool, n, [f"{n}_{t}{x}" for t, _ in TARGETS for x in suffixes]) for n in REST}


STATUS = {
    "ActiTraC-ProM, published results": {log_name: "Published" for log_name in LOGS},
    "ActiTraC-ProM emulation (Java)": {log_name: "Sizes only" for log_name in LOGS},
    "python-ActiTraC · default": {log_name: "Run" for log_name in LOGS},
    "python-ActiTraC · prom_compatible": {log_name: "Run" for log_name in LOGS},
    "actitraceR (R)": {
        "Helpdesk": "Run",
        "Sepsis": "Clusters only",
        **{k: v for n in REST for k, v in rest("r", n, [""]).items()},
    },
    "actitraceR replica (Python)": {
        "Helpdesk": "Run",
        "Sepsis": "Run",
        **{k: v for n in REST for k, v in rest("replica", n, [""]).items()},
    },
    "python-ActiTraC · Inductive Miner setup": {
        "Helpdesk": "Run",
        "Sepsis": "Run",
        **{k: v for n in REST for k, v in rest("pyactitrac", n, ["_w25", "_w1"]).items()},
    },
}
write(
    "coverage",
    [{"implementation": k, **{NAMES[log_name]: v[log_name] for log_name in LOGS}} for k, v in STATUS.items()],
    ["implementation"] + [NAMES[log_name] for log_name in LOGS],
)

# actitraceR defect checks
defect_log = open(f"{ROUT}/defects.log", errors="replace").read()
silent = re.search(r"'log_fitness': ([\d.]+)", open(f"{ROUT}/silent_moves.log", errors="replace").read())[1]
rows_w = {w: re.search(rf"window {w} rows (\d+)", defect_log)[1] for w in ("0", "0.25", "1")}
closed = open(f"{ROUT}/r_closed_s0.log", errors="replace").read()
raw = {
    n: re.search(r"Number of traces to cluster: (\d+)", log_text(f"r_raw_{n}_s0"))[1]
    for n in ("BPIC13_incidents", "BPIC12")
}
empty = open(f"{ROUT}/unrefined/r_BPIC13_closedproblems_t10_s0.log", errors="replace").read()
empty_error = re.search(r"must select exactly one column", empty)
evaluation = {}
for stage in ("clusters", "whole"):
    t = log_text(f"evaluation_sep_{stage}_s0") or ""
    evaluation[stage] = {m[1]: float(m[2]) for m in re.finditer(r"^done (.*?): ([\d.]+) s", t, re.M)}
    evaluation[stage]["status"] = (re.search(r"^status (\d+)", t, re.M) or [None, None])[1]
whole_precision = evaluation["whole"].get("whole log precision")
precision_text = (
    f"took {whole_precision:.0f} s"
    if whole_precision is not None
    else "hit the 12-hour limit"
    if evaluation["whole"]["status"] == "124"
    else "had not finished"
)
defects = [
    {
        "defect": "window_size has no effect",
        "check": f"Variants in the window at 0, 0.25 and 1: {rows_w['0']}, {rows_w['0.25']}, {rows_w['1']}. "
        "Clusters are identical at all three on four hash seeds",
    },
    {
        "defect": "The mra distance cannot run",
        "check": "Stops with: " + re.search(r"mra call: (.*?)\s*$", defect_log, re.M)[1],
    },
    {
        "defect": "A perfect fit can fail the target",
        "check": f"A model that fits every Helpdesk trace has log_fitness {float(silent):.5f}",
    },
    {
        "defect": "Edit distance runs over token characters",
        "check": re.search(r"insert \[3\]: .*", defect_log)[0].strip(),
    },
    {
        "defect": "A log with no complete events stops with an error",
        "check": f"Raw BPIC13 closed problems exits with status {re.search(r'status (\d+)', closed)[1]} "
        "in the final evaluation. "
        f"actitraceR finds {raw['BPIC13_incidents']} traces to cluster on raw BPIC13 incidents "
        f"and {raw['BPIC12']} on raw BPIC12",
    },
    {
        "defect": "An empty cluster stops the run with an error",
        "check": (
            "BPIC13 closed problems at target 1.00 stops in pull(): must select exactly one column. "
            "The replica stops at the same point on it and on BPIC13 incidents"
        )
        if empty_error
        else "Not seen",
    },
    {
        "defect": "Final evaluation does not finish on Sepsis",
        "check": f"All 4 runs were still in it at the 3-hour limit. Timed alone, the per-cluster steps took "
        f"{sum(v for k, v in evaluation['clusters'].items() if k != 'status'):.0f} s, the whole-log model at noise 0 "
        f"took {evaluation['whole'].get('whole log fitness', 0):.0f} s for fitness, and its precision {precision_text}",
    },
]
write("defects", defects, ["defect", "check"])
