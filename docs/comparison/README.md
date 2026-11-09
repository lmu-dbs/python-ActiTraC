# Implementation comparison page

This page compares ProM's published results, this package, actitraceR and its Python
port on the eight logs of [Peeperkorn et al.](https://arxiv.org/abs/2506.23776). It shows
cluster sizes, the paper's metrics, the adjusted Rand index between implementations,
run times and actitraceR's defects. [fidelity.md](../fidelity.md) explains the results.

Open [comparison.html](comparison.html) in a browser. It needs no server and no network.

| File | What it is |
| --- | --- |
| `page.html` | The page's markup and script. It reads its data through a small `dash` API that `render.py` supplies |
| `data/*.csv` | The page's data, one file per table |
| `build_data.py` | Writes `data/` from the Docker results |
| `render.py` | Writes `comparison.html` from `page.html` and `data/` |
| `comparison.html` | The standalone page. Generated, so don't edit it by hand |

## Rebuilding

The results come from three Docker runs, with the volume `actitrac-data` at `/data`:

1. `benchmarks/docker/run.sh` writes `/data/out`: this package and ProM's published
   results.
2. `benchmarks/compare_actitracer/run_docker.sh` and `run_docker_rest.sh` write
   `/data/r_out`: actitraceR, the port, and this package with actitraceR's miner.
3. `benchmarks/compare_actitracer/score.py` scores those runs. Save its output as
   `/data/r_out/score.json`.

Before you rerun timed-out jobs with a longer `LIMIT`, move their logs to
`/data/r_out/timeout_12h/`. The times table then marks those rows. Then rebuild:

```bash
python docs/comparison/build_data.py OUT R_OUT    # needs pandas
python docs/comparison/render.py
```

`OUT` and `R_OUT` are local copies of `/data/out` and `/data/r_out`.
