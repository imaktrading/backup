#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手動 whitelist (whitelist_registry) vs eBay公式フィルタ(取得済JSON) 差分チェッカー (2026-06-08)。

持ち腐れ対策: 生成時の Item Specifics 正規化に使う whitelist_registry の値は手動抽出(2026-04-23)で、
取得済の公式 Aspects JSON と連動していない → ドリフトすると「正規化したのに eBay フィルタに無い値」になる。
本ツールは両者を照合し、**手動値が公式 SELECTION_ONLY 許容リストに無い**(=フィルタ不ヒット)を検出する。

read-only (生成ロジックは一切変更しない)。exit 1=ドリフトあり。
"""
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "..", "iMakeBayAPI"))
INPUT = r"C:/dev/iMak_data/catalog/_input"

# whitelist_registry のカテゴリ → 公式 Aspects JSON (対応が取れる分のみ)
WL_TO_OFFICIAL = {
    "porter": "ebay_porter_filter_lists_api.json",
    "ichibankuji": "ebay_ichibankuji_filter_lists_api.json",
    "reel": "ebay_fishingreel_filter_lists_api.json",
}
# eBay 普遍の特殊値 (values配列に無いが許容)
_SPECIAL_OK = {"does not apply", "does not apply.", "n/a", "na", "", "unbranded", "no", "none", "yes"}


def _official_aspects(fname):
    path = os.path.join(INPUT, fname)
    if not os.path.exists(path):
        return None
    try:
        return json.load(open(path, encoding="utf-8")).get("aspects", {})
    except Exception:
        return None


def check_drift(whitelists):
    """whitelists={category:{aspect:{values,...}}} を公式と照合。
    返り: [(category, aspect, kind, detail)]。kind: STALE_VALUE / SELECTION_ONLY_MISS。"""
    drift = []
    for cat, fname in WL_TO_OFFICIAL.items():
        wl = whitelists.get(cat)
        asp = _official_aspects(fname)
        if not wl or not asp:
            continue
        for aspect, spec in wl.items():
            off = asp.get(aspect)
            if not off:
                continue
            mode = off.get("constraint", {}).get("aspect_mode")
            off_vals = set(off.get("values", []))
            if mode != "SELECTION_ONLY" or not off_vals:
                continue  # FREE_TEXT は自由値OK = 照合不要
            for v in spec.get("values", []):
                if v and v.lower() not in _SPECIAL_OK and v not in off_vals:
                    drift.append((cat, aspect, "STALE_VALUE",
                                  f"手動値 '{v}' が公式SELECTION_ONLY許容外 → eBayフィルタ不ヒット"))
    return drift


def main():
    try:
        from whitelist_registry import WHITELISTS
    except Exception as e:
        print(f"❌ whitelist_registry 読込失敗: {e}")
        return 2
    drift = check_drift(WHITELISTS)
    print(f"=== 手動whitelist vs 公式フィルタ ドリフト検査 ({len(WL_TO_OFFICIAL)}カテゴリ) ===")
    if not drift:
        print("✅ ドリフト無し (手動whitelist の SELECTION_ONLY 値は全て公式許容内)")
        return 0
    print(f"⚠️ ドリフト {len(drift)}件:")
    for cat, aspect, kind, detail in drift:
        print(f"  [{cat}] {aspect}: {detail}")
    print("\n→ 手動whitelist_registry の該当値を公式値へ修正 (or normalize マップ追加) してください。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
