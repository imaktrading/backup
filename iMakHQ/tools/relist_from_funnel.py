#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""取下再出品: ファネルの RELIST候補(NO_SEARCH=露出ゼロ ∩ watcher無)を End CSV 化。

旧 dump_us_qty1_sku(snapshot方式・Selenium 10分)を置換。snapshot 不要 —
最新 funnel_*.csv の flags に RELIST が立つ行(=NO_SEARCH かつ watcher無=relistで失うもの無)を読む。

出力:
  1. End CSV (eBay FileExchange Action=EndItem) → c:/dev/iMak_data/revise/ に保存。eBay にアップ=取下げ
  2. 候補一覧CSV → デスクトップ (item_id/title/site/price/watch/impr/ebay_url)

再出品(再Add)は各カテゴリの通常 listing スクリプト or seller_hub_relist が担う(既存 drop-ship flow)。
watcher有は RELIST に含まれない(タイトル編集等 in-place 対応)。
"""
import csv
import datetime
import glob
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

FUNNEL_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "funnel_output"))
DESK = r"C:\Users\imax2\OneDrive\デスクトップ"
END_DIR = r"C:\dev\iMak_data\revise"
END_HEADER = ["*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)", "ItemID", "EndCode"]
END_CODE = "OtherListingError"  # Cassini reset 目的の汎用 code (seller_hub_relist と統一)
CAP = 50   # 1回あたりの上限 (一気に End+再Add は burst リスク+ブースト希釈 → 段階実行)


def relist_candidates(rows):
    """funnel CSV rows から RELIST フラグ行 (watcher無の NO_SEARCH+NO_CLICK) を抽出。"""
    return [r for r in rows if "RELIST" in (r.get("flags") or "").split("|")]


def select(rows, cap=CAP):
    """RELIST 候補を価格(利益額)降順で並べ、先頭 cap 件。戻り: (全候補, 今回分)。"""
    cands = relist_candidates(rows)
    cands.sort(key=lambda x: -float(x.get("price") or 0))
    return cands, cands[:cap]


def main():
    files = glob.glob(os.path.join(FUNNEL_DIR, "funnel_*.csv"))
    if not files:
        sys.exit("funnel_*.csv がありません。先に『📊 ファネル分析』を実行してください。")
    src = max(files, key=os.path.getmtime)
    rows = list(csv.DictReader(open(src, encoding="utf-8")))
    cands, picked = select(rows)
    print(f"対象 funnel: {os.path.basename(src)}")
    print(f"取下再出品(=新規ブースト)候補 = watcher無の NO_SEARCH+NO_CLICK = {len(cands)}件")
    print(f"  今回分 (CAP {CAP}/回, 価格高い順) = {len(picked)}件")
    if len(cands) > CAP:
        print(f"  ※ 残り {len(cands) - CAP}件は レポート再DL→ファネル再実行→本ツール再走 で段階的に")
    if not picked:
        print("候補なし。処理終了。")
        return

    stamp = datetime.date.today().strftime("%Y%m%d")
    # 1) End CSV (eBay FileExchange)
    os.makedirs(END_DIR, exist_ok=True)
    end_path = os.path.join(END_DIR, f"relist_end_{stamp}.csv")
    with open(end_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(END_HEADER)
        for r in picked:
            w.writerow(["End", r["item_id"], END_CODE])
    # 2) 候補一覧 (デスクトップ・確認用)
    cand_path = os.path.join(DESK, f"取下再出品候補_{stamp}.csv")
    fields = ["item_id", "title", "site", "category", "price", "watch", "impr", "ebay_url"]
    with open(cand_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in picked:
            w.writerow(r)

    print(f"\nEnd CSV (eBayアップで取下げ): {end_path}")
    print(f"候補一覧(確認用): {cand_path}")
    print("\n▶ 取下げ: End CSV を eBay FileExchange にアップ → 該当listingが終了(Cassini reset)")
    print("▶ 再出品: 各カテゴリの listing スクリプトで再Add → 新規ブースト+タイトル再生成 (既存 drop-ship flow)")
    print("※ watcher有は候補外 (relistするとwatcher消失→✏️タイトル改修で in-place)")


if __name__ == "__main__":
    main()
