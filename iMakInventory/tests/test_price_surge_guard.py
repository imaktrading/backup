"""価格急増ガード (M/K 書込側 supplier 単位) の regression test.

★ 2026-07-23 実装: scraper の DOM 構造変化で 1 supplier が丸ごと誤パースし、多数行に
  「plausible だが誤った」現在価格が一括で M に landing する事故 (履歴: 2026-06 amazon
  buybox DOM 化で全滅 / scraper_price_vulnerability「最初の¥」誤採用) を防ぐ。

仕様:
- 発火単位は supplier (真の failure mode に一致)。前 M (current_m_jpy_str) と新 price_jpy を
  like-with-like 比較し、|Δ|/prev > 50% の「急変行」が supplier の判定対象行の 50% 以上
  かつ 判定対象 >= 10 行 → その supplier の M/K 書込のみ HOLD。
- prev-M 無し/parse 不能な行、price_jpy 未セット行は判定母数から除外 (初回 cycle は誤発火しない)。
- D/O (取下げ) は絶対に止めない (fail-OPEN=取下げ漏れ が最悪、価格汚染防止とは別レイヤ)。
- グローバル原則 #4「急増ガード (誤一括防止)」の価格版。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _mk(row_index, supplier, price_jpy, prev_m, is_sold=False, points_jpy=None):
    """update dict helper (o_only=False = D/O も書く行)。"""
    u = {"row_index": row_index, "supplier": supplier, "is_sold": is_sold,
         "checked_at": "t", "price_jpy": price_jpy,
         "current_m_jpy_str": ("" if prev_m is None else str(prev_m))}
    if points_jpy is not None:
        u["points_jpy"] = points_jpy
    return u


# ============================================================================
# detect_price_surge の純ロジック
# ============================================================================
def test_constants_defined():
    from sheet_updater import (
        PRICE_SURGE_THRESHOLD, PRICE_SURGE_MIN_ROWS, PRICE_SURGE_MIN_RATIO,
    )
    assert PRICE_SURGE_THRESHOLD == 0.5
    assert PRICE_SURGE_MIN_ROWS == 10
    assert PRICE_SURGE_MIN_RATIO == 0.5


def test_no_surge_when_prices_stable():
    """全行が前 M と近い → HOLD 対象ゼロ."""
    from sheet_updater import detect_price_surge
    updates = [_mk(i, "amazon", 3000 + i, 3000 + i) for i in range(20)]
    held, stats = detect_price_surge(updates)
    assert held == set()
    assert stats["amazon"]["surged"] == 0


def test_surge_holds_supplier_when_systemic_break():
    """amazon の過半が前 M から ±50% 超乖離 → amazon を HOLD."""
    from sheet_updater import detect_price_surge
    # 12 行中 8 行が prev 3000 → 100 (誤パース) = 97% 減、 4 行は正常
    updates = ([_mk(i, "amazon", 100, 3000) for i in range(8)]
               + [_mk(100 + i, "amazon", 3000, 3000) for i in range(4)])
    held, stats = detect_price_surge(updates)
    assert "amazon" in held
    assert stats["amazon"]["total"] == 12
    assert stats["amazon"]["surged"] == 8


def test_other_supplier_unaffected():
    """amazon 崩壊時も mercari は正常なら HOLD されない (機会損失最小)."""
    from sheet_updater import detect_price_surge
    updates = ([_mk(i, "amazon", 100, 3000) for i in range(12)]           # 全崩壊
               + [_mk(200 + i, "mercari", 2000 + i, 2000 + i) for i in range(15)])  # 正常
    held, stats = detect_price_surge(updates)
    assert held == {"amazon"}
    assert "mercari" not in held


def test_below_min_rows_never_fires():
    """判定対象が min_rows(10) 未満なら、 全行急変でも発火しない (個別変動と区別不能)."""
    from sheet_updater import detect_price_surge
    updates = [_mk(i, "snkrdunk", 100, 3000) for i in range(9)]  # 9 行 < 10
    held, stats = detect_price_surge(updates)
    assert held == set()
    assert stats["snkrdunk"]["total"] == 9


def test_below_min_ratio_never_fires():
    """急変が過半 (50%) 未満なら発火しない (実市場の個別値動きを HOLD しない)."""
    from sheet_updater import detect_price_surge
    # 20 行中 9 行 (45%) だけ急変 → 発火しない
    updates = ([_mk(i, "amazon", 100, 3000) for i in range(9)]
               + [_mk(100 + i, "amazon", 3000, 3000) for i in range(11)])
    held, _ = detect_price_surge(updates)
    assert held == set()


def test_rows_without_prev_m_excluded():
    """前 M 空欄 (初回 cycle) は判定母数外 → 誤発火しない."""
    from sheet_updater import detect_price_surge
    updates = [_mk(i, "amazon", 100, None) for i in range(20)]  # prev-M 全欠
    held, stats = detect_price_surge(updates)
    assert held == set()
    assert "amazon" not in stats  # 母数ゼロ


def test_price_jpy_none_excluded_from_denominator():
    """price_jpy 未セット (fetch 失敗) 行は判定母数外."""
    from sheet_updater import detect_price_surge
    updates = [_mk(i, "amazon", None, 3000) for i in range(20)]
    held, stats = detect_price_surge(updates)
    assert held == set()
    assert "amazon" not in stats


def test_moderate_price_move_not_surge():
    """前 M から 30% 程度の値動きは急変とみなさない (閾値 50% 未満)."""
    from sheet_updater import detect_price_surge
    updates = [_mk(i, "amazon", 3900, 3000) for i in range(20)]  # +30%
    held, stats = detect_price_surge(updates)
    assert held == set()
    assert stats["amazon"]["surged"] == 0


# ============================================================================
# update_listings_sold_marks への統合 (HOLD 行の M/K skip + D/O は書く)
# ============================================================================
def test_held_supplier_skips_m_and_k_but_writes_d_o():
    """HOLD された supplier の行は M/K を書かず、 D/O は通常どおり書く (fail-OPEN 回避)."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    ws.batch_update = MagicMock()
    # amazon 全崩壊 (12 行、 うち 1 行は is_sold=True で取下げ対象)
    updates = [_mk(i, "amazon", 100, 3000, is_sold=(i == 0), points_jpy=10)
               for i in range(12)]
    res = update_listings_sold_marks(ws, updates)

    assert res["surge_held"] == ["amazon"]
    assert res["m_writes"] == 0          # 価格書込は全 HOLD
    assert res["k_writes"] == 0          # K も HOLD
    assert res["m_held"] == 12           # 見送り 12 行
    assert res["d_writes"] == 12         # ★ D (取下げ) は全行書く = fail-OPEN にしない
    assert res["o_writes"] == 12

    ranges = [c["range"] for c in ws.batch_update.call_args[0][0]]
    assert "D2" in ranges                # row_index 0 → D2 (is_sold=True 取下げ)
    assert not any(r.startswith("M") for r in ranges)  # M 一切書かない
    assert not any(r.startswith("K") for r in ranges)  # K 一切書かない


