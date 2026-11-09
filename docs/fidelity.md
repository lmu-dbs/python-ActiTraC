# How this implementation relates to its references

## Sources

| Source | Used for |
| --- | --- |
| ProM `ActiTrac` 6.9.7 package (Java source inside the [JAR](https://promtools.org/prom6/packages/ActiTrac/ActiTrac.jar)) | Reference for ActiTraC behaviour and defaults |
| ProM `ExpertTraceClustering` package | Reference for ActiTraC-MO (`ParallelClusterer`) |
| ProM `HeuristicsMiner` and `GuideTreeMiner` packages | ICS replay semantics, miner defaults, MRA features |
| [actitraceR](https://github.com/bupaverse/actitraceR) | API names and accessors, and a run-by-run comparison |
| [EntropicClustering](https://github.com/jaripeeperkorn/EntropicClustering) | `cluster()` calling convention, ProM reference results |
| [Peeperkorn et al.](https://arxiv.org/abs/2506.23776) | ProM version and settings behind those results, log preparation, metrics |
| [processmining.be/actitrac](https://www.processmining.be/actitrac/) and [/multiobjective](https://processmining.be/multiobjective/) | Event logs, β and P/T connectivity description |

The TKDE 2013 and BPI 2016 papers themselves were not available while this was
written, so nothing here is checked against their text. Where the sources
disagree, the authors' Java source decides.

All the results below are also on one page:
[comparison.html, rendered](https://htmlpreview.github.io/?https://github.com/lmu-dbs/python-ActiTraC/blob/main/docs/comparison/comparison.html). Its source and data are in
[comparison/](comparison/).

## Validation against ProM

Peeperkorn et al. ran ProM's ActiTraC on eight logs and published the results in
their repository. The paper gives the settings: ProM 6.13, minimal cluster size
0.25, target ICS fitness 1.0, remaining traces assigned to existing clusters, and
`k` from an elbow analysis. `benchmarks/compare_entropic.py` repeats this with the
same settings. The default `lifecycle="classifier"` names activities as ProM does.

**Frequency mode** (`window_size=0`):

| Log | `k` | This package | ProM | Cases differ |
| --- | --- | --- | --- | --- |
| BPIC13 closed problems | 5 | 884, 153, 208, 175, 67 | 884, 153, 208, 175, 67 | 0% |
| BPIC13 incidents | 5 | 1893, 2175, 352, 2784, 350 | 1893, 2179, 352, 2780, 350 | 0.1% |
| Helpdesk | 4 | 3824, 412, 246, 98 | 3828, 408, 246, 98 | 0.1% |
| Hospital Billing | 5 | 62599, 22453, 10718, 3638, 592 | 63002, 22453, 10304, 3638, 603 | 0.4% |
| RTFM | 4 | 62426, 63263, 20897, 3784 | 59928, 65881, 20777, 3784 | 1.7% |
| Sepsis | 6 | 72, 633, 185, 62, 40, 58 | 72, 609, 208, 62, 41, 58 | 2.3% |
| BPIC15 | 4 | 2871, 1014, 1065, 698 | 3011, 989, 1060, 588 | 2.5% |
| BPIC12 | 4 | 4224, 1965, 722, 6176 | 8466, 2325, 596, 1700 | **35.2%** |

**Distance mode** (`window_size=0.25`):

| Log | `k` | This package | ProM | Cases differ |
| --- | --- | --- | --- | --- |
| BPIC12 | 4 | 4224, 1965, 722, 6176 | 4224, 1965, 722, 6176 | 0% |
| BPIC13 closed problems | 5 | 575, 175, 351, 206, 180 | 575, 175, 351, 206, 180 | 0% |
| BPIC13 incidents | 5 | 1900, 2083, 352, 2848, 371 | 1900, 2110, 352, 2826, 366 | 0.4% |
| RTFM | 4 | 62316, 49883, 20627, 17544 | 62316, 46745, 20535, 20774 | 2.1% |
| Helpdesk | 4 | 2949, 883, 500, 248 | 2772, 879, 685, 244 | 4.0% |
| Sepsis | 6 | 57, 651, 182, 63, 39, 58 | 67, 543, 202, 82, 94, 62 | 10.3% |
| Hospital Billing | 5 | 41471, 22468, 22668, 9710, 3683 | 62472, 22451, 6507, 3638, 4932 | **22.2%** |
| BPIC15 | 4 | 3063, 1312, 393, 880 | 1628, 2619, 677, 725 | **28.2%** |

"Cases differ" compares sizes cluster by cluster, so it is the smallest share of
cases that must lie in a different cluster. The published cluster logs are not in
the repository, so membership cannot be compared directly. The metrics support it
indirectly: ER, graph density and graph entropy depend only on membership, and
they match to 3 decimals wherever the sizes match exactly.

### Why this package does not match exactly

`benchmarks/prom_emulation/` reimplements ProM's behaviour from its source in Java,
because Java's `float` casts, `HashSet` and `java.util.Random` are part of that
behaviour. No ProM code was run: executing ProM's JARs was not permitted in the
environment where this was done. So the result below is a match with ProM's
published output, not a direct comparison run by run.

- **With all behaviours on,** the emulation gives all 16 published sets of cluster
  sizes exactly. BPIC15 in frequency mode has 3012 traces in the first cluster
  against ProM's 3011, and 3011 is the number of distinct case IDs in it (see below).
- **Membership also agrees.** ER, graph density and graph entropy depend on which
  traces share a cluster. Of the 48 published values, 47 match to within rounding.
  The other is BPIC15's frequency entropy, 24.250 against 24.257.
- **With all behaviours off,** the emulation gives this package's sizes on all 16,
  again up to those BPIC15 case IDs. So these behaviours account for the whole gap.

These behaviours cause it:

| Behaviour in ProM | Where | Effect |
| --- | --- | --- |
| Distance lookup bug | `MaxRepeatAlphabetDistanceXLog` | Stores `matrix[i][j-i]` from a square matrix, so distances between variants `a` and `b` are read from the row of `a` at column `b-a` |
| Float rounding | `ProcessModel.getFitness` | The fitness is cast to a `float` before the comparison with the target. A net that parses every event but leaves a few tokens behind rounds to exactly 1.0 on a large log |
| Truncated sum | `GreedyDistanceClusterer` | `int distance += float` truncates at every step, and ties go to the first candidate |
| Wrong encoding length | `MaxRepeatAlphabetDistanceXLog`, `FeatureSelection` | The selector uses the length of the encoding with one symbol per trace (2 or 3), but the features use the shorter one (1). It cuts features into 2 or 3 character chunks, and repeats shorter than a chunk all share one empty alphabet |
| Seeded token choice | `MarkingHeuristicsNet` | Picks tokens with `new Random(Long.MAX_VALUE)`, drawing across all traces of the log in order, so runs are deterministic but depend on the log order |
| Last stream only | `FeatureSelection.getRepeats` | The buffer is reset inside the loop, so only the last stream is decomposed |

The tables show the share of cases that differ from ProM when one behaviour alone is
switched off in the emulation. "Exact" means switching it off changes nothing.

Frequency mode:

| Log | Float rounding | Seeded token choice |
| --- | --- | --- |
| BPIC12 | **35.2%** | exact |
| RTFM | 1.7% | exact |
| Hospital Billing | 0.4% | exact |
| BPIC15 | exact | 2.5% |
| Sepsis | exact | 2.3% |
| Helpdesk | exact | 0.1% |
| BPIC13 incidents | exact | 0.1% |
| BPIC13 closed problems | exact | exact |

Distance mode:

| Log | Lookup bug | Truncated sum | Encoding length | Float rounding | Token choice | Last stream |
| --- | --- | --- | --- | --- | --- | --- |
| BPIC15 | **37.3%** | **25.0%** | **28.4%** | exact | 1.7% | exact |
| Hospital Billing | **23.3%** | **23.3%** | **23.3%** | **23.3%** | <0.1% | exact |
| BPIC12 | exact | 5.7% | exact | exact | exact | exact |
| BPIC13 incidents | 6.5% | 0.4% | exact | exact | exact | 0.4% |
| Sepsis | 6.4% | 1.3% | exact | exact | 3.0% | exact |
| BPIC13 closed problems | 5.9% | exact | exact | exact | exact | exact |
| Helpdesk | 3.8% | exact | 1.7% | exact | exact | exact |
| RTFM | 2.1% | 2.3% | exact | exact | exact | exact |

These behaviours were tested and made no difference on any of the eight logs:

- **`HashSet` iteration order.** Earlier versions of this page named it as the likely
  cause. That was wrong: replacing ProM's `String` sets with sorted sets, or with three
  different pseudo-random orders, gives the same sizes on all eight logs.
- **Lowered thresholds that persist.** ProM mutates a shared settings object, so
  thresholds lowered for a small log stay lowered for the rest of the run.
- **The limit of 10 on alphabet size.**

Input details matter as well:

- **Log order.** Lookups use absolute variant indices, so the order of variants with
  equal frequency affects distance mode. Each log has to stay in file order.
- **BPIC15.** Its merged log is not published. The match needs each municipality's
  log kept in file order and its cases kept apart. Two case IDs occur in two
  municipalities: ProM treats them as separate traces, while pm4py, which scored the
  paper's clusters, merges them. That explains ProM's totals of 5,648 and 5,649 against
  pm4py's 5,647, and merging them also gives the published density of 0.308.

**The JAR that was read is 6.9.7**, and the runs used ProM 6.13. The exact match
suggests the behaviour did not change between them on these logs.

### The `prom_compatible` option

`cluster_traces(..., prom_compatible=True)` adds the two behaviours that decide
frequency mode: ProM's seeded token choice, and comparing fitness and sizes as
`float`. It needs the native miner. The distance bugs stay out, because they would
only match ProM by reproducing wrong distances.

| Log | Frequency | Distance: default | Distance: option | Distance sizes with the option |
| --- | --- | --- | --- | --- |
| BPIC12 | exact | exact | exact | 4224, 1965, 722, 6176 |
| BPIC13 closed problems | exact | exact | exact | 575, 175, 351, 206, 180 |
| BPIC13 incidents | exact | 0.4% | 0.4% | 1900, 2083, 352, 2848, 371 |
| RTFM | exact | 2.1% | 2.1% | 62316, 49883, 20627, 17544 |
| Helpdesk | exact | 4.0% | 4.0% | 2949, 883, 500, 248 |
| Sepsis | exact | 10.3% | 8.3% | 57, 627, 205, 63, 40, 58 |
| Hospital Billing | exact | 22.2% | 22.3% | 41391, 22457, 22632, 9841, 3679 |
| BPIC15 | exact | 28.2% | 27.1% | 3009, 1403, 364, 872 |

The percentages are the "Cases differ" measure above. BPIC15 counts distinct case IDs,
as ProM's published sizes do.

The emulation, with its distance behaviours off and these two on, gives the same
sizes on all 16 runs, which checks the Python replay against the Java one.

**Membership also agrees in frequency mode.** ER, graph density and graph entropy depend
only on membership, and they equal ProM's to 3 decimals on 22 of 24 values. The other two
are BPIC15's ER, 25.147 against 25.146, and its entropy, 24.255 against 24.257. Every
metric on closed problems, incidents, Helpdesk, RTFM and Sepsis matches.

Frequency mode is slower where variants need a real token choice, because those replay
case by case. It took 4.0 s rather than 0.3 s on Helpdesk, 18.6 s rather than 13.8 s on
BPIC12, and 100 s rather than 92 s on BPIC15. All these runs used
`minimal_cluster_size` 0.25 and target 1, and the option is not checked at other settings.

### Quality metrics

The script computes the paper's eight metrics with pm4py 2.7.8.4, the paper's
version. The version matters: with pm4py 2.7.23, RTFM's full-log fitness is 1.000
against the published 0.929, on identical data. With 2.7.8.4 the full-log rows
match to within 0.001, with these exceptions:

- RTFM simplicity is 0.619 against 0.630 in every run.
- Helpdesk precision is 0.781 or 0.796, against the published 0.781.
- Sepsis precision is 0.616 or 0.619, against the published 0.619.

The last two vary between runs on identical input, because pm4py's Inductive Miner does
(see "pm4py's run-to-run variation"). The same applies to every metric that uses it, so
identical clusters can still score differently. BPIC12 in distance mode matches ProM's
sizes and membership, yet its replay fitness was 0.944 in one run and 0.970 in another,
against the published 0.944.

Replacing ProM's rows with this package's and re-ranking against the paper's other
ten clustering methods and the full-log baseline gives the average ranks below.
The ProM column reproduces the paper's Table 2 for all 16 values. Alignment
metrics cover 6 logs, the others 8. Lower ranks are better.

| Metric | Frequency: default | Frequency: option | Frequency: ProM | Distance: default | Distance: option | Distance: ProM |
| --- | --- | --- | --- | --- | --- | --- |
| Replay fitness | 7.12 | 7.62 | 7.62 | 8.25 | 8.75 | 7.88 |
| Replay precision | 8.12 | 8.25 | 8.25 | 6.75 | 6.00 | 5.75 |
| Alignment fitness | 6.00 | 6.83 | 6.83 | 7.67 | 8.00 | 5.50 |
| Alignment precision | 7.00 | 7.33 | 7.33 | 6.83 | 5.83 | 6.00 |
| Simplicity | 9.25 | 8.38 | 8.50 | 6.38 | 5.50 | 6.62 |
| ER | 8.88 | 8.50 | 8.50 | 8.00 | 8.00 | 7.88 |
| Graph density | 8.88 | 8.38 | 8.38 | 8.62 | 8.50 | 8.62 |
| Graph entropy | 8.62 | 8.75 | 8.75 | 7.12 | 6.88 | 7.38 |

"Option" means `prom_compatible=True`. In frequency mode it equals ProM's rank on seven
metrics and differs by 0.12 on simplicity. By default, frequency mode stays within 0.83
of ProM's rank. Distance mode differs by up to 2.17 by default and 2.50 with the option,
both on alignment fitness.

Ranks on metrics that use the Inductive Miner vary between runs. In an earlier run,
default frequency mode ranked 7.75 on replay fitness rather than 7.12. These ranks should
not be read as one implementation being better, because a lower rank only reflects a
different clustering. The Friedman and Nemenyi tests were not rerun.

Clustering took 0.1 s to 100 s per run, with the longest on BPIC15. The paper reports no
ProM run times.

These numbers come from `benchmarks/docker/`, which builds the environment with pm4py
2.7.8.4, downloads the logs and runs the tests and both modes. Its `run.sh` has the commands.
The cluster sizes in default mode match an earlier run outside Docker on all 16 runs.

## Results on the ActiTraC page's logs

The [ActiTraC page](https://www.processmining.be/actitrac/) offers four more logs,
but no cluster sizes to compare with, so this table shows behaviour and run time
only. It uses `k=4` and assigns remaining traces to existing clusters. ICS fitness
can be negative, and the weighted average is by cases.

| Log | Mode | Time | Cluster sizes | Weighted ICS | Full log ICS |
| --- | --- | --- | --- | --- | --- |
| MCRM | frequency | 0.5 s | 742, 143, 24, 47 | 0.292 | -0.128 |
| MCRM | distance | 0.5 s | 462, 210, 237, 47 | 0.714 | -0.128 |
| KIM | frequency | 2.8 s | 18962, 3171, 1343, 1294 | 0.837 | 0.791 |
| KIM | distance | 6.4 s | 14201, 4061, 2519, 3989 | 0.831 | 0.791 |
| TSL | frequency | 1.0 s | 9583, 7660, 308, 261 | -1.170 | -1.414 |
| TSL | distance | 26.5 s | 8494, 5865, 2148, 1305 | -1.149 | -1.414 |
| ICP | frequency | 12.7 s | 9047, 2412, 314, 618 | -0.515 | -0.776 |
| ICP | distance | 16.7 s | 5425, 2755, 2907, 1304 | 0.372 | -0.776 |

Case, event and activity counts match the page, with one exception. For TSL the
page lists 1,908 variants and 42 activities, and the downloaded file gives 2,551
and 40, although its case and event counts match. The cause is unknown, so treat
the TSL rows with care.

## actitraceR differs from the authors' code

[actitraceR](https://github.com/bupaverse/actitraceR) (commit 89e3e24) ran on R 4.3.3
with its pm4py wrapper's pinned version, 2.7.2. This package ran with the same miner,
fitness and edit distance. The harness is in `benchmarks/compare_actitracer/`.
`run_docker.sh` there runs Helpdesk and Sepsis in a container with fixed hash seeds, and
`run_docker_rest.sh` runs the other six logs. `summarize.py` prints the tables, and
`score.py` scores the clusters with the paper's eight metrics.

### Behaviour

| Behaviour | actitraceR | ProM, and this package |
| --- | --- | --- |
| Miner and fitness | Inductive Miner, alignments | Heuristics Miner, ICS |
| Window | Ignored (see below) | Share of remaining variants, plus frequency ties |
| Minimal cluster size | Against cases left now | Against cases left when the cluster started |
| Look-ahead | Only after a stop at minimal size; fitness at least the target | Always; perfect fit only |
| Seed | Can be ignored, so clusters can end up empty | Always forms the cluster |
| `number_of_clusters` | Excludes the residual cluster | Includes it |
| Defaults (`k`, `mcs`) | 3, 0.6 | 4, 0.25 |

### Defects

This package does not reproduce these:

| Defect | Evidence |
| --- | --- |
| `window_size` has no effect. `relative_frequency` is computed on a table still grouped by trace, so every value is 1 | Run: all 226 Helpdesk variants stay in the window at 0, 0.25 and 1. On each of four hash seeds, the three windows give identical clusters (ARI 1.000) |
| The `mra` distance cannot run, because the function is commented out | Run: stops with "subscript out of bounds" |
| A perfect fit can fail the target. pm4py's `log_fitness` includes a small cost for silent moves | Run: an Inductive Miner model of all of Helpdesk fits 100% of traces, with `log_fitness` 0.99953 to 0.99956 across runs. At noise 0 and target 1 it gives 3059, 725, 479, 317, where this package gives one cluster of 4580 |
| Edit distance runs over the characters of tokens such as `[12]`, not over activities | Run: inserting `[3]` costs 3, inserting `[13]` costs 4, and replacing `[2]` with `[12]` costs 1. See the table below for the effect |
| `discover_pm` does not forward `...` to the miner, so a noise threshold passed that way is lost | Source. The runs here pass it through a wrapper instead |
| A log with no `complete` events stops with an error. The filter is exact, so `COMPLETE` and logs without lifecycle values lose every event | Run: on raw BPIC13 incidents and BPIC12 it reports 0 traces to cluster. The error comes later, in the final evaluation: raw BPIC13 closed problems stops in `mutate()` |
| An empty cluster stops the run with an error. A seed that misses the target leaves the cluster empty, and `pull()` then fails | Run: BPIC13 closed problems at target 1.00 stops with "`!!enquo(var)` must select exactly one column". The port stops at the same point there and on BPIC13 incidents at both targets |
| The maximal-repeat check reads single characters of tokens | Source only, because the `mra` option cannot run |

### Results

All runs use noise 0.2 and `k=4` unless noted. ARI is the adjusted Rand index between
two labellings, where 1 means identical. A port of actitraceR to Python, written from
its source, gives every case the same cluster as R with the same hash seed in all 48
runs where R finished: 20 on Helpdesk, 4 on Sepsis and 24 on the other six logs (ARI
1.000 each). That includes the different results of different hash seeds on Hospital
Billing and on BPIC12 and BPIC15 at target 0.99. It confirms this reading of the source on all eight logs.

Helpdesk, on hash seeds 0 to 3. Where the seeds give different results, each outcome
is listed and the ARI is a range:

| Target | `mcs` | actitraceR | This package, window 0.25 | ARI | This package, window 1 | ARI |
| --- | --- | --- | --- | --- | --- | --- |
| 0.99 | 0.25 | 3685, 279, 203, 413 | 3452, 317, 310, 501 | 0.438 | 3770, 340, 177, 293<br>3760, 338, 177, 305 | 0.519 to 0.524 |
| 0.95 | 0.25 | 4378, 73, 111, 18 | 3429, 317, 680, 154 | 0.214 | 3746, 590, 244 | 0.301 |
| 0.99 | 0.60 | 3647, 638, 203, 92<br>3637, 727, 113, 103<br>3645, 640, 203, 92 | 3433, 933, 162, 52 | 0.402 to 0.414 | 3750, 366, 434, 30 | 0.517 to 0.529 |
| 1.00 | 0.25 | 3059, 725, 479, 317 | 3508, 386, 295, 391 | 0.273 | 3451, 317, 301, 511<br>3451, 317, 302, 510 | 0.287 |
| 1.00, noise 0 | 0.25 | 3059, 725, 479, 317 | 4580 | 0.000 | 4580 | 0.000 |

Window 1 is the closest match to actitraceR ignoring the window. In actitraceR, the
1.00 rows at noise 0.2 and noise 0 give identical clusters. This package's window 1
gives three clusters at target 0.95, because every variant has a cluster by then.

Sepsis, with `k=6` and hash seeds 0 and 1. Windows 0.25 and 1 give identical clusters
in this package. The ARI compares the same seed:

| Target | actitraceR, and the port | This package | ARI |
| --- | --- | --- | --- |
| 0.99 | 148, 710, 139, 43, 6, 4<br>172, 676, 26, 5, 167, 4 | 704, 34, 136, 146, 23, 7<br>705, 33, 132, 78, 93, 9 | 0.208<br>0.195 |
| 1.00 | 36, 94, 37, 671, 191, 21<br>36, 94, 37, 671, 191, 21 | 175, 109, 257, 447, 23, 39<br>175, 108, 258, 446, 23, 40 | 0.247<br>0.246 |

actitraceR's final evaluation did not finish on Sepsis. All four runs were still in it
at the 3-hour limit, 2.4 to 2.6 hours after clustering ended, so `cluster_traces` never
returned. The labels above exist because `run_r.R` saves them just before that step,
which leaves the clustering unchanged. On the 28 Helpdesk runs that finished, the saved
sizes equal the returned sizes.

`evaluation_time.py` repeats the steps of that evaluation on the clusters of target 1.00,
seed 0, and times each. Fitness and precision of the six cluster models take 430 s
together, 408 s of it for one cluster's precision. The evaluation also mines the whole
log at noise 0, a model with 39 places and 50 transitions. Its fitness takes 769 s and
its precision 40,412 s (11.2 hours). So a full actitraceR run on Sepsis needs about
12 to 13 hours, almost all of it for the precision of a model of the whole log.

#### The other six logs

These ran with `run_docker_rest.sh`, with a 12-hour limit per run and 32 runs at once
on 32 CPUs, on hash seeds 0 and 1. The 15 runs that reached the limit, all on BPIC12 and
BPIC15, ran again with a 48-hour limit (`LIMIT=172800`) and 15 runs at once on 16 CPUs,
and all finished. Two changes were needed to get results from
actitraceR, and the port and this package got the same input:

- **Lifecycle.** actitraceR keeps only events whose lifecycle is exactly `complete`.
  `make_csv.py` turns BPIC12's `COMPLETE` into `complete`, so the other values stay out
  as before, and marks every event of BPIC13 complete, since its lifecycle values are
  statuses. The other four logs are unchanged.
- **Empty clusters.** With `ACTITRACER_DROP_EMPTY=1`, `run_r.R` removes empty clusters
  before the residual step, and the port does the same with `empty=drop`. This changed
  only BPIC13: closed problems at target 1.00 and incidents at both targets otherwise
  stop with an error.

The final evaluation was left out (`ACTITRACER_EVALUATE=0`), since it does not change
the clusters. The original error logs are kept in `unrefined/` in the result
directory. Sizes are for seed 0, and seed 1 gave the same unless listed:

| Log | Target | actitraceR, and the port | This package, window 0.25 | ARI | This package, window 1 | ARI |
| --- | --- | --- | --- | --- | --- | --- |
| BPIC13 closed problems, `k=5` | 1.00 | 947, 534, 5, 1 | 946, 469, 33, 10, 29 | 0.844 | Same as window 0.25 | 0.844 |
| | 0.99 | 952, 485, 23, 22, 5 | 946, 510, 25, 4, 2 | 0.957 | Same as window 0.25 | 0.957 |
| BPIC13 incidents, `k=5` | 1.00 | 3046, 4503, 5 | 2930, 3241, 1120, 228, 35 | 0.680 | Same as window 0.25 | 0.680 |
| | 0.99 | 7550, 4 | 7095, 449, 4, 1, 5 | 0.016 | Same as window 0.25 | 0.016 |
| RTFM | 1.00 | 75556, 67134, 3583, 4097 | 66194, 70372, 9668, 4136 | 0.846 | 66086, 70372, 9786, 4126 | 0.847 |
| | 0.99 | 66050, 70324, 6018, 7978 | 66017, 70370, 13031, 952 | 0.990 | 66277, 70336, 12158, 1599<br>Seed 1: 66277, 70363, 12133, 1597 | 0.987 |
| Hospital Billing, `k=5` | 1.00 | 40105, 22436, 26900, 8595, 1964 | 57279, 30810, 9389, 1667, 855<br>Seed 1: 57461, 30810, 8990, 1645, 1094 | 0.469 | 54684, 30911, 6266, 2246, 5893 | 0.443 |
| | 0.99 | 57389, 33060, 3296, 3112, 3143<br>Seed 1: 57770, 33060, 3351, 3019, 2800 | 60484, 33053, 3069, 2061, 1333<br>Seed 1: 60485, 33052, 3128, 2567, 768 | 0.888<br>0.896 | 57378, 33153, 3843, 3098, 2528<br>Seed 1: 57384, 33154, 3935, 3500, 2027 | 0.956<br>0.965 |
| BPIC12 | 1.00 | 3484, 6167, 946, 2490 | 6083, 1989, 2583, 2432<br>Seed 1: 6082, 2186, 2942, 1877 | 0.223<br>0.215 | Same as window 0.25 | 0.223<br>0.215 |
| | 0.99 | 6211, 1923, 2174, 2779<br>Seed 1: 6211, 1891, 2338, 2647 | 6210, 2273, 2709, 1895<br>Seed 1: 6214, 4555, 2313, 5 | 0.816<br>0.730 | Same as window 0.25 | 0.816<br>0.730 |
| BPIC15 | 1.00 | 824, 980, 757, 3088 | 4011, 388, 428, 822 | 0.006 | Same as window 0.25 | 0.006 |
| | 0.99 | 1418, 2521, 1028, 682<br>Seed 1: 1372, 2095, 1296, 886 | 1370, 2665, 1434, 180<br>Seed 1: 5562, 53, 23, 11 | 0.346<br>−0.003 | Same as window 0.25 | 0.346<br>−0.003 |

The BPIC15 sizes count the unique case IDs of the five municipalities, so they sum to
5649. On the raw logs, without the lifecycle change, actitraceR finds 0 traces to
cluster on BPIC13 and BPIC12.

Across the eight logs, this package and actitraceR agree from not at all (ARI −0.003
and 0.006 on BPIC15) to nearly fully (0.990 on RTFM at target 0.99). Which of the
differences causes the gap on these logs was measured only on Helpdesk (below).

Run times with 16 jobs at once on 16 CPUs:

| Log and setting | actitraceR | Port | This package |
| --- | --- | --- | --- |
| Helpdesk, target 0.99, `mcs` 0.25 | 144 s to 148 s (about 123 s clustering) | 9 s to 10 s | 8 s to 9 s |
| Sepsis, target 0.99 | 1750 s to 2264 s clustering, evaluation unfinished | 1264 s to 1611 s | 708 s to 762 s |
| Sepsis, target 1.00 | 1377 s to 1396 s clustering, evaluation unfinished | 192 s to 194 s | 1210 s to 1245 s |

On Helpdesk, most of R's time is not the algorithm, since the port runs the same steps
in far less time. R also converts each sublog from R to Python, and evaluates fitness
and precision at the end. The port leaves that evaluation out.

On the other six logs, with 32 runs at once on 32 CPUs and no final evaluation in R,
in seconds. Times marked * come from the rerun with a 48-hour limit and 15 runs at once
on 16 CPUs, so the load differed:

| Log and target | actitraceR | Port | This package, window 0.25 |
| --- | --- | --- | --- |
| BPIC13 closed problems, 1.00 | 147 | 10 | 3 |
| BPIC13 closed problems, 0.99 | 39 | 5 | 13 |
| BPIC13 incidents, 1.00 | 3340 to 3494 | 181 to 184 | 157 to 167 |
| BPIC13 incidents, 0.99 | 375 to 376 | 49 | 75 to 92 |
| RTFM, 1.00 | 4633 to 4638 | 49 to 57 | 7 |
| RTFM, 0.99 | 3907 to 3916 | 29 to 36 | 8 |
| Hospital Billing, 1.00 | 18677 to 18731 | 126 to 155 | 1359 to 3198 |
| Hospital Billing, 0.99 | 14662 to 14948 | 430 to 457 | 296 to 299 |
| BPIC12, 1.00 | 19910 to 20180 | 1784 to 1786 | 42249 to 43036* |
| BPIC12, 0.99 | 49966 to 56688* | 19942 to 22468 | 20695; seed 1: 50372* |
| BPIC15, 1.00 | 6629 to 7071 | 621 to 637 | 22794 to 23128 |
| BPIC15, 0.99 | 44042 to 84797* | 35482; seed 1: 67102* | 47596 to 96923* |

In the first batch, each of the runs marked * reached the 12-hour limit.

On BPIC12 at target 1.00 and on BPIC15, this package in actitraceR's configuration is
far slower than the port. It keeps adding to a cluster until the minimal size counted at
the cluster's start, and its look-ahead aligns every remaining variant, so it may mine and
align many more sublogs. That is a likely cause, not a measured one.

### What causes the gap

The port has one switch for each difference, and turning on all of them gives this
package's clusters exactly, with ARI 1.000 on four hash seeds. That accounts for the
whole gap on Helpdesk at target 0.99. Turning on one at a time from actitraceR gives
the following on hash seed 1. The last column shows the seeds with other results:

| Change to actitraceR | Sizes | ARI against actitraceR | Other seeds |
| --- | --- | --- | --- |
| Look-ahead always, at perfect fit | 2811, 554, 645, 570 | 0.239 | Seed 0: 2812, 554, 644, 570 (0.240) |
| Edit distance over activities | 4045, 336, 92, 107 | 0.250 | Seed 0: 4074, 335, 109, 62 (0.239)<br>Seed 3: 4357, 81, 118, 24 (0.199) |
| Minimal size against the cases at the start | 3663, 556, 203, 158 | 0.926 | Seed 0: 3670, 549, 203, 158 (0.929) |
| Fitness without the silent-move cost | 3714, 248, 203, 415 | 0.975 | Seed 0: 3693, 248, 203, 436 (0.960) |
| Miner input in cluster order | 3671, 275, 203, 431 | 0.975 | Seed 3: 3692, 279, 203, 406 (0.982) |
| Frequency ties in log order | 3693, 287, 203, 397 | 0.990 | None |
| Residuals against the model before look-ahead | 3679, 279, 203, 419 | 0.995 | None |
| Seed always joins | 3685, 279, 203, 413 | 1.000 | None |

### pm4py's run-to-run variation

pm4py's Inductive Miner with a noise threshold can give different models for the
same traces, so neither implementation repeats exactly by default:

- **Hash seed.** With hash seeds left unset, one R configuration gave 3685, 279, 203,
  413 in six of nine runs and 3653, 464, 205, 258 in three (ARI 0.740). Seeds 0 to 3
  all gave the first result, so the second has no known seed. Other settings do vary
  with these seeds. R and the port give three outcomes at `mcs` 0.60 (lowest ARI 0.958),
  and two at target 0.99 on Sepsis (ARI 0.711), as well as on Hospital Billing at
  target 0.99 and on BPIC12 and BPIC15 at target 0.99. This package gave 3760, 338, 177, 305 or
  3770, 340, 177, 293 (ARI 0.991), and on Sepsis ARI 0.967 at target 0.99 and 0.996 at
  target 1.00. On BPIC12 and BPIC15 at target 0.99 its two seeds differ widely, for
example 1370, 2665, 1434, 180 against 5562, 53, 23, 11 on BPIC15. `PYTHONHASHSEED`
selects the outcome.
- **Trace order.** The same traces in a different order can give a different model
  when passed as an event log. At one Helpdesk step, 2 of 6 random orders gave fitness
  0.91719 and the others 0.99993. Four shuffled data frames did not vary at that step.
  This check has not been repeated in the container.

Differences below this level say nothing about the two implementations. Set
`PYTHONHASHSEED` to repeat a run with this miner.

With correct fitness, the Inductive Miner at noise 0 fits everything, so one cluster
takes the whole log. `discover_algorithm` therefore needs a noise threshold to be
useful here.

## Deliberate differences from ProM

| Area | ProM | This package | Why |
| --- | --- | --- | --- |
| Small-log thresholds | Lowered thresholds stay lowered for the rest of the run | Recomputed for each log | Order-dependent side effect. No effect on the eight logs above |
| Token choice in replay | Seeded random among options, drawn per trace in log order | Smallest cover, lowest index first | Lets variants be replayed once instead of every case. `prom_compatible=True` follows ProM |
| Fitness comparison | Cast to `float` first | Exact | The cast hides leftover tokens on large logs, more so the larger the log. It is the main cause of the BPIC12 gap in frequency mode. `prom_compatible=True` follows ProM |
| Distance lookup | Reads the wrong matrix cell (see above) | Reads the correct cell | Bug |
| Replay with conflicting input sets | Can drop the combination and consume nothing | Always consumes a cover | Appears to be an unintended outcome of the search |
| Base MRA features | Decomposes only the last repeat from a `HashSet`, and drops super-maximal repeats | Uses all repeats, drops only the inputs | Bug: the buffer is reset inside the loop |
| Distance sum | Truncated to an `int` at each step | Exact | Rounding artefact. It only reaches ProM's results together with the lookup bug |
| Base MRA alphabets | Cut with the wrong encoding length (see above) | One alphabet symbol per activity | Bug |
| Petri net conversion | ProM's converter returns no final marking | One place per XOR set, joined by silent transitions, with a sink | Alignments need a final marking |

Frequency mode keeps one ProM quirk on purpose: the seed does not count towards
the minimal cluster size, and its fitness is not tested. Normalising this moved
the Helpdesk result from 3824 to 3456 cases in the first cluster, against ProM's
3828.

## ActiTraC-MO

The published page describes a threshold on weighted F-score and P/T
connectivity. The code differs from that description, and this package combines
them:

| Aspect | ProM code | This package |
| --- | --- | --- |
| Algorithm | Clusters grown in parallel from random frequent seeds | Same |
| Miner | Fodina, with Heuristics Miner commented out in the wizard | Native Heuristics Miner, because no Python Fodina was available |
| Recall | Recall from ProM's `PetrinetEvaluatorPlugin` | pm4py token-based fitness |
| Precision | ETConformance | pm4py ETConformance |
| Trace score | F-score on a log holding only that trace | Same |
| β | Fixed at 1; the UI value is unused | Applied as documented on the page |
| Complexity | Average connector degree, as an ineffective tie-break | P/T connectivity, as a tie-break and an optional limit |
| Residual assignment | Ranks by cluster F-score first, which sends nearly every variant to one cluster | Ranks by the variant's F-score first |
| Seeds that never qualify | Retries forever | Widens the window, then returns fewer clusters |

Because of the miner and recall substitutions, results are **not** expected to
match ProM's ActiTraC-MO, and no reference results were available to compare
against.

Results on MCRM (956 cases, 212 variants) with `k=4`:

| Thresholds (cluster, trace) | Seed | Time | Clusters, as cases/variants |
| --- | --- | --- | --- |
| 0.95, 0.90 (defaults) | 1 | 23 s | 444/3, 117/4, 22/3, 50/6, residual 323/196 |
| 0.95, 0.90 (defaults) | 2 | 22 s | 117/3, 46/5, 447/3, 30/3, residual 316/198 |
| 0.80, 0 | 1 | 197 s | 576/101, 308/78, 50/31, 22/2 |
| 0.80, 0 | 2 | 146 s | 305/100, 41/4, 564/97, 46/11 |

For seed 2 with the lower thresholds, the F-score weighted over clusters is 0.934,
against 0.844 for one model of the full log. Precision is 0.987 against 0.838, and
fitness 0.889 against 0.850.

**The default thresholds leave most variants in the residual cluster on this
log.** A likely reason is the trace score: ETConformance on a log of one trace
penalises every choice the model allows and that trace does not take. ProM uses
the same measure, but whether it behaves this way there is unknown, because this
package uses a different miner and recall measure. Lower
`minimal_trace_correctness` if the residual cluster is too large.

Run time grows with the cluster size, since each variant retrains and rescores up
to `k` clusters. pm4py's replay and ETConformance account for almost all of it.
Precision is skipped when recall alone already rules a cluster out.

## Not implemented

- Long-distance dependencies in the Heuristics Miner, which are off by default.
- Duplicate-task handling in replay, which the Heuristics Miner never produces.
- The other ExpertTraceClustering plugins (seeded, semi-supervised, constrained).
