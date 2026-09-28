# -*- coding: utf-8 -*-
"""別PC (LAPTOP) とやり取りするための受け箱 (2026-09-29 ユーザー確定・案2)。

## なぜ要るか

監視くんは LAPTOP に移り、**LAPTOP からは C:/dev/iMak_data が見えない**。
依頼書 (requests/*.md) を置いても届かないので、2026-09-28 の依頼は
メッセージに要点を書いて渡すしかなかった。メッセージは相手の窓が閉じていると届かず、
後から開いても受け取れないので、**閉じている間の用件が落ちる**。

## 決め (ユーザー確定 2026-09-29)

1. **記録の正は これまでどおり requests/ のファイル**。受け箱はファイル名 + 本文を写すだけ
2. **回答も同じ受け箱に書く** (監視くんは LAPTOP から requests/ に書けないため)
3. 置き場所: 「既存メンテ」スプシのタブ **`受け箱`** (両方の PC から見える唯一の共有場所)

## 使い方

    python request_box.py post --to 監視くん --file 2026-09-29_xxx.md --from ADV --body "本文"
    python request_box.py post --to 監視くん --file 2026-09-29_xxx.md --from ADV --body-file <path>
    python request_box.py list                 # 未処理 (状態が空) だけ
    python request_box.py list --all
    python request_box.py done <id> --note "..."   # 処理済にする

列: id / 日時 / 宛先 / 差出 / ファイル名 / 本文 / 状態 / 処理日時 / 備考
本文はセル上限 (5万字) に収まる長さにする。長い時は要点だけ写し、全文はファイルを見る。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TAB = "受け箱"
HEADER = ["id", "日時", "宛先", "差出", "ファイル名", "本文", "状態", "処理日時", "備考"]
_CELL_MAX = 45000


def _now():
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _read():
    from sheet_io import read_tab
    rows = read_tab(TAB)
    if not rows or not rows[0] or rows[0][0] != HEADER[0]:
        return [HEADER]
    return rows


def next_id(rows):
    """既存行の最大 id + 1 (純関数)。"""
    mx = 0
    for r in rows[1:]:
        try:
            mx = max(mx, int((r[0] or "").strip()))
        except Exception:                                      # noqa: BLE001
            continue
    return mx + 1


def build_row(rid, to, frm, fname, body, now=None):
    """1行ぶんを組み立てる (純関数)。本文はセル上限で切る。"""
    body = (body or "").strip()
    if len(body) > _CELL_MAX:
        body = body[:_CELL_MAX - 20] + "\n…(以下はファイル)"
    return [str(rid), now or _now(), to, frm, fname, body, "", "", ""]


def pending(rows):
    """状態が空の行だけ返す (純関数)。"""
    return [r for r in rows[1:] if r and len(r) > 6 and not (r[6] or "").strip()]


def mark_done(rows, rid, note=""):
    """id の行を処理済にした rows を返す (純関数)。見つからなければ None。"""
    hit = False
    out = [list(r) for r in rows]
    for r in out[1:]:
        if (r[0] or "").strip() == str(rid):
            while len(r) < len(HEADER):
                r.append("")
            r[6], r[7], r[8] = "処理済", _now(), note
            hit = True
    return out if hit else None


def post(to, fname, body, frm):
    rows = _read()
    rid = next_id(rows)
    rows.append(build_row(rid, to, frm, fname, body))
    from sheet_io import write_rows_to_tab
    write_rows_to_tab(TAB, rows)
    print(f"✅ 受け箱に置きました id={rid} 宛先={to} ファイル={fname}")
    return rid


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("post")
    p.add_argument("--to", required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--from", dest="frm", required=True)
    p.add_argument("--body")
    p.add_argument("--body-file")
    lp = sub.add_parser("list")
    lp.add_argument("--all", action="store_true")
    dp = sub.add_parser("done")
    dp.add_argument("id")
    dp.add_argument("--note", default="")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                          # noqa: BLE001
        pass

    if a.cmd == "post":
        body = a.body or ""
        if a.body_file:
            with open(a.body_file, encoding="utf-8") as f:
                body = f.read()
        return 0 if post(a.to, a.file, body, a.frm) else 1
    if a.cmd == "list":
        rows = _read()
        tgt = rows[1:] if a.all else pending(rows)
        print(f"受け箱 {len(tgt)}件" + ("" if a.all else " (未処理)"))
        for r in tgt:
            print(f"  [{r[0]}] {r[1]} {r[3]}→{r[2]}  {r[4]}  {(r[6] or '未処理')}")
        return 0
    if a.cmd == "done":
        rows = _read()
        out = mark_done(rows, a.id, a.note)
        if out is None:
            print(f"id={a.id} が受け箱にありません")
            return 1
        from sheet_io import write_rows_to_tab
        write_rows_to_tab(TAB, out)
        print(f"✅ id={a.id} を処理済にしました")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
