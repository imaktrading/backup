"""楽天 即納/予約 判定の test — 条件表 (SSOT) は共有 JSON から読む.

窓口 GO: `inventory/requests/2026-08-19_rakuten_delivery_wording_ssot_response.md`
条件表: `C:/dev/iMak_data/shared/rakuten_delivery_rule.json`

守る性質:
  1. **同じ正規表現を書き写さない**。ケースも判定も SSOT の JSON から読む。
     写した瞬間に監視くん / 抽出くん / 出品側がズレる。
  2. **即納と読めないものを即納にしない**。旧実装は「否定語が無ければ即納」で、
     取寄せ・入荷次第を掴んでいた (= 売れてから発送不能 → キャンセル → Defect Rate)。
  3. **判定不能 (None) を無言で通さない**。巡回は「要対応」に上げる (取下げはしない)。
  4. 条件表が読めない時は全件 判定不能に倒す (即納と決めつけない)。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scrapers import rakuten_scraper as rk  # noqa: E402

RULE_PATH = rk.DELIVERY_RULE_PATH
#: SSOT が消えていたら test ごと落とす (skip で隠すと 3 者のズレに気づけない)
assert RULE_PATH.exists(), f"条件表 (SSOT) が無い: {RULE_PATH}"
RULE = json.loads(RULE_PATH.read_text(encoding="utf-8"))

#: True=予約 / False=即納 / None=判定不能
_EXPECT = {"preorder": True, "immediate": False, "skip": None}
CASES = [(c["msg"], _EXPECT[c["expect"]]) for c in RULE["cases"]]


@pytest.fixture(autouse=True)
def _fresh_rule_cache():
    """module cache を毎回捨てる (JSON 差替 test が後続に漏れないように)."""
    rk._RULE_CACHE = None
    yield
    rk._RULE_CACHE = None


# ============================================================================
# 条件表そのもの (ケースは JSON から)
# ============================================================================
def test_cases_cover_all_three_outcomes():
    """SSOT のケースが即納/予約/skip を全部含むこと (片寄ったら守れていない)."""
    assert {e for _, e in CASES} == {True, False, None}


@pytest.mark.parametrize("msg,expect", CASES, ids=[c["expect"] for c in RULE["cases"]])
def test_judge_delivery_matches_ssot(msg, expect):
    assert rk.judge_delivery(msg) is expect, f"SSOT のケースと食い違う: {msg!r}"


def test_yotei_alone_is_not_preorder():
    """★「予定」単体を DENY に入れない (入れると即納が全部予約に落ちる)."""
    assert rk.judge_delivery("1〜2日以内に発送予定（店舗休業日を除く）") is False


def test_unknown_wording_is_indeterminate_not_immediate():
    """★ 旧実装のバグ: 否定語が無いだけで即納にしていた。読めなければ None."""
    for msg in ("お届けまで1週間程度かかります", "在庫状況はお問い合わせください", "▲△▲"):
        assert rk.judge_delivery(msg) is None, msg


def test_rule_unreadable_is_indeterminate():
    """条件表が読めない時に即納へ倒れないこと (fail-closed)."""
    with patch.object(rk, "DELIVERY_RULE_PATH", Path(r"C:/dev/__no_such_rule__.json")):
        rk._RULE_CACHE = None
        assert rk.judge_delivery("1〜2日以内発送") is None
        assert rk.judge_delivery("2026年10月発売予定") is None


# ============================================================================
# HTML 経由 (detect_preorder)
# ============================================================================
def _html(msg: str) -> str:
    return '{"deliveryMessage":"%s"}' % msg


@pytest.mark.parametrize("msg,expect", [(m, e) for m, e in CASES if m])
def test_detect_preorder_from_html(msg, expect):
    is_pre, got = rk.detect_preorder(_html(msg))
    assert is_pre is expect
    assert got == msg


def test_no_delivery_message_is_indeterminate():
    assert rk.detect_preorder('{"soldout":0}') == (None, "")


# ============================================================================
# 巡回への反映 (★ここが本体: skip を無言で通さない)
# ============================================================================
def _rakuten_info(is_pre, msg):
    return {"status": "IN_STOCK", "is_preorder": is_pre, "delivery_message": msg,
            "skus": [{"in_stock": True, "price_jpy": 1750}]}


def test_indeterminate_delivery_is_raised_not_silently_passed():
    """★ None を素通しすると『即納として監視し続ける』= fail-OPEN が残る."""
    import monitor_listings as ml  # noqa: PLC0415

    logged = []
    info = _rakuten_info(None, "ご注文後、お取り寄せとなります")
    with patch.object(ml, "fetch_rakuten", return_value=info), \
         patch.object(ml, "log", side_effect=lambda *a, **k: logged.append(str(a[0]))):
        sub = ml._check_single_url("https://item.rakuten.co.jp/shop/x/", sleep_sec=0)

    assert sub["is_sold"] is False                    # 取下げはしない
    assert sub["preorder"] is None                    # 判定不能として保持
    assert "即納不明" in sub["raw_status"]             # 無言で通さない
    assert any("判定不能" in m for m in logged)


def test_missing_delivery_message_is_also_raised():
    """配送メッセージ欠落 (decode 失敗の残骸含む) も要対応に上げる."""
    import monitor_listings as ml  # noqa: PLC0415

    with patch.object(ml, "fetch_rakuten", return_value=_rakuten_info(None, "")), \
         patch.object(ml, "log"):
        sub = ml._check_single_url("https://item.rakuten.co.jp/shop/x/", sleep_sec=0)

    assert sub["is_sold"] is False
    assert "即納不明" in sub["raw_status"]


def test_immediate_is_not_flagged():
    """即納は静かに通す (要対応が墓場にならないように)."""
    import monitor_listings as ml  # noqa: PLC0415

    with patch.object(ml, "fetch_rakuten", return_value=_rakuten_info(False, "1〜2日以内発送")), \
         patch.object(ml, "log"):
        sub = ml._check_single_url("https://item.rakuten.co.jp/shop/x/", sleep_sec=0)

    assert sub["is_sold"] is False
    assert sub.get("preorder") is None or "preorder" not in sub
    assert "即納不明" not in sub["raw_status"]
    assert "予約" not in sub["raw_status"]


def test_other_supplier_is_not_flagged_by_missing_is_preorder():
    """★ 楽天以外は is_preorder を返さない (= 常に None)。これを要対応にしない."""
    import monitor_listings as ml  # noqa: PLC0415

    info = {"status": "ON_SALE", "skus": [{"in_stock": True, "price_jpy": 3000}]}
    with patch.object(ml, "fetch_mercari", return_value=info), patch.object(ml, "log"):
        sub = ml._check_single_url("https://jp.mercari.com/item/m123", sleep_sec=0)

    assert sub["is_sold"] is False
    assert "即納不明" not in sub["raw_status"]
