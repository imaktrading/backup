# -*- coding: utf-8 -*-
"""QUICK — 急ぐ出品だけをすぐ見る短い巡回 (2026-10-14 ブラボー GO B-20261014-007).

ユーザー「通常の監視とは別で、走らせるのがあればいいんだ。例えば、補を追加したとか、(急ぐ出品だけを短い間隔で見る)」。
HIGH (6 時間おき) を待たずに、出品くんが「既存メンテ」のタブ `すぐ見る` に書いた itemID の行だけを読み、
M・在庫を書いて、合図 (タブ `合図` の E1 = QUICK_done_at) を出す。

- 10 分おきにタスクで起動。未処理 (状態が空) が無ければすぐ終わる
- **API だけ** (メルカリ mercapi / スニダン 一覧 API / Amazon は requests)。Chrome は立てない = HIGH / CAND と取り合わない。
  API で決まらない行は触らず、次の HIGH に任せる
- **HIGH (と CAND) の巡回中は待つ** (同じ行を HIGH が読んだ古い値で上書きしないため)。行は未処理のまま残し、次の 10 分で見る
- 売切になった行は取下げ待ちに積み、その場で取下げを送る (毎時を待たない)
- 復活と急落の「2 回確認」は数えない (数分おきの読み直しで 2 回にしない。通常の巡回で数える)
- ★ 2026-10-14 (B-20261014-010、ユーザー「急ぐ出品は一番安い仕入元だけ見ればいい」): 理由に「急ぐ」がある行は
  **1 時間おきに繰り返し** 見る (処理時刻から 55 分たったら また見る)。読むのは 控えで一番安い生きている 1 本だけ
  (売切・値上がりの時だけ次へ。monitor_listings.check_one_row_cheapest)。理由=補を書いた 等は 1 回だけ全部読む

タブ `すぐ見る` の列: itemID / 理由 / 依頼時刻 / 依頼者 / 状態 / 処理時刻 / 結果
  出品くんが 1〜4 列を足す。監視くんが 5〜7 列を書く (状態 = 済 / シートに無い)。
"""
from __future__ import annotations

import os
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

MAINT_SHEET_ID = "1UAVBdosIqqOI8qx-P-4k_ftTGuGWGzfIOU7vk7S2dz4"   # 「既存メンテ」スプシ
QUICK_TAB = "すぐ見る"
QUICK_HEADER = ["itemID", "理由", "依頼時刻", "依頼者", "状態", "処理時刻", "結果"]
COL_STATE, COL_DONE_AT, COL_RESULT = 5, 6, 7          # 1 始まり
HIGH_SHEET_ID = "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk"
LABEL = "QUICK"
DECISION_LOG_DIR = SCRIPT_DIR / "decision_log"
QUICK_LOCK = DECISION_LOG_DIR / ".quick.lock"
MAX_ITEMS_PER_RUN = 200                               # 1 回に見る上限 (メルカリ API の負担を抑える)
URGENT_WORD = "急ぐ"
URGENT_EVERY_MIN = 55                                 # 急ぐ行を また見るまでの分 (10 分おきの起動なので 実質 1 時間おき)


def _log(msg: str) -> None:
    line = f"[{datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        with (SCRIPT_DIR / "logs" / f"quick_{datetime.now():%Y-%m-%d}.log").open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


# ── 純関数 ────────────────────────────────────────────────────────────────
def _parse_ts(s: str):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(str(s).strip(), fmt)
        except ValueError:
            continue
    return None


def pending_rows(values: list, now: datetime = None) -> list:
    """タブの値 (見出し込み) → 今回見る [(シート行番号, itemID, 急ぐ?)] (純関数).

    同じ itemID が何行あっても 1 つにまとめ、いちばん下の行に結果を書く。
    見るのは 状態が空の行 か、急ぐ行で最後に見てから URGENT_EVERY_MIN 分たった物。
    """
    now = now or datetime.now()
    last = {}                                         # itemID → (行番号, 急ぐ?, 状態, 処理時刻)
    for i, r in enumerate(values[1:], start=2):
        r = list(r) + [""] * len(QUICK_HEADER)
        iid = str(r[0]).strip()
        if not iid:
            continue
        urgent = URGENT_WORD in str(r[1])
        prev = last.get(iid)
        last[iid] = (i, urgent or bool(prev and prev[1]), str(r[COL_STATE - 1]).strip(),
                     str(r[COL_DONE_AT - 1]).strip())
    out = []
    for iid, (row_no, urgent, state, done_at) in last.items():
        if not state:
            out.append((row_no, iid, urgent))
            continue
        if urgent:
            t = _parse_ts(done_at)
            if t is None or (now - t).total_seconds() >= URGENT_EVERY_MIN * 60:
                out.append((row_no, iid, urgent))
    return out


