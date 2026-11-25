# Changelog

## Unreleased

### Bug fixes
- Handled missing (`NaN`/`None`) and `Categorical` values in DataFrame event logs without crashing under pandas 3.x.
- Fixed `cluster_traces(..., number_of_clusters=1, cluster_remaining_traces=True)` silently producing 2 clusters instead of enforcing the residual-cluster invariant.
- Wired `fitness_metric="alignments"` through `cluster_traces_mo` (both fitness and precision scoring) instead of silently falling back to token replay.
- Returned `inf` for MRA distance between distinct variants with no repeat features, matching ActiTraC-ProM's `Integer.MAX_VALUE` behaviour instead of `0.0`.
- Guarded `alignment_fitness` and `PetriNetModel` against unsound Petri nets so alignment-based clustering falls back to fitness `0.0` instead of raising an exception.
- Connected `source` and `sink` via silent transitions in `heuristics_to_petri_net` when start or end activities have incoming/outgoing loop edges.
- Used `self.dependency_divisor` and guarded `cases <= 0` in `HeuristicsSettings.for_log_size`, guarded empty traces in `HeuristicsNet.trace_fitness`, guarded empty nets in `pt_connectivity`, and avoided duplicate single-variant seed evaluations and repeated `to_petri_net()` conversions in `cluster_traces_mo`.

### Behaviour changes
- `cluster_traces` now raises `ValueError` when `number_of_clusters < 2` with `cluster_remaining_traces=True` and no `stop_percentage`.
- Events with missing activity names are dropped with a `UserWarning`; missing lifecycle transitions become `name+` in `"classifier"` mode and are dropped in `"complete"` mode.
- Unsound Petri nets evaluated for alignments emit a `RuntimeWarning` when scoring `0.0`.

### Additions
- Added validation for `minimal_cluster_size`, `stop_percentage`, `cluster_traces_mo(..., beta=...)`, and `cluster_traces_mo(..., fitness_metric=...)`.
- Added `f_score_beta` propagation from `cluster_traces_mo` to `TraceClustering.metrics()` and an optional `beta` override on `TraceClustering.metrics()`.
- Added `tests/test_online_alignment.py` (cross-checks against `Emu.java`, `replica.py`, `entroclus`, and `ActiTraC-MO`) and expanded `tests/test_prom_reference.py` to cover all eight Peeperkorn et al. benchmark logs.
