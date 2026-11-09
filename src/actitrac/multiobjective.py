"""ActiTraC-MO: multi-objective trace clustering (De Koninck & De Weerdt, 2016)."""

from __future__ import annotations

import logging
import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from . import petri
from .clustering import resolve_miner
from .heuristics import HeuristicsSettings
from .log import ACTIVITY_KEY, CASE_KEY, LIFECYCLE_KEY, TIMESTAMP_KEY, Variant, extract_variants
from .result import Cluster, TraceClustering

logger = logging.getLogger("actitrac")


@dataclass
class _Candidate:
    model: object
    variants: list[Variant]
    score: float
    trace_score: float
    complexity: float

    def rank(self) -> tuple[float, float, float]:
        return self.score, self.trace_score, -self.complexity


def cluster_traces_mo(
    log,
    number_of_clusters: int = 4,
    minimal_correctness: float = 0.95,
    minimal_trace_correctness: float = 0.90,
    beta: float = 1.0,
    maximal_complexity: float | None = None,
    cluster_remaining_traces: bool = True,
    seed: int | None = None,
    discover_algorithm: Callable | None = None,
    fitness_metric: str = "token_replay",
    settings: HeuristicsSettings | None = None,
    case_key: str = CASE_KEY,
    activity_key: str = ACTIVITY_KEY,
    timestamp_key: str = TIMESTAMP_KEY,
    lifecycle_key: str = LIFECYCLE_KEY,
    lifecycle: str | None = "classifier",
) -> TraceClustering:
    """Grow ``number_of_clusters`` clusters in parallel, scored by F-score.

    Unlike ActiTraC, clusters start from random frequent variants. Each variant,
    most frequent first, joins the cluster whose retrained model scores best,
    provided it clears the thresholds. Requires pm4py. Defaults follow the
    authors' ProM plugin; docs/fidelity.md lists the substitutions.

    Parameters
    ----------
    number_of_clusters:
        Clusters to grow, not counting the residual cluster.
    minimal_correctness:
        F-score the grown cluster's model must reach on the cluster's log.
    minimal_trace_correctness:
        F-score the grown model must reach on the variant alone.
    beta:
        F-score weight; above 1 favours recall over precision.
    maximal_complexity:
        Optional upper limit on the model's P/T connectivity degree. Values
        depend on the Petri net conversion, so they do not transfer from ProM.
    cluster_remaining_traces:
        Put variants that fit nowhere in an extra cluster (true), or give each
        to the cluster that scores it best (false).
    seed:
        Seed for the random choice of initial variants.
    """
    petri._require_pm4py()
    if number_of_clusters < 1:
        raise ValueError("number_of_clusters must be at least 1")

    variant_log = extract_variants(
        log, case_key, activity_key, timestamp_key, lifecycle_key, lifecycle
    )
    remaining = list(variant_log.variants)
    if not remaining:
        raise ValueError("the log contains no traces")
    miner = resolve_miner(discover_algorithm, fitness_metric, settings)
    rng = random.Random(seed)

    def evaluate(variants: list[Variant], newcomer: Variant) -> _Candidate:
        model = miner(variants)
        net, initial, final = model.to_petri_net()
        score = _f_score(variants, net, initial, final, beta, minimal_correctness)
        trace_score = (
            _f_score([newcomer], net, initial, final, beta, minimal_trace_correctness)
            if score >= minimal_correctness
            else 0.0
        )
        return _Candidate(model, variants, score, trace_score, petri.pt_connectivity(net))

    def acceptable(candidate: _Candidate) -> bool:
        return (
            candidate.score >= minimal_correctness
            and candidate.trace_score >= minimal_trace_correctness
            and (maximal_complexity is None or candidate.complexity <= maximal_complexity)
        )

    groups = _seed_clusters(remaining, number_of_clusters, rng, evaluate, acceptable)
    logger.info("seeded %d clusters, %d variants left", len(groups), len(remaining))

    # Phase 1: assign each variant to the best cluster that can absorb it.
    unassigned = []
    for variant in remaining:
        options = [
            (position, candidate)
            for position, group in enumerate(groups)
            if acceptable(candidate := evaluate(group.variants + [variant], variant))
        ]
        if options:
            position, best = max(options, key=lambda option: option[1].rank())
            groups[position] = best
        else:
            unassigned.append(variant)

    clusters = [
        Cluster(i, group.variants, group.model) for i, group in enumerate(groups)
    ]

    # Phase 2: place what is left.
    if unassigned and (cluster_remaining_traces or not clusters):
        clusters.append(
            Cluster(len(clusters), unassigned, miner(unassigned), is_residual=True)
        )
    elif unassigned:
        for variant in unassigned:
            best = max(clusters, key=lambda c: _residual_rank(c, groups, variant, beta))
            best.external.append(variant)

    return TraceClustering(clusters, variant_log, miner)


def _seed_clusters(
    remaining: list[Variant],
    count: int,
    rng: random.Random,
    evaluate: Callable,
    acceptable: Callable,
) -> list[_Candidate]:
    """Draw seeds from the most frequent 10% of variants, widening if none qualify.

    ProM retries the 10% window forever when no seed qualifies; here the window
    grows instead, and fewer clusters are returned if the log runs out.
    """
    window = math.ceil(len(remaining) * 0.1)
    groups: list[_Candidate] = []
    rejected: set[int] = set()
    while len(groups) < count and remaining:
        options = [v for v in remaining[:window] if v.id not in rejected]
        if not options:
            if window >= len(remaining):
                break
            window = min(window * 2, len(remaining))
            continue
        variant = rng.choice(options)
        candidate = evaluate([variant], variant)
        if acceptable(candidate):
            groups.append(candidate)
            remaining.remove(variant)
        else:
            rejected.add(variant.id)
    return groups


def _f_score(
    variants: Sequence[Variant], net, initial, final, beta: float, floor: float = 0.0
) -> float:
    """F-score, or an upper bound below ``floor`` when precision cannot rescue it."""
    recall = petri.token_fitness(variants, net, initial, final)
    best_possible = petri.f_score(1.0, recall, beta)
    if best_possible < floor:
        return best_possible
    precision = petri.etc_precision(variants, net, initial, final)
    return petri.f_score(precision, recall, beta)


def _residual_rank(cluster: Cluster, groups: list[_Candidate], variant: Variant, beta: float):
    net, initial, final = cluster.model.to_petri_net()
    return (
        _f_score([variant], net, initial, final, beta),
        groups[cluster.id].score,
    )
