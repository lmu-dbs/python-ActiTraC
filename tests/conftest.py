from __future__ import annotations

import pytest

from actitrac import Variant


def make_variants(counts: dict[str, int]) -> list[Variant]:
    """Build variants from strings, one activity per character, in the given order."""
    return [
        Variant(i, tuple(trace), frequency) for i, (trace, frequency) in enumerate(counts.items())
    ]


class FittingModel:
    """A model that accepts exactly the traces starting with its members' first activities."""

    def __init__(self, starts: set[str]):
        self.starts = starts

    def trace_fitness(self, trace) -> float:
        return 1.0 if trace[0] in self.starts else 0.0

    def fitness(self, variants) -> float:
        # A model covering more than one start activity is a poor model.
        if len(self.starts) > 1:
            return 0.5
        return min(self.trace_fitness(v.activities) for v in variants)


class FittingMiner:
    """Records how often it was called, so tests can check what was retrained."""

    def __init__(self):
        self.calls: list[list[tuple[str, ...]]] = []

    def __call__(self, variants) -> FittingModel:
        self.calls.append([v.activities for v in variants])
        return FittingModel({v.activities[0] for v in variants})


@pytest.fixture
def fitting_miner() -> FittingMiner:
    return FittingMiner()
