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
URGENT_BATCH_WINDOW_MIN = 10                          # 出品くんの「同じ回」とみなす依頼時刻の幅


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
    ★ 2026-10-14 (B-20261014-010 追加、出品くんの指摘): 見直し (55 分ごと) の対象は **出品くんの直近の回**
      (急ぐの行で一番新しい依頼時刻から URGENT_BATCH_WINDOW_MIN 分以内) に載った itemID だけ。
      急ぐでなくなった出品が見直しに残り続けないため。出品くんは 2 時間おきに今の急ぐを全部載せ直す。
    """
    now = now or datetime.now()
    urgent_times = [t for t in (_parse_ts((list(r) + [""] * 3)[2]) for r in values[1:]
                                if URGENT_WORD in str((list(r) + [""] * 2)[1])) if t]
    latest = max(urgent_times) if urgent_times else None
    in_latest = set()
    if latest is not None:
        for r in values[1:]:
            r = list(r) + [""] * len(QUICK_HEADER)
            t = _parse_ts(r[2])
            if URGENT_WORD in str(r[1]) and t and (latest - t).total_seconds() <= URGENT_BATCH_WINDOW_MIN * 60:
                in_latest.add(str(r[0]).strip())
    last = {}                                         # itemID → (行番号, 急ぐ?, 状態, 処理時刻)
    for i, r in enumerate(values[1:], start=2):
        r = list(r) + [""] * len(QUICK_HEADER)
        iid = str(r[0]).strip()
        if not iid:
            continue
        own_urgent = URGENT_WORD in str(r[1])
        last[iid] = (i, own_urgent, str(r[COL_STATE - 1]).strip(), str(r[COL_DONE_AT - 1]).strip())
    out = []
    for iid, (row_no, urgent, state, done_at) in last.items():
        if not state:
            # いちばん下の行が「補を書いた」等なら 全部読む (新しい補を読むため)。急ぐの行なら 1 本だけ
            out.append((row_no, iid, urgent))
            continue
        if iid in in_latest:
            urgent = True                             # 見直しは 急ぐの扱い (一番安い 1 本だけ)
            t = _parse_ts(done_at)
            if t is None or (now - t).total_seconds() >= URGENT_EVERY_MIN * 60:
                out.append((row_no, iid, urgent))
    return out


def merged_rows(values: list) -> list:
    """同じ itemID の下に新しい行がある、状態が空の古い行 → [(行番号, まとめ先の行番号)] (純関数).

    ★ 2026-10-15 (ブラボー・出品くんの確認): 結果は いちばん下の行にだけ書くので、出品くんが 2 時間おきに
      載せ直すたびに 上の古い行が状態=空のまま残り、「未処理 327 行」に見えていた (実際は見ている)。
    """
    last = {}
    for i, r in enumerate(values[1:], start=2):
        iid = str((list(r) + [""])[0]).strip()
        if iid:
            last[iid] = i
    out = []
    for i, r in enumerate(values[1:], start=2):
        r = list(r) + [""] * len(QUICK_HEADER)
        iid = str(r[0]).strip()
        if iid and not str(r[COL_STATE - 1]).strip() and last.get(iid, i) > i:
            out.append((i, last[iid]))
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
def _cmdline_of(pid: int) -> str:
    """pid のコマンドライン (取れなければ "")。窓を出さずに CIM で見る."""
    import subprocess  # noqa: PLC0415
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                            f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return (r.stdout or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def is_cand_cmdline(cmd: str) -> bool:
    """CAND (出品前の候補だけ見る巡回) か (純関数)。CAND は QUICK と同じ行を触らないので待たなくてよい."""
    return "--sheet-label CAND" in (cmd or "")


def high_cycle_running() -> bool:
    """HIGH (SHEET) の巡回が動いているか。run_cycle と同じ lock を同じ判定で見る.

    ★ 2026-10-14: CAND も同じ lock を使う (Chrome の profile を共有するため)。CAND は itemID 空の行だけ書くので
      QUICK (itemID ありの行) とは触る行が重ならない → lock の持ち主が CAND なら待たない
      (初日、SHEET 13:30〜15:32 の後に CAND 15:33〜 が続き、QUICK が 3 時間待った)。
    """
    import re  # noqa: PLC0415
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
    if alive is False or age >= rc.LOCK_STALE_HOURS * 3600:
        return False
    m = re.search(r"pid=(\d+)", content)
    if m and is_cand_cmdline(_cmdline_of(int(m.group(1)))):
        return False
    return True


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


_values_cache: dict = {}

# ★ 2026-10-15 (ブラボー GO): タブ `すぐ見る` は 出品くんの 2 時間おきの載せ直しで 1 日 約 2,000 行増える。
#   毎日 1 回、処理から 1 日たった 済・まとめた・シートに無い の行を `すぐ見る_済` へ移す (出品くんには他人の行を消させない)。
#   `すぐ見る_済` は 30 日より古い行を消す。ログに「すぐ見る_済へ移した N行 / 残り M行」。
ARCHIVE_TAB = "すぐ見る_済"
ARCHIVE_AFTER_HOURS = 24
ARCHIVE_KEEP_DAYS = 30
ARCHIVE_STATE = DECISION_LOG_DIR / "quick_archive_state.json"
DONE_STATES = {"済", "まとめた", "シートに無い"}


def rows_to_archive(values: list, now: datetime = None) -> list:
    """移す行の行番号 (純関数)。処理時刻から ARCHIVE_AFTER_HOURS たった 済・まとめた・シートに無い の行."""
    now = now or datetime.now()
    out = []
    for i, r in enumerate(values[1:], start=2):
        r = list(r) + [""] * len(QUICK_HEADER)
        if str(r[COL_STATE - 1]).strip() not in DONE_STATES:
            continue
        t = _parse_ts(r[COL_DONE_AT - 1])
        if t and (now - t).total_seconds() >= ARCHIVE_AFTER_HOURS * 3600:
            out.append(i)
    return out


def _ranges_desc(rows: list) -> list:
    """行番号 → 続いている範囲 [(始め, 終わり)] を 下から順に (消す時に上の行番号がずれないように)."""
    out = []
    for r in sorted(rows):
        if out and r == out[-1][1] + 1:
            out[-1][1] = r
        else:
            out.append([r, r])
    return [tuple(x) for x in reversed(out)]


def archive_daily(ws, values: list, now: datetime = None) -> None:
    import json  # noqa: PLC0415
    now = now or datetime.now()
    today = now.strftime("%Y-%m-%d")
    try:
        st = json.loads(ARCHIVE_STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    if st.get("date") == today:
        return
    rows = rows_to_archive(values, now)
    sh = ws.spreadsheet
    try:
        aws = sh.worksheet(ARCHIVE_TAB)
    except Exception:  # noqa: BLE001
        aws = sh.add_worksheet(title=ARCHIVE_TAB, rows=1000, cols=len(QUICK_HEADER))
        aws.update(values=[QUICK_HEADER], range_name="A1", value_input_option="RAW")
    if rows:
        moved = [(list(values[i - 1]) + [""] * len(QUICK_HEADER))[:len(QUICK_HEADER)] for i in rows]
        aws.append_rows(moved, value_input_option="RAW", table_range="A1")   # 先に写す (消してから写すと失う)
        for a, b in _ranges_desc(rows):
            ws.delete_rows(a, b)
    # すぐ見る_済 の 30 日より古い行を消す
    av = aws.get_all_values()
    old = [i for i, r in enumerate(av[1:], start=2)
           if (t := _parse_ts((list(r) + [""] * len(QUICK_HEADER))[COL_DONE_AT - 1]))
           and (now - t).days > ARCHIVE_KEEP_DAYS]
    for a, b in _ranges_desc(old):
        aws.delete_rows(a, b)
    ARCHIVE_STATE.write_text(json.dumps({"date": today, "moved": len(rows)}), encoding="utf-8")
    _log(f"🗄 すぐ見る_済へ移した {len(rows)}行 / 残り {len(values) - 1 - len(rows)}行 (すぐ見る_済 から 30 日より古い {len(old)}行を消した)")


def run() -> int:
    ws = _open_tab()
    values = ws.get_all_values()
    try:
        if not high_cycle_running():
            archive_daily(ws, values)
            values = ws.get_all_values()
    except Exception as e:  # noqa: BLE001 - 整理できなくても見るのは続ける
        _log(f"  [!] すぐ見る_済への整理に失敗 (見るのは続ける): {type(e).__name__}: {e}")
    _values_cache["v"] = values
    pend = pending_rows(values)
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
    # 同じ itemID の古い行 (状態が空) には「まとめた」を書く (未処理に見せない)
    for row_no, to_row in merged_rows(_values_cache.get("v") or []):
        cells.append({"range": f"E{row_no}:G{row_no}", "values": [["まとめた", now, f"行 {to_row} にまとめて見た"]]})
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
