import random

import numpy as np
import pytest
from conftest import make_variants

from actitrac import maximal_repeats, mra_features, osa_distance
from actitrac.distance import base_features, distance_rows


def as_tuples(*traces):
    return [tuple(trace) for trace in traces]


def strings(repeats):
    return {"".join(repeat) for repeat in repeats}


def brute_force_maximal_repeats(traces):
    """Check the definition directly: two occurrences differing on both sides."""
    occurrences = {}
    for t, trace in enumerate(traces):
        for i in range(len(trace)):
            for j in range(i + 1, len(trace) + 1):
                occurrences.setdefault(trace[i:j], []).append((t, i, j))
    found = set()
    for pattern, places in occurrences.items():
        lefts, rights = set(), set()
        for t, i, j in places:
            lefts.add(traces[t][i - 1] if i else ("start", t, i))
            rights.add(traces[t][j] if j < len(traces[t]) else ("end", t, j))
        if len(places) > 1 and len(lefts) > 1 and len(rights) > 1:
            found.add(pattern)
    return found


def test_maximal_repeats_on_the_example_from_bose():
    repeats = strings(maximal_repeats(as_tuples("abcdabxabcd", "xycda")))
    assert {"abcd", "cda", "ab", "x"} <= repeats
    assert "abc" not in repeats  # always followed by d
    assert "bcd" not in repeats  # always preceded by a


def test_maximal_repeats_matches_brute_force():
    rng = random.Random(7)
    for _ in range(200):
        traces = [
            tuple(rng.choices("abc", k=rng.randint(1, 8)))
            for _ in range(rng.randint(1, 4))
        ]
        assert maximal_repeats(traces) == brute_force_maximal_repeats(traces)


def test_identical_context_is_not_maximal():
    assert strings(maximal_repeats(as_tuples("xay", "xay"))) == {"xay"}
    assert strings(maximal_repeats(as_tuples("xaybxay"))) == {"xay"}


def test_base_features_decompose_longer_repeats():
    assert strings(base_features({tuple("abab")})) == {"ab"}
    assert strings(base_features({tuple("ab"), tuple("abab")})) == {"ab"}
    assert strings(base_features({tuple("abc")})) == {"abc"}


def test_base_features_terminate_on_repeats_that_recur_across_inputs():
    # abcabc occurs inside the other input as well as being an input itself.
    features = base_features({tuple("abcabc"), tuple("xabcabcyabcabc")})
    assert "abc" in strings(features)
    assert all(len(feature) == len(set(feature)) for feature in features)


def test_mra_features_group_repeats_by_alphabet():
    features = mra_features(as_tuples("abxba", "abyba", "qq"))
    # ab and ba share an alphabet, so each trace counts both in one column.
    assert features.shape[0] == 3
    assert (features[0] == features[1]).all()
    assert features[0].sum() > features[2].sum()


def test_mra_distance_separates_traces_with_different_patterns():
    variants = make_variants({"abcabc": 1, "abcxabc": 1, "pqrpqr": 1, "pqrypqr": 1})
    row = distance_rows("mra", variants)
    assert row(0)[0] == 0
    assert row(0)[1] < row(0)[2]
    assert row(2)[3] < row(2)[1]


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [("", "", 0), ("abc", "", 3), ("abc", "abc", 0), ("abcd", "acbd", 1), ("abc", "axc", 1)],
)
def test_osa_distance(a, b, expected):
    assert osa_distance(a, b) == expected


def test_osa_operates_on_activities_not_characters():
    assert osa_distance(("register", "pay"), ("register", "refund")) == 1


def test_callable_distance_metric():
    variants = make_variants({"ab": 1, "abc": 1})
    row = distance_rows(lambda a, b: abs(len(a) - len(b)), variants)
    assert np.array_equal(row(0), [0.0, 1.0])


def test_unknown_distance_metric_is_rejected():
    with pytest.raises(ValueError):
        distance_rows("euclid", make_variants({"a": 1}))
