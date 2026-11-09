"""ActiTraC: active trace clustering (De Weerdt et al., TKDE 2013)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import replace

import numpy as np

from .distance import DistanceMetric, distance_rows
from .heuristics import HeuristicsMiner, HeuristicsSettings
from .log import ACTIVITY_KEY, CASE_KEY, LIFECYCLE_KEY, TIMESTAMP_KEY, Variant, extract_variants
from .result import Cluster, TraceClustering

logger = logging.getLogger("actitrac")

_PERFECT = 1.0 - 1e-9


def resolve_miner(
    discover_algorithm: Callable | None,
    fitness_metric: str,
    settings: HeuristicsSettings | None,
) -> Callable:
    """Return the miner: native Heuristics Miner, or a wrapped pm4py function."""
    if discover_algorithm is None:
        return HeuristicsMiner(settings or HeuristicsSettings())
    if settings is not None:
        raise ValueError("settings only apply to the native Heuristics Miner")
    from .petri import PetriNetMiner

    return PetriNetMiner(discover_algorithm, fitness_metric)


def cluster_traces(
    log,
    number_of_clusters: int = 4,
    target_fitness: float = 1.0,
    minimal_cluster_size: float = 0.25,
    window_size: float = 0.25,
    cluster_remaining_traces: bool = True,
    distance_metric: DistanceMetric = "mra",
    stop_percentage: float | None = None,
    discover_algorithm: Callable | None = None,
    fitness_metric: str = "alignments",
    settings: HeuristicsSettings | None = None,
    case_key: str = CASE_KEY,
    activity_key: str = ACTIVITY_KEY,
    timestamp_key: str = TIMESTAMP_KEY,
    lifecycle_key: str = LIFECYCLE_KEY,
    lifecycle: str | None = "classifier",
    prom_compatible: bool = False,
) -> TraceClustering:
    """Cluster a log by growing each cluster until its model stops fitting.

    Defaults follow ActiTraC-ProM, the authors' ProM plugin, not actitraceR. See
    docs/fidelity.md for the differences.

    Parameters
    ----------
    log:
        A DataFrame, pm4py EventLog or ``{activity_tuple: count}`` dict.
    number_of_clusters:
        Total number of clusters, including the residual cluster when
        ``cluster_remaining_traces`` is true.
    target_fitness:
        Fitness a cluster's model must keep while it grows.
    minimal_cluster_size:
        Fraction of the cases still unclustered when a cluster starts. Below
        this size a non-fitting variant is skipped; at or above it the cluster
        stops growing. With ``window_size=0`` the seed does not count towards
        the size, as in ActiTraC-ProM's frequency-based clusterer.
    window_size:
        Fraction of remaining variants, most frequent first, eligible for
        selection. ``0`` selects strictly by frequency and computes no distances.
    cluster_remaining_traces:
        Put leftover variants in one extra cluster (true), or give each to the
        cluster whose model fits it best (false).
    distance_metric:
        ``"mra"`` (maximal repeat alphabet), ``"osa"`` (edit distance over
        activities), or a callable taking two activity sequences.
    stop_percentage:
        If set, stop forming clusters once this percentage of cases is clustered,
        instead of using ``number_of_clusters``.
    discover_algorithm:
        ``None`` for the native Heuristics Miner with ICS fitness, or a function
        mapping a pm4py EventLog to ``(net, initial, final)``.
    fitness_metric:
        ``"alignments"`` or ``"token_replay"``, for ``discover_algorithm`` only.
    settings:
        Thresholds for the native Heuristics Miner.
    prom_compatible:
        Follow ProM's seeded token choice and compare fitness and sizes as ``float``.
        This gives ActiTraC-ProM's published cluster sizes in frequency mode, and can run
        slower. Distance mode stays different, because ProM's distance bugs are not
        reproduced. Needs the native miner. See docs/fidelity.md.
    """
    if number_of_clusters < 1:
        raise ValueError("number_of_clusters must be at least 1")
    if not 0 <= window_size <= 1:
        raise ValueError("window_size must be between 0 and 1")

    if prom_compatible:
        if discover_algorithm is not None:
            raise ValueError("prom_compatible only applies to the native Heuristics Miner")
        settings = replace(settings or HeuristicsSettings(), prom_replay=True)

    variant_log = extract_variants(
        log, case_key, activity_key, timestamp_key, lifecycle_key, lifecycle
    )
    variants = list(variant_log.variants)
    if not variants:
        raise ValueError("the log contains no traces")
    miner = resolve_miner(discover_algorithm, fitness_metric, settings)
    row = distance_rows(distance_metric, variants) if window_size > 0 else None

    remaining = list(range(len(variants)))
    clusters: list[Cluster] = []
    total_cases = variant_log.n_cases
    clustered_cases = 0
    regular_clusters = number_of_clusters - 1 if cluster_remaining_traces else number_of_clusters

    while remaining:
        cluster = _grow_cluster(
            len(clusters), variants, remaining, miner, row,
            target_fitness, minimal_cluster_size, window_size, prom_compatible,
        )
        clusters.append(cluster)
        clustered_cases += cluster.n_cases
        logger.info("cluster %d: %d cases, %d left",
                    cluster.id, cluster.n_cases, total_cases - clustered_cases)
        if stop_percentage is not None:
            if clustered_cases / total_cases * 100 >= stop_percentage:
                break
        elif len(clusters) >= regular_clusters:
            break

    _resolve_residuals(clusters, variants, remaining, miner, cluster_remaining_traces)
    return TraceClustering(clusters, variant_log, miner)


def _grow_cluster(
    cluster_id: int,
    variants: Sequence[Variant],
    remaining: list[int],
    miner: Callable,
    row: Callable[[int], np.ndarray] | None,
    target_fitness: float,
    minimal_cluster_size: float,
    window_size: float,
    prom_compatible: bool = False,
) -> Cluster:
    """Build one cluster, removing the variants it takes from ``remaining``."""
    # Phase 1: selection. The most frequent variant always seeds the cluster.
    left = sum(variants[i].frequency for i in remaining)
    seed = remaining[0]
    members = [seed]
    model = miner([variants[seed]])
    candidates = remaining[1:]

    def fits(candidate_model, log: list[Variant]) -> bool:
        if not prom_compatible:
            return candidate_model.fitness(log) >= target_fitness
        # ActiTraC-ProM's distance clusterer lists the newest variant first, and replay order
        # decides the seeded token choices.
        return candidate_model.fits(log if row is None else log[::-1], target_fitness)

    if row is None:
        # ActiTraC-ProM's two clusterers differ here. The frequency-based one leaves the
        # seed out of the size and never tests it. Reproducing its published
        # results depends on this, because a dominant seed would otherwise end
        # the cluster at the first misfit.
        size = 0
        distances = None
        stop = False
    else:
        size = variants[seed].frequency
        distances = row(seed).copy()
        stop = not fits(model, [variants[seed]])
    large_enough = _size_test(left, minimal_cluster_size, row is None, prom_compatible)

    while not stop and candidates:
        choice = _select(candidates, variants, distances, window_size)
        grown = [variants[i] for i in members] + [variants[choice]]
        new_model = miner(grown)
        candidates.remove(choice)
        if fits(new_model, grown):
            members.append(choice)
            model = new_model
            size += variants[choice].frequency
            if distances is not None:
                distances += row(choice)
        elif large_enough(size):
            stop = True

    taken = set(members)
    remaining[:] = [i for i in remaining if i not in taken]

    # Phase 2: look-ahead. Variants that fit perfectly join without retraining.
    external = [i for i in remaining if model.trace_fitness(variants[i].activities) >= _PERFECT]
    joined = set(external)
    remaining[:] = [i for i in remaining if i not in joined]

    return Cluster(
        cluster_id,
        [variants[i] for i in members],
        model,
        [variants[i] for i in external],
    )


def _size_test(
    left: int, minimal_cluster_size: float, frequency_mode: bool, prom_compatible: bool
) -> Callable[[int], bool]:
    """Return the test for a cluster reaching its minimal size."""
    if not prom_compatible:
        minimal = left * minimal_cluster_size
        minimal = minimal if frequency_mode else int(minimal)
        return lambda size: size >= minimal
    rounded = np.float32(left) * np.float32(minimal_cluster_size)
    if frequency_mode:
        return lambda size: bool(np.float32(size) >= rounded)
    return lambda size: size >= int(rounded)


def _select(
    candidates: list[int],
    variants: Sequence[Variant],
    distances: np.ndarray | None,
    window_size: float,
) -> int:
    """Pick the variant nearest the cluster among the window's frequent ones."""
    if distances is None:
        return candidates[0]
    rank = max(int(len(candidates) * window_size), 1)
    minimal_frequency = variants[candidates[rank - 1]].frequency
    window = [i for i in candidates if variants[i].frequency >= minimal_frequency]
    return min(window, key=lambda i: distances[i])


