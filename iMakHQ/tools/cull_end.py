#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B: CULL(在庫切れ&需要皆無) 段階的 出品停止 End CSV 生成。

CULL = qty=0 ∩ 一度も売れず watcher も付かず。掲載しても無害(qty=0=購入不可)だが、
整理 + 誤って qty を戻して売れる事故の予防として段階的に End する。

安全策 (2026-06-05 ユーザー合意):
  1. age>=21日 の行のみ (NEW_WAIT補正: 出品から時間不足の良品を巻き込まない)。
     age 不明(0)は fail-closed で対象外 (判定不能を破壊側に倒さない)。
  2. CAP=50件/回 (burst禁止: 1755件一括 END はしない)。
  3. 自動アップ無し (End CSV を生成するのみ。eBay FileExchange へは人が手動アップ)。
  並び: age 降順 (最も長く需要0=最も確実に dead を先に) → 同 age は価格昇順 (損失小を先に)。

入力 : ../funnel_output/funnel_*.csv (CULL flag, age_days)
出力 : End CSV → C:/dev/iMak_data/revise/cull_end_YYYYMMDD.csv
       確認用一覧 → デスクトップ CULL出品停止候補_YYYYMMDD.csv
"""
import csv
import datetime
import glob
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
FUNNEL_DIR = os.path.normpath(os.path.join(_HERE, "..", "funnel_output"))
DESK = r"C:\Users\imax2\OneDrive\デスクトップ"
END_DIR = r"C:\dev\iMak_data\revise"

CAP = 50          # 1回あたりの上限 (burst禁止)
MIN_AGE = 21      # これ未満(日)は新規=時間不足の可能性 → 対象外 (NEW_WAIT補正)

# relist_from_funnel / seller_hub_relist と統一
END_HEADER = ["*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)", "ItemID", "EndCode"]
END_CODE = "OtherListingError"


def _i(v):
    try:
        return int(float(str(v).strip()))
    except (ValueError, TypeError):
        return 0


def _f(v):
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return 0.0


def select(rows, cap=CAP, min_age=MIN_AGE):
    """CULL ∩ age>=min_age を age降順・価格昇順で並べ、先頭 cap 件。

    age 不明(0)は対象外 (fail-closed)。テスト可能なよう純関数化。
    """
    cull = [r for r in rows if "CULL" in (r.get("flags") or "").split("|")]
    eligible = [r for r in cull if _i(r.get("age_days")) >= min_age]
    eligible.sort(key=lambda r: (-_i(r.get("age_days")), _f(r.get("price"))))
    return cull, eligible, eligible[:cap]


def main():
    fs = glob.glob(os.path.join(FUNNEL_DIR, "funnel_*.csv"))
    if not fs:
        sys.exit("funnel_*.csv がありません。先に『📊 ファネル分析』を実行してください。")
    src = max(fs, key=os.path.getmtime)
    rows = list(csv.DictReader(open(src, encoding="utf-8")))
    cull, eligible, picked = select(rows)

    print(f"対象 funnel: {os.path.basename(src)}")
    print(f"CULL(在庫切れ&需要皆無) = {len(cull)}件")
    print(f"  うち age>={MIN_AGE}日 (NEW_WAIT補正後) = {len(eligible)}件")
    print(f"  今回 End 対象 (CAP {CAP}/回, age降順) = {len(picked)}件")
    skipped_young = len(cull) - len(eligible)
    if skipped_young:
        print(f"  ※ age<{MIN_AGE}日 or age不明で対象外 = {skipped_young}件 (新規=時間不足を保護)")
    if not picked:
        print("対象なし。処理終了。")
        return

    stamp = datetime.date.today().strftime("%Y%m%d")
    os.makedirs(END_DIR, exist_ok=True)
    end_path = os.path.join(END_DIR, f"cull_end_{stamp}.csv")
    with open(end_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(END_HEADER)
        for r in picked:
            w.writerow(["End", r["item_id"], END_CODE])

    cand_path = os.path.join(DESK, f"CULL出品停止候補_{stamp}.csv")
    fields = ["item_id", "title", "site", "category", "price", "age_days", "watch", "ebay_url"]
    with open(cand_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in picked:
            w.writerow(r)

    print(f"\nEnd CSV (eBayアップで取下げ): {end_path}")
    print(f"確認用一覧: {cand_path}")
    print(f"\n▶ End CSV を eBay FileExchange に手動アップ → {len(picked)}件 終了")
    print("▶ 残りは レポート再DL → ファネル再実行 → 本ツール再走 で段階的に (1回50件まで)")
    print("※ 在庫切れ(qty=0)=購入不可なので急がなくてよい。誤判定混入を避け少量ずつ。")


if __name__ == "__main__":
    main()
