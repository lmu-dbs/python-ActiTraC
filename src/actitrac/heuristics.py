"""Heuristics Miner and improved continuous semantics (ICS) fitness.

ActiTraC grows clusters by mining a heuristics net and replaying the log on it,
so this behaviour defines the clustering. It follows ProM's
``HeuristicsMinerNoUI``, ``MarkingHeuristicsNet`` and
``ImprovedContinuousSemantics``; docs/fidelity.md lists where it differs.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from typing import NamedTuple

from .log import Variant
from .prom_replay import SeededReplay, prom_input_sets


@dataclass(frozen=True)
class HeuristicsSettings:
    """Heuristics Miner thresholds, with ProM's defaults."""

    dependency_threshold: float = 0.9
    relative_to_best: float = 0.05
    l1l_threshold: float = 0.9
    l2l_threshold: float = 0.9
    and_threshold: float = 0.1
    positive_observations: int = 1
    dependency_divisor: int = 1
    all_tasks_connected: bool = True
    adapt_to_log_size: bool = True
    prom_replay: bool = False

    def for_log_size(self, cases: int) -> HeuristicsSettings:
        """Lower thresholds that a log of ``cases`` cases could never reach."""
        if not self.adapt_to_log_size:
            return self
        reachable = cases / (cases + 1)
        lowered = reachable - 0.01
        return replace(
            self,
            dependency_threshold=(
                lowered if reachable < self.dependency_threshold else self.dependency_threshold
            ),
            l1l_threshold=lowered if reachable < self.l1l_threshold else self.l1l_threshold,
            l2l_threshold=lowered if reachable < self.l2l_threshold else self.l2l_threshold,
        )


class Replay(NamedTuple):
    parsed: int
    missing: int
    extra: int


@dataclass(frozen=True)
class HeuristicsNet:
    """A causal net. Each entry of ``inputs``/``outputs`` is an AND of XOR sets."""

    activities: tuple[str, ...]
    inputs: tuple[tuple[frozenset[int], ...], ...]
    outputs: tuple[tuple[frozenset[int], ...], ...]
    # Input sets in ProM's order. When given, replay follows ProM's seeded token choice.
    prom_inputs: tuple[tuple[tuple[int, ...], ...], ...] | None = field(default=None, compare=False)
    _index: dict[str, int] = field(init=False, repr=False, compare=False)
    _related: tuple[dict[int, tuple[int, ...]], ...] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "_index", {a: i for i, a in enumerate(self.activities)})
        # _related[element][task]: output sets of task that contain element.
        related: list[dict[int, list[int]]] = [{} for _ in self.activities]
        for task, output_sets in enumerate(self.outputs):
            for k, output_set in enumerate(output_sets):
                for element in output_set:
                    related[element].setdefault(task, []).append(k)
        object.__setattr__(
            self,
            "_related",
            tuple({t: tuple(ks) for t, ks in r.items()} for r in related),
        )
        seeded = (
            SeededReplay(self._index, self.prom_inputs, self.outputs, self._related)
            if self.prom_inputs is not None
            else None
        )
        object.__setattr__(self, "_seeded", seeded)

    def replay(self, trace: Iterable[str]) -> Replay:
        """Replay a trace with continuous semantics, adding tokens where missing."""
        if self._seeded is not None:
            return Replay(*self._seeded.trace(tuple(trace)))
        tokens = [[0] * len(output_sets) for output_sets in self.outputs]
        start, end, total = 1, 0, 1
        parsed = missing = 0

        for name in trace:
            element = self._index.get(name)
            if element is None:
                missing += 1
                continue

            input_sets = self.inputs[element]
            if input_sets:
                related = self._related[element]
                available = {
                    task
                    for task, indices in related.items()
                    if all(tokens[task][k] > 0 for k in indices)
                }
                remaining = [s & available for s in input_sets]
                lacking = sum(1 for s in remaining if not s)
                for task in _smallest_cover([s for s in remaining if s]):
                    for k in related[task]:
                        if tokens[task][k] > 0:
                            tokens[task][k] -= 1
                            total -= 1
            else:
                lacking = 0 if start > 0 else 1
                if start > 0:
                    start -= 1
                    total -= 1

            output_sets = self.outputs[element]
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

        return Replay(parsed, missing, total - 1 if end > 0 else total)

    def fitness(self, variants: Sequence[Variant]) -> float:
        """Improved continuous semantics fitness of a log on this net."""
        if self._seeded is not None:
            return self._seeded.fitness(variants)
        cases = events = parsed = missing = extra = cases_missing = cases_extra = 0
        for variant in variants:
            result = self.replay(variant.activities)
            frequency = variant.frequency
            cases += frequency
            events += frequency * len(variant.activities)
            parsed += frequency * result.parsed
            if result.missing:
                cases_missing += frequency
                missing += frequency * result.missing
            if result.extra:
                cases_extra += frequency
                extra += frequency * result.extra
        if not events:
            return 0.0
        punishment = missing / (cases - cases_missing + 1) + extra / (cases - cases_extra + 1)
        return (parsed - punishment) / events

    def fits(self, variants: Sequence[Variant], target: float) -> bool:
        """Whether a log reaches the target, compared as ProM does if replay is seeded."""
        if self._seeded is not None:
            return self._seeded.fits(variants, target)
        return self.fitness(variants) >= target

    def trace_fitness(self, trace: Sequence[str]) -> float:
        """Share of a trace that parses cleanly, used by look-ahead and residuals."""
        result = self.replay(trace)
        return (result.parsed - result.extra - result.missing) / len(trace)

    def to_petri_net(self):
        from .petri import heuristics_to_petri_net

        return heuristics_to_petri_net(self)


