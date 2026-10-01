"""compare_mercari_api_vs_chrome の純関数テスト (= compare())."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from compare_mercari_api_vs_chrome import compare  # noqa: E402


def test_compare_full_match():
    chrome = {"kw1": ["a", "b", "c"]}
    api = {"kw1": ["a", "b", "c", "d"]}  # API が多く拾っても Chrome 側は全部一致
    result = compare(chrome, api)
    row = result["rows"][0]
    assert row["chrome"] == 3
    assert row["api"] == 4
    assert row["both"] == 3
    assert row["chrome_only"] == 0
    assert row["api_only"] == 1
    assert row["match_rate_of_chrome"] == 1.0
    assert result["overall_match_rate_of_chrome"] == 1.0


def test_compare_partial_match():
    chrome = {"kw1": ["a", "b"]}
    api = {"kw1": ["a", "z"]}
    row = compare(chrome, api)["rows"][0]
    assert row["both"] == 1
    assert row["chrome_only"] == 1
    assert row["api_only"] == 1
    assert row["match_rate_of_chrome"] == 0.5


def test_compare_empty_chrome_result_no_divide_by_zero():
    chrome = {"kw1": []}
    api = {"kw1": ["a"]}
    row = compare(chrome, api)["rows"][0]
    assert row["match_rate_of_chrome"] is None


def test_compare_overall_aggregates_across_keywords():
    chrome = {"kw1": ["a", "b"], "kw2": ["c"]}
    api = {"kw1": ["a"], "kw2": ["c"]}
    result = compare(chrome, api)
    assert result["total_chrome"] == 3
    assert result["total_both"] == 2
    assert result["overall_match_rate_of_chrome"] == round(2 / 3, 3)
