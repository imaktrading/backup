#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""監視くんの短い巡回 QUICK に「この出品をすぐ見て」と頼む (出品くん側・2026-10-14)。

★ユーザー「通常の監視とは別で、走らせるのがあればいいんだ。例えば、補を追加したとか、(急ぐ出品だけ) とかね」
  → ブラボー GO (B-20261014-008 / hq/requests/2026-10-14_quick_watch_go.md)。
  「既存メンテ」のタブ `すぐ見る` に1行ずつ足すと、監視くん (LAPTOP) が10分おきに未処理を読んで API で見て
  M・在庫を書き、合図を出す → リバイスが約7分で値段を直す。タブは監視くんが作る (列: itemID / 理由 / 依頼時刻 /
  依頼者 / 状態 / 処理時刻)。状態が空 = 未処理。
  ① 補 (AC〜AG) を書いた時 → 理由=補を書いた (psa_hoju_fill の確定の後から呼ぶ)
  ② 急ぐ出品を2時間おき → 理由=急ぐ (python quick_watch_request.py urgent)
     急ぐ = 補0本 / 次の仕入元で買うと赤字 (psa_hoju_fill.mark_loss_risk が正)
     ★「よく売れる」は入れない (ブラボー判断 2026-10-14: 入れると293行/2時間でメルカリの負担が見込みの3倍強になる)

★タブ全体を書き直さず **末尾に足す** (監視くんが同じタブの状態を書いているので、書き直すと取り合いで消える)。
★未処理のまま同じ itemID が載っていれば足さない (二重に頼まない)。
"""
from __future__ import annotations

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

TAB = "すぐ見る"
FROM = "出品くん"
R_AUX = "補を書いた"
R_URGENT = "急ぐ"


def pending_ids(rows):
    """タブの行 (見出し込み) → 未処理 (状態が空) の itemID の集合 (純関数)。"""
    out = set()
    for r in (rows or [])[1:]:
        iid = (r[0] if r else "").strip()
        state = (r[4] if len(r) > 4 else "").strip()
        if iid and not state:
            out.add(iid)
    return out


def build_rows(item_ids, reason, pending, now):
    """足す行 (純関数)。空・未処理と重なる・同じ回の重複は外す。"""
    out, seen = [], set(pending or ())
    for iid in item_ids or []:
        iid = str(iid or "").strip()
        if not iid or iid in seen:
            continue
        seen.add(iid)
        out.append([iid, reason, now, FROM, "", ""])
    return out


def add(item_ids, reason):
    """タブの末尾に足す (I/O)。戻り: (足した件数, 未処理で重なった件数)。タブが無い・見出しが無い時は足さない。"""
    import sheet_io
    ws = sheet_io._open(sheet_io.MAINT_SHEET_ID).worksheet(TAB)
    rows = ws.get_all_values()
    if not rows or not rows[0] or (rows[0][0] or "").strip() != "itemID":
        print(f"  ⚠ タブ `{TAB}` の見出しがまだ無い (監視くんが作る) — 足さない", flush=True)
        return 0, 0
    pend = pending_ids(rows)
    body = build_rows(item_ids, reason, pend, time.strftime("%Y-%m-%d %H:%M:%S"))
    if body:
        ws.append_rows(body, value_input_option="RAW")
    return len(body), len([i for i in set(map(str, item_ids or [])) if i in pend])


def add_safely(item_ids, reason):
    """失敗しても呼び手 (補の書込など) を止めない版。必ず1行ログを出す。"""
    try:
        n, dup = add(item_ids, reason)
        print(f"⚡ すぐ見るに足した: {reason} {n}件 (頼んだ {len(set(item_ids or []))}件 / 未処理で重なり {dup}件)",
              flush=True)
        return n
    except Exception as e:                                     # noqa: BLE001
        print(f"⚠️要対応 すぐ見るに足せなかった ({reason} {len(set(item_ids or []))}件): {type(e).__name__}: {e}",
              flush=True)
        return 0


def urgent_ids():
    """急ぐ出品の itemID (I/O)。戻り: (ids, 内訳 dict)。"""
    import psa_hoju_fill as H
    import hoju_url_from_dupes as hd
    vals = H._read_high()
    live = H.select_backfill_targets(vals, max_backups=H.AUXN + 1)
    zero = [t["itemID"] for t in live if int(t.get("n_backups") or 0) == 0]
    loss = sorted(H.mark_loss_risk(live, vals, H._price_cache_get(hd)))
    ids = list(dict.fromkeys(zero + loss))
    return ids, {"補0本": len(zero), "次で赤字": len(loss)}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                          # noqa: BLE001
        pass
    if "urgent" in sys.argv:
        try:
            ids, why = urgent_ids()
        except Exception as e:                                 # noqa: BLE001
            print(f"⚠️要対応 急ぐ出品を数えられなかった: {type(e).__name__}: {e}", flush=True)
            return 1
        print(f"  急ぐ出品: {len(ids)}件 {why}", flush=True)
        add_safely(ids, R_URGENT)
        return 0
    print("使い方: python quick_watch_request.py urgent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
