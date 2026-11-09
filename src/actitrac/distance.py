"""Distances between variants: maximal repeat alphabets (MRA) and edit distance."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence

import numpy as np

from .log import Variant

Trace = tuple[str, ...]

MAX_ALPHABET_SIZE = 10


def maximal_repeats(traces: Sequence[Trace]) -> set[Trace]:
    """Return substrings that occur twice and are left- and right-diverse.

    A trace boundary counts as a context that is unique to that occurrence, as
    the per-trace delimiters do in Bose's suffix-tree implementation.
    """
    found: set[Trace] = set()
    groups: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for t, trace in enumerate(traces):
        for position, symbol in enumerate(trace):
            groups[symbol].append((t, position))

    stack = [((symbol,), occurrences) for symbol, occurrences in groups.items()]
    while stack:
        pattern, occurrences = stack.pop()
        if len(occurrences) < 2:
            continue

        left = set()
        following: dict[str, list[tuple[int, int]]] = defaultdict(list)
        right = set()
        for t, position in occurrences:
            before = position - 1
            left.add(traces[t][before] if before >= 0 else ("start", t, position))
            after = position + len(pattern)
            if after < len(traces[t]):
                right.add(traces[t][after])
                following[traces[t][after]].append((t, position))
            else:
                right.add(("end", t, position))

        if len(left) > 1 and len(right) > 1:
            found.add(pattern)
        stack.extend((pattern + (symbol,), occ) for symbol, occ in following.items())
    return found


def base_features(repeats: set[Trace]) -> set[Trace]:
    """Reduce repeats to those using each activity of their alphabet once.

    Longer repeats are replaced by the repeats found inside them. For example
    ``abab`` has alphabet ``{a, b}`` and reduces to ``ab``.
    """
    base: set[Trace] = set()
    by_alphabet: dict[frozenset[str], set[Trace]] = defaultdict(set)
    for repeat in repeats:
        by_alphabet[frozenset(repeat)].add(repeat)

    for alphabet, members in by_alphabet.items():
        longer = set()
        for repeat in members:
            if len(repeat) == len(alphabet):
                base.add(repeat)
            else:
                longer.add(repeat)
        if longer:
            inner = maximal_repeats(sorted(longer)) - longer
            if inner:
                base |= base_features(inner)
    return base


def mra_features(traces: Sequence[Trace]) -> np.ndarray:
    """Count, per trace, occurrences of each maximal repeat alphabet's features."""
    classes: dict[frozenset[str], set[Trace]] = defaultdict(set)
    for feature in base_features(maximal_repeats(traces)):
        alphabet = frozenset(feature)
        if len(alphabet) <= MAX_ALPHABET_SIZE:
            classes[alphabet].add(feature)

    ordered = sorted(classes.items(), key=lambda item: sorted(item[0]))
    features = np.zeros((len(traces), len(ordered)))
    for column, (_, members) in enumerate(ordered):
        for row, trace in enumerate(traces):
            features[row, column] = sum(_count(trace, feature) for feature in members)
    return features


def _count(trace: Trace, feature: Trace) -> int:
    width = len(feature)
    return sum(
        trace[i : i + width] == feature for i in range(len(trace) - width + 1)
    )


def osa_distance(a: Sequence, b: Sequence) -> int:
    """Optimal string alignment distance between two activity sequences."""
    previous_previous: list[int] = []
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            cost = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (x != y))
            if i > 1 and j > 1 and x == b[j - 2] and a[i - 2] == y:
                cost = min(cost, previous_previous[j - 2] + 1)
            current.append(cost)
        previous_previous, previous = previous, current
    return previous[-1]


DistanceMetric = str | Callable[[Sequence[str], Sequence[str]], float]


def distance_rows(
    metric: DistanceMetric, variants: Sequence[Variant]
) -> Callable[[int], np.ndarray]:
    """Return a function mapping a variant position to distances to all variants."""
    traces = [v.activities for v in variants]
    if metric == "mra":
        features = mra_features(traces)

        def row(position: int) -> np.ndarray:
            return np.linalg.norm(features - features[position], axis=1)

        return row

    if metric == "osa":
        metric = osa_distance
    if not callable(metric):
        raise ValueError("distance_metric must be 'mra', 'osa' or a callable")

    def row(position: int) -> np.ndarray:
        return np.array([metric(traces[position], other) for other in traces], dtype=float)

    return row
