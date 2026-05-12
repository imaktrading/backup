"""Regression: 2026-05-12 seller_hub_tier (Active 改善対象抽出ツール).

【判定軸】(5/12 ユーザー判断、論点 2):
  改善対象 = 出品 30日超 AND (
    views == 0
    OR
    (views < 5 AND watchers == 0)
  )

タイトル/価格を 1回見直し → 30日後 再評価 → 改善なければ END。
"""
from __future__ import annotations
import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_HQ = _REPO_ROOT / "iMakHQ"


def _load_tier():
    path = _HQ / "seller_hub_tier.py"
    spec = importlib.util.spec_from_file_location("_test_tier", str(path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_filter_views_zero():
    """views=0 + 30日超 → 改善対象."""
    mod = _load_tier()
    today = datetime(2026, 5, 12)
    rows = [
        {"listed_date": "2026-03-01", "views": "0", "watchers": "0", "title": "Test1", "price_usd": "100"},
        {"listed_date": "2026-05-10", "views": "0", "watchers": "0", "title": "Recent", "price_usd": "100"},
    ]
    targets = mod.filter_improvement_targets(rows, today=today)
    assert len(targets) == 1
    assert targets[0]["title"] == "Test1"  # 30日超


def test_filter_views_low_watchers_zero():
    """views<5 AND watchers=0 + 30日超 → 改善対象."""
    mod = _load_tier()
    today = datetime(2026, 5, 12)
    rows = [
        {"listed_date": "2026-03-01", "views": "3", "watchers": "0", "title": "Low view", "price_usd": "100"},
        {"listed_date": "2026-03-01", "views": "3", "watchers": "1", "title": "Low view + watch", "price_usd": "100"},
        {"listed_date": "2026-03-01", "views": "10", "watchers": "0", "title": "OK views", "price_usd": "100"},
    ]
    targets = mod.filter_improvement_targets(rows, today=today)
    titles = [t["title"] for t in targets]
    assert "Low view" in titles  # views<5 + watchers=0
    assert "Low view + watch" not in titles  # watchers>=1 で除外
    assert "OK views" not in titles  # views>=5


def test_filter_excludes_recent_listings():
    """出品 30日以内 → views=0 でも改善対象外."""
    mod = _load_tier()
    today = datetime(2026, 5, 12)
    rows = [
        {"listed_date": "2026-04-20", "views": "0", "watchers": "0", "title": "Recent", "price_usd": "100"},
    ]
    targets = mod.filter_improvement_targets(rows, today=today)
    assert len(targets) == 0  # 22 日しか経ってない


def test_filter_handles_missing_listed_date():
    """listed_date 空 → skip (parse 失敗 listing は対象外)."""
    mod = _load_tier()
    today = datetime(2026, 5, 12)
    rows = [
        {"listed_date": "", "views": "0", "watchers": "0", "title": "No date", "price_usd": "100"},
    ]
    targets = mod.filter_improvement_targets(rows, today=today)
    assert len(targets) == 0


def test_categorize_by_keyword():
    """Title からカテゴリ推定."""
    mod = _load_tier()
    assert mod.categorize_by_keyword("Porter Tanker Shoulder Bag") == "Porter"
    assert mod.categorize_by_keyword("CASIO G-Shock GA-2100") == "G-Shock"
    assert mod.categorize_by_keyword("PSA 10 Pokemon Card") == "PSA10 TCG"
    assert mod.categorize_by_keyword("Ichiban Kuji Hololive") == "Ichiban Kuji"
    assert mod.categorize_by_keyword("Shimano Reel") == "Reel"
    assert mod.categorize_by_keyword("Tomica Limited") == "Tomica"
    assert mod.categorize_by_keyword("UNIQLO UT Anime") == "UNIQLO UT"
    assert mod.categorize_by_keyword("Random Sanrio Plush") == "Other"


def test_parse_date_formats():
    """parse_date が複数フォーマット対応."""
    mod = _load_tier()
    assert mod.parse_date("2026-05-11") == datetime(2026, 5, 11)
    assert mod.parse_date("2026/05/11") == datetime(2026, 5, 11)
    assert mod.parse_date("") is None
    assert mod.parse_date("invalid") is None


def test_summarize_returns_category_counts():
    """summarize() がカテゴリ別件数と平均経過日数を返す."""
    mod = _load_tier()
    targets = [
        {"title": "Porter Bag 1", "_days_listed": 60},
        {"title": "Porter Bag 2", "_days_listed": 100},
        {"title": "G-Shock Watch", "_days_listed": 50},
    ]
    summary = mod.summarize(targets)
    assert summary["Porter"]["count"] == 2
    assert summary["Porter"]["avg_days"] == 80
    assert summary["G-Shock"]["count"] == 1
