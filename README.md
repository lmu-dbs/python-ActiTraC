# python-ActiTraC

python-ActiTraC is a Python implementation of ActiTraC (active trace clustering) and
ActiTraC-MO, its multi-objective variant. ActiTraC splits an event log into clusters by
growing each one until a process model mined from it stops fitting, so that discovery
on each cluster gives a better model than discovery on the whole log.

> **Disclaimer:** python-ActiTraC was written using AI (Claude Code), from the Java
> code of ActiTraC-ProM, the authors' ProM plugin, and the R code of actitraceR. The
> repository is heavily tested:
>
> - a test suite;
> - a comparison with ActiTraC-ProM's published results on eight logs;
> - a comparison with actitraceR, where the actitraceR replica, a Python copy of it, gives
>   the same clusters in all 48 runs that finished.
>
> Even so, check the results on your own data before you rely on them. The sections
> below give the known differences.

## Install

```bash
pip install -e .            # ActiTraC with the native Heuristics Miner
pip install -e ".[pm4py]"   # also Petri-net miners, conformance metrics, ActiTraC-MO
pip install -e ".[dev]"     # also the test suite
```

The core needs only NumPy and pandas. pm4py is optional and licensed under
AGPL-3.0, which matters if you distribute software that depends on it.

## Usage

```python
import pm4py
from actitrac import cluster_traces

log = pm4py.read_xes("log.xes", return_legacy_log_object=False)

result = cluster_traces(
    log,
    number_of_clusters=4,
    target_fitness=1.0,
    minimal_cluster_size=0.25,
    window_size=0.25,               # 0 selects purely by frequency
    cluster_remaining_traces=False, # True puts leftovers in their own cluster
)

print(result)                       # cluster sizes
result.labels                       # {case id: cluster id}
result.augment()                    # the log with a "cluster" column
result.logs()                       # one filtered log per cluster
result.select_cluster(0)            # one of them; ids start at 0
result.group_by_cluster()           # pandas groupby on the cluster
result.variant_logs()               # one {activities: count} dict per cluster
result.metrics(conformance=True)    # per cluster, weighted average, full log
```

The input can be a DataFrame, a pm4py `EventLog` or a `{activity_tuple: count}`
dict. DataFrames use the XES column names by default; pass `case_key`,
`activity_key` and `timestamp_key` to change them.

### Selection strategies

| Strategy | Setting |
| --- | --- |
| Frequency-based | `window_size=0` |
| Maximal repeat alphabet distance | `window_size=0.25`, the default |
| Edit distance over activities | `distance_metric="osa"` |
| Your own distance | `distance_metric=lambda a, b: ...` |

### Other miners

Without `discover_algorithm`, clusters are mined with a native Python version of
ProM's Heuristics Miner and scored with improved continuous semantics (ICS) fitness,
as in ActiTraC-ProM. Any pm4py Petri-net miner can replace it:

```python
result = cluster_traces(
    log,
    discover_algorithm=lambda log: pm4py.discover_petri_net_inductive(log, noise_threshold=0.2),
    fitness_metric="alignments",    # or "token_replay"
    target_fitness=0.99,
)
```

Set a noise threshold here. Without one the Inductive Miner guarantees fitness 1,
so the target is never missed and one cluster absorbs the whole log. A low target
has the same effect: on Helpdesk, this example gives one cluster at a target of
0.95.

### ActiTraC-MO

```python
from actitrac import cluster_traces_mo

result = cluster_traces_mo(
    log,
    number_of_clusters=4,
    minimal_correctness=0.95,       # F-score of the model on its cluster
    minimal_trace_correctness=0.90, # F-score of the model on the new variant
    beta=1.0,
    seed=42,
)
```

This is much slower than `cluster_traces`: about 20 seconds to 3 minutes on a log
of about 200 variants. With these default thresholds, most of that log's variants
ended up in the residual cluster, so lower `minimal_trace_correctness` if that
happens to you.

### With EntropicClustering

`actitrac.cluster` follows the calling convention of `entroclus`, so ActiTraC can
sit next to the other methods in that repository's experiments:

```python
from actitrac import cluster

clusters = cluster(log, 4, outputshape="log", variant="frequency", cluster_remaining_traces=False)
```

## Names in the comparisons

The two sections below compare python-ActiTraC with three other implementations:

| Name | What it is |
| --- | --- |
| **ActiTraC-ProM** | The authors' ActiTraC plugin for ProM. Its numbers here are the published results of Peeperkorn et al. |
| **ActiTraC-ProM emulation** | Java code that reproduces the plugin, including its bugs |
| **actitraceR** | The R package |
| **actitraceR replica** | Python code that reproduces actitraceR, including its bugs |

