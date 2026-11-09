"""Bridge to pm4py: Petri nets, pm4py miners, and conformance measures.

pm4py is imported inside functions because it is optional, AGPL-3.0 licensed and
prints a banner on import.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .heuristics import HeuristicsNet
from .log import Variant

_QUIET = {"show_progress_bar": False}
_MOVE_COST = 10000


def _require_pm4py():
    try:
        import pm4py
    except ImportError as error:
        raise ImportError(
            "this feature needs pm4py: pip install 'actitrac[pm4py]'"
        ) from error
    return pm4py


def event_log(variants: Sequence[Variant], weighted: bool = True):
    """Build a pm4py EventLog, repeating traces per frequency if ``weighted``."""
    _require_pm4py()
    from pm4py.objects.log.obj import Event, EventLog, Trace

    traces = []
    for variant in variants:
        trace = Trace(Event({"concept:name": name}) for name in variant.activities)
        traces.extend([trace] * (variant.frequency if weighted else 1))
    return EventLog(traces)


def heuristics_to_petri_net(net: HeuristicsNet):
    """Convert a causal net to a workflow-style Petri net.

    Each output and input XOR set gets a place, and silent transitions connect
    them wherever the net has a dependency. Unlike ProM's converter this keeps
    every dependency and yields a final marking.
    """
    _require_pm4py()
    from pm4py.objects.petri_net.obj import Marking, PetriNet
    from pm4py.objects.petri_net.utils.petri_utils import add_arc_from_to

    petri = PetriNet("heuristics_net")

    def place(name: str):
        new = PetriNet.Place(name)
        petri.places.add(new)
        return new

    def transition(name: str, label: str | None = None):
        new = PetriNet.Transition(name, label)
        petri.transitions.add(new)
        return new

    source, sink = place("source"), place("sink")
    in_places, out_places = {}, {}
    for task, label in enumerate(net.activities):
        fire = transition(f"t{task}", label)
        if net.inputs[task]:
            for k in range(len(net.inputs[task])):
                in_places[task, k] = place(f"in_{task}_{k}")
                add_arc_from_to(in_places[task, k], fire, petri)
        else:
            add_arc_from_to(source, fire, petri)
        if net.outputs[task]:
            for k in range(len(net.outputs[task])):
                out_places[task, k] = place(f"out_{task}_{k}")
                add_arc_from_to(fire, out_places[task, k], petri)
        else:
            add_arc_from_to(fire, sink, petri)

    for task, output_sets in enumerate(net.outputs):
        for k, output_set in enumerate(output_sets):
            for element in sorted(output_set):
                for m, input_set in enumerate(net.inputs[element]):
                    if task in input_set:
                        silent = transition(f"tau_{task}_{k}_{element}_{m}")
                        add_arc_from_to(out_places[task, k], silent, petri)
                        add_arc_from_to(silent, in_places[element, m], petri)

    return petri, Marking({source: 1}), Marking({sink: 1})


def is_easy_sound(net, initial, final) -> bool:
    """Tell whether pm4py can compute alignments on this net."""
    from pm4py.objects.petri_net.utils.check_soundness import (
        check_easy_soundness_net_in_fin_marking,
    )

    return check_easy_soundness_net_in_fin_marking(net, initial, final)


def _alignments(variants: Sequence[Variant], net, initial, final):
    from pm4py.algo.conformance.alignments.petri_net import algorithm as alignments

    return alignments.apply(event_log(variants, weighted=False), net, initial, final, parameters=_QUIET)


def _token_replay(variants: Sequence[Variant], net, initial, final):
    from pm4py.algo.conformance.tokenreplay import algorithm as token_replay

    return token_replay.apply(event_log(variants, weighted=False), net, initial, final, parameters=_QUIET)


def alignment_fitness(variants: Sequence[Variant], net, initial, final) -> float:
    """Frequency-weighted alignment fitness, ignoring pm4py's silent-move epsilon.

    pm4py's ``log_fitness`` keeps that tiny cost, so a model that fits perfectly
    can score just below 1 and fail a target of 1.
    """
    cost = worst = 0
    for variant, result in zip(variants, _alignments(variants, net, initial, final)):
        if result is None:
            continue
        cost += variant.frequency * (result["cost"] // _MOVE_COST) * _MOVE_COST
        worst += variant.frequency * result["bwc"]
    return 1.0 - cost / worst if worst > 0 else 0.0


def token_fitness(variants: Sequence[Variant], net, initial, final) -> float:
    """Frequency-weighted token-based replay fitness."""
    missing = consumed = remaining = produced = 0
    for variant, result in zip(variants, _token_replay(variants, net, initial, final)):
        missing += variant.frequency * result["missing_tokens"]
        consumed += variant.frequency * result["consumed_tokens"]
        remaining += variant.frequency * result["remaining_tokens"]
        produced += variant.frequency * result["produced_tokens"]
    if not consumed or not produced:
        return 0.0
    return 0.5 * (1 - missing / consumed) + 0.5 * (1 - remaining / produced)


def etc_precision(variants: Sequence[Variant], net, initial, final) -> float:
    """ETConformance precision, the measure ActiTraC-MO uses in ProM."""
    from pm4py.algo.evaluation.precision import algorithm as precision

    return precision.apply(
        event_log(variants),
        net,
        initial,
        final,
        variant=precision.Variants.ETCONFORMANCE_TOKEN,
        parameters=_QUIET,
    )


def alignment_precision(variants: Sequence[Variant], net, initial, final) -> float:
    from pm4py.algo.evaluation.precision import algorithm as precision

    return precision.apply(
        event_log(variants),
        net,
        initial,
        final,
        variant=precision.Variants.ALIGN_ETCONFORMANCE,
        parameters=_QUIET,
    )


def f_score(precision: float, recall: float, beta: float = 1.0) -> float:
    """Weighted F-score; ``beta`` above 1 favours recall."""
    denominator = beta**2 * precision + recall
    return (1 + beta**2) * precision * recall / denominator if denominator > 0 else 0.0


def pt_connectivity(net) -> float:
    """Place/transition connectivity degree: ``(|A|/|P| + |A|/|T|) / 2``."""
    arcs = len(net.arcs)
    return (arcs / len(net.places) + arcs / len(net.transitions)) / 2


@dataclass
class PetriNetModel:
    """A discovered Petri net, exposing the same fitness methods as a heuristics net."""

    net: object
    initial: object
    final: object
    metric: str = "alignments"

    def fitness(self, variants: Sequence[Variant]) -> float:
        measure = alignment_fitness if self.metric == "alignments" else token_fitness
        return measure(variants, self.net, self.initial, self.final)

    def trace_fitness(self, trace: Sequence[str]) -> float:
        variant = Variant(0, tuple(trace), 1)
        return self.fitness([variant])

    def to_petri_net(self):
        return self.net, self.initial, self.final


@dataclass(frozen=True)
class PetriNetMiner:
    """Wrap a pm4py discovery function such as ``pm4py.discover_petri_net_inductive``."""

    discover: Callable
    metric: str = "alignments"

    def __post_init__(self) -> None:
        if self.metric not in ("alignments", "token_replay"):
            raise ValueError("fitness_metric must be 'alignments' or 'token_replay'")

    def __call__(self, variants: Sequence[Variant]) -> PetriNetModel:
        net, initial, final = self.discover(event_log(variants))
        return PetriNetModel(net, initial, final, self.metric)
