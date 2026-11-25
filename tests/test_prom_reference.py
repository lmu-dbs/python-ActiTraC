"""Compare against the published results of ActiTraC-ProM (Peeperkorn et al. / EntropicClustering).

The reference sizes come from the published results of
https://github.com/jaripeeperkorn/EntropicClustering.

- Set ``ACTITRAC_HELPDESK_CSV`` to ``finale.csv`` from
  https://data.4tu.nl/articles/dataset/Dataset_belonging_to_the_help_desk_log_of_an_Italian_Company/12675977
  to run the Helpdesk reference tests.
- Set ``ACTITRAC_DATA_DIR`` to a directory containing all eight 4TU benchmark logs
  (as downloaded by ``benchmarks/docker/fetch_logs.py``) to validate all eight logs
  against ActiTraC-ProM's published cluster sizes.
"""

import os
import sys
from pathlib import Path

import pandas as pd
import pytest

from actitrac import cluster_traces

HELPDESK = os.environ.get("ACTITRAC_HELPDESK_CSV")
DATA_DIR = os.environ.get("ACTITRAC_DATA_DIR")

# Published ActiTraC-ProM cluster sizes from Peeperkorn et al. (docs/fidelity.md).
PROM_PUBLISHED_FREQ = {
    "Helpdesk": (4, [3828, 408, 246, 98]),
    "RTFM": (4, [59928, 65881, 20777, 3784]),
    "BPIC13_incidents": (5, [1893, 2179, 352, 2780, 350]),
    "BPIC13_closedproblems": (5, [884, 153, 208, 175, 67]),
    "Hospital_Billing": (5, [63002, 22453, 10304, 3638, 603]),
    "Sepsis": (6, [72, 609, 208, 62, 41, 58]),
    "BPIC12": (4, [8466, 2325, 596, 1700]),
    "BPIC15": (4, [3011, 989, 1060, 588]),
}

PROM_PUBLISHED_DIST = {
    "Helpdesk": (4, [2772, 879, 685, 244], [2949, 883, 500, 248], 0.040),
    "RTFM": (4, [62316, 46745, 20535, 20774], [62316, 49883, 20627, 17544], 0.021),
    "BPIC13_incidents": (5, [1900, 2110, 352, 2826, 366], [1900, 2083, 352, 2848, 371], 0.004),
    "BPIC13_closedproblems": (5, [575, 175, 351, 206, 180], [575, 175, 351, 206, 180], 0.0),
    "Hospital_Billing": (5, [62472, 22451, 6507, 3638, 4932], [41471, 22468, 22668, 9710, 3683], 0.222),
    "Sepsis": (6, [67, 543, 202, 82, 94, 62], [57, 651, 182, 63, 39, 58], 0.103),
    "BPIC12": (4, [4224, 1965, 722, 6176], [4224, 1965, 722, 6176], 0.0),
    "BPIC15": (4, [1628, 2619, 677, 725], [3063, 1312, 393, 880], 0.282),
}


@pytest.fixture(scope="module")
def helpdesk():
    frame = pd.read_csv(HELPDESK, usecols=["Case ID", "Activity", "Complete Timestamp"])
    frame.columns = ["case:concept:name", "concept:name", "time:timestamp"]
    frame["time:timestamp"] = pd.to_datetime(frame["time:timestamp"])
    return frame


@pytest.mark.skipif(not HELPDESK, reason="ACTITRAC_HELPDESK_CSV is not set")
def test_frequency_mode_regression_and_prom_gap(helpdesk):
    """Pin python-ActiTraC's sizes and verify ProM agreement within the 8-case bound."""
    result = cluster_traces(
        helpdesk, number_of_clusters=4, window_size=0, cluster_remaining_traces=False
    )
    sizes = [c.n_cases for c in result]
    assert sizes == [3824, 412, 246, 98]
    # ProM's seeded token choice moves these 4 cases. See the prom_compatible test below.
    assert sum(abs(a - b) for a, b in zip(sizes, [3828, 408, 246, 98])) <= 8