def _smallest_cover(sets: list[frozenset[int]]) -> tuple[int, ...]:
    """Pick the fewest tasks hitting every set, lowest indices first on ties."""
    if not sets:
        return ()
    if len(sets) == 1:
        return (min(sets[0]),)

    best: tuple[int, ...] | None = None

    def search(chosen: tuple[int, ...]) -> None:
        nonlocal best
        if best is not None and len(chosen) >= len(best):
            return
        uncovered = next((s for s in sets if not s.intersection(chosen)), None)
        if uncovered is None:
            best = chosen
            return
        for task in sorted(uncovered):
            search(chosen + (task,))

    search(())
    return best


def mine(
    variants: Sequence[Variant], settings: HeuristicsSettings | None = None
) -> HeuristicsNet:
    """Mine a heuristics net from weighted variants."""
    settings = (settings or HeuristicsSettings()).for_log_size(
        sum(v.frequency for v in variants)
    )
    activities = tuple(sorted({a for v in variants for a in v.activities}))
    index = {a: i for i, a in enumerate(activities)}
    size = len(activities)
    labels = range(size)

    direct = [[0] * size for _ in labels]
    two_step = [[0] * size for _ in labels]
    self_loops = [0] * size
    starts = [0] * size
    ends = [0] * size
    for variant in variants:
        frequency = variant.frequency
        trace = [index[a] for a in variant.activities]
        starts[trace[0]] += frequency
        ends[trace[-1]] += frequency
        for position, event in enumerate(trace):
            if position >= 1:
                previous = trace[position - 1]
                direct[previous][event] += frequency
                if previous == event:
                    self_loops[event] += frequency
            if position >= 2 and trace[position - 2] == event:
                two_step[event][trace[position - 1]] += frequency

    observed = settings.positive_observations
    divisor = settings.dependency_divisor

    def dependency(i: int, j: int) -> float:
        return (direct[i][j] - direct[j][i]) / (direct[i][j] + direct[j][i] + divisor)

    has_self_loop = [False] * size
    inputs: list[set[int]] = [set() for _ in labels]
    outputs: list[set[int]] = [set() for _ in labels]
    accepted = [[0.0] * size for _ in labels]

    def accept(i: int, j: int, measure: float) -> None:
        accepted[i][j] = measure
        inputs[j].add(i)
        outputs[i].add(j)

    for i in labels:
        if self_loops[i]:
            measure = self_loops[i] / (self_loops[i] + divisor)
            if measure >= settings.l1l_threshold and direct[i][i] >= observed:
                has_self_loop[i] = True
                accept(i, i, measure)

    best_start = best_end = 0
    for i in range(1, size):
        if starts[i] > starts[best_start]:
            best_start = i
        if ends[i] > ends[best_end]:
            best_end = i

    def two_loop(i: int, j: int) -> float:
        if (has_self_loop[i] and two_step[i][j] >= observed) or (
            has_self_loop[j] and two_step[j][i] >= observed
        ):
            return 0.0
        count = two_step[i][j] + two_step[j][i]
        return count / (count + divisor)

    partner = [-1] * size

    def accept_two_loop(i: int, j: int, measure: float) -> None:
        partner[i], partner[j] = j, i
        accept(i, j, measure)
        accept(j, i, measure)

    best_input = [-10.0] * size
    best_output = [-10.0] * size
    best_input_event = [-1] * size
    best_output_event = [-1] * size
    for i in labels:
        for j in labels:
            if i > j:
                measure = two_loop(i, j)
                if (
                    measure >= settings.l2l_threshold
                    and two_step[i][j] + two_step[j][i] >= observed
                ):
                    accept_two_loop(i, j, measure)
            if i != j:
                measure = dependency(i, j)
                if measure > best_output[i]:
                    best_output[i], best_output_event[i] = measure, j
                if measure > best_input[j]:
                    best_input[j], best_input_event[j] = measure, i

    for i in labels:
        if i not in (best_start, best_end):
            for j in labels:
                measure = two_loop(i, j)
                if measure > best_input[i]:
                    accept_two_loop(i, j, measure)

    if settings.all_tasks_connected:
        for i in labels:
            j = partner[i]
            if i != best_start and best_input_event[i] >= 0:
                if not (j > -1 and best_input[j] > best_input[i]):
                    accept(best_input_event[i], i, best_input[i])
            if i != best_end and best_output_event[i] >= 0:
                if not (j > -1 and best_output[j] > best_output[i]):
                    accept(i, best_output_event[i], best_output[i])

    for i in labels:
        for j in labels:
            if accepted[i][j] <= 0.0001:
                measure = dependency(i, j)
                if (
                    best_output[i] - measure <= settings.relative_to_best
                    and direct[i][j] >= observed
                    and measure >= settings.dependency_threshold
                ):
                    accept(i, j, measure)

    def and_in(owner: int, old: int, new: int) -> float:
        if owner == new or direct[old][new] < observed or direct[new][old] < observed:
            return 0.0
        return (direct[old][new] + direct[new][old]) / (
            direct[new][owner] + direct[old][owner] + 1
        )

    def and_out(owner: int, old: int, new: int) -> float:
        if owner == new or direct[old][new] < observed or direct[new][old] < observed:
            return 0.0
        return (direct[old][new] + direct[new][old]) / (
            direct[owner][new] + direct[owner][old] + 1
        )

    threshold = settings.and_threshold
    return HeuristicsNet(
        activities,
        tuple(_xor_sets(i, inputs[i], and_in, threshold) for i in labels),
        tuple(_xor_sets(i, outputs[i], and_out, threshold) for i in labels),
        tuple(prom_input_sets(i, inputs[i], and_in, threshold) for i in labels)
        if settings.prom_replay
        else None,
    )


def _xor_sets(owner, members, and_measure, threshold) -> tuple[frozenset[int], ...]:
    """Split a task's connections into XOR sets; separate sets run in parallel."""
    groups: list[set[int]] = []
    ordered = sorted(members)
    for new in ordered:
        welcomed = False
        for group in groups:
            if all(
                and_measure(owner, old, new) <= threshold for old in group if old != new
            ):
                welcomed = True
                group.add(new)
        if not welcomed:
            groups.append({new})
    # A second pass turns [AB] [C] into [AB] [BC] for (A xor B) and (B xor C).
    for new in ordered:
        for group in groups:
            if all(
                and_measure(owner, old, new) <= threshold for old in group if old != new
            ):
                group.add(new)
    return tuple(dict.fromkeys(frozenset(group) for group in groups))


@dataclass(frozen=True)
class HeuristicsMiner:
    """Discovers a :class:`HeuristicsNet`, the miner used by ActiTraC in ProM."""

    settings: HeuristicsSettings = HeuristicsSettings()

    def __call__(self, variants: Sequence[Variant]) -> HeuristicsNet:
        return mine(variants, self.settings)
