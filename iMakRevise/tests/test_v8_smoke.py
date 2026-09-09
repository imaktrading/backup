"""V8 smoke test - reference 4 件で V8 sheet と数値完全一致確認.

reference (2026-05-21 implementation_go.md):
  357111565952 Tシャツ ¥2,400  → $77.98 / $19.06
  357056658672 フィギュア ¥5,030 → $98.98 / $19.88
  358564731464 G-Shock ¥32,046 → $397.98 / $75.01
  357008112686 Tシャツ ¥1,700  → $65.98 / $16.87

注: この test は本元 iMakeBayAPI を import するため、本元 git checkout 状態に依存する。
yaml v6_pricing.enabled=true 前提。失敗 → V8 yaml 設定変更を疑う。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

THIS = Path(__file__).resolve().parent
PROJECT = THIS.parent
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from revise.price_revise import (
    ReviseCandidate, _import_v8_pricing, compute_new_usd, normalize_category,
)


REFERENCE_CASES = [
    # 2026-05-24 update: V8 FIX (C group split 0.5→1.0) で Tシャツ系 price 下落、shipping 上昇
    # ★2026-08-21: 一時「+$1 ドリフト」に見えたが、正体は FX 非決定 (exchange_rate が
    #   pricing gsheet の生値で入り毎回ぶれる)。pricing_engine は変わっていない。
    #   REFERENCE_FX_USD=159.245 に pin すれば下記の 2026-05-24 値に完全一致する (検証済)。
    #   → 参照値は元のまま据置。値は書き換えない (書き換えると FX 追従になり再び腐る)。
    {
        "item_id": "357111565952", "title": "Pokemon T-shirt UNIQLO UT",
        "category": "Tシャツ", "cost_jpy": 2400,
        "expected_price": 62.98, "expected_shipping": 32.23,
    },
    {
        # 2026-09-09: 本元 iMak df7e12b でフィギュア送料見込みが ¥3,000→¥4,000 に是正され
        # (2枚あった価格シートの複製=stale の方を読んでいたバグ修正)、この参照値もそれに追随。
        # FX ドリフトではなく実額の是正 — 前回 (744b712) の「参照値更新は誤り」とは別種。
        "item_id": "357056658672", "title": "Pokemon Figure",
        "category": "フィギュア", "cost_jpy": 5030,
        "expected_price": 107.98, "expected_shipping": 23.55,
    },
    {
        "item_id": "358564731464", "title": "Casio G-Shock GA-2100",
        "category": "G-shock", "cost_jpy": 32046,
        "expected_price": 397.98, "expected_shipping": 75.01,
    },
    {
        "item_id": "357008112686", "title": "Pokemon T-shirt UNIQLO UT",
        "category": "Tシャツ", "cost_jpy": 1700,
        "expected_price": 52.98, "expected_shipping": 27.84,
    },
]


# 基準 FX (固定)。yaml exchange_rate_usd と同じ「現在値に追随させない」参照レート。
# ★2026-08-21: exchange_rate は pricing gsheet の生値で入るため、これを固定しないと
#   同一入力でも FX tick ごとに新USD/送料USD が数ドルぶれ、完全一致テストが恒常的に
#   赤くなる (「+$1 誤差」に見えていた正体はこれ)。参照値更新では直らない。FX を pin して決定化する。
REFERENCE_FX_USD = 159.245


@pytest.fixture(autouse=True)
def _pin_fx():
    """profit_params の実効 exchange_rate を REFERENCE_FX_USD に固定 (テスト決定化)。

    他パラメータ (fvf / 送料 / 手数料 / カテゴリ) は実値のまま、FX だけ差し替える。
    """
    # 本元 iMakeBayAPI を path に確保 (fixture 順序で未追加でも動くように)。
    _api = r"C:/dev/iMak/iMakeBayAPI"
    if _api not in sys.path:
        sys.path.insert(0, _api)
    try:
        import profit_params as pp
    except ImportError:
        pytest.skip("profit_params import 不可")

    real = dict(pp._load())  # 実パラメータ取得 (categories / fees 等)
    for k in ("exchange_rate", "exchange_rate_eur", "exchange_rate_gbp", "exchange_rate_aud"):
        real.pop(k, None)
    real["exchange_rate"] = REFERENCE_FX_USD
    saved = pp._cache
    pp._cache = real
    try:
        yield
    finally:
        pp._cache = saved


@pytest.fixture(scope="module")
def v8_fn():
    try:
        return _import_v8_pricing()
    except ImportError as e:
        pytest.skip(f"V8 pricing_engine import 不可: {e}")


@pytest.mark.parametrize("case", REFERENCE_CASES, ids=[c["item_id"] for c in REFERENCE_CASES])
def test_v7_reference_match(v8_fn, case):
    """V8 sheet の reference 数値と完全一致確認."""
    c = ReviseCandidate(
        row_index=2, item_id=case["item_id"], category=case["category"],
        new_jpy=case["cost_jpy"], ah_jpy=None, f_jpy=None,
        delta_pct=10.0, basis="F", title=case["title"],
    )
    compute_new_usd(c, v8_fn)
    assert c.skip_reason is None, f"V8 計算失敗: {c.skip_reason}"
    assert c.new_usd == case["expected_price"], (
        f"{case['item_id']} 新USD 不一致: got {c.new_usd}, expected {case['expected_price']}"
    )
    assert c.shipping_usd == case["expected_shipping"], (
        f"{case['item_id']} 送料USD 不一致: got {c.shipping_usd}, expected {case['expected_shipping']}"
    )
    assert c.profit_jpy is not None and c.profit_jpy >= 0, (
        f"{case['item_id']} 赤字検出: 利益¥{c.profit_jpy}"
    )


def test_normalize_category():
    """R 列略称 → V8 yaml 正式名."""
    assert normalize_category("Tシャツ") == "Tシャツ(UT)"
    assert normalize_category("G-shock") == "G-SHOCK"
    assert normalize_category("フィギュア") == "フィギュア"
    assert normalize_category("カプセルトイ") == "ガシャポン"
    assert normalize_category("アウトドア・ジャケット") == "Montbell(重)"
    assert normalize_category("") == ""


def test_normalize_category_2026_05_23_additions():
    """2026-05-23 追加分 (= v7_calc_failed 87件 解消)."""
    # グッズ → サンリオぬいぐるみ (= サンリオキーホルダー想定)
    assert normalize_category("グッズ") == "サンリオぬいぐるみ"
    # 文具 → サンリオ文具 (= 三菱ジェット 等)
    assert normalize_category("文具") == "サンリオ文具"
    # スニーカー / ゴルフ (= yaml 新規 category 追加済、同名で normalize)
    assert normalize_category("スニーカー") == "スニーカー"
    assert normalize_category("ゴルフ") == "ゴルフ"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