@pytest.mark.skipif(not HELPDESK, reason="ACTITRAC_HELPDESK_CSV is not set")
def test_prom_compatible_frequency_mode_matches_prom_exactly(helpdesk):
    result = cluster_traces(
        helpdesk,
        number_of_clusters=4,
        window_size=0,
        cluster_remaining_traces=False,
        prom_compatible=True,
    )
    assert [c.n_cases for c in result] == [3828, 408, 246, 98]


@pytest.mark.skipif(not HELPDESK, reason="ACTITRAC_HELPDESK_CSV is not set")
def test_distance_mode_helpdesk_regression_snapshot(helpdesk):
    """Regression snapshot + documented gap vs ProM (ProM's distance bugs are omitted)."""
    result = cluster_traces(
        helpdesk,
        number_of_clusters=4,
        window_size=0.25,
        cluster_remaining_traces=False,
    )
    sizes = [c.n_cases for c in result]
    assert sizes == [2949, 883, 500, 248]
    # Gap vs ActiTraC-ProM (which has the distance-matrix lookup bug) is 4.0%.
    prom = [2772, 879, 685, 244]
    differ = sum(abs(a - b) for a, b in zip(sizes, prom)) / 2 / sum(prom)
    assert differ == pytest.approx(0.040, abs=0.002)


@pytest.mark.skipif(not DATA_DIR, reason="ACTITRAC_DATA_DIR is not set")
@pytest.mark.parametrize("log_name", list(PROM_PUBLISHED_FREQ))
def test_all_eight_logs_prom_compatible_frequency_matches_published(log_name):
    benchmarks_dir = str(Path(__file__).resolve().parent.parent / "benchmarks")
    if benchmarks_dir not in sys.path:
        sys.path.insert(0, benchmarks_dir)
    from compare_entropic import CASE, ORIGINAL_CASE, load_log

    frame = load_log(DATA_DIR, log_name)
    k, expected = PROM_PUBLISHED_FREQ[log_name]
    result = cluster_traces(
        frame,
        number_of_clusters=k,
        window_size=0,
        minimal_cluster_size=0.25,
        target_fitness=1.0,
        cluster_remaining_traces=False,
        prom_compatible=True,
    )
    if ORIGINAL_CASE in frame:
        sizes = [
            group[ORIGINAL_CASE].nunique()
            for _, group in frame.groupby(frame[CASE].map(result.labels))
        ]
    else:
        sizes = [c.n_cases for c in result]
    assert sizes == expected


@pytest.mark.skipif(not DATA_DIR, reason="ACTITRAC_DATA_DIR is not set")
@pytest.mark.parametrize("log_name", list(PROM_PUBLISHED_DIST))
def test_all_eight_logs_distance_mode_regression_snapshot(log_name):
    """Regression snapshot + documented gap vs ProM (ProM's distance bugs are omitted)."""
    benchmarks_dir = str(Path(__file__).resolve().parent.parent / "benchmarks")
    if benchmarks_dir not in sys.path:
        sys.path.insert(0, benchmarks_dir)
    from compare_entropic import CASE, ORIGINAL_CASE, load_log

    frame = load_log(DATA_DIR, log_name)
    k, prom_sizes, expected, expected_gap = PROM_PUBLISHED_DIST[log_name]
    result = cluster_traces(
        frame,
        number_of_clusters=k,
        window_size=0.25,
        minimal_cluster_size=0.25,
        target_fitness=1.0,
        cluster_remaining_traces=False,
    )
    if ORIGINAL_CASE in frame:
        sizes = [
            group[ORIGINAL_CASE].nunique()
            for _, group in frame.groupby(frame[CASE].map(result.labels))
        ]
    else:
        sizes = [c.n_cases for c in result]
    assert sizes == expected
    n = max(len(sizes), len(prom_sizes))
    s_pad = sizes + [0] * (n - len(sizes))
    p_pad = prom_sizes + [0] * (n - len(prom_sizes))
    differ = sum(abs(a - b) for a, b in zip(s_pad, p_pad)) / 2 / max(sum(sizes), sum(prom_sizes))
    assert differ == pytest.approx(expected_gap, abs=0.001)
