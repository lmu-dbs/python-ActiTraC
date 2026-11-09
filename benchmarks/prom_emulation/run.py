"""ActiTraC-ProM emulation: reproduce its published results and test what explains the gap.

Reimplements ActiTraC-ProM's behaviour, including its bugs, in Java, because Java's float
casts, ``HashSet`` and ``java.util.Random`` are part of that behaviour. The result
matches every cluster size that Peeperkorn et al. published. With ``--flags`` it
switches one behaviour off, which shows what that behaviour contributes.

    python benchmarks/prom_emulation/run.py --data logs/ --results RESULTS [--flags norng]

``--data`` and ``--results`` are as in ``compare_entropic.py``. Needs a JDK 8 or
later. See docs/fidelity.md for the findings.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from compare_entropic import (  # noqa: E402
    ACTIVITY,
    CASE,
    LIFECYCLE,
    LOGS,
    MODES,
    TIME,
    load_log,
    published_rows,
)

FLAGS = {
    "lookup=ok": "correct lookup in getDistance",
    "exactsum": "sum distances as a double, not truncated to an int at each step",
    "nofloat": "compare fitness as a double, not a float",
    "norng": "always take the first token option instead of a seeded random one",
    "truelen": "FeatureSelection uses the true encoding length",
    "allstreams": "getRepeats keeps all streams, not only the last",
    "nosticky": "lowered miner thresholds do not persist",
    "nofilter": "keep alphabets larger than 10",
    "sorted": "sorted sets instead of HashSet",
    "seed=1": "pseudo-random set order instead of HashSet",
}


def dump(data: str, name: str, path: str) -> None:
    """Write one line per case, in log order, with events sorted within the case."""
    frame = load_log(data, name)
    names = frame[ACTIVITY].astype(str).tolist()
    transitions = (
        frame[LIFECYCLE].astype(str).tolist() if LIFECYCLE in frame else ["complete"] * len(frame)
    )
    order = frame[TIME].to_numpy().argsort(kind="stable")
    cases = frame[CASE].tolist()
    traces: dict = {case: [] for case in cases}
    for row in order:
        traces[cases[row]].append(f"{names[row]}\x1f{transitions[row]}")
    with open(path, "w", encoding="utf-8") as out:
        for events in traces.values():
            out.write("\t".join(events) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", required=True)
    parser.add_argument("--results", required=True)
    parser.add_argument("--flags", nargs="*", default=[], choices=list(FLAGS))
    parser.add_argument("--logs", nargs="*", default=list(LOGS), choices=list(LOGS))
    parser.add_argument("--jdk", default="", help="JDK bin directory, if not on PATH")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as work:
        sources = [os.path.join(HERE, f) for f in ("Emu.java", "Mra.java")]
        subprocess.run(
            [os.path.join(args.jdk, "javac"), "-nowarn", "-d", work, *sources],
            check=True,
            stderr=subprocess.DEVNULL,
        )
        for name in args.logs:
            dump(args.data, name, os.path.join(work, f"{name}.txt"))

        def run(job: tuple[str, str]) -> list[int]:
            name, mode = job
            output = subprocess.run(
                [
                    os.path.join(args.jdk, "java"),
                    "-Xmx12g",
                    "-cp",
                    work,
                    "Emu",
                    os.path.join(work, f"{name}.txt"),
                    str(LOGS[name]),
                    mode[9:],
                    *args.flags,
                ],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            return [int(x) for x in re.search(r"\[([\d,]*)\]", output).group(1).split(",")]

        jobs = [(name, mode) for name in args.logs for mode in MODES]
        with ThreadPoolExecutor(max_workers=os.cpu_count()) as pool:
            results = list(pool.map(run, jobs))

    for (name, mode), sizes in zip(jobs, results):
        prom = published_rows(args.results, name)[1][mode]
        padded = sizes + [0] * (len(prom) - len(sizes))
        differ = sum(abs(a - b) for a, b in zip(padded, prom)) / 2 / max(sum(sizes), sum(prom))
        verdict = "exact" if sizes == prom else f"{differ:.1%}"
        print(f"{name:22s} {mode[9:]:5s} {verdict:>6s} {sizes} ProM {prom}", flush=True)


if __name__ == "__main__":
    main()
