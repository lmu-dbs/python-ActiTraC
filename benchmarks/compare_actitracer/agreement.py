"""Adjusted Rand index between two label files with the columns case, cluster.

Usage: python agreement.py A.csv B.csv
"""
import sys

import pandas as pd


def load(path):
    return pd.read_csv(path, keep_default_na=False, dtype={"case": str}).set_index("case")["cluster"]


def adjusted_rand_index(a, b):
    table = pd.crosstab(a, b.reindex(a.index)).values
    pairs = lambda x: x * (x - 1) / 2
    both, left, right = pairs(table).sum(), pairs(table.sum(1)).sum(), pairs(table.sum(0)).sum()
    expected = left * right / pairs(table.sum())
    mean = (left + right) / 2
    return (both - expected) / (mean - expected) if mean != expected else 1.0


if __name__ == "__main__":
    print(f"{adjusted_rand_index(load(sys.argv[1]), load(sys.argv[2])):.3f}")
