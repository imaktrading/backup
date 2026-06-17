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

# 商品管理シート (出品マスタ。canonical KEY = AI列(idx34)、itemID = B列(idx1))。
# 既存メンテとは別スプシ。再仕入れ/需要マップが canonical KEY を引く血統元 (Step6, 2026-06-10)。
PRODUCT_SHEET_ID = "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk"
PRODUCT_GID = 851100680
PRODUCT_COL_ITEMID = 1   # B
PRODUCT_COL_CERT = 8     # I (PSA cert#。psa_cache.json で CardImageUrl=現物PSA画像を引く)
PRODUCT_COL_KEY = 34     # AI (canonical product_id)


def build_key_map(rows2d, itemid_col=PRODUCT_COL_ITEMID, key_col=PRODUCT_COL_KEY):
    """商品管理シート rows(2d, header含む) → {itemID(str): canonical_KEY(str)} (純関数, test可)。

    canonical KEY が空 / url-key(item:/shops:) の行は除外 (= catalog-backed の固有id のみ)。
    """
    out = {}
    for r in rows2d[1:]:
        if len(r) <= max(itemid_col, key_col):
            continue
        iid = (r[itemid_col] or "").strip()
        key = (r[key_col] or "").strip()
        if not iid or not key or key.startswith("item:") or key.startswith("shops:"):
            continue
        out[iid] = key
    return out


PRODUCT_COL_AUX_START = 28   # AC (補URL1)。AC-AG = 補URL1-5 (idx28-32 / 1-indexed col 29-33)。
PRODUCT_AUX_MAX = 5


def _product_ws():
    import gspread
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_file(
        CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(PRODUCT_SHEET_ID)
    ws = next((w for w in sh.worksheets() if w.id == PRODUCT_GID), None)
    if ws is None:
        raise RuntimeError(f"商品管理シート gid={PRODUCT_GID} が見つからない")
    return ws


def product_key_map():
    """商品管理シートを読んで {itemID: canonical_KEY} を返す (I/O)。失敗は例外送出。"""
    return build_key_map(_product_ws().get_all_values())


def build_cert_map(rows2d, itemid_col=PRODUCT_COL_ITEMID, cert_col=PRODUCT_COL_CERT):
    """商品管理シート rows → {itemID(str): cert#(str)} (純関数, test可)。空itemID/空cert は除外。"""
    out = {}
    for r in rows2d[1:]:
        if len(r) <= max(itemid_col, cert_col):
            continue
        iid = (r[itemid_col] or "").strip()
        cert = (r[cert_col] or "").strip()
        if iid and cert:
            out[iid] = cert
    return out


def product_index():
    """商品管理シートを1回読んで (key_map, itemid_to_row, cert_map) を返す (I/O)。

    key_map = {itemID: canonical_KEY}、 itemid_to_row = {itemID: 1-indexed行番号}、
    cert_map = {itemID: PSA cert#}(再仕入れの目視確認で 現物PSA画像 を引くのに使う)。
    再仕入れゲートが KEY 解決 + 補URL書戻し + cert の全てに使う(sheet読みを1回に集約)。
    """
    vals = _product_ws().get_all_values()
    key_map = build_key_map(vals)
    cert_map = build_cert_map(vals)
    itemid_to_row = {}
    for i, r in enumerate(vals):
        if i == 0:
            continue
        if len(r) > PRODUCT_COL_ITEMID:
            iid = (r[PRODUCT_COL_ITEMID] or "").strip()
            if iid:
                itemid_to_row.setdefault(iid, i + 1)
    return key_map, itemid_to_row, cert_map


def write_aux_urls(row_to_urls):
    """{1-indexed行番号: [url,...]} を 商品管理シート 補URL列(AC-AG)に batch_update。

    各行 最大5URL、不足は空文字でクリア(古い補URLを残さない)。touch するのは AC-AG のみ。
    戻り: 書込んだ行数。row_to_urls 空なら 0。
    """
    if not row_to_urls:
        return 0
    ws = _product_ws()

    def _coln(idx0):
        return chr(65 + idx0) if idx0 < 26 else "A" + chr(65 + idx0 - 26)
    c0 = _coln(PRODUCT_COL_AUX_START)                      # AC
    c1 = _coln(PRODUCT_COL_AUX_START + PRODUCT_AUX_MAX - 1)  # AG
    reqs = []
    for row, urls in row_to_urls.items():
        vals5 = (list(urls)[:PRODUCT_AUX_MAX] + [""] * PRODUCT_AUX_MAX)[:PRODUCT_AUX_MAX]
        reqs.append({"range": f"{c0}{row}:{c1}{row}", "values": [vals5]})
    if reqs:
        ws.batch_update(reqs, value_input_option="RAW")
    return len(reqs)


def read_tab(tab, sheet_id=MAINT_SHEET_ID):
    """スプシ tab を 2d list で返す (I/O)。タブが無ければ []。PDCA台帳の前回値読込に使う。"""
    import gspread
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_file(
        CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(sheet_id)
    try:
        return sh.worksheet(tab).get_all_values()
    except gspread.WorksheetNotFound:
        return []


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
