"""M列(現在価格) = 「在庫あり候補の min price(主+補)」採用の regression test.

★ 2026-07-26 HQ依頼 (M_price_min_live_supply_impl)。旧実装は「順序上最初の在庫あり」1本の価格を M に
採用していたが、主売切+複数補が別価格生存時に最安を採らず N(仕入れ値)が過大/過小になる GAP があった。
→ M = min(在庫あり かつ 価格取得できた候補)、K = その min を採った "同一URL" の points (M/K 一貫性)。
在庫判定(取下げ可否)は不変 (1本でも在庫あり→取下げない)。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _stub(table):
    """url -> {"is_sold":bool|None, "price":int|None, "points":int|None, "supplier":str}."""
    def _f(url, sleep_sec=0, mercari_driver=None, amazon_driver=None):
        d = table[url]
        return {"url": url, "supplier": d.get("supplier", "amazon"),
                "is_sold": d["is_sold"], "raw_status": "in_stock" if d["is_sold"] is False else "x",
                "error": ("e" if d["is_sold"] is None else None),
                "price_jpy": d.get("price"), "points_jpy": d.get("points")}
    return _f


def _row(main, slots):
    return {"row_index": 100, "url": main, "item_id": "356x", "title": "t",
            "current_sold": "", "backup_url_slots": list(slots) + [None] * (5 - len(slots))}


def test_min_price_across_live_backups_not_first():
    """★主売切 + AC在庫3000 + AD売切 + AE在庫2000 → M=2000(AE最安), K=AEのpoints (順序上最初のAC=3000を採らない)."""
    import monitor_listings as ml
    table = {
        "main": {"is_sold": True,  "price": None, "points": None},
        "AC":   {"is_sold": False, "price": 3000, "points": 60},
        "AD":   {"is_sold": True,  "price": None, "points": None},
        "AE":   {"is_sold": False, "price": 2000, "points": 40},
    }
    with patch("monitor_listings._check_single_url", side_effect=_stub(table)):
        r = ml.check_one_row_with_fallback(_row("main", ["AC", "AD", "AE"]))
    assert r["is_sold"] is False          # 在庫あり (取下げない) 不変
    assert r["price_jpy"] == 2000         # ★min (AE)、AC=3000 ではない
    assert r["points_jpy"] == 40          # ★min を採った同一URL(AE) の points


def test_min_includes_main_when_main_cheapest():
    """主在庫1000 + AC在庫1500 → M=1000 (主が最安)."""
    import monitor_listings as ml
    table = {
        "main": {"is_sold": False, "price": 1000, "points": 10},
        "AC":   {"is_sold": False, "price": 1500, "points": 20},
    }
    with patch("monitor_listings._check_single_url", side_effect=_stub(table)):
        r = ml.check_one_row_with_fallback(_row("main", ["AC"]))
    assert r["price_jpy"] == 1000
    assert r["points_jpy"] == 10


def test_min_ignores_sold_and_uncertain():
    """売切/uncertain の価格は無視 (在庫あり かつ price ありのみ)."""
    import monitor_listings as ml
    table = {
        "main": {"is_sold": True,  "price": 500,  "points": 5},    # 売切(安いが対象外)
        "AC":   {"is_sold": None,  "price": 800,  "points": 8},    # uncertain(対象外)
        "AD":   {"is_sold": False, "price": 2500, "points": 50},   # 唯一の在庫あり
    }
    with patch("monitor_listings._check_single_url", side_effect=_stub(table)):
        r = ml.check_one_row_with_fallback(_row("main", ["AC", "AD"]))
    assert r["is_sold"] is False
    assert r["price_jpy"] == 2500     # 売切500/uncertain800 は採らない
    assert r["points_jpy"] == 50


def test_in_stock_but_no_price_leaves_m_untouched():
    """在庫ありだが価格取得できた候補ゼロ (snkrdunk is_listing_live 等) → price_jpy=None (M不触=fail-closed)."""
    import monitor_listings as ml
    table = {
        "main": {"is_sold": False, "price": None, "points": None, "supplier": "snkrdunk"},
        "AC":   {"is_sold": False, "price": None, "points": None, "supplier": "snkrdunk"},
    }
    with patch("monitor_listings._check_single_url", side_effect=_stub(table)):
        r = ml.check_one_row_with_fallback(_row("main", ["AC"]))
    assert r["is_sold"] is False       # 在庫あり (取下げない)
    assert r["price_jpy"] is None      # M 不触
    assert r["points_jpy"] is None


def test_all_sold_unchanged():
    """全売切 → is_sold=True (取下げ)。 価格採用ロジックの分岐外 (従来どおり)."""
    import monitor_listings as ml
    table = {
        "main": {"is_sold": True, "price": 900, "points": None},
        "AC":   {"is_sold": True, "price": None, "points": None},
    }
    with patch("monitor_listings._check_single_url", side_effect=_stub(table)):
        r = ml.check_one_row_with_fallback(_row("main", ["AC"]))
    assert r["is_sold"] is True
