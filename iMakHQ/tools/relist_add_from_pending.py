#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""取下再出品② Add生成オーケストレータ — 保留リスト→カテゴリ振り分け→各--relist実行。

①(relist_from_funnel)が出した最新 relist_pending_*.csv を読み、カテゴリごとに対応する
listing script の --relist モードを呼ぶ。各scriptは pending を自分のカテゴリ分だけに
自己フィルタするので、同じ pending を渡すだけでよい。出力: 各カテゴリの Add CSV +
relist_skumap_<stamp>.csv (③書戻しが参照)。

出品くんパネル「取下再出品② Add生成」ボタンの実体。eBayへの Add CSV アップは手動。
"""
import collections
import csv
import glob
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_TOOLS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_TOOLS, "..", ".."))   # C:/dev/iMak
REVISE_DIR = r"c:\dev\iMak_data\revise"

# pending の category(=商品管理シート col17 の正本カテゴリ) → (cwd, cmd[])。
# 各 listing script は pending を自カテゴリ分に自己フィルタ (col17 + supply_url) するので、
# 同じ pending を渡すだけでよい。キーは funnel の eBay カテゴリでなく col17 (2026-06-23 ASIN/
# col17 統一。funnel カテゴリは混在して信頼できない: 例 "Other Animation Merchandise"=グッズ+一番くじ)。
CATEGORY_DISPATCH = {
    "G-shock":  (os.path.join(_ROOT, "iMakG-shock"),
                 ["python", "gshock_to_csv.py", "--relist", "{pending}"]),
    "リール":    (os.path.join(_ROOT, "iMakMercari"),
                 ["python", "mercari_to_ebay_csv.py", "--sheet", "reel", "--relist", "{pending}"]),
    "一番くじ":   (os.path.join(_ROOT, "iMakMercari"),
                 ["python", "mercari_to_ebay_csv.py", "--sheet", "ichibankuji", "--relist", "{pending}"]),
    "バッグ":    (os.path.join(_ROOT, "iMakMercari"),
                 ["python", "mercari_to_ebay_csv.py", "--sheet", "porter", "--relist", "{pending}"]),
    "tomica":   (os.path.join(_ROOT, "iMakMercari"),
                 ["python", "mercari_to_ebay_csv.py", "--sheet", "tomica", "--relist", "{pending}"]),
}


def latest_pending():
    cands = sorted(glob.glob(os.path.join(REVISE_DIR, "relist_pending_*.csv")))
    return cands[-1] if cands else None


def categories_in(pending):
    with open(pending, "r", encoding="utf-8-sig", newline="") as f:
        return collections.Counter((r.get("category") or "").strip() for r in csv.DictReader(f))


def run_category(cwd, cmd, pending):
    real = [a.replace("{pending}", pending) for a in cmd]
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    print(f"\n{'='*60}\n▶ {os.path.basename(cwd)}: {' '.join(real)}\n{'='*60}", flush=True)
    r = subprocess.run(real, cwd=cwd, env=env)
    return r.returncode


def main():
    pending = latest_pending()
    if not pending:
        sys.exit("relist_pending_*.csv がありません。先に①『取下再出品』ボタンを実行してください。")
    print(f"📂 保留リスト: {os.path.basename(pending)}")
    cats = categories_in(pending)
    print(f"   カテゴリ内訳: {dict(cats)}")

    ran, skipped = [], []
    for cat, cnt in cats.items():
        if cat in CATEGORY_DISPATCH:
            cwd, cmd = CATEGORY_DISPATCH[cat]
            rc = run_category(cwd, cmd, pending)
            ran.append((cat, cnt, rc))
        else:
            skipped.append((cat, cnt))

    print(f"\n{'='*60}\n② Add生成 サマリー\n{'='*60}")
    for cat, cnt, rc in ran:
        print(f"  ✅ {cat} ({cnt}件) → exit {rc}")
    for cat, cnt in skipped:
        print(f"  ⚠️ {cat} ({cnt}件) → --relist 未対応カテゴリ (スキップ)。listing script 側の対応が必要")

    skufiles = sorted(glob.glob(os.path.join(REVISE_DIR, "relist_skumap_*.csv")))
    addfiles = sorted(glob.glob(os.path.join(_ROOT, "iMakHQ", "csv_output", "*_upload_*.csv")),
                      key=os.path.getmtime)[-5:]
    print(f"\n  skumap: {os.path.basename(skufiles[-1]) if skufiles else '(無)'}")
    print("  生成 Add CSV (直近):")
    for a in addfiles:
        print(f"    {a}")
    print("\n▶ 次: 上の Add CSV を eBay FileExchange にアップ → 結果レポートDL → ③書戻しボタン")


if __name__ == "__main__":
    main()