def _resolve_residuals(
    clusters: list[Cluster],
    variants: Sequence[Variant],
    remaining: list[int],
    miner: Callable,
    separate: bool,
) -> None:
    """Phase 3: place variants left over once the stop criterion is reached."""
    if not remaining:
        return
    leftovers = [variants[i] for i in remaining]
    if separate:
        clusters.append(Cluster(len(clusters), leftovers, miner(leftovers), is_residual=True))
    else:
        for variant in leftovers:
            best = max(clusters, key=lambda c: c.model.trace_fitness(variant.activities))
            best.external.append(variant)
    remaining.clear()


def cluster(
    input,
    num_clusters: int,
    outputshape: str = "log",
    variant: str = "distance",
    **kwargs,
):
    """Run ActiTraC with the calling convention of ``entroclus.entropic_clustering``.

    ``variant`` is ``"distance"`` (``actitrac_dist``) or ``"frequency"``
    (``actitrac_freq``). ``outputshape`` is ``"log"`` for a list of filtered logs
    or ``"variant_log"`` for a list of ``{activities: count}`` dicts.
    """
    if variant not in ("distance", "frequency"):
        raise ValueError("variant has to be 'distance' or 'frequency'")
    if outputshape not in ("log", "variant_log"):
        raise ValueError("outputshape has to be 'log' or 'variant_log'")
    if isinstance(input, dict) and outputshape != "variant_log":
        raise ValueError("when input is a variant log, outputshape has to be 'variant_log'")
    if variant == "frequency":
        kwargs["window_size"] = 0
    result = cluster_traces(input, number_of_clusters=num_clusters, **kwargs)
    return result.logs() if outputshape == "log" else result.variant_logs()