def result_text(res) -> tuple:
    """process_sheet の item_results の 1 件 → (状態, 結果)."""
    if res is None:
        return "シートに無い", "HIGH の商品管理シートに この itemID の行が無い (9999 や出品前の行も含む)"
    if res.get("is_sold") is True:
        return "済", f"売切 ({res.get('raw_status') or ''}) → 取下げ待ちへ"
    if res.get("is_sold") is False:
        p = res.get("price_jpy")
        return "済", f"在庫あり M=¥{p:,}" if isinstance(p, int) else "在庫あり (値段は書かない)"
    return "済", f"API で決まらず ({(res.get('error') or '')[:60]}) → 次の HIGH で見る"


# ── I/O ────────────────────────────────────────────────────────────────────
def high_cycle_running() -> bool:
    """HIGH (と CAND) の巡回が動いているか。run_cycle と同じ lock を同じ判定で見る."""
    import run_cycle as rc  # noqa: PLC0415
    lf = rc.LOCK_FILE
    if not lf.exists():
        return False
    try:
        content = lf.read_text(encoding="utf-8", errors="replace")[:200]
        age = time.time() - lf.stat().st_mtime
    except OSError:
        return False
    alive = rc._lock_pid_alive(content)
    if alive is False:
        return False
    return age < rc.LOCK_STALE_HOURS * 3600


def _take_own_lock() -> bool:
    """QUICK どうしの二重起動を防ぐ (10 分おきなので前の回が長引いた時)."""
    if QUICK_LOCK.exists():
        try:
            import run_cycle as rc  # noqa: PLC0415
            if rc._lock_pid_alive(QUICK_LOCK.read_text(encoding="utf-8", errors="replace")) is not False \
                    and time.time() - QUICK_LOCK.stat().st_mtime < 3600:
                return False
        except Exception:  # noqa: BLE001
            return False
    QUICK_LOCK.write_text(f"pid={os.getpid()} host={socket.gethostname()} ts={datetime.now().isoformat()}\n",
                          encoding="utf-8")
    return True


def _open_tab():
    from sheet_updater import open_sheet_by_id  # noqa: PLC0415
    sh = open_sheet_by_id(MAINT_SHEET_ID)
    try:
        return sh.worksheet(QUICK_TAB)
    except Exception:  # noqa: BLE001 - 無ければ作る
        ws = sh.add_worksheet(title=QUICK_TAB, rows=500, cols=len(QUICK_HEADER))
        ws.update(values=[QUICK_HEADER], range_name="A1", value_input_option="RAW")
        return ws


def run() -> int:
    ws = _open_tab()
    pend = pending_rows(ws.get_all_values())
    if not pend:
        return 0                      # 何も無い回は ログも出さない (10 分おきなので)
    if high_cycle_running():
        _log(f"⏸ QUICK: 未処理 {len(pend)} 件。HIGH (または CAND) の巡回中なので待つ (次の 10 分で見る)")
        return 0
    if not _take_own_lock():
        _log("⏸ QUICK: 前の QUICK がまだ動いている")
        return 0
    try:
        return _run_items(ws, pend[:MAX_ITEMS_PER_RUN])
    finally:
        QUICK_LOCK.unlink(missing_ok=True)


def _run_items(ws, pend: list) -> int:
    import cycle_signal as sig  # noqa: PLC0415
    import monitor_listings as ml  # noqa: PLC0415
    started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ids = {iid for _, iid, _u in pend}
    urgent = {iid for _, iid, u in pend if u}
    _log(f"▶ QUICK: {len(ids)} 件 (急ぐ {len(urgent)} 件は一番安い 1 本だけ / ほか {len(ids) - len(urgent)} 件は全部)")
    stats = ml.process_sheet(sheet_id=HIGH_SHEET_ID, sheet_label=LABEL, rows_filter="listed",
                             only_item_ids=ids, api_only=True, cheapest_only_ids=urgent)
    items = stats.get("item_results") or {}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cells = []
    for row_no, iid, _u in pend:
        state, text = result_text(items.get(iid))
        cells += [{"range": f"E{row_no}:G{row_no}", "values": [[state, now, text]]}]
    if cells:
        ws.batch_update(cells, value_input_option="RAW")
    # 売切は その場で取下げを送る (毎時を待たない)
    if stats.get("newly_sold"):
        try:
            import subprocess  # noqa: PLC0415
            r = subprocess.run([sys.executable, "-u", "-m", "tools.drain_pending_takedowns", "--execute"],
                               cwd=str(SCRIPT_DIR), capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=600,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            _log(f"  取下げをその場で送った (rc={r.returncode})")
        except Exception as e:  # noqa: BLE001 - 送れなくても毎時の取下げが拾う
            _log(f"  [!] 取下げをその場で送れなかった (毎時の取下げが拾う): {type(e).__name__}: {e}")
    sig.signal("QUICK", started, stats.get("sheet_write"), stats.get("processed", 0),
               log=lambda m: _log(m.strip()))
    _log(f"■ QUICK 終わり: 見た {stats.get('processed', 0)} 件 / 売切 {stats.get('newly_sold', 0)} / "
         f"復活 {stats.get('newly_in_stock', 0)} / エラー {stats.get('errors', 0)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(run())
    except Exception as e:  # noqa: BLE001
        _log(f"[NG] QUICK 例外: {type(e).__name__}: {e}")
        sys.exit(1)
