# -*- coding: utf-8 -*-
"""買えない仕入元の台帳と補URL消込の日別本数を、メインPC から見えるスプシへ写す (2026-09-28 ADV 依頼).

監視くんが LAPTOP に移ってから、監視くんが書く次の3つがメインPC に届かなくなった
(LAPTOP の C:\\dev\\iMak_data はメインPC と共有されていない):
  - not_buyable_urls.json         (売切で消した補URL = 二度と候補に出さない)
  - not_buyable_restockable.json  (売切だが再入荷しうる = 候補を後ろへ回す)
  - cleared_backups_archive.jsonl (消した補URL の控え)

出品くん (メインPC) は「既存メンテ」スプシのタブ「買えない仕入元」も読んでファイルと合わせる
(iMakHQ tools/mercari_psa_resource.py, 2026-09-27)。列は url / 種類 / 理由 / 日時 / 書いた担当、
種類は not_buyable | restockable。ここではそのタブを LAPTOP の台帳の中身で **丸ごと書き直す**
(再入荷台帳は在庫が戻ると消えるので、追記では消えた分が残ってしまう)。

消込の控えは全文ではなく 1日1行 (日付 / 消した本数) をタブ「補URL消込_日別」へ書く。

どちらも書けなくても巡回は止めない (出品側の都合で、取下げの正しさには影響しない)。
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

MAINT_SHEET_ID = "1UAVBdosIqqOI8qx-P-4k_ftTGuGWGzfIOU7vk7S2dz4"   # 「既存メンテ」スプシ
NOT_BUYABLE_TAB = "買えない仕入元"
CLEAR_DAILY_TAB = "補URL消込_日別"
TAB_HEADER = ["url", "種類", "理由", "日時", "書いた担当"]
CLEAR_DAILY_HEADER = ["日付", "消した本数"]
WRITER = "監視くん(LAPTOP)"


def build_tab_rows(not_buyable: dict, restockable: dict) -> list:
    """2つの台帳 → タブの2次元配列 (見出し付き、純関数).

    同じ URL が両方にあれば not_buyable を残す (二度と出さない方が安全側)。
    """
    rows = [TAB_HEADER]
    seen = set()
    for kind, ledger in (("not_buyable", not_buyable), ("restockable", restockable)):
        for url in sorted((ledger or {})):
            u = (url or "").strip()
            if not u or u in seen:
                continue
            seen.add(u)
            v = ledger[url] if isinstance(ledger[url], dict) else {}
            rows.append([u, kind, str(v.get("why", "")), str(v.get("at", "")), WRITER])
    return rows


def build_clear_daily_rows(archive_lines) -> list:
    """消込の控え (jsonl の各行) → [日付, 消した本数] の表 (見出し付き、日付の昇順、純関数).

    ts は "2026/09/28 17:23:54" 形式。読めない行は数えない。
    """
    per_day = Counter()
    for line in archive_lines:
        try:
            d = json.loads(line)
        except (ValueError, TypeError):
            continue
        ts = str(d.get("ts") or "") if isinstance(d, dict) else ""
        day = ts[:10].replace("/", "-")
        if len(day) == 10:
            per_day[day] += 1
    return [CLEAR_DAILY_HEADER] + [[day, per_day[day]] for day in sorted(per_day)]


def _load_json_dict(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _rewrite_tab(sh, title: str, rows: list) -> None:
    """タブを rows で丸ごと書き直す。無ければ作る。

    先に上書きしてから余った下の行を消す (一度空にすると、その間に出品くんが読んだ時に空に見える)。
    """
    import gspread  # noqa: PLC0415
    try:
        ws = sh.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=max(len(rows) + 50, 100), cols=len(rows[0]))
    if ws.row_count < len(rows):
        ws.add_rows(len(rows) - ws.row_count + 50)
    ws.update(values=rows, range_name="A1", value_input_option="RAW")
    if ws.row_count > len(rows):
        ws.batch_clear([f"A{len(rows) + 1}:{chr(ord('A') + len(rows[0]) - 1)}{ws.row_count}"])


def sync(not_buyable_path: Path, restockable_path: Path, archive_path: Path,
         sheet_id: str = MAINT_SHEET_ID) -> dict:
    """台帳と消込の日別本数をスプシへ写す (I/O)。失敗しても例外は出さず結果に書く."""
    nb = _load_json_dict(not_buyable_path)
    rs = _load_json_dict(restockable_path)
    tab_rows = build_tab_rows(nb, rs)
    try:
        lines = archive_path.read_text(encoding="utf-8").splitlines() if archive_path.exists() else []
    except OSError:
        lines = []
    daily_rows = build_clear_daily_rows(lines)
    result = {"not_buyable": sum(1 for r in tab_rows[1:] if r[1] == "not_buyable"),
              "restockable": sum(1 for r in tab_rows[1:] if r[1] == "restockable"),
              "clear_days": len(daily_rows) - 1, "error": None}
    try:
        from sheet_updater import open_sheet_by_id  # noqa: PLC0415
        sh = open_sheet_by_id(sheet_id)
        _rewrite_tab(sh, NOT_BUYABLE_TAB, tab_rows)
        _rewrite_tab(sh, CLEAR_DAILY_TAB, daily_rows)
    except Exception as e:  # noqa: BLE001
        result["error"] = f"{type(e).__name__}: {e}"
    return result
