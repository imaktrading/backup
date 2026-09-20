# -*- coding: utf-8 -*-
"""月1回の取り込みが「走ったのに失敗した」時に、翌日 気づける形にする (2026-09-20 常設).

## なぜ要るか (実害)

OPCG の公式 dump 更新は月1回の自動。**9/01 の回が検証で巻き戻って失敗**したが、
誰も気づかず、見つかったのは **9/13 に人が手で調べた時**。月1回なので1回落ちると
次は翌月 = **2か月 新弾が catalog に入らない**。
「失敗しても誰も気づかない」= fail-OPEN。気づく面をこちらに作る。

## 何を見るか (走った結果だけ。走らせはしない)

    OPCG dump      _opcg_official_dumps の一番新しい日付 (45日より古い = 止まっている)
                   + タスク iMakCatalog_OpcgDumpRefresh の前回の結果コード
    月次の取り込み  iMakCatalog_TcgMonthly / iMakCatalog_UniqloMonthly の前回の結果コード

## 見つけたらどうするか

**持ち主の受け箱に依頼書を置く** (口頭で言っても残らない):

    OPCG dump       → HQ の持ち物   C:/dev/iMak_data/hq/requests/
    月次の取り込み   → カタログ自身  C:/dev/iMak_data/catalog/requests/

同じ話を毎日置かないよう、**同じ内容なら1日1回まで** (state ファイルで判定)。
直ったら state を消して、次に壊れた時にまた出る。

実行:
  python tools/scheduled_ingest_watch.py
  python tools/scheduled_ingest_watch.py --dry-run   # 依頼書を書かない
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

DATA = Path("C:/dev/iMak_data/catalog")
DUMPS = DATA / "_opcg_official_dumps"
HQ_REQ = Path("C:/dev/iMak_data/hq/requests")
CAT_REQ = DATA / "requests"
STATE = DATA / "_scheduled_ingest_watch_state.json"
STALE_DAYS = 45  # opcg_dump_refresh.py の基準に合わせる

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def task_result(name: str):
    """タスクの前回の結果コード。取れなければ None (落とさない)."""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            f"(Get-ScheduledTask -TaskName '{name}' | Get-ScheduledTaskInfo)"
                            ".LastTaskResult"],
                           capture_output=True, text=True, timeout=120)
        return int(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def dump_age_days():
    files = list(DUMPS.glob("series_*.json"))
    if not files:
        return None
    return (time.time() - max(f.stat().st_mtime for f in files)) / 86400


def dump_not_ingested() -> int | None:
    """dump に在って catalog に無いカードの数.

    ★dump の日付だけ見ると騙される。2026-09-17 の回は **取得だけ済んで取り込み前に落ちた**ので、
      dump は新しいのに DB には入っていない状態だった (日付は3日前 = 緑に見える)。
      本当に見たいのは「取りこぼしているカードが在るか」なので、中身で数える。
    """
    import sqlite3
    ids = set()
    for f in DUMPS.glob("series_*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        rows = d if isinstance(d, list) else (d.get("cards") or d.get("items") or [])
        for r in rows:
            n = (r.get("card_number") or r.get("cardNumber") or r.get("product_id") or "").strip()
            if n:
                ids.add(n)
    if not ids:
        return None
    try:
        con = sqlite3.connect(f"file:{DATA / 'products.sqlite'}?mode=ro", uri=True, timeout=120)
        have = {r[0] for r in con.execute(
            "SELECT product_id FROM products WHERE category='one_piece_tcg'")}
    except sqlite3.Error:
        return None
    finally:
        try:
            con.close()
        except Exception:
            pass
    return len(ids - have)


def problems() -> list[tuple[str, str, str]]:
    """(置き先, 見出し, 本文) の一覧. 空 = 問題なし."""
    out = []

    age = dump_age_days()
    rc = task_result("iMakCatalog_OpcgDumpRefresh")
    missing = dump_not_ingested()
    if missing:
        out.append(("hq", "opcg_dump_not_ingested",
                    f"ワンピースの dump に在って **catalog に無いカードが {missing}枚** あります。"
                    f"(dump は {age:.0f}日前 / 前回のタスクの結果コード {rc})\n"
                    "取得だけ済んで取り込みが終わっていない状態です。"
                    "`iMakHQ/tools/opcg_dump_refresh.py` を最後まで走らせてください。"))
    elif age is None or age > STALE_DAYS:
        aged = "1件も無い" if age is None else f"{age:.0f}日前"
        out.append(("hq", "opcg_dump_stale",
                    f"ワンピースの公式 dump が **{aged}** です (基準 {STALE_DAYS}日)。"
                    f"前回のタスクの結果コード: {rc}。\n"
                    "月1回の自動なので、このまま待つと次は翌月になり、"
                    "**その間の新弾が catalog に入りません**。\n"
                    "`iMakHQ/tools/opcg_dump_refresh.py` を手で1回 走らせて、結果を返してください。"))
    elif rc not in (0, None):
        # 前回は失敗しているが、**取りこぼしは0枚で dump も期限内** = 実害が出ていない。
        # 依頼書は置かず、ログに出すだけにする (毎日 同じ紙を置くと読まれなくなる)。
        print(f"    (記録のみ) dump 更新の前回の結果コードが {rc}。"
              f"取りこぼし0枚 / dump {age:.0f}日前なので依頼書は置きません")

    for name, label in (("iMakCatalog_TcgMonthly", "TCG の月次取り込み"),
                        ("iMakCatalog_UniqloMonthly", "UNIQLO の月次取り込み")):
        rc = task_result(name)
        # 267011 = まだ1度も走っていない (異常ではない)
        if rc not in (0, None, 267011):
            out.append(("catalog", f"{name}_failed",
                        f"{label} (`{name}`) が **失敗しています** (結果コード {rc})。\n"
                        f"ログ: `{DATA}/_tcg_monthly_log.txt` / `_uniqlo_monthly_log.txt`。\n"
                        "月1回なので、直さないと次は翌月です。"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        state = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}

    probs = problems()
    today = date.today().isoformat()
    if not probs:
        print(f"[{today}] 月次の取り込み: 問題なし ✅")
        if state and not args.dry_run:
            STATE.unlink(missing_ok=True)  # 直った = 次に壊れた時にまた出す
        return 0

    for where, key, body in probs:
        print(f"[{today}] ⚠️ {key}: {body.splitlines()[0]}")
        if state.get(key) == today:
            print("    (今日はもう置いたので置きません)")
            continue
        if args.dry_run:
            continue
        d = HQ_REQ if where == "hq" else CAT_REQ
        f = d / f"{today}_{key}.md"
        f.write_text(
            f"# 自動の見張り: {key}\n\n"
            f"- 発行日 {today} / 発行者 Catalog `tools/scheduled_ingest_watch.py` / 緊急度 中\n"
            f"- 判定: 値の話ではなく **走るはずの処理が走っていない** 件です\n\n"
            f"{body}\n\n"
            "直ったらこの依頼書を `_processed.md` にリネームしてください。\n"
            "同じ状態が続く限り、**1日1回**ここに出ます。\n",
            encoding="utf-8")
        print(f"    依頼書を置きました: {f}")
        state[key] = today

    if not args.dry_run:
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
