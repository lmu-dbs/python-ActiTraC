"""Reduce an event log to its distinct process instances (dpi)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import pandas as pd

CASE_KEY = "case:concept:name"
ACTIVITY_KEY = "concept:name"
TIMESTAMP_KEY = "time:timestamp"
LIFECYCLE_KEY = "lifecycle:transition"


@dataclass(frozen=True)
class Variant:
    """A distinct process instance: one activity sequence and its cases."""

    id: int
    activities: tuple[str, ...]
    frequency: int
    case_ids: tuple = ()


@dataclass(frozen=True)
class VariantLog:
    """Variants sorted by descending frequency, plus the log they came from."""

    variants: tuple[Variant, ...]
    source: pd.DataFrame | None = None
    case_key: str = CASE_KEY

    @property
    def n_cases(self) -> int:
        return sum(v.frequency for v in self.variants)


def extract_variants(
    log,
    case_key: str = CASE_KEY,
    activity_key: str = ACTIVITY_KEY,
    timestamp_key: str = TIMESTAMP_KEY,
    lifecycle_key: str = LIFECYCLE_KEY,
    lifecycle: str | None = "classifier",
) -> VariantLog:
    """Build a :class:`VariantLog` from a DataFrame, pm4py log or variant dict.

    ``lifecycle`` applies only if the lifecycle column exists: ``"classifier"``,
    the default, appends the transition to the activity name (ProM),
    ``"complete"`` keeps complete events only (actitraceR), and ``None`` ignores
    the column.

    Events are sorted by timestamp within each case. Ties in frequency keep the
    order in which cases first appear in the log, as ProM's ``GroupedXLog`` does.
    """
    if isinstance(log, VariantLog):
        return log
    if isinstance(log, Mapping):
        return _from_variant_dict(log)
    if not isinstance(log, pd.DataFrame):
        log = _pm4py_to_frame(log)
    return _from_frame(log, case_key, activity_key, timestamp_key, lifecycle_key, lifecycle)


def _from_variant_dict(counts: Mapping) -> VariantLog:
    for activities, frequency in counts.items():
        if not activities:
            raise ValueError("variant logs cannot contain empty traces")
        if frequency < 1:
            raise ValueError(f"variant {activities!r} has frequency {frequency}")
    ordered = sorted(counts.items(), key=lambda item: -item[1])
    return VariantLog(
        tuple(Variant(i, tuple(a), int(f)) for i, (a, f) in enumerate(ordered))
    )


def _pm4py_to_frame(log) -> pd.DataFrame:
    try:
        import pm4py
    except ImportError as error:
        raise TypeError(
            "expected a DataFrame or {variant: count} dict; "
            "install pm4py to pass an EventLog"
        ) from error
    return pm4py.convert_to_dataframe(log)


def _from_frame(
    frame: pd.DataFrame,
    case_key: str,
    activity_key: str,
    timestamp_key: str,
    lifecycle_key: str,
    lifecycle: str | None,
) -> VariantLog:
    missing = {case_key, activity_key} - set(frame.columns)
    if missing:
        raise ValueError(f"log is missing columns: {sorted(missing)}")
    if lifecycle not in ("complete", "classifier", None):
        raise ValueError("lifecycle must be 'complete', 'classifier' or None")

    events = frame
    if lifecycle_key in frame.columns and lifecycle == "complete":
        events = frame[frame[lifecycle_key].astype(str).str.lower() == "complete"]
    # Cases keep their log order, which decides frequency ties below.
    traces: dict[object, list[str]] = {case: [] for case in events[case_key].tolist()}
    if timestamp_key in events.columns:
        events = events.sort_values(timestamp_key, kind="stable")

    names = events[activity_key].astype(str)
    if lifecycle_key in frame.columns and lifecycle == "classifier":
        names = names + "+" + events[lifecycle_key].astype(str)

    for case, name in zip(events[case_key].tolist(), names.tolist()):
        traces[case].append(name)

    groups: dict[tuple[str, ...], list] = {}
    for case, trace in traces.items():
        groups.setdefault(tuple(trace), []).append(case)

    ordered = sorted(groups.items(), key=lambda item: -len(item[1]))
    variants = tuple(
        Variant(i, activities, len(cases), tuple(cases))
        for i, (activities, cases) in enumerate(ordered)
    )
    return VariantLog(variants, frame, case_key)


def variant_log_dict(variants) -> dict[tuple[str, ...], int]:
    """Return variants as the ``{activities: count}`` dict used by entroclus."""
    return {v.activities: v.frequency for v in variants}
