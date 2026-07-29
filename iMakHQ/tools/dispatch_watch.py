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
MAX_PARALLEL = 3       # 同時に走らせる worktree 数 (課金と CPU の上限。0 = 無制限にしない)
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


def _run_one(wt: str, names: str, done: dict, fresh_names: list, inflight: set, lock,
             mode: str = "draft") -> None:
    """1 worktree 分を最後まで走らせる (別スレッド)。例外は握って常駐を守る。"""
    try:
        _what = "実装" if mode == "implement" else "新規"
        log(f"[{wt}] {_what} {len(fresh_names)}件 検出 → dispatch: {names}")
        if not dw.acquire_lock(wt):
            log(f"[{wt}] 同じ worktree の dispatch が実行中 → 次の周回で再試行")
            return
        try:
            r = dw._dispatch(wt, dry_run=False, mode=mode)
            log(f"[{wt}] 完了: {r.get('status')} / {r.get('summary', '')}")
            for v in r.get("violations", []):
                log(f"[{wt}] ⚠️ {v}")
        finally:
            dw.release_lock(wt)
        with lock:
            done[wt].update(fresh_names)
    except Exception as e:
        log(f"[{wt}] !! 例外 (継続します): {type(e).__name__}: {e}")
    finally:
        with lock:
            inflight.discard(wt)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    import threading
    done: dict[str, set[str]] = {wt: set() for wt in dw.TARGETS}
    impl_done: dict[str, set[str]] = {wt: set() for wt in dw.TARGETS}
    seen_at: dict[tuple[str, str], float] = {}
    inflight: set[str] = set()          # 今走っている worktree
    guard = threading.Lock()
    log(f"watch 開始 (poll={POLL_SEC}s / debounce={DEBOUNCE_SEC}s / 並行={MAX_PARALLEL} / "
        f"対象={list(dw.TARGETS)})")

    while True:
        try:
            for wt in dw.TARGETS:
                # ★2026-07-30: 担当ごとに **並行**で走らせる (従来は全体で1本の lock =
                # 直列だったため、依頼を出した担当が前の担当の終了を数分待たされていた)。
                # worktree は別々で、headless は共有DB/スプシへ書けないので衝突しない。
                with guard:
                    if wt in inflight or len(inflight) >= MAX_PARALLEL:
                        continue
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
                fresh_names = [p.name for p in fresh]
                with guard:
                    inflight.add(wt)
                threading.Thread(target=_run_one, daemon=True,
                                 args=(wt, names, done, fresh_names, inflight, guard)).start()

            # ★2026-07-30: 実装キュー。窓口が `_response.md` に「実装 GO」と書いた案件を
            # 担当が自分で実装する。従来はここが **人がセッションを開くまで動かない**
            # 待ち行列になっており、GO を出した案件が全部滞留していた。
            for wt in dw.TARGETS:
                if wt in dw.NO_AUTO_IMPLEMENT:
                    continue
                with guard:
                    if wt in inflight or len(inflight) >= MAX_PARALLEL:
                        continue
                todo = dw.implement_for(wt)
                fresh = [p for p in todo if p.name not in impl_done[wt]]
                if not fresh:
                    continue
                names = ", ".join(p.name for p in fresh)
                fresh_names = [p.name for p in fresh]
                with guard:
                    inflight.add(wt)
                    impl_done[wt].update(fresh_names)   # 走らせたら再投入しない (完了印は担当が書く)
                threading.Thread(target=_run_one, daemon=True,
                                 args=(wt, names, impl_done, fresh_names, inflight, guard,
                                       "implement")).start()
        except Exception as e:                      # 常駐なので落とさない
            log(f"!! 例外 (継続します): {type(e).__name__}: {e}")
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    raise SystemExit(main())
