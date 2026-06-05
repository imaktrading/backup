#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""取下再出品 ①取下げ: ファネルの RELIST候補(NO_SEARCH+NO_CLICK)を上位10件 End CSV 化。

旧 dump_us_qty1_sku(snapshot方式・Selenium 10分)を置換。snapshot 不要 —
最新 funnel_*.csv の flags に RELIST が立つ行を価格降順で読み、上位 CAP 件を取下げ対象に。

取下再出品の半自動化フロー (2026-06-05 確定・3コマンド):
  ① 取下げ(ここ): RELIST上位10 → End CSV + 保留リスト保存
  ② 再出品:        保留リスト → スプシB列空欄化 → 出品くん即live → Add CSV
  ③ 書戻し:        ACTIVEレポート → SKU照合 → スプシB列に新ItemID上書き

出力:
  1. End CSV (eBay FileExchange Action=EndItem) → c:/dev/iMak_data/revise/。eBay にアップ=取下げ
  2. 保留リスト relist_pending_<stamp>.csv → c:/dev/iMak_data/revise/。
     「取下げた10」を②③が参照する行固定キー (sku/old_item_id/category/supply_url/price/title)。
     supply_url(=スプシA列・仕入元URL) が ②再出品・③書戻しの不変アンカー。
  3. 候補一覧CSV → デスクトップ (確認用)

安全策: supply_url(行固定キー) が欠落した RELIST 行は ②③ で追えない (writeback不能) ため
取下げ対象から除外し、除外件数をログ明示する (silent cap 禁止)。
watcher有は RELIST に含まれない(タイトル編集等 in-place 対応)。
"""
import csv
import datetime
import glob
import os
import re
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
CAP = 10  # 1バッチ=10件 (ユーザー指示 2026-06-05)。少量ずつ取下→再出品→書戻しを回す


def sku_from_url(url: str) -> str:
    """仕入元URL → listing が付与する Custom Label(SKU) を best-effort 再現。

    listing script (gshock_to_csv.py:1515-1527 / montbell・tshirt・ichibankuji・psa) と
    同じパターン規約:
      - Amazon ASIN:   /dp/XXXXXXXXXX (10文字)  → ASIN
      - Mercari itemID: /item/m+数字            → m<id>
      - それ以外:       末尾12文字 fallback
    casio.com は型番(build_row の model_official)で URL から導けない → 末尾12にフォール
    バック(正確には ②再出品で出品くんが生成する Add CSV の CustomLabel が権威。①は best-effort)。

    ③書戻しで ACTIVEレポート Custom Label と照合する不変キー。
    """
    if not url:
        return ""
    m = re.search(r"/dp/([A-Z0-9]{10})", url)
    if m:
        return m.group(1)
    m = re.search(r"/item/(m\d+)", url)
    if m:
        return m.group(1)
    cleaned = url.split("?")[0].split("#")[0].rstrip("/")
    return cleaned[-12:].lstrip("/")


def relist_candidates(rows):
    """funnel CSV rows から RELIST フラグ行 (NO_SEARCH+NO_CLICK) を抽出。"""
    return [r for r in rows if "RELIST" in (r.get("flags") or "").split("|")]


def select(rows, cap=CAP):
    """RELIST 候補のうち supply_url を持つ行を価格降順で上位 cap 件。

    戻り: (picked, total_relist, skipped_no_supply)。
      picked            = 取下げ対象 (supply_url 有・価格降順・上位 cap)
      total_relist      = RELIST フラグ総数 (進捗表示用)
      skipped_no_supply = supply_url 欠落で除外した件数 (silent cap 禁止のログ用)
    """
    cands = relist_candidates(rows)
    with_supply = [r for r in cands if (r.get("supply_url") or "").strip()]
    skipped_no_supply = len(cands) - len(with_supply)
    ordered = sorted(with_supply, key=lambda x: -float(x.get("price") or 0))
    return ordered[:cap], len(cands), skipped_no_supply


def write_pending(picked, path):
    """保留リスト出力。②再出品・③書戻しが参照する行固定キー。

    列: sku / old_item_id / category / supply_url / price / title。
    sku = supply_url末尾12 (③書戻しで ACTIVEレポート Custom Label と照合)。
    """
    fields = ["sku", "old_item_id", "category", "supply_url", "price", "title"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, quoting=csv.QUOTE_NONNUMERIC)
        w.writeheader()
        for r in picked:
            supply_url = (r.get("supply_url") or "").strip()
            w.writerow({
                "sku": sku_from_url(supply_url),
                "old_item_id": r.get("item_id", ""),
                "category": r.get("category", ""),
                "supply_url": supply_url,
                "price": r.get("price", ""),
                "title": r.get("title", ""),
            })


def main():
    files = glob.glob(os.path.join(FUNNEL_DIR, "funnel_*.csv"))
    if not files:
        sys.exit("funnel_*.csv がありません。先に『📊 ファネル分析』を実行してください。")
    src = max(files, key=os.path.getmtime)
    rows = list(csv.DictReader(open(src, encoding="utf-8")))
    picked, total_relist, skipped_no_supply = select(rows)
    print(f"対象 funnel: {os.path.basename(src)}")
    print(f"RELIST候補(NO_SEARCH+NO_CLICK) = {total_relist}件 → 取下げ {len(picked)}件 (価格高い順・上限{CAP})")
    if skipped_no_supply:
        print(f"  ⚠ supply_url(仕入元URL)欠落で除外 = {skipped_no_supply}件 (②再出品/③書戻しで追えないため対象外)")
    if not picked:
        print("候補なし(supply_url 有 RELIST が0件)。処理終了。")
        return

    stamp = datetime.date.today().strftime("%Y%m%d")
    os.makedirs(END_DIR, exist_ok=True)

    # 1) End CSV (eBay FileExchange)
    end_path = os.path.join(END_DIR, f"relist_end_{stamp}.csv")
    with open(end_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(END_HEADER)
        for r in picked:
            w.writerow(["End", r["item_id"], END_CODE])

    # 2) 保留リスト (②③の参照元・行固定キー)
    pending_path = os.path.join(END_DIR, f"relist_pending_{stamp}.csv")
    write_pending(picked, pending_path)

    # 3) 候補一覧 (デスクトップ・確認用)
    cand_path = os.path.join(DESK, f"取下再出品候補_{stamp}.csv")
    fields = ["item_id", "title", "site", "category", "price", "watch", "flags", "supply_url", "ebay_url"]
    with open(cand_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in picked:
            w.writerow(r)

    print(f"\nEnd CSV (eBayアップで取下げ): {end_path}")
    print(f"保留リスト (②再出品/③書戻しが参照): {pending_path}")
    print(f"候補一覧(確認用): {cand_path}")
    print(f"\n▶ ① 取下げ: End CSV を eBay FileExchange にアップ → 該当 {len(picked)} listing が終了(Cassini reset)")
    print("▶ ② 再出品: 保留リストを relist_add_from_pending で出品くん即live → Add CSV (次コマンド)")
    print("▶ ③ 書戻し: 再出品が live 後、ACTIVEレポートDL → seller_hub_writeback でスプシB列に新ItemID")
    print("※ watcher有は候補外 (relistするとwatcher消失→✏️タイトル改修で in-place)")


if __name__ == "__main__":
    main()
