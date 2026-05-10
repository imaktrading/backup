"""Unit tests for monthly_report helpers (PDCA Check 事後 集計の起点).

Google Sheet ops は test 不可 (実 spreadsheet 必要)、helper 関数のみ検証.
"""
from __future__ import annotations
import importlib.util
import sys
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_HQ = _REPO_ROOT / "iMakHQ"
if str(_HQ) not in sys.path:
    sys.path.insert(0, str(_HQ))


def _load_mr():
    path = _HQ / "monthly_report.py"
    spec = importlib.util.spec_from_file_location("_test_monthly_report", str(path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_parse_money_handles_currency_symbols():
    mr = _load_mr()
    assert mr._parse_money("$12.34") == 12.34
    assert mr._parse_money("¥1,234") == 1234.0
    assert mr._parse_money("¥12,345") == 12345.0
    assert mr._parse_money("1234") == 1234.0
    assert mr._parse_money("") == 0.0
    assert mr._parse_money(None) == 0.0
    assert mr._parse_money("invalid") == 0.0


def test_parse_money_negative():
    mr = _load_mr()
    assert mr._parse_money("-500") == -500.0
    assert mr._parse_money("¥-1,000") == -1000.0


def test_parse_date_multiple_formats():
    mr = _load_mr()
    assert mr._parse_date("2026/05/11") == datetime(2026, 5, 11)
    assert mr._parse_date("2026-05-11") == datetime(2026, 5, 11)
    assert mr._parse_date("2026年5月11日") == datetime(2026, 5, 11)
    assert mr._parse_date("") is None
    assert mr._parse_date(None) is None
    assert mr._parse_date("invalid") is None


def test_aggregate_by_category_basic():
    mr = _load_mr()
    sales = [
        {"item_id": "i1", "name": "A", "sale_date": None, "price": 100.0, "profit": 1000.0, "category": "TCG"},
        {"item_id": "i2", "name": "B", "sale_date": None, "price": 50.0, "profit": 500.0, "category": "TCG"},
        {"item_id": "i3", "name": "C", "sale_date": None, "price": 30.0, "profit": 300.0, "category": "Tシャツ"},
    ]
    actives = [
        {"url": "u1", "item_id": "i100", "title": "T", "category": "TCG", "added_date": None},
        {"url": "u2", "item_id": "i101", "title": "T", "category": "TCG", "added_date": None},
        {"url": "u3", "item_id": "i102", "title": "T", "category": "Tシャツ", "added_date": None},
    ]
    rows = mr.aggregate_by_category(sales, actives)
    by_cat = {r[0]: r for r in rows}
    # TCG: 2 sold, 2 active, 100% sell-through (sold=active で 100%)
    assert by_cat["TCG"][1] == 2  # sold count
    assert by_cat["TCG"][2] == 2  # active count
    assert by_cat["TCG"][3] == "100.0%"
    # Tシャツ: 1 sold, 1 active, 100%
    assert by_cat["Tシャツ"][1] == 1


def test_top_selling_keywords():
    mr = _load_mr()
    sales = [
        {"item_id": "i1", "name": "PSA Pikachu Card", "sale_date": None, "price": 100.0, "profit": 1000.0, "category": "TCG"},
        {"item_id": "i2", "name": "PSA Pikachu Promo", "sale_date": None, "price": 80.0, "profit": 800.0, "category": "TCG"},
        {"item_id": "i3", "name": "PSA Charizard", "sale_date": None, "price": 200.0, "profit": 2000.0, "category": "TCG"},
    ]
    rows = mr.top_selling_keywords(sales, top_n=10)
    by_kw = {r[0]: r for r in rows}
    # Pikachu: 2 sold, Charizard: 1 sold
    assert by_kw["Pikachu"][1] == 2
    assert by_kw["Charizard"][1] == 1
    # 4 文字以上 keyword のみ集計 (regex [A-Z][a-zA-Z]{3,}). PSA / TCG 等の 3 文字
    # は除外 (noise 削減). 重要なら別途 explicit keyword 化検討.
    assert "PSA" not in by_kw


def test_stale_listings_filters_recent_and_sold():
    from datetime import datetime, timedelta
    mr = _load_mr()
    today = datetime.now()
    sales = [
        {"item_id": "sold-id", "name": "Sold Item", "sale_date": today, "price": 100.0, "profit": 1000.0, "category": "TCG"},
    ]
    actives = [
        # 売れた商品 → 死蔵対象外
        {"url": "u1", "item_id": "sold-id", "title": "Sold Item", "category": "TCG",
         "added_date": today - timedelta(days=120)},
        # 90 日経ってない → 対象外
        {"url": "u2", "item_id": "fresh", "title": "Fresh", "category": "TCG",
         "added_date": today - timedelta(days=30)},
        # 90+ 日経過、売れてない → 死蔵
        {"url": "u3", "item_id": "stale", "title": "Stale Item", "category": "TCG",
         "added_date": today - timedelta(days=120)},
    ]
    stale = mr.stale_listings(actives, sales, stale_days=90)
    item_ids = [r[1] for r in stale]
    assert "stale" in item_ids
    assert "sold-id" not in item_ids
    assert "fresh" not in item_ids
