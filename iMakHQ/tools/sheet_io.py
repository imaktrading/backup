#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""スプシ集約の共有ヘルパ (2026-06-07)。eBayアップCSV以外はスプシに集約する方針。

各分析ボタン(需要・新規強化/再仕入れ/効果測定 等)は結果を「既存メンテ」スプシの
専用タブに書く。デスクトップCSVは廃止。
"""
import os

MAINT_SHEET_ID = "1UAVBdosIqqOI8qx-P-4k_ftTGuGWGzfIOU7vk7S2dz4"   # 「既存メンテ」スプシ
MAINT_URL = f"https://docs.google.com/spreadsheets/d/{MAINT_SHEET_ID}/edit"
CREDS_PATH = r"c:\dev\iMak\double-hold-421922-7c0d38d3f73d.json"


def write_rows_to_tab(tab, rows2d, sheet_id=MAINT_SHEET_ID):
    """rows2d ([[header...],[row...],...]) をスプシ tab に書く (clear+update, 無ければ作成)。

    タブは維持 (gid 安定)。戻り: 書込行数。失敗は例外送出 (呼出側で握る)。
    """
    import gspread
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_file(
        CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(sheet_id)
    ncols = max((len(r) for r in rows2d), default=4)
    try:
        ws = sh.worksheet(tab)
        ws.clear()
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab, rows=max(10, len(rows2d) + 5), cols=max(4, ncols))
    ws.update(range_name="A1", values=rows2d, value_input_option="RAW")
    return len(rows2d)
