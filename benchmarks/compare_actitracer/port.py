"""actitraceR's cluster_traces as read from its source, in Python.

Usage: python port.py NAME K TARGET MCS NOISE OUT.csv [FLAG=VALUE ...]

dump_r.R writes the variant order, case map and tokens this reads. With no flags it
gives actitraceR's clusters, up to pm4py's run-to-run variation. With all the flags
below it gives this package's clusters at window_size=1. Each flag switches one behaviour:
  dist=char|act     edit distance over token characters (R) or over activities
  fit=log|pkg       pm4py log_fitness (R) or this package's fitness without the silent-move cost
  mcs=now|start     minimal size against cases left now (R) or when the cluster started
  seed=test|force   the seed must pass the target (R) or always joins
  look=stop|always  look-ahead after a minimal-size stop at the target (R) or always at perfect fit
  resid=r|pkg       residual traces against models of all members (R) or of the members before look-ahead
  feed=r|pkg        miner input as a data frame in log order (R) or an event log in cluster order
  order=r|pkg       frequency ties in R's order or in order of first appearance in the log
  empty=keep|drop   an empty cluster stops the run with an error (R) or goes before the residual step,
                    as run_r.R does with ACTITRACER_DROP_EMPTY=1
"""
import os
import re
import sys
import time
import warnings

import pandas as pd
import pm4py

warnings.filterwarnings("ignore")
K = dict(activity_key="concept:name", case_id_key="case:concept:name", timestamp_key="time:timestamp")

def osa(a, b):
    if a == b:
        return 0
    prev2, prev = None, list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y))
            if i > 1 and j > 1 and x == b[j - 2] and a[i - 2] == y:
                v = min(v, prev2[j - 2] + 1)
            cur.append(v)
        prev2, prev = prev, cur
    return prev[-1]

def main(name, k, target, mcs, noise, out, dist="char", fit="log", mcsmode="now", seed="test", look="stop", order="r", resid="r", feed="r", empty="keep"):
    f = pd.read_csv(f"{name}.csv", keep_default_na=False, dtype={"case": str})
    f.columns = ["case:concept:name", "concept:name", "time:timestamp", "lifecycle:transition"]
    f["time:timestamp"] = pd.to_datetime(f["time:timestamp"])
    f = f[f["lifecycle:transition"] == "complete"]
    var = pd.read_csv(f"dump_{name}_var.csv", keep_default_na=False, dtype={"trace_id": str})
    cases = pd.read_csv(f"dump_{name}_case.csv", keep_default_na=False, dtype={"case": str, "trace_id": str})
    f = f.assign(_v=f["case:concept:name"].map(dict(zip(cases.case, cases.trace_id))))
    groups = {v: g for v, g in f.groupby("_v", sort=False)}
    if order == "pkg":
        first = {v: i for i, v in reversed(list(enumerate(f["_v"].tolist())))}
        var = var.assign(_f=var.trace_id.map(first)).sort_values(["freq", "_f"], ascending=[False, True], kind="stable")
    freq = dict(zip(var.trace_id, var.freq))
    tok = dict(zip(var.trace_id, var.tokens if dist == "char" else [tuple(re.findall(r"\[\d+\]", t)) for t in var.tokens]))
    cache = {}
    def d(a, b):
        key = (a, b) if a < b else (b, a)
        if key not in cache:
            cache[key] = osa(tok[a], tok[b])
        return cache[key]
    def sub(ids):
        return pd.concat([groups[i] for i in ids])
    seq = {v: tuple(g[g["case:concept:name"] == g["case:concept:name"].iloc[0]].sort_values("time:timestamp", kind="stable")["concept:name"]) for v, g in groups.items()}
    def disc(ids):
        if feed == "pkg":
            from actitrac.petri import event_log
            from actitrac.log import Variant
            return pm4py.discover_petri_net_inductive(event_log([Variant(0, seq[i], freq[i]) for i in ids]), noise_threshold=noise, **K)
        return pm4py.discover_petri_net_inductive(sub(ids), noise_threshold=noise, **K)
    def fitness(ids, m):
        if fit == "log":
            return pm4py.fitness_alignments(sub(ids), *m, **K)["log_fitness"]
        rs = pm4py.conformance_diagnostics_alignments(sub(ids), *m, **K)
        cost = sum(r["cost"] // 10000 * 10000 for r in rs)
        worst = sum(r["bwc"] for r in rs)
        return 1 - cost / worst if worst else 0.0
    R, CS, models = list(var.trace_id), [], []
    while len(CS) < k and R:
        C, I = [], []
        minimal = int(mcs * sum(freq[r] for r in R))
        last, stopped = None, False
        if seed == "force":
            C.append(R.pop(0))
            last = disc(C)
            stopped = fitness(C, last) < target
        while not stopped and R and sorted(R) != sorted(I):
            W = [v for v in R if v not in I]
            if not C or len(W) == 1:
                cur = W[0]
            else:
                avg = [sum(d(c, w) for c in C) / len(C) for w in W]
                cur = W[avg.index(min(avg))]
            m = disc(C + [cur])
            if fitness(C + [cur], m) >= target:
                C.append(cur)
                R.remove(cur)
                last = m
            elif sum(freq[c] for c in C) >= (minimal if mcsmode == "start" else mcs * sum(freq[r] for r in R)):
                if look == "stop":
                    m = disc(C)
                    for i in list(R):
                        if fitness([i], m) >= target:
                            C.append(i)
                            R.remove(i)
                I.append(cur)
                break
            else:
                I.append(cur)
        if look == "always" and last is not None:
            for i in list(R):
                if fitness([i], last) >= 1 - 1e-9:
                    C.append(i)
                    R.remove(i)
        CS.append(C)
        models.append(last)
    if empty == "drop":
        models = [m for C, m in zip(CS, models) if C]
        CS = [C for C in CS if C]
        if not CS:
            CS, models, R = [list(R)], [None], []
    if R:
        ms = models if resid == "pkg" else [disc(c) for c in CS]
        for i in list(R):
            a = [fitness([i], m) for m in ms]
            CS[a.index(max(a))].append(i)
    rows = [(c, n) for n, C in enumerate(CS) for v in C for c in groups[v]["case:concept:name"].unique()]
    pd.DataFrame(rows, columns=["case", "cluster"]).to_csv(out, index=False)
    return [sum(freq[v] for v in C) for C in CS]

if __name__ == "__main__":
    name, k, target, mcs, noise, out, *flags = sys.argv[1:]
    s = time.time()
    sizes = main(name, int(k), float(target), float(mcs), float(noise), out, **{("mcsmode" if a == "mcs" else a): b for a, b in (x.split("=") for x in flags)})
    print(out, flags, os.environ.get("PYTHONHASHSEED"), sizes, f"{time.time()-s:.0f}s", flush=True)
