"""復活 採算 gate の regression test (2026-08-07 revive_qty1_impl §4).

依頼書 完了条件 4 「採算の回帰テスト (推奨価格 > 現在価格 の行が復活せず「価格改定待ち」)」。

`check_pricing_gate` と apply_gates() 経由の 価格 gate が、
「推奨価格 ≤ 現在の出品価格 → 復活可 / それ以外 → 価格改定待ち or skip」 を
担保する。 価格は決めない・書かない (V8 SSOT の管轄)。
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ebay_actions.revive_csv_generator import check_pricing_gate, apply_gates  # noqa: E402
from sheet_updater import resolve_pricing_category  # noqa: E402


def _row(cur_m="10000", price="10000", category="G-SHOCK"):
    return {
        "current_m_jpy_str": cur_m,
        "price": price,
        "category": category,
        "current_sold": "",
        "err_flag_prev": "",
        "checked_at": "2026/08/07 12:00:00",
    }


# ============================================================================
# CAT_SHEET_TO_PRICING (sheet 生値 → pricing_engine カテゴリ) の SSOT ミラー
# ============================================================================
def test_resolve_pricing_category_maps_common_values():
    """依頼書 §12-1 で実測した「変換 OK/NG」 一覧の再現テスト。"""
    assert resolve_pricing_category("G-SHOCK") == "G-SHOCK"
    assert resolve_pricing_category("G-shock") == "G-SHOCK"     # 大小無視
    assert resolve_pricing_category("TCG") == "TCG(PSA10)"
    assert resolve_pricing_category("PSA") == "TCG(PSA10)"
    assert resolve_pricing_category("Tシャツ") == "Tシャツ(UT)"
    assert resolve_pricing_category("montbell") == "Montbell(軽)"
    assert resolve_pricing_category("一番くじ") == "一番くじ"
    # ★ fail-closed: 未対応カテゴリは None (= 復活対象外)
    assert resolve_pricing_category("バッグ") is None
    assert resolve_pricing_category("アウトドア・ジャケット") is None
    assert resolve_pricing_category("グリグラ") is None
    assert resolve_pricing_category("カプセルトイ") is None
    assert resolve_pricing_category("") is None
    assert resolve_pricing_category(None) is None


# ============================================================================
# check_pricing_gate 単体
# ============================================================================
def test_pricing_gate_ok_when_cur_gte_recommended():
    """現在価格 ≥ 推奨価格 → 復活可 ("ok")。"""
    r = _row(cur_m="10000")
    verdict, detail = check_pricing_gate(r, cur_price_usd=300.0,
                                          compute_fn=lambda c, m, cat: {"price": 250.98})
    assert verdict == "ok"
    assert detail["cur_usd"] == 300.0
    assert detail["rec_usd"] == 250.98


def test_pricing_gate_hold_when_cur_below_recommended():
    """現在価格 < 推奨価格 → 価格改定待ち ("hold_below_recommended")。"""
    r = _row(cur_m="10000")
    verdict, detail = check_pricing_gate(r, cur_price_usd=200.0,
                                          compute_fn=lambda c, m, cat: {"price": 300.98})
    assert verdict == "hold_below_recommended"
    assert detail["gap_pct"] > 0


def test_pricing_gate_skip_no_cost():
    """仕入値 取れず → skip_no_cost (復活しない、 fail-closed)。"""
    r = _row(cur_m="", price="")
    verdict, _ = check_pricing_gate(r, cur_price_usd=300.0,
                                     compute_fn=lambda c, m, cat: {"price": 100.0})
    assert verdict == "skip_no_cost"


def test_pricing_gate_skip_no_price():
    """eBay 現在価格 取れず → skip_no_price (復活しない、 fail-closed)。"""
    r = _row(cur_m="10000")
    verdict, _ = check_pricing_gate(r, cur_price_usd=None,
                                     compute_fn=lambda c, m, cat: {"price": 100.0})
    assert verdict == "skip_no_price"


def test_pricing_gate_skip_no_category_unmapped():
    """CAT2CALC に無いカテゴリ (バッグ等) → skip_no_category (復活しない、 fail-closed)。"""
    r = _row(cur_m="10000", category="バッグ")
    verdict, detail = check_pricing_gate(r, cur_price_usd=100.0,
                                          compute_fn=lambda c, m, cat: {"price": 50.0})
    assert verdict == "skip_no_category"
    assert detail["cat_sheet"] == "バッグ"


def test_pricing_gate_engine_error_returns_skip():
    """pricing_engine.compute_listing_price が例外 → skip (壊れて復活はしない)。"""
    r = _row(cur_m="10000")

    def raiser(*a, **k):
        raise ValueError("boom")

    verdict, detail = check_pricing_gate(r, cur_price_usd=100.0, compute_fn=raiser)
    assert verdict == "skip_pricing_engine_err"
    assert "boom" in detail["error"]


# ============================================================================
# apply_gates 経由: 採算割れは price_hold に、 通過は allowed に
# ============================================================================
def _valid_row(iid, cur_m="10000", price="10000"):
    return {
        "row_index": int(iid[-3:]) if iid[-3:].isdigit() else 100,
        "url": "https://amazon.co.jp/dp/B00000000X",
        "item_id": iid,
        "title": iid,
        "current_sold": "",
        "err_flag_prev": "",
        "checked_at": "2026/08/07 12:00:00",
        "sheet_label": "HIGH",
        "key_number": "",
        "category": "G-SHOCK",
        "price": price,
        "current_m_jpy_str": cur_m,
    }


def test_apply_gates_price_hold_routes_to_price_hold_list():
    """apply_gates: 採算割れ 1 件 / OK 1 件 / no_category 1 件 → 分岐が正しい。"""
    cycle_start = datetime(2026, 8, 7, 11, 0, 0)
    candidates = [
        _valid_row("IID_OK_001"),
        _valid_row("IID_HOLD_002"),
        _valid_row("IID_NOCAT_003"),
    ]
    # IID_NOCAT_003 だけカテゴリを未対応に (バッグ)
    candidates[2]["category"] = "バッグ"

    # rec_price: OK=200 vs cur=300 → allowed / HOLD=400 vs cur=300 → price_hold
    def _fetch(iid):
        return (300.0, 0)

    def _compute(cost, med, cat):
        # 呼ばれるのは OK と HOLD の 2 件 (NOCAT は resolve_pricing_category で先に落ちる)
        if med is not None:
            raise AssertionError("復活の compute は median_usd=None で呼ぶ規約")
        # cost_jpy 10000 で HOLD は高い値、 OK は低い値
        return {"price": 400.98 if cost == 10000 and False else 200.98}
    # 別 approach: item ごとに切り替えるため cost_jpy を変える方が確実
    candidates[1]["current_m_jpy_str"] = "50000"  # HOLD 側は仕入値変えて識別

    def _compute2(cost, med, cat):
        assert med is None
        return {"price": 400.98 if cost >= 20000 else 100.98}

    allowed, deferred, price_hold = apply_gates(
        candidates=candidates,
        sheet_key_maps={"HIGH": {}},
        cycle_started_at=cycle_start,
        active_qty_map={},
        fetch_price_fn=_fetch,
        compute_fn=_compute2,
    )
    allowed_iids = {c["item_id"] for c in allowed}
    hold_iids = {c["item_id"] for c in price_hold}
    deferred_iids = {c["item_id"] for c in deferred}
    assert "IID_OK_001" in allowed_iids
    assert "IID_HOLD_002" in hold_iids
    assert "IID_NOCAT_003" in deferred_iids
    nocat = next(c for c in deferred if c["item_id"] == "IID_NOCAT_003")
    assert nocat["skip_reason"] == "skip_no_category"


def test_apply_gates_recommended_equal_current_is_ok():
    """境界: 推奨価格 == 現在価格 → 復活可 (等号は許容)。"""
    cycle_start = datetime(2026, 8, 7, 11, 0, 0)
    candidates = [_valid_row("IID_EQ_010")]
    allowed, deferred, _ = apply_gates(
        candidates=candidates,
        sheet_key_maps={"HIGH": {}},
        cycle_started_at=cycle_start,
        active_qty_map={},
        fetch_price_fn=lambda iid: (200.98, 0),
        compute_fn=lambda cost, med, cat: {"price": 200.98},
    )
    assert len(allowed) == 1
    assert allowed[0]["item_id"] == "IID_EQ_010"
