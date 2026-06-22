#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PSA再仕入れ funnel の「出品状態」列をフロー内で自動更新する (2026-06-22)。

PSA再仕入れタブ(funnel)の各行に「どの段階か」(再出品済/入稿待ち/確証待ち/対象外/End候補)を
RESTOCK確定タブ + RESTOCK対象外タブ との join で付与する。手動スナップショットだと 🔄書戻しで
実行済になっても funnel に反映されないため、出品状態が変わる2地点で本関数を呼び自動同期する:
  - 🃏 psa_resource_gate: funnel 再生成(write_rows_to_tab)直後
  - 🔄 psa_restock_writeback: RESTOCK確定を実行済に更新した直後

funnel は write_rows_to_tab で毎回 clear+書換され列が消えるので、本関数は「列が無ければ追加」
(グリッド拡張込み)で冪等に動く。
"""
from __future__ import annotations

PSA_FUNNEL_GID = 2119598150
STATUS_HEADER = "出品状態"


def compute_status(itemid, confirmed_map, excluded_set, kahi):
    """funnel 1行の出品状態ラベルを返す(純関数・I/Oなし)。

    Args:
        itemid: 行の eBay itemID(空可)。
        confirmed_map: {itemID: RESTOCK確定の RESTOCK状態文字列}。
        excluded_set: RESTOCK対象外の itemID 集合。
        kahi: 行の「再仕入れ可否」文字列(例 '再仕入れ可◎' / '不能✕(End候補)')。
    """
    if itemid and itemid in excluded_set:
        return "✕対象外"
    if itemid and itemid in confirmed_map:
        s = confirmed_map[itemid] or ""
        if "実行済" in s:
            return "✅再出品済"
        if "入稿待ち" in s:
            return "⏳入稿待ち(CSV→UL)"
        return s or "確定"
    if "可" in (kahi or ""):
        return "🔍確証待ち(🃏)"
    return "—(End候補)"


def _item_id_from_url(url):
    import re
    m = re.search(r"/(\d{11,})", url or "")
    return m.group(1) if m else ""


def update_funnel_listing_status():
    """PSA再仕入れ funnel の出品状態列を RESTOCK確定 join で最新化 (I/O)。

    失敗は例外送出(呼出側で握って非致命にする)。戻り: {ラベル: 件数} の集計。
    """
    import gspread
    from google.oauth2.service_account import Credentials
    import sheet_io as s

    creds = Credentials.from_service_account_file(
        s.CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(s.MAINT_SHEET_ID)

    cf = s.read_tab("RESTOCK確定")
    confirmed_map = {}
    if cf:
        ch = cf[0]
        i_iid = ch.index("itemID") if "itemID" in ch else 0
        i_st = ch.index("RESTOCK状態") if "RESTOCK状態" in ch else -1
        for r in cf[1:]:
            if r and i_iid < len(r) and r[i_iid].strip():
                confirmed_map[r[i_iid].strip()] = (r[i_st].strip() if 0 <= i_st < len(r) else "")
    excluded_set = {r[0].strip() for r in (s.read_tab("RESTOCK対象外")[1:] or [])
                    if r and r[0].strip()}

    ws = next((w for w in sh.worksheets() if w.id == PSA_FUNNEL_GID), None)
    if ws is None:
        raise RuntimeError(f"PSA再仕入れ gid={PSA_FUNNEL_GID} が見つからない")
    v = ws.get_all_values()
    if not v:
        return {}
    h = v[0]
    iu = h.index("ebay_url") if "ebay_url" in h else len(h) - 1
    col_idx = h.index(STATUS_HEADER) if STATUS_HEADER in h else len(h)

    from collections import Counter
    out = [[STATUS_HEADER]]
    tally = Counter()
    for r in v[1:]:
        iid = _item_id_from_url(r[iu] if len(r) > iu else "")
        kahi = r[2] if len(r) > 2 else ""
        st = compute_status(iid, confirmed_map, excluded_set, kahi)
        out.append([st])
        tally[st] += 1

    # グリッドに列が足りなければ拡張(funnel は16列固定で clear+書換される)
    if col_idx >= ws.col_count:
        ws.add_cols(col_idx - ws.col_count + 1)
    from gspread.utils import rowcol_to_a1
    col_a = rowcol_to_a1(1, col_idx + 1).rstrip("1")
    ws.update(range_name=f"{col_a}1", values=out, value_input_option="RAW")
    return dict(tally)


if __name__ == "__main__":
    import sys
    try:
        t = update_funnel_listing_status()
        print("出品状態列 同期:", t)
    except Exception as e:
        sys.exit(f"出品状態同期 失敗: {type(e).__name__}: {e}")
