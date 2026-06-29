#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PSA TCG 既存 active listing の Item Specific "Age Level" 削除 Revise CSV 生成。

依頼: 2026-06-29_psa_age_level_remove.md ① (CPSC eFiling 7/8 対応)。
PSA鑑定品=非児童製品。"Age Level=6+" が児童製品扱い→通関リスク → 全 active から削除。

方式: eBay File Exchange Revise + DeletedField 列に "C:Age Level"
  (C: プレフィックス=Item Specific。複数削除は pipe 区切り。公式 File Exchange 仕様)

対象: active listing report の Title に "PSA 10" or "PSA 9" を含む行 (= PSA TCG)。
  ※ report に Category 列が無いため Title で判定 (依頼指定のフィルタ)。

安全運用 (依頼の安全策):
  1. まず --test (在庫あり1件) で Revise CSV → 人が入稿 → GetItem で Age Level 消失確認
  2. 確認できたら --all で全件 CSV → 入稿
  fail-closed: itemID/Title が取れない行は除外 (推測しない)。

入力 : 最新 eBay-all-active-listings-report-*.csv (REPORT_DIR)
出力 : デスクトップ psa_age_level_delete_{TEST|ALL}_YYYYMMDD.csv
"""
import csv
import datetime
import glob
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPORT_DIR = r"C:\Users\imax2\local_data\iMakInventory\ebay_active_listing_dl"
DESK = r"C:\Users\imax2\OneDrive\デスクトップ"

# Revise: ItemID 指定 + DeletedField で Item Specific 削除
HEADER = ["*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)", "ItemID", "DeletedField"]
DELETED_FIELD = "C:Age Level"

_PSA_RE = re.compile(r"\bPSA\s?(10|9)\b", re.IGNORECASE)


def is_psa(title):
    return bool(_PSA_RE.search(title or ""))


def latest_report():
    fs = glob.glob(os.path.join(REPORT_DIR, "eBay-all-active-listings-report-*.csv"))
    return max(fs, key=os.path.getmtime) if fs else None


def select_targets(rows, test=False):
    """report rows → [(item_id, title, qty)]。PSA10/9 のみ。fail-closed (itemID欠落除外)。

    test=True は 在庫あり(qty>0)の先頭1件のみ (GetItem検証を生きた listing で行うため)。
    """
    out = []
    for r in rows:
        iid = (r.get("Item number") or "").strip()
        title = (r.get("Title") or "").strip()
        if not iid or not title:
            continue          # fail-closed: 識別不能は除外
        if not is_psa(title):
            continue
        qty = (r.get("Available quantity") or "0").strip()
        out.append((iid, title, qty))
    if test:
        instock = [t for t in out if t[2] not in ("0", "")]
        return instock[:1] or out[:1]
    return out


def write_csv(targets, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        w.writerow(HEADER)
        for iid, _title, _qty in targets:
            w.writerow(["Revise", iid, DELETED_FIELD])


def main():
    test = "--test" in sys.argv
    do_all = "--all" in sys.argv
    if not test and not do_all:
        sys.exit("使い方: python psa_age_level_delete_csv.py --test   (在庫あり1件で試験)\n"
                 "        python psa_age_level_delete_csv.py --all    (全PSA10/9件)")

    src = latest_report()
    if not src:
        sys.exit(f"active listing report が無い: {REPORT_DIR}")
    rows = list(csv.DictReader(open(src, encoding="utf-8-sig", errors="replace")))
    all_psa = select_targets(rows, test=False)
    targets = select_targets(rows, test=test)

    stamp = datetime.date.today().strftime("%Y%m%d")
    tag = "TEST" if test else "ALL"
    out = os.path.join(DESK, f"psa_age_level_delete_{tag}_{stamp}.csv")
    write_csv(targets, out)

    print(f"元 report: {os.path.basename(src)}")
    print(f"PSA10/9 active 総数 = {len(all_psa)}件")
    print(f"今回出力 ({tag}) = {len(targets)}件 → {out}")
    print(f"DeletedField = '{DELETED_FIELD}' (Revise で Item Specific 削除)")
    if test:
        print("\n▶ この1件を File Exchange に入稿 → GetItem で Age Level が消えたか確認")
        print("  確認できたら: python psa_age_level_delete_csv.py --all")
        for iid, title, _q in targets:
            print(f"  試験対象: {iid}  {title[:60]}")
    else:
        print("\n▶ File Exchange に入稿 → 完了後 GetItem 3件サンプルで削除確認")


if __name__ == "__main__":
    main()
