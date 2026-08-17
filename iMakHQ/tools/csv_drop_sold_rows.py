#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""csv_drop_sold_rows.py — 入稿CSVから「仕入元が売り切れた行」を落とす。

人がやっていた手順の自動化 (2026-08-17 ユーザー整理):
    CSVをUP → **HIGHT で売り切れていないか確認 → 売り切れていたら出品しない(行を削除)**
    → プロモ8% → 入稿 → itemID 書込

売り切れた現物を出品すると仕入れられず、キャンセル = eBay の Defect Rate に直結する
(= 永久BAN リスク)。だから「出さない」側に倒すのが正しい。

在庫の根拠は **シートの売り切れ欄 (D列)** = 監視くんが巡回で付けた値。
メルカリの商品ページは JS で描くので HQ 側の素の取得では判定できない
(実測 2026-08-17: 売り切れた商品と売れていない商品の両方でページに「売り切れ」が4回出る)。
ブラウザを動かす在庫判定は監視くんの担当なので、ここでは**その結果を使うだけ**にする。
巡回が古い行は「古い」と警告に出す (黙って通さない)。入稿直前の即時判定は監視くんに別途依頼。

実行:
    python csv_drop_sold_rows.py <csv>            # dry-run (何を落とすか出すだけ)
    python csv_drop_sold_rows.py <csv> --write    # 実際に落とす (.bak を残す)
"""
import csv
import datetime
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sheet_io  # noqa: E402

A, B, D, I, O = 0, 1, 3, 8, 14      # A URL / B itemID / D 売り切れ / I cert / O 巡回時刻
STALE_DAYS = 3                       # これより古い巡回は「古い」と警告 (落とさない)


def _cell(row, idx):
    return (row[idx].strip() if len(row) > idx else "")


def cert_from_label(label):
    """CustomLabel から PSA cert を取り出す (純関数)。PSA以外は None。"""
    m = re.match(r"^PSA10-(\d+)$", (label or "").strip())
    return m.group(1) if m else None


def supply_index(rows2d):
    """シート → {cert or SKU: {"sold": bool, "checked": str, "url": str, "row": int}} (純関数)。

    メルカリ由来の行は CustomLabel が URL 末尾 (`m21409027696`) なので、cert と URL 末尾の
    両方を鍵にする。
    """
    idx = {}
    for i, r in enumerate(rows2d[1:], start=2):
        url, cert = _cell(r, A), _cell(r, I)
        info = {"sold": bool(_cell(r, D)), "checked": _cell(r, O), "url": url, "row": i}
        if cert:
            idx.setdefault(cert, info)
        m = re.search(r"/(?:item/|shops/product/)(\w+)", url)
        if m:
            idx.setdefault(m.group(1), info)
    return idx


def _is_stale(checked, today, days=STALE_DAYS):
    """巡回時刻が古いか (純関数)。読めない/空は「古い」扱い = 警告に出す。"""
    m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", checked or "")
    if not m:
        return True
    d = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return (today - d).days > days


def plan(csv_rows, header, index, today):
    """(pure) CSV行 → (残す行, 落とす[(label,url)], 古い[(label,日付)], 照合不能[label])。"""
    try:
        li = header.index("CustomLabel")
    except ValueError:
        return csv_rows, [], [], []
    keep, dropped, stale, unknown = [], [], [], []
    for row in csv_rows:
        label = row[li].strip() if li < len(row) else ""
        info = index.get(cert_from_label(label) or "") or index.get(label)
        if info is None:
            unknown.append(label)
            keep.append(row)
            continue
        if info["sold"]:
            dropped.append((label, info["url"]))
            continue
        if _is_stale(info["checked"], today):
            stale.append((label, info["checked"] or "(記録なし)"))
        keep.append(row)
    return keep, dropped, stale, unknown


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    do_write = "--write" in sys.argv
    if not args:
        print("使い方: python csv_drop_sold_rows.py <csv> [--write]")
        return 2
    path = args[0]
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        print("CSV が空 → 何もしない")
        return 0
    header, body = rows[0], rows[1:]

    index = supply_index(sheet_io._product_ws().get_all_values())
    keep, dropped, stale, unknown = plan(body, header, index, datetime.date.today())

    print(f"=== 売り切れ行の除外 [{'実書込' if do_write else 'dry-run'}] {os.path.basename(path)} ===")
    print(f"  対象 {len(body)}行 → 残す {len(keep)} / 落とす {len(dropped)}")
    for label, url in dropped:
        print(f"  🚫 {label} 仕入元が売り切れ → 出品しない  {url}")
    for label, checked in stale:
        print(f"  ⚠️ {label} 在庫の確認が古い ({checked}) → 出すが注意")
    for label in unknown:
        print(f"  ⚠️ {label} シートに該当行が無く在庫を照合できない → 出す (fail-open を明示)")
    if not dropped:
        print("  ✅ 売り切れは0件")

    if do_write and dropped:
        shutil.copy(path, path + ".bak_sold_drop")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
            w.writerow(header)
            w.writerows(keep)
        print(f"  ✏️ {len(dropped)}行を除外 / backup: {os.path.basename(path)}.bak_sold_drop")
    return 0


if __name__ == "__main__":
    sys.exit(main())
