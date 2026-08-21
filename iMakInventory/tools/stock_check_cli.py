"""stock_check_cli — 仕入元 URL の在庫を返す CLI (HQ の入稿前ゲート用).

HQ 2026-08-18 依頼 (`inventory/requests/2026-08-18_stock_check_cli_for_upload_gate.md`):
  入稿の直前に「売り切れた現物を出さない」を機械で止めたい。

★ 2026-08-21 設計変更 (`2026-08-20_stock_check_cli_hang_response.md` / 窓口 IMPLEMENT-GO)
  旧版は「実ブラウザで今すぐ見に行く」が既定で、巡回 lock を既定 10 分 無言で待っていた。
  巡回は 1 回 2〜3 時間・4 時間おき (+LOW 8 時間おき) なので 10 分では絶対に空かず、
  「600 秒沈黙して全件 判定不能」が設計どおりの結果になっていた (一度も成功していない)。

  1. 既定は待たない (LOCK_WAIT_MINUTES = 0)。lock が埋まっていたら即座に
     「巡回中なので今は判定できません (開始 HH:MM / 概ね2〜3時間)」と出して終わる。無言にしない。
  2. 既定の動作は **巡回が既に書いた記録を返す** (decision_log)。値 + それを取得した時刻。
     実ブラウザで取りに行くのは `--live` を明示した時だけ (その時だけ lock を待てる)。
  3. 出力はバッファしない (flush)。--json は 1 件ごとに atomic 書き出し (途中で殺されても空にならない)。

判定は巡回本体と同じ `monitor_listings._check_single_url()` をそのまま呼ぶ (二重実装しない)。
そのため fail-closed 特性も同じ: 判定不能は絶対に sold に倒れず unknown になる
(2026-07-25 snkrdunk CSR 化で偽 sold を量産した事故の対策がそのまま効く)。

使用例:
  python -u -m tools.stock_check_cli --urls urls.txt --json out.json           # 記録 (既定・即答)
  python -u -m tools.stock_check_cli --url https://... --live --wait-minutes 0 # 実ブラウザ

出力 (out.json):
  [{"url": "...", "status": "sold"|"in_stock"|"unknown", "source": "record"|"live",
    "checked_at": "2026-08-18T17:20:00", "age_minutes": 34, "reason": "unknown 時のみ"}]
  ※ checked_at は「その値を取得した時刻」。record なら巡回が見た時刻 (= 今ではない)。

exit code:
  0 = 全件判定できた / 1 = unknown が 1 件以上あった (= HQ 側で警告に回す)
  2 = 入力エラー (URL ゼロ等)
  ※ sold があっても 0。「売り切れを見つけた」は正常動作であって異常ではない。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

# 親ディレクトリを sys.path に
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    # errors=replace は cp932 端末対策。line_buffering=True で走行中も 1 行ずつ出る
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

#: 巡回 (cycle) 保持中に解放を待つ上限。★既定 0 = 待たない。
#: 巡回は 2〜3 時間走るので「待てば空く」は成り立たない。待ちたい時だけ --wait-minutes で明示する。
LOCK_WAIT_MINUTES = 0
LOCK_WAIT_POLL_SEC = 20

#: 巡回 1 回の所要 (ユーザー実測)。lock 保持中のメッセージに出して「待っても無駄」を伝える。
CYCLE_TYPICAL = "概ね2〜3時間"

#: --live の chrome 起動上限。uc.Chrome() 自体は timeout を持たないので、無限待ちを外から止める。
DRIVER_START_TIMEOUT_SEC = 120

#: 記録モードで遡る decision_log の本数 (新しい順)。1 本 ≒ 巡回 1 回。
#: 全件 (1,000 本超 / 500MB 超) を舐めないための上限。見つからなければ unknown (fail-closed)。
RECORD_SCAN_FILES = 40

DECISION_LOG_DIR = ROOT_DIR / "decision_log"

#: 巡回本体が書く実記録だけを読む。TEST は test の生成物なので混ぜない。
_RECORD_GLOBS = ("listings_SHEET_*.jsonl", "listings_HIGH_*.jsonl", "listings_LOW_*.jsonl")


def _out(msg: str):
    """走行中でも 1 行ずつ出す (ブロックバッファリングで無言にしない)."""
    print(msg, flush=True)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read_urls(args) -> list:
    """--urls (ファイル) / --url (直接指定) から URL 一覧を作る。重複は保持 (呼出側の行と 1:1)."""
    urls = []
    if args.urls:
        try:
            text = Path(args.urls).read_text(encoding="utf-8")
        except Exception as e:
            print(f"[NG] URL ファイルが読めません: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            return []
        for line in text.splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                urls.append(s)
    urls.extend(args.url or [])
    return urls


def _url_key(url) -> str:
    """同一商品ページを指す URL を突き合わせる key (scheme/大小/末尾スラッシュ/query を無視).

    実例: 巡回は `https://jp.mercari.com/item/m123`、HQ 側は `...?afid=xxx` を持っていることがある。
    path が違うもの (Amazon の /dp/ASIN/ref=... 等) は別物として扱う = 見つからず unknown = 安全側。
    """
    s = str(url or "").strip()
    if not s:
        return ""
    try:
        p = urlsplit(s)
        host = (p.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        path = (p.path or "").rstrip("/")
        if not host:
            return s.lower().rstrip("/")
        return f"{host}{path}".lower()
    except Exception:
        return s.lower().rstrip("/")


# ============================================================================
# 巡回 lock (待たないのが既定。保持中は理由と開始時刻を必ず出す)
# ============================================================================
def _lock_state() -> tuple:
    """(保持中か, 巡回の開始時刻 or None) を返す。判定できなければ (False, None) = 続行."""
    try:
        from run_cycle import LOCK_FILE, _lock_pid_alive, LOCK_STALE_HOURS  # noqa: PLC0415
    except Exception as e:
        print(f"[!] lock 判定を import できません ({type(e).__name__}) → 待たずに続行",
              file=sys.stderr, flush=True)
        return False, None

    if not LOCK_FILE.exists():
        return False, None
    try:
        age = time.time() - LOCK_FILE.stat().st_mtime
        content = LOCK_FILE.read_text(encoding="utf-8", errors="replace")[:200]
        alive = _lock_pid_alive(content)
        # 死んだ pid の残骸 / 6h 超の stale は「保持中」ではない (削除はしない = 巡回側の責務)
        held = not (alive is False or age >= LOCK_STALE_HOURS * 3600)
        if not held:
            return False, None
        started = None
        m = re.search(r"ts=(\S+)", content)
        if m:
            try:
                started = datetime.fromisoformat(m.group(1))
            except Exception:
                started = None
        if started is None:
            started = datetime.fromtimestamp(LOCK_FILE.stat().st_mtime)
        return True, started
    except Exception:
        return True, None   # 読めない = 安全側 (保持中とみなす)


def _lock_reason(wait_minutes: int) -> str:
    """lock 保持中に返す理由文 (巡回の開始時刻つき。無言で終わらせない)."""
    _, started = _lock_state()
    when = f"開始 {started:%H:%M}" if started else "開始時刻 不明"
    if wait_minutes > 0:
        return f"巡回が走行中 ({when} / {wait_minutes}分待っても解放されず)"
    return f"巡回が走行中なので今は判定できません ({when} / {CYCLE_TYPICAL})"


def _wait_for_cycle_lock(wait_minutes: int) -> bool:
    """巡回 lock が解放されるまで待つ。True=空いた / False=保持中 (既定は 0 分 = 即 False).

    ★ lock は取らない (= 取ると次の定期巡回を待たせる)。空いたのを確認して走るだけ。
      走行中に巡回が始まった場合は chrome kill で unknown になるが、fail-closed 側
      (= 偽 sold にはならない) なので安全に倒れる。
    """
    deadline = time.time() + max(0, wait_minutes) * 60
    while True:
        held, _ = _lock_state()
        if not held:
            return True
        if time.time() >= deadline:
            return False
        _out(f"[..] 巡回が走行中。解放待ち (残り {max(0, deadline - time.time()) / 60:.0f} 分)")
        time.sleep(LOCK_WAIT_POLL_SEC)


# ============================================================================
# 既定モード: 巡回が既に書いた記録を返す (ブラウザを開かない = 巡回中でも答えられる)
# ============================================================================
def _record_files(scan_files: int) -> list:
    """decision_log の巡回記録を新しい順に返す (上限つき)."""
    files = []
    for pat in _RECORD_GLOBS:
        try:
            files.extend(DECISION_LOG_DIR.glob(pat))
        except Exception:
            pass
    try:
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        files.sort(key=lambda p: p.name, reverse=True)
    return files[:max(1, scan_files)]


def _row_from_record(url: str, entry: dict, ts: str) -> dict:
    """decision_log の 1 レコード → CLI の出力行 (is_sold の 3 値写像は live と同じ)."""
    row = {"url": url, "source": "record", "checked_at": ts or ""}
    try:
        age = (datetime.now() - datetime.fromisoformat(ts)).total_seconds() / 60
        row["age_minutes"] = int(max(0, age))
    except Exception:
        row["age_minutes"] = None
    is_sold = entry.get("is_sold")
    if is_sold is True:
        row["status"] = "sold"
    elif is_sold is False:
        row["status"] = "in_stock"
    else:
        row["status"] = "unknown"
        row["reason"] = entry.get("error") or "巡回も判定できていない (判定不能のまま記録)"
    return row


def read_recorded(urls: list, scan_files: int = RECORD_SCAN_FILES, on_result=None) -> list:
    """URL 一覧 → 巡回が最後に記録した状態 (入力順を保持)。ブラウザを開かない.

    記録が無い URL は unknown (推測で in_stock にしない = fail-closed)。
    """
    if not urls:
        return []

    wanted = {}
    for u in urls:
        wanted.setdefault(_url_key(u), None)

    files = _record_files(scan_files)
    scanned = 0
    for f in files:
        if all(v is not None for v in wanted.values()):
            break
        scanned += 1
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if not isinstance(rec, dict):
                continue
            ts = rec.get("ts") or ""
            for entry in [rec] + list(rec.get("sub_results") or []):
                if not isinstance(entry, dict):
                    continue
                k = _url_key(entry.get("url"))
                # 新しい file から順に見ているので、最初に当たったものが最新
                if k and k in wanted and wanted[k] is None:
                    wanted[k] = (entry, ts)

    results = []
    for u in urls:
        hit = wanted.get(_url_key(u))
        if hit is None:
            row = {"url": u, "status": "unknown", "source": "record",
                   "checked_at": "", "age_minutes": None,
                   "reason": f"巡回の記録に無い (直近 {scanned} 本を確認)。--live で実取得できます"}
        else:
            row = _row_from_record(u, hit[0], hit[1])
        results.append(row)
        if on_result:
            on_result(results)
    return results


# ============================================================================
# --live: 実ブラウザで今の在庫を取りに行く (巡回 lock が空いている時だけ)
# ============================================================================
def _create_mercari_driver(timeout_sec: int = DRIVER_START_TIMEOUT_SEC) -> tuple:
    """(driver, error) を返す。chrome 起動に上限をかける (uc.Chrome() は自前 timeout を持たない).

    上限を超えたら諦めて続行する (mercari 行だけ unknown = fail-closed)。起動中のスレッドは
    daemon なので プロセス終了で落ちる。orphan chrome は巡回開始時の一括 kill が回収する。
    """
    box = {}

    def _work():
        try:
            from monitor_listings import create_mercari_driver  # noqa: PLC0415
            box["driver"] = create_mercari_driver(headless=True)
        except Exception as e:
            box["error"] = f"{type(e).__name__}: {e}"

    t = threading.Thread(target=_work, daemon=True, name="stock_check_driver")
    t.start()
    t.join(max(1, timeout_sec))
    if t.is_alive():
        return None, f"chrome の起動が {timeout_sec} 秒で終わらない (諦めて続行)"
    if "error" in box:
        return None, box["error"]
    return box.get("driver"), None


def check_urls(urls: list, wait_minutes: int = LOCK_WAIT_MINUTES, on_result=None) -> list:
    """URL 一覧 → 実ブラウザで見た [{url, status, checked_at, ...}] (入力順を保持)."""
    if not urls:
        return []

    if not _wait_for_cycle_lock(wait_minutes):
        # 巡回中。sold を推測で埋めるくらいなら全件 unknown で返す
        # (= HQ 側は「落とさず警告」に回す = 判定不能で出品機会を捨てない)
        reason = _lock_reason(wait_minutes)
        _out(f"[NG] {reason} → 記録でよければ --live を外してください")
        results = []
        for u in urls:
            results.append({"url": u, "status": "unknown", "source": "live",
                            "checked_at": _now(), "age_minutes": 0, "reason": reason})
            if on_result:
                on_result(results)
        return results

    # 遅延 import (lock 待ちの前に重い import をしない)
    from monitor_listings import (  # noqa: PLC0415
        _check_single_url, DEFAULT_SLEEP_SEC,
    )
    from sheet_updater import detect_supplier, _domain_of  # noqa: PLC0415

    needs_mercari = any(detect_supplier(_domain_of(u)) == "mercari" for u in urls)
    mercari_driver = None
    if needs_mercari:
        # driver が上がらなくても snkrdunk 等は判定できる。mercari 行だけ unknown になる
        mercari_driver, err = _create_mercari_driver()
        if err:
            print(f"[!] mercari driver 起動失敗: {err}", file=sys.stderr, flush=True)

    results = []
    try:
        for i, u in enumerate(urls, 1):
            sub = _check_single_url(u, DEFAULT_SLEEP_SEC, mercari_driver, None)
            is_sold = sub.get("is_sold")
            row = {"url": u, "source": "live", "checked_at": _now(), "age_minutes": 0}
            if is_sold is True:
                row["status"] = "sold"
            elif is_sold is False:
                row["status"] = "in_stock"
            else:
                row["status"] = "unknown"
                row["reason"] = sub.get("error") or "判定不能 (理由不明)"
            results.append(row)
            _out(f"[{i}/{len(urls)}] {row['status']:<8} {u}")
            if on_result:
                on_result(results)
    finally:
        if mercari_driver is not None:
            try:
                mercari_driver.quit()
            except Exception:
                pass

    return results


def _write_json(json_out: str, results: list):
    """常に「完全な JSON」だけが見えるように atomic 置換で書く (途中で殺されても空にならない)."""
    out = Path(json_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out)


def main() -> int:
    p = argparse.ArgumentParser(description="仕入元 URL の在庫を返す (入稿前ゲート用)")
    p.add_argument("--urls", help="URL を 1 行 1 件で書いたファイル (# 始まりは無視)")
    p.add_argument("--url", action="append", help="URL を直接指定 (複数可)")
    p.add_argument("--json", dest="json_out", help="結果 JSON の出力先 (省略時は stdout)")
    p.add_argument("--live", action="store_true",
                   help="実ブラウザで今の在庫を取りに行く (巡回中は判定できない)。"
                        "既定は巡回が記録した最新値を返す")
    p.add_argument("--wait-minutes", type=int, default=LOCK_WAIT_MINUTES,
                   help=f"--live 時に巡回 lock の解放を待つ上限 (既定 {LOCK_WAIT_MINUTES} 分 = 待たない)")
    p.add_argument("--scan-files", type=int, default=RECORD_SCAN_FILES,
                   help=f"記録モードで遡る巡回記録の本数 (既定 {RECORD_SCAN_FILES})")
    args = p.parse_args()

    urls = _read_urls(args)
    if not urls:
        print("[NG] URL がゼロ件です (--urls / --url を確認してください)", file=sys.stderr, flush=True)
        return 2

    # 1 件確定するたびに書き出す (途中で殺されても、そこまでの結果は完全な JSON で残る)
    on_result = (lambda rs: _write_json(args.json_out, rs)) if args.json_out else None

    if args.live:
        _out(f"[mode] live — 実ブラウザで {len(urls)} 件を確認します")
        results = check_urls(urls, wait_minutes=args.wait_minutes, on_result=on_result)
    else:
        _out(f"[mode] 記録 — 巡回が最後に見た値を返します ({len(urls)} 件 / 今の値が要るなら --live)")
        results = read_recorded(urls, scan_files=args.scan_files, on_result=on_result)

    if args.json_out:
        _write_json(args.json_out, results)
    else:
        _out(json.dumps(results, ensure_ascii=False, indent=2))

    n_sold = sum(1 for r in results if r["status"] == "sold")
    n_unknown = sum(1 for r in results if r["status"] == "unknown")
    n_stock = sum(1 for r in results if r["status"] == "in_stock")
    ages = [r.get("age_minutes") for r in results if r.get("age_minutes") is not None]
    age_note = f" / 記録の古さ 最大 {max(ages)} 分" if (ages and not args.live) else ""
    _out(f"[結果] 在庫あり {n_stock} 件 / 売切 {n_sold} 件 / 判定不能 {n_unknown} 件{age_note}"
         + (f"  → 出力: {args.json_out}" if args.json_out else ""))
    return 1 if n_unknown else 0


if __name__ == "__main__":
    sys.exit(main())