python-ActiTraC itself has three settings: `default`, `prom_compatible` and the
Inductive Miner setup, which uses actitraceR's miner, fitness and edit distance.
[docs/fidelity.md](docs/fidelity.md#names) has the details.

## How closely it follows ActiTraC-ProM

Activities are named by their name and lifecycle transition together, as ProM
does. Pass `lifecycle="complete"` to keep only complete events, as actitraceR does.
On a log with none, such as BPIC 2013, no traces remain and clustering stops with an
error. Unlike actitraceR, the comparison ignores case, so BPIC 2012's `COMPLETE` events
count.

python-ActiTraC does not reproduce ActiTraC-ProM exactly. Compared with its published
results in [Peeperkorn et al.](https://arxiv.org/abs/2506.23776) on eight logs:

- **Frequency mode** is exact on BPIC 2013 closed problems and within 2.5% on six
  logs. It is 35% off on BPIC 2012.
- **Distance mode** is exact on BPIC 2012 and BPIC 2013 closed problems and within
  4% on three logs. It is 10% to 28% off on Sepsis, Hospital Billing and BPIC 2015.
- **ActiTraC-MO** substitutes the miner and the recall measure, so it is not
  expected to match ActiTraC-MO in ProM. It has no reference results.

The causes are known: a lookup bug in ProM's distance matrix, a fitness rounded to
a `float`, and four smaller behaviours. The ActiTraC-ProM emulation in
`benchmarks/prom_emulation/` includes them and gives every published cluster size, and
with them off it gives python-ActiTraC's.

Pass `prom_compatible=True` to add ProM's seeded token choice and `float` comparison.
Frequency mode then gives ActiTraC-ProM's cluster sizes on all eight logs. Distance mode
stays different, because ProM's distance bugs are left out, and its gaps barely change.

[docs/fidelity.md](docs/fidelity.md) has the details. To repeat the comparison, run
`benchmarks/compare_entropic.py`, with `--prom-compatible` for the option.
`benchmarks/docker/` runs all of it in a container, including the downloads.

## How it differs from actitraceR

In its Inductive Miner setup, python-ActiTraC uses the same miner, fitness and edit
distance as [actitraceR](https://github.com/bupaverse/actitraceR), but the two give
different clusters. The adjusted Rand index between them is 0.21 to 0.53 on Helpdesk,
0.20 to 0.25 on Sepsis and about 0 to 0.99 on the other logs, at noise 0.2. On Helpdesk
the largest causes are that actitraceR measures edit distance over the characters of
tokens such as `[12]`, and that it runs look-ahead only after a minimal-size stop. Its
`window_size` has no effect, its `mra` option cannot run, and it stops with an error on
an empty cluster or on a log with no `complete` events.

The actitraceR replica, `benchmarks/compare_actitracer/replica.py`, reproduces
actitraceR's clusters in all 48 runs where actitraceR finished, on all eight logs. On
Helpdesk it also gives python-ActiTraC's clusters when all the differences are switched.
`run_docker.sh` and `run_docker_rest.sh` in the same directory repeat the comparison in
a container.

[docs/comparison/comparison.html](docs/comparison/comparison.html) shows every result of
both comparisons on one page
([view it rendered](https://htmlpreview.github.io/?https://github.com/lmu-dbs/python-ActiTraC/blob/main/docs/comparison/comparison.html)).
It is a standalone file that also opens in a browser, and
[docs/comparison/](docs/comparison/) has its data and the scripts that build it.

pm4py's Inductive Miner with a noise threshold depends on the hash seed and on trace
order, so set `PYTHONHASHSEED` to repeat a run with it.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

`tests/test_prom_reference.py` needs the Helpdesk log and is skipped unless
`ACTITRAC_HELPDESK_CSV` points to it.

## Citation

If you use python-ActiTraC in your work, please cite it:

```bibtex
@software{schlegel2026pythonactitrac,
  author  = {Schlegel, Udo},
  title   = {python-ActiTraC: A Python Implementation of Active Trace Clustering},
  year    = {2026},
  version = {0.1.0},
  url     = {https://github.com/lmu-dbs/python-ActiTraC},
  license = {MIT}
}
```

Please also cite the original ActiTraC paper:

```bibtex
@article{deweerdt2013actitrac,
  author  = {De Weerdt, Jochen and vanden Broucke, Seppe and Vanthienen, Jan and Baesens, Bart},
  title   = {Active Trace Clustering for Improved Process Discovery},
  journal = {IEEE Transactions on Knowledge and Data Engineering},
  year    = {2013},
  doi     = {10.1109/TKDE.2013.64}
}
```

## License

MIT, copyright (c) 2026 Udo Schlegel. See [LICENSE](LICENSE).

## References

- J. De Weerdt, S. vanden Broucke, J. Vanthienen and B. Baesens. Active Trace
  Clustering for Improved Process Discovery. *IEEE TKDE* 25(12), 2013.
  [doi:10.1109/TKDE.2013.64](https://doi.org/10.1109/TKDE.2013.64)
- P. De Koninck and J. De Weerdt. Multi-objective Trace Clustering: Finding More
  Balanced Solutions. *BPM Workshops* 2016.
  [doi:10.1007/978-3-319-58457-7_4](https://doi.org/10.1007/978-3-319-58457-7_4)
- [ProM ActiTraC plugin](https://www.processmining.be/actitrac/) and
  [ActiTraC-MO](https://processmining.be/multiobjective/)
- [actitraceR](https://github.com/bupaverse/actitraceR) by G. Janssenswillen and I. Esin
- [EntropicClustering](https://github.com/jaripeeperkorn/EntropicClustering) by
  J. Peeperkorn, J. De Smedt and J. De Weerdt
