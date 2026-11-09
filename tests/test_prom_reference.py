"""Compare against the published results of ActiTraC-ProM.

The reference sizes come from the Helpdesk results of
https://github.com/jaripeeperkorn/EntropicClustering. To run these tests, set
ACTITRAC_HELPDESK_CSV to the ``finale.csv`` file from
https://data.4tu.nl/articles/dataset/Dataset_belonging_to_the_help_desk_log_of_an_Italian_Company/12675977
"""

import os

import pandas as pd
import pytest

from actitrac import cluster_traces

HELPDESK = os.environ.get("ACTITRAC_HELPDESK_CSV")

pytestmark = pytest.mark.skipif(not HELPDESK, reason="ACTITRAC_HELPDESK_CSV is not set")


@pytest.fixture(scope="module")
def helpdesk():
    frame = pd.read_csv(HELPDESK, usecols=["Case ID", "Activity", "Complete Timestamp"])
    frame.columns = ["case:concept:name", "concept:name", "time:timestamp"]
    frame["time:timestamp"] = pd.to_datetime(frame["time:timestamp"])
    return frame


def test_frequency_mode_reproduces_prom(helpdesk):
    result = cluster_traces(
        helpdesk, number_of_clusters=4, window_size=0, cluster_remaining_traces=False
    )
    sizes = [c.n_cases for c in result]
    assert sizes == pytest.approx([3828, 408, 246, 98], abs=4)
    # ProM's seeded token choice moves these 4 cases. See the prom_compatible test below.
    assert sum(abs(a - b) for a, b in zip(sizes, [3828, 408, 246, 98])) <= 8


def test_prom_compatible_frequency_mode_matches_prom_exactly(helpdesk):
    result = cluster_traces(
        helpdesk,
        number_of_clusters=4,
        window_size=0,
        cluster_remaining_traces=False,
        prom_compatible=True,
    )
    assert [c.n_cases for c in result] == [3828, 408, 246, 98]
