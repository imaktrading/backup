#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""取下再出品 進捗ダッシュボード → 管理スプシの「再出品進捗」タブに一覧出力。

「ボタンは10件しか出ず全体像が見えない」への対策(ユーザー要望 2026-06-07・案1=可視化)。
funnel の RELIST候補(supply_url有)を全件、状態付きで一覧化:
  ✅ 済   = スプシB列が funnel itemID と不一致 (=③で新itemIDに書換済=再出品済)
  ⏳ 未   = B列が funnel itemID のまま (=未着手)
  ❓ 不明 = B列空 / スプシに無い
価格降順 = 処理順。10件ずつ上から消化していく俯瞰図。listing処理は別(①②③)。
"""
import csv
import datetime
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import relist_from_funnel as rf  # FUNNEL_DIR / relist_candidates / load_current_b_map / sku_from_url
from relist_writeback import SHEETS, CREDS_PATH

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DASH_SHEET_ID = "1UAVBdosIqqOI8qx-P-4k_ftTGuGWGzfIOU7vk7S2dz4"  # 「既存メンテ」スプシ (PDCA司令塔)
DASH_TAB = "取下再出品"
HEADERS = ["#", "状態", "価格$", "カテゴリ", "タイトル", "SKU", "旧ItemID", "新ItemID", "処理日時", "仕入URL"]


def build_rows(funnel_rows, b_map, stock_index=None, now=None, times_map=None):
    """funnel RELIST候補(supply_url有) → ダッシュボード行 + サマリー。価格降順。

    b_map は load_current_b_map の戻り = {ASIN/SKU: 現B列}。照合は sku_from_url(supply_url)
    で行う (2026-06-23 ASINキー化。coliid 揺れ起因の「不明」誤判定を解消)。

    stock_index (load_sheet_index の戻り) を渡すと **在庫切れ(監視くん取下げ/3RD)** を
    🔴在庫切れ として区別表示する (2026-06-23)。「未」に見えても仕入不可なものを可視化。

    times_map (load_relist_times の戻り = {ASIN: 処理日時}) を渡すと、アイテム毎の
    **処理日時**(③書戻し完了時刻)を列表示する (2026-06-23)。
    """
    cands = [r for r in rf.relist_candidates(funnel_rows) if (r.get("supply_url") or "").strip()]
    cands.sort(key=lambda x: -float(x.get("price") or 0))
    if now is None:
        now = datetime.datetime.now()
    times_map = times_map or {}
    out, done, todo, unknown, oos = [], 0, 0, 0, 0
    for i, r in enumerate(cands, 1):
        url = (r.get("supply_url") or "").strip()
        fid = (r.get("item_id") or "").strip()
        key = rf.sku_from_url(url)
        cur = (b_map.get(key) or "").strip()
        # 在庫切れ(売り切れ○)は最優先で区別。未/済の前に判定 (仕入不可は再出品対象外)
        if stock_index is not None and (stock_index.get(key) or {}).get("sold_out"):
            state, newid = "🔴在庫切れ", ""; oos += 1   # 新ItemIDは空 (再出品してない=旧IDを出さない)
        elif cur and fid and cur == fid:
            state, newid = "⏳未", ""; todo += 1
        elif cur and fid and cur != fid:
            state, newid = "✅済", cur; done += 1
        else:
            state, newid = "❓不明", cur; unknown += 1
        proc_time = times_map.get(key, "")
        out.append([i, state, r.get("price", ""), r.get("category", ""),
                    (r.get("title", "") or "")[:60], key, fid, newid, proc_time, url])
    return out, {"total": len(cands), "done": done, "todo": todo,
                 "unknown": unknown, "oos": oos}


def write_dashboard(rows, summary, src_name):
    import gspread
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_file(
        CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(DASH_SHEET_ID)
    # タブは維持(gid安定=ブックマーク不変)。clear して書き直す。
    # 注: 列U付近に日付が出るのはスプシ側 Apps Script(日次backup自動化)の編集スタンプで、無害。
    try:
        ws = sh.worksheet(DASH_TAB)
        ws.clear()
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=DASH_TAB, rows=len(rows) + 5, cols=len(HEADERS))
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    batches = -(-summary["todo"] // 10)
    oos = summary.get("oos", 0)
    summary_line = (f"取下再出品 進捗  |  総数 {summary['total']}  /  ✅済 {summary['done']}  /  "
                    f"⏳未 {summary['todo']} (あと{batches}バッチ)  /  🔴在庫切れ {oos}  /  ❓不明 {summary['unknown']}  "
                    f"|  元funnel: {src_name}  |  更新 {now}")
    data = [[summary_line] + [""] * (len(HEADERS) - 1), HEADERS] + rows
    ws.update(range_name="A1", values=data, value_input_option="RAW")
    return now, summary_line


def main():
    files = glob.glob(os.path.join(rf.FUNNEL_DIR, "funnel_*.csv"))
    if not files:
        sys.exit("funnel_*.csv がありません。先に『📊 ファネル分析』を実行してください。")
    src = max(files, key=os.path.getmtime)
    funnel_rows = list(csv.DictReader(open(src, encoding="utf-8")))
    print(f"対象 funnel: {os.path.basename(src)}")
    print("📊 スプシ読込中 (B列 + 監視くん売り切れ状態)...")
    stock_index = rf.load_sheet_index()
    b_map = {k: v["b"] for k, v in stock_index.items()}
    times_map = rf.load_relist_times()
    rows, summary = build_rows(funnel_rows, b_map, stock_index=stock_index, times_map=times_map)
    _, line = write_dashboard(rows, summary, os.path.basename(src))
    print("✅ ダッシュボード更新:", line)
    print(f"   → 管理スプシ2 タブ「{DASH_TAB}」を参照")


if __name__ == "__main__":
    main()
