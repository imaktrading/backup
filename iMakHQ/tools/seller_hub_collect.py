#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「ダウンロード」フォルダに落ちた Seller Hub のレポートを、ファネルの置き場へ移す (2026-09-26)。

拡張 (tools/sellerhub_grab) が落とした5本は ダウンロード フォルダに入る。
ファネル (listing_funnel.py) は C:\\dev\\iMak_data\\seller_hub\\reports\\**\\ を探すので、
今日の日付のフォルダに移す。夜間バッチでファネルの前に走らせる。何度走らせても同じ (冪等)。

    python seller_hub_collect.py          # 移す
    python seller_hub_collect.py --dry    # 何を移すかだけ見る
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import shutil
import sys
from datetime import date

DOWNLOADS = os.path.join(os.path.expanduser("~"), "Downloads")
REPORT_DIR = r"C:\dev\iMak_data\seller_hub\reports"
# listing_funnel.py が探す名前と同じ形 (あちらを変えたらここも)
PATTERNS = ("*all-active-listings*.csv", "*inactive-listings*.csv", "*unsold-listings*.csv",
            "*orders-report*.csv", "*promoted-listing*report*.csv", "Listing quality report*.xlsx")


def is_report(name):
    """ファネルの材料になる Seller Hub レポートの名前か。純関数。"""
    n = name.lower()
    if n.endswith((".crdownload", ".tmp", ".partial")):
        return False                       # まだ落としている途中
    return any(fnmatch.fnmatch(n, p.lower()) for p in PATTERNS)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                             # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--src", default=DOWNLOADS)
    a = ap.parse_args()

    dest = os.path.join(REPORT_DIR, date.today().strftime("%Y%m%d"))
    names = sorted(n for n in os.listdir(a.src) if is_report(n)) if os.path.isdir(a.src) else []
    if not names:
        print("Seller Hub レポート: ダウンロード フォルダに新しい物はありません")
        return 0
    if not a.dry:
        os.makedirs(dest, exist_ok=True)
    for n in names:
        print(("(dry) " if a.dry else "") + "移す: %s → %s" % (n, dest))
        if not a.dry:
            shutil.move(os.path.join(a.src, n), os.path.join(dest, n))
    print("Seller Hub レポート: %d本" % len(names))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
