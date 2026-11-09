import pandas as pd
import pytest

from actitrac import extract_variants


def frame(rows):
    return pd.DataFrame(rows, columns=["case:concept:name", "concept:name", "time:timestamp"])


def test_variants_are_sorted_by_frequency_with_first_seen_ties():
    log = frame([
        ("1", "x", 1), ("2", "a", 2), ("3", "a", 3), ("4", "y", 4),
    ])
    variants = extract_variants(log).variants
    assert [v.activities for v in variants] == [("a",), ("x",), ("y",)]
    assert [v.frequency for v in variants] == [2, 1, 1]
    assert [v.id for v in variants] == [0, 1, 2]
    assert variants[0].case_ids == ("2", "3")


def test_events_are_ordered_by_timestamp_within_a_case():
    log = frame([("1", "b", 2), ("1", "a", 1)])
    assert extract_variants(log).variants[0].activities == ("a", "b")


def test_equal_timestamps_keep_log_order():
    log = frame([("1", "b", 1), ("1", "a", 1)])
    assert extract_variants(log).variants[0].activities == ("b", "a")


def lifecycle_log():
    log = frame([("1", "a", 1), ("1", "a", 2), ("1", "b", 3), ("2", "c", 4)])
    log["lifecycle:transition"] = ["start", "complete", "complete", "start"]
    return log


def test_lifecycle_complete_drops_other_events_and_empty_cases():
    variants = extract_variants(lifecycle_log(), lifecycle="complete").variants
    assert [v.activities for v in variants] == [("a", "b")]


def test_lifecycle_classifier_is_the_default_and_keeps_all_events():
    variants = extract_variants(lifecycle_log()).variants
    assert variants[0].activities == ("a+start", "a+complete", "b+complete")
    assert variants[1].activities == ("c+start",)


def test_log_without_complete_events_keeps_every_case():
    log = frame([("1", "a", 1), ("1", "b", 2), ("2", "a", 3)])
    log["lifecycle:transition"] = ["In Progress", "Closed", "Closed"]
    assert extract_variants(log).n_cases == 2
    assert extract_variants(log, lifecycle="complete").n_cases == 0


def test_equal_frequencies_keep_the_order_cases_appear_in_the_log():
    # Case 2 appears first in the log although its events are later in time.
    log = frame([("2", "x", 9), ("1", "y", 1), ("2", "z", 10)])
    assert [v.activities for v in extract_variants(log).variants] == [("x", "z"), ("y",)]


def test_variant_dict_input():
    variants = extract_variants({("a", "b"): 1, ("c",): 5}).variants
    assert [(v.activities, v.frequency) for v in variants] == [(("c",), 5), (("a", "b"), 1)]


@pytest.mark.parametrize("counts", [{(): 1}, {("a",): 0}])
def test_invalid_variant_dict_is_rejected(counts):
    with pytest.raises(ValueError):
        extract_variants(counts)


def test_missing_columns_are_reported():
    with pytest.raises(ValueError, match="concept:name"):
        extract_variants(pd.DataFrame({"case:concept:name": ["1"]}))
