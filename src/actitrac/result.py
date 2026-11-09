"""The result of a clustering run."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd

from .log import Variant, VariantLog, variant_log_dict


@dataclass
class Cluster:
    """A cluster and its model.

    ``internal`` variants trained the model. ``external`` variants joined later,
    through look-ahead or residual assignment, without retraining it.
    """

    id: int
    internal: list[Variant]
    model: object
    external: list[Variant] = field(default_factory=list)
    is_residual: bool = False

    @property
    def variants(self) -> list[Variant]:
        return self.internal + self.external

    @property
    def n_cases(self) -> int:
        return sum(v.frequency for v in self.variants)

    @property
    def case_ids(self) -> list:
        return [case for v in self.variants for case in v.case_ids]


@dataclass
class TraceClustering:
    """Clusters plus helpers mirroring actitraceR's accessors. Ids start at 0."""

    clusters: list[Cluster]
    log: VariantLog
    miner: Callable

    def __len__(self) -> int:
        return len(self.clusters)

    def __iter__(self):
        return iter(self.clusters)

    def __getitem__(self, cluster_id: int) -> Cluster:
        return self.clusters[cluster_id]

    def __str__(self) -> str:
        sizes = ", ".join(str(c.n_cases) for c in self.clusters)
        return f"Trace clustering with {len(self)} clusters of sizes {sizes}"

    @property
    def labels(self) -> dict:
        """Map each case id to its cluster id."""
        return {case: c.id for c in self.clusters for case in c.case_ids}

    def variant_logs(self) -> list[dict[tuple[str, ...], int]]:
        """Return one ``{activities: count}`` dict per cluster."""
        return [variant_log_dict(c.variants) for c in self.clusters]

    def _source(self) -> pd.DataFrame:
        if self.log.source is None:
            raise ValueError("no event log available: the input was a variant dict")
        return self.log.source

    def augment(self) -> pd.DataFrame:
        """Return clustered cases of the original log with a ``cluster`` column."""
        source = self._source()
        clusters = source[self.log.case_key].map(self.labels)
        return source[clusters.notna()].assign(cluster=clusters.dropna().astype(int))

    def logs(self) -> list[pd.DataFrame]:
        """Return the original log filtered to each cluster."""
        source = self._source()
        return [source[source[self.log.case_key].isin(c.case_ids)] for c in self.clusters]

    def select_cluster(self, cluster_id: int) -> pd.DataFrame:
        if not 0 <= cluster_id < len(self.clusters):
            raise IndexError(f"there are only {len(self.clusters)} clusters")
        return self.logs()[cluster_id]

    def group_by_cluster(self):
        return self.augment().groupby("cluster")

    def metrics(self, conformance: bool = False, alignments: bool = False) -> pd.DataFrame:
        """Evaluate each cluster, the case-weighted average, and the unclustered log.

        Every row uses a model mined on all of that row's variants, including
        those that joined without retraining, as actitraceR and the entroclus
        evaluation do. ``conformance`` adds pm4py token-based fitness, ETC
        precision, F-score and connectivity; ``alignments`` adds alignment
        fitness and precision, which can be slow and are NaN for an unsound net.
        """
        rows = [
            {"cluster": c.id, **self._evaluate(c.variants, conformance, alignments)}
            for c in self.clusters
        ]
        frame = pd.DataFrame(rows)
        measures = [m for m in frame.columns if m not in ("cluster", "cases", "variants")]
        weights = frame["cases"] / frame["cases"].sum()
        average = {m: float((frame[m] * weights).sum(skipna=False)) for m in measures}
        average.update(
            cluster="weighted_average",
            cases=int(frame["cases"].sum()),
            variants=int(frame["variants"].sum()),
        )
        full = {
            "cluster": "full_log",
            **self._evaluate(list(self.log.variants), conformance, alignments),
        }
        return pd.concat([frame, pd.DataFrame([average, full])], ignore_index=True)

    def _evaluate(self, variants: list[Variant], conformance: bool, alignments: bool) -> dict:
        from .heuristics import HeuristicsNet

        model = self.miner(variants)
        row = {
            "cases": sum(v.frequency for v in variants),
            "variants": len(variants),
            "fitness": model.fitness(variants),
        }
        if isinstance(model, HeuristicsNet):
            row["ics_fitness"] = row.pop("fitness")
        if conformance or alignments:
            from . import petri

            net, initial, final = model.to_petri_net()
            if conformance:
                recall = petri.token_fitness(variants, net, initial, final)
                precision = petri.etc_precision(variants, net, initial, final)
                row.update(
                    replay_fitness=recall,
                    replay_precision=precision,
                    f_score=petri.f_score(precision, recall),
                    pt_connectivity=petri.pt_connectivity(net),
                )
            if alignments:
                # Heuristics nets can be unsound, and pm4py cannot align on those.
                sound = petri.is_easy_sound(net, initial, final)
                row.update(
                    align_fitness=(
                        petri.alignment_fitness(variants, net, initial, final)
                        if sound
                        else float("nan")
                    ),
                    align_precision=(
                        petri.alignment_precision(variants, net, initial, final)
                        if sound
                        else float("nan")
                    ),
                )
        return row
