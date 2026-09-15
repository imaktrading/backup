"""backfill_size_color_uniqlo_ut - mercari_uniqlo_ut の S/T 列が空の行を埋め直す.

2026-09-14: 抽出ロジックに2つの修正を入れた後、 既存478行には未反映だったので
this スクリプトで再取得する。
  1. `should_skip_color_size` の TCG 誤爆是正 (タイトルが服なら skip しない)
  2. `_extract_size_from_description` 追加 (構造化欄が無い出品は説明文から拾う)

対象は **S 列 (色) or T 列 (サイズ) が空の行だけ**。既に値がある行は触らない。
他列 (A-R) も一切触らない。`backfill_color_size_montbell.py` と同じ骨格 + 収集系
runner と同じ安全策 (途中保存 / 1件失敗の隔離 / driver 再生成) を入れる。
"""
from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

# Windows コンソールの既定コードページ (cp932) だと絵文字ログで落ちる
# (2026-09-14 実害: 10行書込後にクラッシュし、 残り75行が手つかずのままだった)。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers import mercari_item_detail  # noqa: E402
from scrapers._chrome_util import kill_chrome_for_profile  # noqa: E402
from scrapers.mercari_seller import create_anonymous_driver, CHROME_PROFILE_DIR_ANON  # noqa: E402
from sheet_writer_mercari_seller import open_seller_staging_sheet  # noqa: E402

COL_URL = 1
COL_COLOR = 19  # S
COL_SIZE = 20   # T
TAB_NAME = "mercari_uniqlo_ut"
SAVE_EVERY = 10
MAX_CONSECUTIVE_FAILS = 3
MAX_RESTARTS = 3


def _log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def _col_letter(col_1based: int) -> str:
    s = ""
    n = col_1based
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def main() -> int:
    sh = open_seller_staging_sheet()
    ws = sh.worksheet(TAB_NAME)
    all_values = ws.get_all_values()
    _log(f"{TAB_NAME}: 総行数 {len(all_values) - 1}")

    targets: list[tuple[int, str, str, str]] = []  # (row_idx, url, old_color, old_size)
    for idx, row in enumerate(all_values[1:], start=2):
        url = (row[COL_URL - 1] if len(row) >= COL_URL else "").strip()
        if not url:
            continue
        old_color = (row[COL_COLOR - 1] if len(row) >= COL_COLOR else "") or ""
        old_size = (row[COL_SIZE - 1] if len(row) >= COL_SIZE else "") or ""
        if not old_color or not old_size:
            targets.append((idx, url, old_color, old_size))

    _log(f"対象 (色 or サイズが空): {len(targets)} 行")
    if not targets:
        return 0

    s_col = _col_letter(COL_COLOR)
    t_col = _col_letter(COL_SIZE)
    pending: list[dict] = []
    done = 0
    consecutive_fails = 0
    restarts = 0

    def _new_driver():
        kill_chrome_for_profile(CHROME_PROFILE_DIR_ANON)
        return create_anonymous_driver(headless=False)

    driver = _new_driver()

    def _flush() -> None:
        nonlocal pending
        if not pending:
            return
        batch = [
            {"range": f"{s_col}{p['row']}:{t_col}{p['row']}",
             "values": [[p["color"], p["size"]]]}
            for p in pending
        ]
        try:
            ws.batch_update(batch, value_input_option="USER_ENTERED")
            _log(f"  💾 書込: {len(pending)} 行")
            pending = []
        except Exception as e:  # noqa: BLE001
            _log(f"  ⚠️ 書込失敗 (次回に持ち越し): {type(e).__name__}: {e}")

    try:
        for i, (row_idx, url, old_color, old_size) in enumerate(targets, start=1):
            try:
                detail = mercari_item_detail.fetch_detail(driver, url)
                consecutive_fails = 0
            except Exception as e:  # noqa: BLE001
                consecutive_fails += 1
                _log(f"  [{i}/{len(targets)}] row={row_idx} ❌ 例外 {type(e).__name__}: {e}")
                if consecutive_fails >= MAX_CONSECUTIVE_FAILS and restarts < MAX_RESTARTS:
                    restarts += 1
                    _log(f"  🔄 連続{consecutive_fails}件失敗 → driver 再生成 ({restarts}/{MAX_RESTARTS})")
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    driver = _new_driver()
                    consecutive_fails = 0
                continue

            if detail is None:
                _log(f"  [{i}/{len(targets)}] row={row_idx} ⚠️ 詳細取得失敗/削除済: {url}")
                continue

            # ★既に値がある列は再判定しない (2026-09-14 実害: Vision の判定揺れで
            #   4行の色が別物に上書きされた。「空欄を埋める」だけの約束を破っていた)。
            new_color = old_color or (detail.get("color", "") or "")
            new_size = old_size or (detail.get("size", "") or "")
            if new_color != old_color or new_size != old_size:
                pending.append({"row": row_idx, "color": new_color, "size": new_size})
                _log(f"  [{i}/{len(targets)}] row={row_idx} 色:{old_color!r}→{new_color!r} "
                     f"サイズ:{old_size!r}→{new_size!r}")
            done += 1

            if len(pending) >= SAVE_EVERY:
                _flush()
            time.sleep(1.0)
    finally:
        _flush()
        try:
            driver.quit()
        except Exception:
            pass

    _log(f"完了: 処理 {done}/{len(targets)} 件 (driver 再生成 {restarts} 回)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
