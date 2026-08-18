"""stock_check_cli — 仕入元 URL を渡すと「今の在庫」を返す CLI (HQ の入稿前ゲート用).

HQ 2026-08-18 依頼 (`inventory/requests/2026-08-18_stock_check_cli_for_upload_gate.md`):
  入稿の直前に「売り切れた現物を出さない」を機械で止めたい。巡回結果 (シート D 列) は
  1 日古いことがあり、生成〜入稿の間に売れた分を止められない (8/17 cert 153025508 の実害)。

判定は巡回本体と同じ `monitor_listings._check_single_url()` をそのまま呼ぶ (二重実装しない)。
そのため fail-closed 特性も同じ: 判定不能は絶対に sold に倒れず unknown になる
(2026-07-25 snkrdunk CSR 化で偽 sold を量産した事故の対策がそのまま効く)。

使用例:
  python -m tools.stock_check_cli --urls urls.txt --json out.json
  python -m tools.stock_check_cli --url https://jp.mercari.com/item/m123 --json out.json

出力 (out.json):
  [{"url": "...", "status": "sold"|"in_stock"|"unknown",
    "checked_at": "2026-08-18T17:20:00", "reason": "unknown 時のみ"}]

exit code:
  0 = 全件判定できた / 1 = unknown が 1 件以上あった (= HQ 側で警告に回す)
  2 = 入力エラー (URL ゼロ等)
  ※ sold があっても 0。「売り切れを見つけた」は正常動作であって異常ではない。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

# 親ディレクトリを sys.path に
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

#: 巡回 (cycle) 保持中に解放を待つ上限。巡回は開始時に chrome を一括 kill するので、
#: 重なると当 CLI の driver が落ちて全件 unknown になる。待てば普通に判定できる。
LOCK_WAIT_MINUTES = 10
LOCK_WAIT_POLL_SEC = 20


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read_urls(args) -> list:
    """--urls (ファイル) / --url (直接指定) から URL 一覧を作る。重複は保持 (呼出側の行と 1:1)."""
    urls = []
    if args.urls:
        try:
            text = Path(args.urls).read_text(encoding="utf-8")
        except Exception as e:
            print(f"[NG] URL ファイルが読めません: {type(e).__name__}: {e}", file=sys.stderr)
            return []
        for line in text.splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                urls.append(s)
    urls.extend(args.url or [])
    return urls


def _wait_for_cycle_lock(wait_minutes: int) -> bool:
    """巡回 lock が解放されるまで待つ。True=空いた / False=待っても保持中.

    ★ lock は取らない (= 取ると次の定期巡回を待たせる)。空いたのを確認して走るだけ。
      走行中に巡回が始まった場合は chrome kill で unknown になるが、fail-closed 側
      (= 偽 sold にはならない) なので安全に倒れる。
    """
    try:
        from run_cycle import LOCK_FILE, _lock_pid_alive, LOCK_STALE_HOURS  # noqa: PLC0415
    except Exception as e:
        print(f"[!] lock 判定を import できません ({type(e).__name__}) → 待たずに続行", file=sys.stderr)
        return True

    deadline = time.time() + wait_minutes * 60
    while True:
        held = False
        if LOCK_FILE.exists():
            try:
                age = time.time() - LOCK_FILE.stat().st_mtime
                content = LOCK_FILE.read_text(encoding="utf-8", errors="replace")[:200]
                alive = _lock_pid_alive(content)
                # 死んだ pid の残骸 / 6h 超の stale は「保持中」ではない (削除はしない = 巡回側の責務)
                held = not (alive is False or age >= LOCK_STALE_HOURS * 3600)
            except Exception:
                held = True   # 読めない = 安全側 (待つ)
        if not held:
            return True
        if time.time() >= deadline:
            return False
        print(f"[..] 巡回が走行中。解放待ち (残り {max(0, deadline - time.time()) / 60:.0f} 分)")
        time.sleep(LOCK_WAIT_POLL_SEC)


def check_urls(urls: list, wait_minutes: int = LOCK_WAIT_MINUTES) -> list:
    """URL 一覧 → [{url, status, checked_at, reason}] (入力順を保持)."""
    if not urls:
        return []

    if not _wait_for_cycle_lock(wait_minutes):
        # 巡回が長引いている。sold を推測で埋めるくらいなら全件 unknown で返す
        # (= HQ 側は「落とさず警告」に回す = 判定不能で出品機会を捨てない)
        return [{"url": u, "status": "unknown", "checked_at": _now(),
                 "reason": f"巡回が走行中 ({wait_minutes}分待っても解放されず)"} for u in urls]

    # 遅延 import (lock 待ちの前に重い import をしない)
    from monitor_listings import (  # noqa: PLC0415
        _check_single_url, create_mercari_driver, DEFAULT_SLEEP_SEC,
    )
    from sheet_updater import detect_supplier, _domain_of  # noqa: PLC0415

    needs_mercari = any(detect_supplier(_domain_of(u)) == "mercari" for u in urls)
    mercari_driver = None
    if needs_mercari:
        try:
            mercari_driver = create_mercari_driver(headless=True)
        except Exception as e:
            # driver が上がらなくても snkrdunk 等は判定できる。mercari 行だけ unknown になる
            print(f"[!] mercari driver 起動失敗: {type(e).__name__}: {e}", file=sys.stderr)
            mercari_driver = None

    results = []
    try:
        for u in urls:
            sub = _check_single_url(u, DEFAULT_SLEEP_SEC, mercari_driver, None)
            is_sold = sub.get("is_sold")
            if is_sold is True:
                row = {"url": u, "status": "sold", "checked_at": _now()}
            elif is_sold is False:
                row = {"url": u, "status": "in_stock", "checked_at": _now()}
            else:
                row = {"url": u, "status": "unknown", "checked_at": _now(),
                       "reason": sub.get("error") or "判定不能 (理由不明)"}
            results.append(row)
    finally:
        if mercari_driver is not None:
            try:
                mercari_driver.quit()
            except Exception:
                pass

    return results


def main() -> int:
    p = argparse.ArgumentParser(description="仕入元 URL の在庫を返す (入稿前ゲート用)")
    p.add_argument("--urls", help="URL を 1 行 1 件で書いたファイル (# 始まりは無視)")
    p.add_argument("--url", action="append", help="URL を直接指定 (複数可)")
    p.add_argument("--json", dest="json_out", help="結果 JSON の出力先 (省略時は stdout)")
    p.add_argument("--wait-minutes", type=int, default=LOCK_WAIT_MINUTES,
                   help=f"巡回 lock の解放待ち上限 (既定 {LOCK_WAIT_MINUTES} 分)")
    args = p.parse_args()

    urls = _read_urls(args)
    if not urls:
        print("[NG] URL がゼロ件です (--urls / --url を確認してください)", file=sys.stderr)
        return 2

    results = check_urls(urls, wait_minutes=args.wait_minutes)
    payload = json.dumps(results, ensure_ascii=False, indent=2)

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
    else:
        print(payload)

    n_sold = sum(1 for r in results if r["status"] == "sold")
    n_unknown = sum(1 for r in results if r["status"] == "unknown")
    n_stock = sum(1 for r in results if r["status"] == "in_stock")
    print(f"[結果] 在庫あり {n_stock} 件 / 売切 {n_sold} 件 / 判定不能 {n_unknown} 件"
          + (f"  → 出力: {args.json_out}" if args.json_out else ""))
    return 1 if n_unknown else 0


if __name__ == "__main__":
    sys.exit(main())
