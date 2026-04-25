#!/usr/bin/env python3
"""価格決定エンジン（全プロジェクト共通SSOT）

設計思想:
  価格 = コストプラス（仕入 + 送料 + 手数料 + 価格帯別利益率上限）
  乖離 ≤ 価格帯別乖離率上限 → 出品OK
  乖離 > 価格帯別乖離率上限 → 見送りアラート

参照SSOT:
  - 利益計算シートv2.xlsx: 為替/手数料/プロモ/Payo（profit_params.py 経由）
  - GATE判定パラメータ検討.xlsx: 価格帯別 利益率上限 / 乖離率上限

使い方:
  from pricing_engine import compute_listing_price
  result = compute_listing_price(cost_jpy=1500, median_usd=25, category="Tシャツ(UT)")
  result["price"]      → 出品価格
  result["status"]     → "GO" / "ALERT" / "NO_MEDIAN"
  result["alert_msg"]  → アラート時の人間向けメッセージ
"""
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# profit_params 経由で利益計算シートv2を参照
sys.path.insert(0, SCRIPT_DIR)
from profit_params import _load as _profit_load, get_category_params, INTL_FEE

# GATE.xlsx パス
GATE_XLSX_PATH = os.path.join(SCRIPT_DIR, "..", "iMakHQ", "sheets", "GATE判定パラメータ検討.xlsx")

# フォールバック値（GATE.xlsx読込失敗時）
_TIER_FALLBACK = [
    (39, 0.25, 0.50), (60, 0.25, 0.50), (100, 0.20, 0.50), (200, 0.15, 0.50),
    (300, 0.15, 0.40), (400, 0.10, 0.25), (500, 0.10, 0.20), (600, 0.10, 0.15),
    (800, 0.10, 0.10), (9999, 0.10, 0.10),
]


def _load_tier_params():
    try:
        import openpyxl
        wb = openpyxl.load_workbook(GATE_XLSX_PATH, read_only=True, data_only=True)
        if "確定値" not in wb.sheetnames:
            return _TIER_FALLBACK
        ws = wb["確定値"]
        out = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or row[0] is None:
                continue
            try:
                out.append((float(row[0]), float(row[1]), float(row[2])))
            except (TypeError, ValueError):
                continue
        return sorted(out, key=lambda x: x[0]) if out else _TIER_FALLBACK
    except Exception:
        return _TIER_FALLBACK


TIER_PARAMS = _load_tier_params()


def get_tier_params(price_usd):
    """価格(USD)から(profit_target, gap_limit)を取得。"""
    for threshold, profit_target, gap_limit in TIER_PARAMS:
        if price_usd <= threshold:
            return profit_target, gap_limit
    return 0.10, 0.10


def _compute_target_usd(cost_jpy, category, profit_target):
    """コストプラスで最低出品価格を計算。"""
    cache = _profit_load()
    params = get_category_params(category)
    if params is None:
        raise ValueError(f"Unknown category: {category}")
    net_ratio = 1 - params["fvf"] - INTL_FEE - cache["ad_rate"] - cache["payo_fee"] - profit_target
    if net_ratio <= 0:
        raise ValueError(f"net_ratio<=0 (profit_target {profit_target} too high)")
    return (cost_jpy + params["shipping_jpy"]) / (cache["exchange_rate"] * net_ratio)


def _round_98(price_usd):
    """$X.98 形式に丸め。$10以下はそのまま round。"""
    p = round(price_usd, 2)
    if p > 10:
        return int(p) + 0.98
    return p


def compute_listing_price(cost_jpy, median_usd, category):
    """出品価格を決定する（全プロジェクト共通SSOT）。

    Args:
      cost_jpy: 仕入価格（円）
      median_usd: eBay市場中央値（USD）。0 or None なら中央値なしモード
      category: 利益計算v2のカテゴリ名（例: "Tシャツ(UT)"）

    Returns:
      dict {
        price:          確定出品価格（USD, $X.98丸め済）
        target_usd:     コストプラス計算結果（丸め前）
        profit_target:  適用された利益率
        profit_jpy:     見込利益（JPY）
        gap_pct:        中央値との乖離率（%）None=中央値なし
        gap_limit_pct:  当該ティアの乖離率上限（%）
        status:         "GO" / "ALERT" / "NO_MEDIAN"
        alert_msg:      見送り推奨時の説明文（statusがALERTの時のみ）
      }
    """
    # 1. 価格決定: 価格自身からティア確定（イテレーション）
    #    まず最高利益率(25%)で仮計算 → 結果のティアで再計算 → 収束
    profit_target, _ = get_tier_params(0)  # 0なら最小ティア(最高利益率)
    for _ in range(5):  # 最大5回反復で収束
        target_usd = _compute_target_usd(cost_jpy, category, profit_target)
        new_profit, _ = get_tier_params(target_usd)
        if abs(new_profit - profit_target) < 0.001:
            break
        profit_target = new_profit
    target_usd = _compute_target_usd(cost_jpy, category, profit_target)
    price = _round_98(target_usd)

    # 利益計算
    cache = _profit_load()
    params = get_category_params(category)
    revenue_jpy = price * cache["exchange_rate"]
    profit_jpy = revenue_jpy * (1 - params["fvf"] - INTL_FEE - cache["ad_rate"] - cache["payo_fee"]) - (cost_jpy + params["shipping_jpy"])

    # 2. 中央値による乖離判定
    if not median_usd or median_usd <= 0:
        return {
            "price": price,
            "target_usd": target_usd,
            "profit_target": profit_target,
            "profit_jpy": profit_jpy,
            "gap_pct": None,
            "gap_limit_pct": None,
            "status": "NO_MEDIAN",
            "alert_msg": None,
        }

    _, gap_limit = get_tier_params(price)
    gap_pct = (target_usd - median_usd) / median_usd * 100
    gap_limit_pct = gap_limit * 100

    if gap_pct <= gap_limit_pct:
        status = "GO"
        alert_msg = None
    else:
        status = "ALERT"
        alert_msg = (
            f"乖離率超過: 当社${price:.2f} vs 中央値${median_usd:.2f} = +{gap_pct:.0f}% "
            f"(上限+{gap_limit_pct:.0f}%) → 見送り推奨"
        )

    return {
        "price": price,
        "target_usd": target_usd,
        "profit_target": profit_target,
        "profit_jpy": profit_jpy,
        "gap_pct": gap_pct,
        "gap_limit_pct": gap_limit_pct,
        "status": status,
        "alert_msg": alert_msg,
    }


if __name__ == "__main__":
    # 自己テスト
    cases = [
        (1500, 25, "Tシャツ(UT)", "Tシャツ低価格（GO想定）"),
        (1500, 10, "Tシャツ(UT)", "Tシャツ低価格・市場安すぎ（ALERT想定）"),
        (50000, 800, "TCG(PSA10)", "TCG高額（GO想定）"),
        (1500, 0, "Tシャツ(UT)", "中央値なし（NO_MEDIAN）"),
    ]
    for cost, median, cat, label in cases:
        r = compute_listing_price(cost, median, cat)
        print(f"\n=== {label} ===")
        print(f"  cost ¥{cost} median ${median} cat={cat}")
        print(f"  → 価格 ${r['price']} 利益¥{r['profit_jpy']:.0f} 利益率{r['profit_target']*100:.0f}% status={r['status']}")
        if r['alert_msg']:
            print(f"  ALERT: {r['alert_msg']}")