def test_non_held_supplier_writes_normally_alongside_held():
    """崩壊 supplier を HOLD しても、 正常 supplier の M/K は通常書込される."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    ws.batch_update = MagicMock()
    updates = ([_mk(i, "amazon", 100, 3000, points_jpy=10) for i in range(12)]   # 崩壊
               + [_mk(200 + i, "mercari", 2000, 2000) for i in range(15)])       # 正常
    res = update_listings_sold_marks(ws, updates)

    assert res["surge_held"] == ["amazon"]
    assert res["m_writes"] == 15         # mercari 15 行は書く
    ranges = [c["range"] for c in ws.batch_update.call_args[0][0]]
    assert "M201" in ranges              # mercari row_index 200 → M201
    assert not any(f"M{i+1}" in ranges for i in range(12))  # amazon 行 (row_index 0-11) は M 書かない


def test_guard_disabled_flag_writes_all():
    """enable_price_surge_guard=False なら崩壊検知しても全部書く (緊急 override 用)."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    ws.batch_update = MagicMock()
    updates = [_mk(i, "amazon", 100, 3000) for i in range(12)]
    res = update_listings_sold_marks(ws, updates, enable_price_surge_guard=False)
    assert res["surge_held"] == []
    assert res["m_writes"] == 12


def test_empty_updates_returns_surge_keys():
    """空 updates でも surge_held/surge_stats キーを返す (呼出側の KeyError 防止)."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    res = update_listings_sold_marks(ws, [])
    assert res["surge_held"] == []
    assert res["surge_stats"] == {}
