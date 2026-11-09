"""ProM's seeded token replay, used by ``cluster_traces(prom_compatible=True)``.

ProM picks among token options with ``new Random(Long.MAX_VALUE)``: one generator
per log, drawn across its cases in log order, and a new one for each single-trace
fitness. It draws even when there is one option, so the set order and the number of
draws decide later choices. This module follows that behaviour, including its binary
searches over sets that changed after they were inserted.

A variant that meets no real choice replays the same way from any generator state, so
it runs once per net and the generator jumps over its other cases.
"""

from __future__ import annotations

from bisect import bisect_left, insort
from collections.abc import Callable, Iterable, Sequence

import numpy as np

_MULTIPLIER = 0x5DEECE66D
_INCREMENT = 0xB
_MASK = (1 << 48) - 1
_LONG_MAX = (1 << 63) - 1
_INT_LIMIT = 1 << 31
# Above this many events, a float can round a fitness with missing tokens up to 1.
_FLOAT_EXACT_EVENTS = 1 << 24


class JavaRandom:
    """``java.util.Random.nextInt(bound)``, seeded as in ProM."""

    def __init__(self, seed: int = _LONG_MAX) -> None:
        self._state = (seed ^ _MULTIPLIER) & _MASK
        self.draws = 0
        self.branched = False

    def _next31(self) -> int:
        self._state = (self._state * _MULTIPLIER + _INCREMENT) & _MASK
        return self._state >> 17

    def next_int(self, bound: int) -> int:
        self.draws += 1
        value = self._next31()
        if bound == 1:
            return 0
        self.branched = True
        if bound & (bound - 1) == 0:
            return (bound * value) >> 31
        result = value % bound
        while value - result + bound - 1 >= _INT_LIMIT:
            value = self._next31()
            result = value % bound
        return result

    def skip(self, draws: int) -> None:
        """Advance over ``draws`` calls of ``next_int(1)`` in logarithmic time."""
        multiplier, increment, total_multiplier, total_increment = _MULTIPLIER, _INCREMENT, 1, 0
        self.draws += draws
        while draws:
            if draws & 1:
                total_multiplier = total_multiplier * multiplier & _MASK
                total_increment = (total_increment * multiplier + increment) & _MASK
            increment = (multiplier + 1) * increment & _MASK
            multiplier = multiplier * multiplier & _MASK
            draws >>= 1
        self._state = (total_multiplier * self._state + total_increment) & _MASK


def _position(sets: list[list[int]], key: list[int]) -> int:
    """Binary search by size, then content. Negative if absent, as in Java."""
    low, high = 0, len(sets) - 1
    size = len(key)
    while low <= high:
        middle = (low + high) >> 1
        value = sets[middle]
        if len(value) < size or (len(value) == size and value < key):
            low = middle + 1
        elif len(value) > size or value > key:
            high = middle - 1
        else:
            return middle
    return -(low + 1)


def _add_set(sets: list[list[int]], new: list[int]) -> None:
    position = _position(sets, new)
    if position < 0:
        sets.insert(-position - 1, new)


def _add_member(members: list[int], value: int) -> None:
    position = bisect_left(members, value)
    if position == len(members) or members[position] != value:
        members.insert(position, value)


def prom_input_sets(
    owner: int,
    members: Iterable[int],
    and_measure: Callable[[int, int, int], float],
    threshold: float,
) -> tuple[tuple[int, ...], ...]:
    """A task's input XOR sets in ProM's order, keeping sets that became duplicates."""
    sets: list[list[int]] = []
    ordered = sorted(members)

    def welcome(new: int, group: list[int]) -> bool:
        return all(and_measure(owner, old, new) <= threshold for old in group)

    for new in ordered:
        welcomed = False
        for group in sets:
            if welcome(new, group):
                welcomed = True
                insort(group, new)
        if not welcomed:
            _add_set(sets, [new])
    for new in ordered:
        for group in sets:
            if new not in group and welcome(new, group):
                insort(group, new)
    return tuple(tuple(group) for group in sets)


def _best_combination(
    best: tuple[tuple[int, ...], int],
    sets: list[list[int]],
    root: int,
    tasks: tuple[int, ...],
    missing: int,
    treated: set[int],
    random: JavaRandom,
) -> tuple[tuple[int, ...], int]:
    """ProM's search for the tasks to fire from. Mutates ``sets`` and ``treated``."""
    if best[0] and best[1] <= missing:
        return best

    if root >= 0:
        marked: list[list[int]] = []
        for group in sets:
            if root in group:
                _add_set(marked, group)
        without_tokens = {task for group in marked for task in group}
        for group in marked:
            position = _position(sets, group)
            if position >= 0:
                del sets[position]
        if root not in tasks:
            tasks = (*tasks, root)

    if not sets:
        return tasks, missing

    if root >= 0:
        left: list[list[int]] = []
        for group in sets:
            group[:] = [t for t in group if t not in without_tokens and t not in treated]
            if group:
                _add_set(left, group)
            else:
                missing += 1
        sets = left

    for group in sets:
        while group:
            task = group[random.next_int(len(group))]
            best = _best_combination(
                best, [list(g) for g in sets], task, tasks, missing, set(treated), random
            )
            treated.add(task)
            group.remove(task)
    return best


