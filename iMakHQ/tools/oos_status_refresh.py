#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「ファネル分析」スプシ 在庫なしタブの S列「状態」を今の実態に合わせ直す (2026-08-25)。

なぜ必要か:
    S列はファネルを回した時点の状態で書かれる。取下げボタンを押すと済みリストが増えるので、
    **押した直後からシートが嘘になる**(実際に踏んだ: 122件 落とした後も「未 (次回の対象)」の
    まま残っていた)。ボタンの最後にこれを呼んで、シートを実態に戻す。

    材料は funnel CSV (ローカル) と 済み台帳だけ。**eBay を1回も叩かない**。

使い方:
    python oos_status_refresh.py            # 何件書き換わるか出すだけ
    python oos_status_refresh.py --commit   # 書く
"""
from __future__ import annotations

import argparse
import csv
import glob
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import listing_funnel as LF   # noqa: E402

TAB = "在庫なし"
STATUS_COL = 19               # S列 (1始まり)


def latest_funnel_csv(funnel_dir=None):
    d = funnel_dir or LF.OUT_DIR
    hits = sorted(glob.glob(os.path.join(d, "funnel_*.csv")))
    return hits[-1] if hits else None


def build_status_map(csv_path, done_ids=None):
    """funnel CSV + 済み台帳 → {item_id: 状態文字列} (純関数寄り, test可)。"""
    done = done_ids if done_ids is not None else LF.load_cull_done()
    out = {}
    with io.open(csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    cull_ids = {r["item_id"] for r in rows if "CULL" in (r.get("flags") or "").split("|")}
    for r in rows:
        out[r["item_id"]] = LF.oos_status(r, cull_ids, done)
    return out


def plan(sheet_values, status_map):
    """シートの現状 → 書き換える (行番号, 新しい値) の一覧 (純関数, test可)。"""
    changes = []
    for i, row in enumerate(sheet_values[1:], start=2):
        if not row or not row[0]:
            continue
        new = status_map.get(row[0])
        if new is None:
            continue                       # CSV に無い行は触らない (作り話をしない)
        cur = row[STATUS_COL - 1] if len(row) >= STATUS_COL else ""
        if cur != new:
            changes.append((i, new))
    return changes


def _run(src, commit):
    """在庫なしタブの S列を src (funnel CSV) の内容に合わせる。書いた件数を返す。"""
    smap = build_status_map(src)
    import gspread
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_file(
        LF.CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    ws = gspread.authorize(creds).open_by_key(LF.FUNNEL_SHEET_ID).worksheet(TAB)
    ch = plan(ws.get_all_values(), smap)
    print(f"▶ 在庫なしシート 状態列: 書き換え {len(ch)}件 ({os.path.basename(src)})")
    if not ch:
        return 0
    if not commit:
        print("  → 実際に書くには --commit")
        return 0
    ws.batch_update([{"range": f"S{i}", "values": [[v]]} for i, v in ch],
                    value_input_option="RAW")
    return len(ch)


def main_commit(src=None):
    """取下げボタンから呼ぶ入口 (書くところまでやる)。"""
    src = src or latest_funnel_csv()
    if not src:
        print("  funnel CSV が無いので状態列は触りません")
        return 0
    return _run(src, commit=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    a = ap.parse_args()
    src = latest_funnel_csv()
    if not src:
        print("  funnel CSV が無いので状態列は触りません")
        return 0
    _run(src, commit=a.commit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
