#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CULL で取り下げた後の管理スプシ後始末 (取下再出品の③に相当)。

なぜ必要か (2026-08-24 ユーザー決定):
    `cull_end.py` はスプシを触らないので、取り下げても **B列に死んだ itemID が残る**。
    このシステムは **B列が埋まっている = 出品済み** として動くので、
    仕入元が復活しても「もう出している」と判断されて二度と出品されない
    (実測: 361件 End のうち 167件 がスプシに残っていた)。

決めたこと (案C):
    - **B列は空にする** … 仕入元が復活したら出品候補に戻す
    - **Q列(FLG)に `CULL <日付>` を残す** … 取り下げた事実を消さない
    - **回数を数える** … `CULL <日付>` → `CULL 2 <日付>` → `CULL 3 <日付>` …
      何回で諦めるかは後からデータを見て決める (印の側で打ち切らない)

使い方:
    python cull_writeback.py                      # 一覧を出すだけ
    python cull_writeback.py --commit             # 書く
    python cull_writeback.py --from-backup <json> # B列を先に空にしてしまった時の後追い
"""
from __future__ import annotations

import argparse
import csv
import datetime
import glob
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

FLG_COL = 17          # Q列「FLG」(1始まり)。全行 空なのを確認済 (2026-08-24)
ITEM_COL = 2          # B列「itemID」
RESULT_DIRS = [
    os.path.join(os.environ.get("USERPROFILE", ""), "OneDrive", "デスクトップ", "新しいフォルダー"),
    os.path.join(os.environ.get("USERPROFILE", ""), "OneDrive", "デスクトップ"),
]


# ★2026-08-24: 番号は **日付の手前の1〜3桁** に限る。`CULL\s*(\d*)` だと
#   `CULL 2026-08-24` の「2026」を回数として読んでしまう (実際に踏んだ)。
#   日付を必須にすることで、番号のある/なしを取り違えない。
_CULL_RE = re.compile(r"CULL(?:\s+(\d{1,3}))?\s+\d{4}-\d{2}-\d{2}")


def _col_letter(n):
    return chr(64 + n) if n <= 26 else "A" + chr(64 + n - 26)


def next_flag(current, today):
    """Q列の次の値を決める (純関数, test可)。

    ★2026-08-24 ユーザー決定: **回数を数える**。上限で止めない。
      `CULL <日付>` → `CULL 2 <日付>` → `CULL 3 <日付>` …
      「何回で諦めるか」は後からデータを見て決めたいので、印の側では打ち切らない
      (×2 で止めると、そこから先の情報が消える)。
      1回目は番号なし = 既に書いた 167件をそのまま1回目として使える。
    """
    cur = (current or "").strip()
    if not cur:
        return f"CULL {today}"
    m = _CULL_RE.search(cur)
    if not m:
        return f"{cur} / CULL {today}"          # 他の印は壊さず足す
    n = int(m.group(1)) if m.group(1) else 1
    nxt = f"CULL {n + 1} {today}"
    head = cur[:m.start()].strip(" /")
    return f"{head} / {nxt}" if head else nxt


def cull_count(current):
    """Q列の値 → これまでに CULL された回数 (0 = 一度もない)。純関数。"""
    m = _CULL_RE.search(current or "")
    if not m:
        return 0
    return int(m.group(1)) if m.group(1) else 1


# ★2026-08-25: **「既に閉じている」は成功と同じ**。目的 (出品が生きていない) は達成済み。
#   実害: 356901060098 (G-SHOCK RANGEMAN GW-9400J-1JF) は 8/15 に自然終了しており、
#   8/23 の取下げで 1047 が返った。Status=Success の行しか後始末しなかったので
#   **B列に死んだ itemID が残り**、仕入元が戻ってもこの商品は二度と出品されない状態だった。
#   取下げ側 (cull_end) は 8/24 に同じ穴を塞いだが、スプシの後始末側が残っていた。
_ALREADY_ENDED_CODE = "1047"


def is_ended_row(r):
    """End 結果 CSV の1行 → その出品はもう生きていないか (純関数, test可)。"""
    if not (r.get("ItemID") or "").strip():
        return False
    if r.get("Status") == "Success":
        return True
    if (r.get("ErrorCode") or "").strip() == _ALREADY_ENDED_CODE:
        return True
    msg = ((r.get("ErrorMessage") or "") + (r.get("Message") or "")).lower()
    return "already been closed" in msg or "already closed" in msg


def ended_ids_from_results(paths):
    """eBay の End 結果 CSV 群 → **もう生きていない** itemID 集合 (純関数寄り, test可)。"""
    out = set()
    for p in paths:
        try:
            for r in csv.DictReader(io.open(p, encoding="utf-8-sig")):
                if is_ended_row(r):
                    out.add(r["ItemID"].strip())
        except OSError:
            continue
    return out


def is_result_file(path):
    """eBay の **アップ結果** か (こちらが作った End CSV と区別する)。純関数寄り, test可。

    ★2026-08-24: 自分で作った `cull_end_YYYYMMDD.csv` まで拾っていた。
      中身が違う (Status 列が無い) ので実害は無いが、件数が合わず紛らわしい。
      結果ファイルには **Status 列がある** ので、そこで見分ける。
    """
    try:
        with io.open(path, encoding="utf-8-sig") as f:
            head = f.readline()
    except OSError:
        return False
    return "Status" in head.split(",")


def find_result_files(days=2):
    """直近の End 結果 CSV を探す (eBay のアップ結果だけ)。"""
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    hits = []
    for d in RESULT_DIRS:
        if not os.path.isdir(d):
            continue
        for p in glob.glob(os.path.join(d, "cull_end_*.csv")):
            try:
                if datetime.datetime.fromtimestamp(os.path.getmtime(p)) < cutoff:
                    continue
            except OSError:
                continue
            if is_result_file(p):
                hits.append(p)
    return sorted(set(hits))


def apply(ended_ids, commit=False, today=None):
    """取り下げ済みの itemID 集合 → B列を空 + Q列に印。処理した行数を返す。

    ★2026-08-24: 取下げを API 直送にしたので、**結果ファイルを介さずその場で呼べる**
      入口が要る (どれが成功したかは送った側が知っている)。
      main() はこれを結果ファイル/控え経由で呼ぶだけにする。
    """
    import gspread
    from google.oauth2.service_account import Credentials
    from relist_writeback import CREDS_PATH, SHEETS

    ended = {str(i).strip() for i in ended_ids if str(i).strip()}
    if not ended:
        return 0
    today = today or datetime.date.today().strftime("%Y-%m-%d")
    cr = Credentials.from_service_account_file(
        CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(cr)
    done = 0
    for cfg in SHEETS:
        ws = gc.open_by_key(cfg["id"]).get_worksheet_by_id(cfg["gid"])
        vals = ws.get_all_values()
        ups = []
        for n, row in enumerate(vals[1:], start=2):
            b = row[ITEM_COL - 1].strip() if len(row) >= ITEM_COL else ""
            if not b or b not in ended:
                continue
            cur = row[FLG_COL - 1].strip() if len(row) >= FLG_COL else ""
            ups.append({"range": f"{_col_letter(FLG_COL)}{n}",
                        "values": [[next_flag(cur, today)]]})
            ups.append({"range": f"{_col_letter(ITEM_COL)}{n}", "values": [[""]]})
        if ups and commit:
            ws.batch_update(ups)
        done += len(ups) // 2
    return done


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                          # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="実際に書く (既定は一覧のみ)")
    ap.add_argument("--from-backup", default="", help="B列を先に空にした時の控え JSON")
    a = ap.parse_args()

    import gspread
    from google.oauth2.service_account import Credentials
    from relist_writeback import CREDS_PATH, SHEETS

    today = datetime.date.today().strftime("%Y-%m-%d")
    cr = Credentials.from_service_account_file(
        CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(cr)

    # 対象の作り方は2通り。既定は eBay の結果 CSV。
    by_row = {}                        # (label, row) → itemID
    if a.from_backup:
        for b in json.load(io.open(a.from_backup, encoding="utf-8")):
            by_row[(b["sheet"], b["row"])] = b["item_id"]
        print(f"控えから {len(by_row)}件 (B列は既に空の想定)")
    else:
        files = find_result_files()
        if not files:
            sys.exit("End 結果 CSV が見つかりません (デスクトップ / 新しいフォルダー を見ます)")
        ended = ended_ids_from_results(files)
        print(f"End 結果 {len(files)}ファイル → 成功 {len(ended)}件")
        for f in files:
            print(f"  {os.path.basename(f)[:60]}")

    plan = []
    for cfg in SHEETS:
        ws = gc.open_by_key(cfg["id"]).get_worksheet_by_id(cfg["gid"])
        vals = ws.get_all_values()
        rows = []
        for n, row in enumerate(vals[1:], start=2):
            cur_flg = row[FLG_COL - 1].strip() if len(row) >= FLG_COL else ""
            if a.from_backup:
                if (cfg["label"], n) not in by_row:
                    continue
            else:
                b = row[ITEM_COL - 1].strip() if len(row) >= ITEM_COL else ""
                if not b or b not in ended:
                    continue
            rows.append((n, cur_flg, next_flag(cur_flg, today)))
        plan.append((cfg, ws, rows))
        n2 = sum(1 for _n, c, _v in rows if c.strip())
        print(f"  {cfg['label'][:30]:<32} 対象 {len(rows):>4}件 (うち2回目 {n2}件)")

    total = sum(len(r) for _c, _w, r in plan)
    print(f"\n対象 合計 {total}件")
    if not total:
        return 0
    if not a.commit:
        for _c, _w, rows in plan:
            for n, cur, new in rows[:4]:
                print(f"    {n}行目  Q: {cur!r} → {new!r}")
            break
        print("→ 実際に書くには --commit")
        return 0

    for cfg, ws, rows in plan:
        if not rows:
            continue
        ups = [{"range": f"{_col_letter(FLG_COL)}{n}", "values": [[v]]} for n, _c, v in rows]
        if not a.from_backup:                      # 結果 CSV 経由なら B列も空にする
            ups += [{"range": f"{_col_letter(ITEM_COL)}{n}", "values": [[""]]}
                    for n, _c, _v in rows]
        ws.batch_update(ups)
        print(f"  {cfg['label'][:30]:<32} {len(rows)}件 書きました")
    print("完了")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