class SeededReplay:
    """Replays traces on one net the way ProM does."""

    def __init__(
        self,
        names: dict[str, int],
        inputs: Sequence[Sequence[tuple[int, ...]]],
        outputs: Sequence[Sequence[frozenset[int]]],
        related: Sequence[dict[int, tuple[int, ...]]],
    ) -> None:
        self._names = names
        self._inputs = inputs
        self._outputs = outputs
        self._related = related
        # Results of traces that met no real choice, with their number of draws.
        self._fixed: dict[tuple[str, ...], tuple[tuple[int, int, int], int]] = {}

    def _replay(self, trace: Iterable[str], random: JavaRandom) -> tuple[int, int, int]:
        tokens = [[0] * len(output_sets) for output_sets in self._outputs]
        start, end, total = 1, 0, 1
        parsed = missing = 0

        for name in trace:
            element = self._names.get(name)
            if element is None:
                missing += 1
                continue

            input_sets = self._inputs[element]
            if input_sets:
                related = self._related[element]
                available = {
                    task
                    for task, indices in related.items()
                    if all(tokens[task][k] > 0 for k in indices)
                }
                lacking = 0
                remaining: list[list[int]] = []
                for input_set in input_sets:
                    group = [task for task in input_set if task in available]
                    if group:
                        _add_set(remaining, group)
                    else:
                        lacking += 1
                if remaining:
                    chosen, more = _best_combination(
                        ((), 0), remaining, -1, (), 0, set(), random
                    )
                    lacking += more
                    for task in chosen:
                        for k in related[task]:
                            if tokens[task][k] > 0:
                                tokens[task][k] -= 1
                                total -= 1
            else:
                lacking = 0 if start > 0 else 1
                if start > 0:
                    start -= 1
                    total -= 1

            output_sets = self._outputs[element]
            if output_sets:
                total += len(output_sets)
                for k in range(len(output_sets)):
                    tokens[element][k] += 1
            else:
                total += 1
                end += 1

            if lacking:
                missing += lacking
            else:
                parsed += 1

        return parsed, missing, total - 1 if end > 0 else total

    def trace(self, trace: Sequence[str], random: JavaRandom | None = None):
        """Replay one trace, with a new generator unless one is passed."""
        key = tuple(trace)
        random = random or JavaRandom()
        fixed = self._fixed.get(key)
        if fixed is not None:
            random.skip(fixed[1])
            return fixed[0]
        random.branched = False
        before = random.draws
        result = self._replay(key, random)
        if not random.branched:
            self._fixed[key] = (result, random.draws - before)
        return result

    def fitness(self, variants: Sequence, stop_on_missing: bool = False) -> float | None:
        """ICS fitness over the log in the given order, or None if stopped early."""
        random = JavaRandom()
        cases = events = parsed = missing = extra = cases_missing = cases_extra = 0

        def count(result: tuple[int, int, int], times: int) -> None:
            nonlocal parsed, missing, extra, cases_missing, cases_extra
            parsed += times * result[0]
            if result[1]:
                cases_missing += times
                missing += times * result[1]
            if result[2]:
                cases_extra += times
                extra += times * result[2]

        for variant in variants:
            frequency = variant.frequency
            cases += frequency
            events += frequency * len(variant.activities)
            result = self.trace(variant.activities, random)
            if stop_on_missing and result[1]:
                return None
            fixed = self._fixed.get(variant.activities)
            if fixed is not None:
                random.skip(fixed[1] * (frequency - 1))
                count(result, frequency)
                continue
            count(result, 1)
            for _ in range(frequency - 1):
                result = self.trace(variant.activities, random)
                if stop_on_missing and result[1]:
                    return None
                count(result, 1)

        if not events:
            return 0.0
        punishment = missing / (cases - cases_missing + 1) + extra / (cases - cases_extra + 1)
        return (parsed - punishment) / events

    def fits(self, variants: Sequence, target: float) -> bool:
        """ProM's test: the fitness cast to a ``float`` reaches the target."""
        events = sum(v.frequency * len(v.activities) for v in variants)
        fitness = self.fitness(variants, target >= 1.0 and events < _FLOAT_EXACT_EVENTS)
        return fitness is not None and bool(np.float32(fitness) >= np.float32(target))
