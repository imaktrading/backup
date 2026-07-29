"""共有 requests dir を常駐監視し、依頼が置かれたら **即座に** 担当を headless 起動する.

背景 (2026-07-29):
    dispatch_worktree.py を日次 cron にしたら「遅い、リアルタイムだろ」とユーザー指摘。
    依頼を置いてから担当が動くまでの待ちを**秒単位**にするため常駐監視にした。

やること:
    - `C:/dev/iMak_data/<worktree>/requests/` を POLL_SEC ごとに見る (共有領域のみ。worktree は読まない)
    - 未処理 (= 自分が返すべき) が現れた worktree を検出したら `dispatch_worktree` を直列で起動
    - **同じ依頼で二度起動しない** (処理済 file 名を憶える)
    - 書きかけを掴まないよう **DEBOUNCE_SEC 静止してから**動く
    - dispatch 側の lock を尊重するので cron 起動と衝突しない

止め方: タスク `iMakHQ_DispatchWatch` を無効化 or このプロセスを kill。
"""
from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dispatch_worktree as dw  # noqa: E402

POLL_SEC = 15          # 監視間隔
DEBOUNCE_SEC = 20      # 依頼が「書き終わって静止」したと判断するまでの待ち
LOG = dw.REVIEW_DIR / "dispatch_watch.log"


def log(msg: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        dw.REVIEW_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    done: dict[str, set[str]] = {wt: set() for wt in dw.TARGETS}
    seen_at: dict[tuple[str, str], float] = {}
    log(f"watch 開始 (poll={POLL_SEC}s / debounce={DEBOUNCE_SEC}s / 対象={list(dw.TARGETS)})")

    while True:
        try:
            for wt in dw.TARGETS:
                mine, _theirs, _drafts = dw.pending_for(wt)
                fresh = [p for p in mine if p.name not in done[wt]]
                if not fresh:
                    continue
                now = time.time()
                # 書きかけを掴まない: 全部が DEBOUNCE_SEC 以上「変化なし」になってから動く
                ready = True
                for p in fresh:
                    key = (wt, p.name)
                    mt = p.stat().st_mtime
                    if seen_at.get(key) != mt:
                        seen_at[key] = mt
                        ready = False
                    elif now - mt < DEBOUNCE_SEC:
                        ready = False
                if not ready:
                    continue

                names = ", ".join(p.name for p in fresh)
                log(f"[{wt}] 新規 {len(fresh)}件 検出 → dispatch: {names}")
                if not dw.acquire_lock():
                    log(f"[{wt}] 他の dispatch 実行中 → 次の周回で再試行")
                    continue
                try:
                    r = dw._dispatch(wt, dry_run=False)
                    log(f"[{wt}] 完了: {r.get('status')} / {r.get('summary', '')}")
                    for v in r.get("violations", []):
                        log(f"[{wt}] ⚠️ {v}")
                finally:
                    dw.release_lock()
                done[wt].update(p.name for p in fresh)
        except Exception as e:                      # 常駐なので落とさない
            log(f"!! 例外 (継続します): {type(e).__name__}: {e}")
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    raise SystemExit(main())
