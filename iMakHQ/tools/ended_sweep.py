#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手で落とした出品の後始末を、itemID を控えずに拾う (2026-08-26)。

なぜ必要か:
    取下げはボタンを使わず Seller Hub で手作業してもよい。ただしボタンがやっている
    後始末 (B列を空にする / 済みリストに記録) が抜けると:
      - B列が埋まったまま = 「出品済み」と判断され、仕入元が復活しても二度と出品されない
      - 済みリストに無い = 次にボタンを押したとき候補の上位を占めて空振りする
    落とした itemID を人が控えるのは現実的でないので、**eBay の出品一覧と突き合わせて**
    「シートには在るが eBay に居ない」行を機械的に見つける。自然終了・売れて終了も同じく拾う。

安全側の作り (誤って生きている出品の B列を消さない):
    - eBay の一覧が **申告件数どおり取れた時だけ** 判定する (`IncompleteFetch` で中断)。
      通信が途中で切れた一覧で判定すると、生きている出品まで「終了」に見える
    - 件数が急に増えた時は止めて警告 (--limit、既定 400)。データ不具合での一括誤処理を防ぐ
    - 既定は dry-run。書くのは --commit を付けた時だけ

使い方:
    python ended_sweep.py                # 何件あるか出すだけ
    python ended_sweep.py --commit       # B列を空 + Q列に印 + 済みリストに記録
    python ended_sweep.py --no-cache     # eBay から取り直す (API を消費する)
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cull_end as CE                 # noqa: E402
import cull_writeback as CW           # noqa: E402
import itemid_writeback_audit as IA   # noqa: E402

# 1回で処理する上限。これを超えたら止めて人に見せる (誤った一括処理の防止)。
LIMIT = 400
# ★B列は itemID だけが入る欄ではない。`9999` は「出品しない」確定の見送りマーカー
#   (relist_from_funnel.MIOKURI_B / 女性物など)。eBay に居ないのは当然なので、
#   itemID として扱うと **見送り印を消してしまう** (2026-08-26 の初回実装で 50行以上が対象に入った)。
#   実 itemID は12桁なので、桁数で弾く。
MIOKURI_B = "9999"
ITEMID_MIN_LEN = 11


def is_real_itemid(value):
    """B列の値が **eBay の itemID か** (純関数, test可)。見送り印や手書きは弾く。"""
    v = (value or "").strip()
    return v.isdigit() and len(v) >= ITEMID_MIN_LEN and v != MIOKURI_B


def find_ended(sheet_rows_by_name, live_ids):
    """{シート名: 行2d} と eBay の生存 itemID → 終了済みの itemID 集合 (純関数, test可)。

    B列に **実 itemID** が在るのに eBay に居ない = もう生きていない。
    """
    ended = set()
    for rows in sheet_rows_by_name.values():
        for row in rows[1:]:
            b = row[CW.ITEM_COL - 1].strip() if len(row) >= CW.ITEM_COL else ""
            if is_real_itemid(b) and b not in live_ids:
                ended.add(b)
    return ended


def _read_sheets():
    import gspread
    from google.oauth2.service_account import Credentials
    from relist_writeback import CREDS_PATH, SHEETS
    gc = gspread.authorize(Credentials.from_service_account_file(
        CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"]))
    out = {}
    for cfg in SHEETS:
        out[cfg.get("name") or cfg["id"][:8]] = (
            gc.open_by_key(cfg["id"]).get_worksheet_by_id(cfg["gid"]).get_all_values())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--limit", type=int, default=LIMIT)
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                          # noqa: BLE001
        pass

    try:
        live = IA._fetch_live(use_cache=not a.no_cache)
    except IA.IncompleteFetch as e:
        print(f"⛔ eBay の出品一覧を取り切れていません → 判定しません: {e}")
        return 1
    live_ids = set(live)
    sheets = _read_sheets()
    ended = find_ended(sheets, live_ids)
    known = CE.load_done()
    fresh = ended - known
    print(f"eBay 生存 {len(live_ids)}件 / シートに itemID がある行のうち "
          f"**もう生きていない** {len(ended)}件 (うち未記録 {len(fresh)}件)")
    if not ended:
        print("  後始末は不要です")
        return 0
    if len(ended) > a.limit:
        print(f"⛔ {len(ended)}件は多すぎます (上限 {a.limit})。データ不具合の可能性があるので止めます。")
        print("   中身を確かめてから --limit を上げてください")
        return 1
    if not a.commit:
        print("  → 実際に書くには --commit")
        return 0
    n = CW.apply(ended, commit=True)
    CE.remember_done(sorted(fresh))
    print(f"  ✅ B列を空 + Q列に印: {n}行 / 済みリストに追加: {len(fresh)}件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
