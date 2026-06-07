#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""既存出品メンテ PDCA 司令塔スプシ「既存メンテ」に 3 タブを集約出力。

ユーザー要望 (2026-06-07): ファネル分析 / 需要・新規強化 / 取下再出品 を1スプシに纏めて
管理しやすく。タブ間借り(管理スプシ)→専用スプシに移設。

  タブ「ファネル分析」    : 全flagのサマリー(件数/意味/推奨アクション) = PDCA の Check 俯瞰
  タブ「需要・新規強化」  : RESTOCK(在庫切れ&需要実証→再仕入れ優先) = Act(増やす)
  タブ「取下再出品」      : RELIST候補の進捗(済/未・価格順) = Act(刷新)  ※relist_dashboard が担当
"""
import csv
import datetime
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import relist_from_funnel as rf
import relist_dashboard as rd
from relist_writeback import CREDS_PATH

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SHEET_ID = rd.DASH_SHEET_ID  # 「既存メンテ」

# flag → (意味, 推奨アクション, 行先タブ)。表示順 = 重要(actionable)順。
FLAG_META = [
    ("RELIST",       "検索露出ゼロ (NO_SEARCH+NO_CLICK)", "取下再出品で全項目刷新+Cassini reset", "→「取下再出品」タブ"),
    ("NO_CONVERT",   "クリック有るが買われない",          "価格(適正価格比)/説明の見直し",        "個別対応"),
    ("RESTOCK",      "在庫切れ&需要実証 (過去販売/watcher)", "再仕入れ優先 (需要大きい順)",        "→「需要・新規強化」タブ"),
    ("NO_CLICK",     "クリックされない",                   "タイトル/サムネ/価格",                "RELISTに含む"),
    ("NEW_WAIT",     "出品21日未満",                       "計測待ち (様子見)",                    "-"),
    ("NO_SEARCH",    "検索に出ていない",                   "キーワード or 取下再出品",             "→「取下再出品」タブ"),
    ("OUT_OF_STOCK", "在庫切れ",                           "RESTOCK/CULL に判定済",               "-"),
    ("CULL",         "在庫切れ&需要皆無",                  "出品停止候補 (整理)",                  "-"),
    ("DEAD_SIMPLE",  "簡易判定 (非US等)",                  "参考 (views/watchersベース)",         "-"),
]


def _flags(r):
    return [f for f in (r.get("flags") or "").split("|") if f]


def build_funnel_summary(funnel_rows, src_name):
    import collections
    c = collections.Counter()
    for r in funnel_rows:
        for fl in _flags(r):
            c[fl] += 1
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    head = (f"既存出品 ファネル分析  |  総listing {len(funnel_rows)}  |  "
            f"元funnel: {src_name}  |  更新 {now}")
    data = [[head, "", "", "", ""],
            ["flag", "件数", "意味", "推奨アクション", "行先"]]
    for key, mean, act, tab in FLAG_META:
        data.append([key, c.get(key, 0), mean, act, tab])
    return data


def build_restock(funnel_rows):
    rows = [r for r in funnel_rows if "RESTOCK" in _flags(r)]

    def _i(r, k):
        try:
            return int(float(r.get(k) or 0))
        except (ValueError, TypeError):
            return 0
    rows.sort(key=lambda r: (-_i(r, "sold_qty"), -_i(r, "sales90"), -_i(r, "watch")))
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    data = [[f"需要・新規強化 (RESTOCK=在庫切れ&需要実証→再仕入れ優先)  |  {len(rows)}件  |  更新 {now}",
             "", "", "", "", ""],
            ["#", "カテゴリ", "価格$", "sold90", "watch", "タイトル"]]
    for i, r in enumerate(rows, 1):
        data.append([i, r.get("category", ""), r.get("price", ""),
                     r.get("sales90", ""), r.get("watch", ""), (r.get("title", "") or "")[:60]])
    return data, len(rows)


def write_tab(gc, tab, data):
    import gspread
    sh = gc.open_by_key(SHEET_ID)
    try:
        ws = sh.worksheet(tab)
        ws.clear()
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab, rows=len(data) + 5, cols=max(8, len(data[0])))
    ws.update(range_name="A1", values=data, value_input_option="RAW")


def main():
    files = glob.glob(os.path.join(rf.FUNNEL_DIR, "funnel_*.csv"))
    if not files:
        sys.exit("funnel_*.csv がありません。先に『📊 ファネル分析』を実行してください。")
    src = max(files, key=os.path.getmtime)
    funnel_rows = list(csv.DictReader(open(src, encoding="utf-8")))
    print(f"対象 funnel: {os.path.basename(src)} ({len(funnel_rows)}行)")
    print("📊 スプシB列読込中...")
    b_map = rf.load_current_b_map()

    import gspread
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_file(
        CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)

    # ファネル分析(サマリー)=別「ファネル分析」スプシ / 需要・新規強化=demand_winners /
    # 再仕入れ=restock_worklist が各々担当 (Stage1-2)。ここは 取下再出品 タブのみ refresh。
    drows, dsummary = rd.build_rows(funnel_rows, b_map)
    rd.write_dashboard(drows, dsummary, os.path.basename(src))

    print(f"✅ 「既存メンテ」取下再出品タブ更新完了")
    print(f"   取下再出品 : 総{dsummary['total']}/✅済{dsummary['done']}/⏳未{dsummary['todo']} (あと{-(-dsummary['todo']//10)}バッチ)")


if __name__ == "__main__":
    main()
