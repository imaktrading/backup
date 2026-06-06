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
HEADERS = ["#", "状態", "価格$", "カテゴリ", "タイトル", "旧ItemID", "新ItemID", "仕入URL"]


def build_rows(funnel_rows, b_map):
    """funnel RELIST候補(supply_url有) → ダッシュボード行 + サマリー。価格降順。"""
    cands = [r for r in rf.relist_candidates(funnel_rows) if (r.get("supply_url") or "").strip()]
    cands.sort(key=lambda x: -float(x.get("price") or 0))
    out, done, todo, unknown = [], 0, 0, 0
    for i, r in enumerate(cands, 1):
        url = (r.get("supply_url") or "").strip()
        fid = (r.get("item_id") or "").strip()
        cur = (b_map.get(url) or "").strip()
        if cur and fid and cur == fid:
            state, newid = "⏳未", ""; todo += 1
        elif cur and fid and cur != fid:
            state, newid = "✅済", cur; done += 1
        else:
            state, newid = "❓不明", cur; unknown += 1
        out.append([i, state, r.get("price", ""), r.get("category", ""),
                    (r.get("title", "") or "")[:60], fid, newid, url])
    return out, {"total": len(cands), "done": done, "todo": todo, "unknown": unknown}


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
    summary_line = (f"取下再出品 進捗  |  総数 {summary['total']}  /  ✅済 {summary['done']}  /  "
                    f"⏳未 {summary['todo']} (あと{batches}バッチ)  /  ❓不明 {summary['unknown']}  "
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
    print("📊 スプシB列読込中...")
    b_map = rf.load_current_b_map()
    rows, summary = build_rows(funnel_rows, b_map)
    _, line = write_dashboard(rows, summary, os.path.basename(src))
    print("✅ ダッシュボード更新:", line)
    print(f"   → 管理スプシ2 タブ「{DASH_TAB}」を参照")


if __name__ == "__main__":
    main()
