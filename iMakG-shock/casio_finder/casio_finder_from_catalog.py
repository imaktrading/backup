#!/usr/bin/env python3
"""iMak Trading Japan - CASIO 未出品モデル発見 (iMakCatalog 版).

旧 casio_finder.py は CASIO 公式サイトを直接スクレイプするが、bot 検出 / 429
で実用性が低い。本スクリプトは iMakCatalog (公式 DB 集約済) の G-shock export
CSV と eBay active_listings.csv を突き合わせて未出品モデルを抽出する。

入力:
  1. iMakCatalog G-shock export: c:/dev/iMak_data/catalog/exports/gshock_*.csv
     最新ファイル自動選択 (または --catalog で path 指定)
  2. eBay active 出品中 CSV: casio_finder/active_listings.csv
     Seller Hub からダウンロードして配置

出力:
  unlisted_from_catalog_YYYYMMDD_HHMMSS.csv
  カラム: product_id, name_en, price_jpy_msrp, year, is_limited, source_url

使い方:
  python casio_finder_from_catalog.py
  python casio_finder_from_catalog.py --catalog path/to/gshock_xxx.csv
"""
from __future__ import annotations

import argparse
import csv
import glob
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# ===== 設定 =====
DEFAULT_CATALOG_DIR = r"c:\dev\iMak_data\catalog\exports"
EBAY_CSV = "active_listings.csv"
OUTPUT_PREFIX = "unlisted_from_catalog"

# eBay Title から CASIO 型番抽出 (例: AWG-M100FP-1A1JR / DW-6900UMS-1 / GA-2100-1A1)
MODEL_RE = re.compile(r"[A-Z]{2,4}-[A-Z0-9]{2,}(?:-[A-Z0-9]+)*")
SUFFIX_STRIP_RE = re.compile(r"(JF|JR)$")


def find_latest_catalog(catalog_dir: str) -> str | None:
    candidates = sorted(glob.glob(os.path.join(catalog_dir, "gshock_*.csv")))
    if not candidates:
        return None
    return candidates[-1]


def load_catalog_models(catalog_path: str) -> list[dict]:
    """iMakCatalog export CSV から G-shock モデル全件を読み込む."""
    rows = []
    with open(catalog_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            pid = (r.get("product_id") or "").strip()
            if pid:
                rows.append(r)
    return rows


def load_active_models(active_csv_path: str) -> set[str]:
    """eBay 出品中 CSV の Title から CASIO 型番を抽出 (JF/JR 末尾も付き/なし両形で登録)."""
    active = set()
    if not os.path.exists(active_csv_path):
        return active
    with open(active_csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            title = row.get("Title", "") or ""
            for m in MODEL_RE.findall(title):
                active.add(m)
                active.add(SUFFIX_STRIP_RE.sub("", m))
    return active


def find_unlisted(catalog_rows: list[dict], active_models: set[str]) -> list[dict]:
    """catalog 全モデルから active に無いもの (未出品) を抽出."""
    unlisted = []
    for r in catalog_rows:
        pid = r["product_id"].strip()
        pid_no_suffix = SUFFIX_STRIP_RE.sub("", pid)
        # JF/JR 込み or なしのどちらでも active に居たら出品済扱い
        if pid in active_models or pid_no_suffix in active_models:
            continue
        unlisted.append(r)
    return unlisted


def write_output(unlisted: list[dict], out_path: str) -> None:
    fields = ["product_id", "name_en", "price_jpy_msrp", "year", "is_limited", "source_url"]
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in unlisted:
            w.writerow({k: r.get(k, "") for k in fields})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", help="iMakCatalog G-shock export CSV パス (省略時は最新自動選択)")
    parser.add_argument("--active", default=EBAY_CSV, help="eBay active CSV path (default: active_listings.csv)")
    args = parser.parse_args()

    print("=== iMak Trading Japan - CASIO 未出品モデル発見 (iMakCatalog 版) ===\n")

    # 1. catalog 読込
    catalog_path = args.catalog or find_latest_catalog(DEFAULT_CATALOG_DIR)
    if not catalog_path or not os.path.exists(catalog_path):
        print(f"❌ iMakCatalog export が見つかりません: {catalog_path}")
        print(f"   ディレクトリ: {DEFAULT_CATALOG_DIR}")
        print("   → Catalog Claude に最新 export 依頼してください")
        return 1
    print(f"📂 catalog: {os.path.basename(catalog_path)}")
    catalog_rows = load_catalog_models(catalog_path)
    print(f"   公式モデル数: {len(catalog_rows)} 件")

    # 2. active 読込
    script_dir = os.path.dirname(os.path.abspath(__file__))
    active_path = args.active if os.path.isabs(args.active) else os.path.join(script_dir, args.active)
    if not os.path.exists(active_path):
        print(f"❌ active_listings.csv が見つかりません: {active_path}")
        print("   → eBay Seller Hub > Listings > Active から CSV ダウンロード、本フォルダに配置")
        return 1
    active = load_active_models(active_path)
    print(f"📂 active: {os.path.basename(active_path)}")
    print(f"   抽出された型番: {len(active)} 個")

    # 3. diff
    unlisted = find_unlisted(catalog_rows, active)
    print(f"\n🔍 未出品モデル: {len(unlisted)} / {len(catalog_rows)} 件")

    # 4. 出力
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(script_dir, f"{OUTPUT_PREFIX}_{ts}.csv")
    write_output(unlisted, out_path)
    print(f"\n✅ 出力: {out_path}")

    # 5. ハイライト: 限定 / 新作モデル優先表示
    limited = [r for r in unlisted if (r.get("is_limited") or "").lower() in ("yes", "true", "1")]
    if limited:
        print(f"\n⭐ うち 限定モデル {len(limited)} 件 (出品候補優先度高):")
        for r in limited[:10]:
            print(f"  - {r['product_id']:20s} ¥{r.get('price_jpy_msrp','')} {r.get('source_url','')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
