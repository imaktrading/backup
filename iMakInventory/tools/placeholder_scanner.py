"""placeholder_scanner - HIGH sheet で 11111/22222 等の placeholder 値が
残置されてる listing を抽出する診断 tool.

背景:
  2026-05-25 358589046154 で col14 仕入価格 = 22222、 col6 商品価格 = 11111 の
  反復数値 placeholder が検出。 これは出品 script 作成時の dummy 値で、 実値に
  置換漏れの listing が他にもある可能性。 全 active で grep して HQ に list 提供。

判定:
  - 反復 placeholder: 11111 / 22222 / 33333 / 44444 / 55555 / 66666 / 77777 /
    88888 / 99999 / 1111 / 2222 / etc. (= 1 桁 N 個繰返し、 length 3 以上)
  - 0 値
  - 空欄

実行:
  python -m tools.placeholder_scanner [--sheet HIGH|LOW]
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from sheet_updater import HIGH_SHEET_ID, LOW_SHEET_ID, open_sheet_by_id  # noqa: E402

OUTPUT_DIR = SCRIPT_DIR / "tools" / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 反復 placeholder regex: 1 文字が 3 回以上繰返す
# 例 OK: 11111, 22222, 1111, 999. NG: 12345, 11122
PLACEHOLDER_RE = re.compile(r"^(\d)\1{2,}$")


def _classify(val: str) -> str:
    """val の異常分類を返す. 正常なら空文字."""
    s = (val or "").strip()
    if not s:
        return "empty"
    if s == "0":
        return "zero"
    if PLACEHOLDER_RE.match(s):
        return f"placeholder_repeat({s})"
    return ""


def scan_sheet(sheet_id: str, sheet_label: str) -> list:
    """sheet を読み込んで anomaly あり行を抽出."""
    sh = open_sheet_by_id(sheet_id)
    ws = sh.worksheets()[0]
    all_vals = ws.get_all_values()
    if len(all_vals) < 2:
        return []

    header = all_vals[0]
    # 列 index 検出
    def _col_idx(name: str) -> int | None:
        for i, h in enumerate(header):
            if name in h:
                return i
        return None

    col_url = _col_idx("URL") or 0
    col_iid = _col_idx("itemID")
    col_title = _col_idx("タイトル") or _col_idx("Title")
    col_status = _col_idx("状態")
    col_price = _col_idx("商品価格")
    col_cost = _col_idx("仕入れ価格")

    out = []
    for i, row in enumerate(all_vals[1:], 2):
        # padding
        r = list(row) + [""] * max(0, len(header) - len(row))
        price_val = r[col_price] if col_price is not None else ""
        cost_val = r[col_cost] if col_cost is not None else ""

        price_flag = _classify(price_val)
        cost_flag = _classify(cost_val)
        if not price_flag and not cost_flag:
            continue

        out.append({
            "sheet": sheet_label,
            "row_index": i,
            "item_id": r[col_iid] if col_iid is not None else "",
            "title": (r[col_title] if col_title is not None else "")[:50],
            "status": r[col_status] if col_status is not None else "",
            "url": r[col_url],
            "col6_商品価格": price_val,
            "col14_仕入価格": cost_val,
            "price_flag": price_flag,
            "cost_flag": cost_flag,
        })
    return out


def main():
    parser = argparse.ArgumentParser(
        description="HIGH/LOW sheet の placeholder 残置 listing を抽出")
    parser.add_argument("--sheet", choices=["high", "low", "both"], default="high",
                        help="対象 sheet (default: high)")
    args = parser.parse_args()

    targets = []
    if args.sheet in ("high", "both"):
        targets.append((HIGH_SHEET_ID, "HIGH"))
    if args.sheet in ("low", "both"):
        targets.append((LOW_SHEET_ID, "LOW"))

    all_hits = []
    for sid, label in targets:
        print(f"[scan] {label} (sheet_id={sid[:24]}...)")
        hits = scan_sheet(sid, label)
        print(f"  → {len(hits)} 件 anomaly")
        all_hits.extend(hits)

    if not all_hits:
        print("anomaly なし、 CSV 出力 skip")
        return

    # CSV 出力
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = OUTPUT_DIR / f"placeholder_listings_{ts}.csv"
    fields = ["sheet", "row_index", "item_id", "title", "status", "url",
              "col6_商品価格", "col14_仕入価格", "price_flag", "cost_flag"]
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, quoting=csv.QUOTE_NONNUMERIC)
        w.writeheader()
        for h in all_hits:
            w.writerow(h)
    print(f"\n[OK] CSV: {out_path}")
    print(f"  全 anomaly: {len(all_hits)} 件")

    # 内訳統計
    from collections import Counter
    price_flags = Counter(h["price_flag"] for h in all_hits if h["price_flag"])
    cost_flags = Counter(h["cost_flag"] for h in all_hits if h["cost_flag"])
    print(f"\n--- 商品価格 anomaly 内訳 ---")
    for k, v in price_flags.most_common():
        print(f"  {k}: {v}")
    print(f"\n--- 仕入価格 anomaly 内訳 ---")
    for k, v in cost_flags.most_common():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
