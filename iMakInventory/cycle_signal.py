# -*- coding: utf-8 -*-
"""巡回が終わった合図を「既存メンテ」のタブ `合図` に書く (2026-10-14 ブラボー GO B-20261014-004).

ユーザー「監視くんの HIGH が終わればリバイスすれば？」「LOW や公式在庫もあるけど」。
KAGOYA のリバイスくんが 15〜30 分おきに B1〜D1 を読み、前回処理した時刻より新しければ、変わった行だけ直す。
押し合いではなく読みに行く形 (どちらかが落ちても壊れない)。LAPTOP ⇄ KAGOYA で両方が見られるのはスプシだけ。

タブ `合図` の形:
  1 行目: A1 = 説明 / **B1 = HIGH の最新 done_at / C1 = LOW / D1 = OFFICIAL** (リバイスはここだけ読めばよい)
  2 行目: 履歴の見出し (SIGNAL_HEADER)
  3 行目〜: 1 走行 1 行 (足していく)

書くのは「最後まで走って M・在庫の書込が成功した」時だけ (半端な M でリバイスを動かさない)。
書けなくても巡回は止めない (呼び出し側がログに出す)。
"""
from __future__ import annotations

from datetime import datetime

MAINT_SHEET_ID = "1UAVBdosIqqOI8qx-P-4k_ftTGuGWGzfIOU7vk7S2dz4"   # 「既存メンテ」スプシ
SIGNAL_TAB = "合図"
LATEST_CELL = {"HIGH": "B1", "LOW": "C1", "OFFICIAL": "D1", "QUICK": "E1"}
TOP_NOTE = "最新 done_at → B1=HIGH / C1=LOW / D1=OFFICIAL / E1=QUICK (完走して書込が成功した時だけ更新)"
SIGNAL_HEADER = ["label", "started_at", "done_at", "rows", "written", "m_changed", "d_changed", "writer"]
WRITER = "監視くん(LAPTOP)"

# 巡回の label → 合図の種類。CAND は出品前の候補 (eBay に出品が無い) なので出さない。
LABEL_OF_CYCLE = {"SHEET": "HIGH", "HIGH": "HIGH", "LOW": "LOW"}


def now_jst() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def build_row(kind: str, started_at: str, done_at: str, rows: int, written: int,
              m_changed: int, d_changed: int) -> list:
    """履歴の 1 行 (純関数)."""
    return [kind, started_at, done_at, int(rows or 0), int(written or 0),
            int(m_changed or 0), int(d_changed or 0), WRITER]


def decide(kind, sheet_write: dict) -> tuple:
    """合図を書くか (純関数)。(書く?, 書かない理由)."""
    if kind not in LATEST_CELL:
        return False, "合図の対象外の巡回"
    if not isinstance(sheet_write, dict):
        return False, "書込の結果が無い"
    if not sheet_write.get("ok"):
        return False, sheet_write.get("reason") or "書込が成功していない"
    return True, ""


def _open(sheet_id: str):
    """iMakInventory の sheet_updater で開く。公式監視くん (inventory_monitor) にも同じ名前の
    sheet_updater があるので、import 名ではなくこのファイルの隣の物を直接読む。"""
    import importlib.util  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415
    spec = importlib.util.spec_from_file_location(
        "_inv_sheet_updater", Path(__file__).resolve().parent / "sheet_updater.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.open_sheet_by_id(sheet_id)


def write(kind: str, row: list, sheet_id: str = MAINT_SHEET_ID) -> None:
    """タブに 1 行足し、最新のセルを書く (I/O、失敗は例外のまま呼び出し側へ)."""
    sh = _open(sheet_id)
    try:
        ws = sh.worksheet(SIGNAL_TAB)
    except Exception:  # noqa: BLE001 - 無ければ作る
        ws = sh.add_worksheet(title=SIGNAL_TAB, rows=200, cols=len(SIGNAL_HEADER))
        ws.update(values=[[TOP_NOTE, "", "", "", ""], SIGNAL_HEADER], range_name="A1",
                  value_input_option="RAW")
    ws.append_row(row, value_input_option="RAW", table_range="A2")
    ws.update(values=[[TOP_NOTE]], range_name="A1", value_input_option="RAW")
    ws.update(values=[[row[2]]], range_name=LATEST_CELL[kind], value_input_option="RAW")


def signal(kind: str, started_at: str, sheet_write: dict, rows: int, log=print) -> dict:
    """判定して書く。必ず 1 行ログを出す (0 件・書かない時も)."""
    ok, why = decide(kind, sheet_write)
    if not ok:
        log(f"  🔔 合図: 書かない [{kind}] (理由: {why})")
        return {"written": False, "reason": why}
    done_at = now_jst()
    row = build_row(kind, started_at, done_at, rows, sheet_write.get("written", 0),
                    sheet_write.get("m_changed", 0), sheet_write.get("d_changed", 0))
    try:
        write(kind, row)
    except Exception as e:  # noqa: BLE001 - 合図が書けなくても巡回は止めない
        log(f"  🔔 合図: 書けなかった [{kind}] {type(e).__name__}: {e} (次の回で書く)")
        return {"written": False, "reason": f"{type(e).__name__}: {e}"}
    log(f"  🔔 合図: 書いた [{kind}] done_at={done_at} rows={row[3]} written={row[4]} "
        f"m_changed={row[5]} d_changed={row[6]}")
    return {"written": True, "done_at": done_at, "row": row}
