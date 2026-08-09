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
# 同時に走らせる worktree 数。★2026-07-30: 3 → 5 → 6。
#   3 では harvest / revise が待たされた (実測)。その後 HQ も自動実装の対象にしたため、
#   全 6 worktree が同時に走れる 6 にする。**上限が対象数を下回ると、そこが待ち行列になる**。
#   1 worktree = headless claude 1本。上げるほど課金と CPU を使うので、対象数以上には上げない。
MAX_PARALLEL = 6
LOG = dw.REVIEW_DIR / "dispatch_watch.log"

# ★2026-08-02: 死んでも誰も気づかない問題の対策 (2日で2回、人が手で再起動している)。
#   watcher が生きている限り毎周回この file を touch する。**これが唯一の生存証明**。
#   - 起動時: heartbeat が新しければ「本物が生きている」→ 新インスタンスは即終了 (多重起動防止)
#   - 起動時: heartbeat が古ければ「前のは死んでいる」→ 引き継いで走る (幽霊 Running の解除)
#   Task Scheduler の `IgnoreNew` に多重起動防止を任せていたが、**プロセスが無いのに
#   Running に張り付く幽霊状態**になると 30分ごとの再起動トリガが全部弾かれ、
#   8/1 は 9時間停止した。判定を「Task Scheduler の状態」から「実際の heartbeat」に移す。
HEARTBEAT = dw.REVIEW_DIR / "dispatch_watch.heartbeat"
# 生存とみなす上限。POLL_SEC(15s) の数倍。dispatch 中も main loop は回るので伸びない。
ALIVE_SEC = 90


def log(msg: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        dw.REVIEW_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def heartbeat_age() -> float | None:
    """heartbeat の経過秒。file が無ければ None (純関数に近い read-only)."""
    try:
        return time.time() - HEARTBEAT.stat().st_mtime
    except OSError:
        return None


def is_alive() -> bool:
    """本物の watcher が生きているか。**Task Scheduler の状態を見ない** (幽霊を掴むため)."""
    age = heartbeat_age()
    return age is not None and age < ALIVE_SEC


def beat() -> None:
    try:
        dw.REVIEW_DIR.mkdir(parents=True, exist_ok=True)
        HEARTBEAT.write_text(f"{datetime.now():%Y-%m-%d %H:%M:%S}\n", encoding="utf-8")
    except OSError:
        pass


# ★2026-08-03: 失敗した実装を再投入するまでの待ち。0 にすると 30分 timeout を
#   15秒ごとに繰り返す hot loop になる (課金と CPU をひたすら焼く)。
RETRY_COOLDOWN_SEC = 15 * 60


def _run_one(wt: str, names: str, done: dict, fresh_names: list, inflight: set, lock,
             mode: str = "draft", fail_at: dict | None = None) -> None:
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
        # ★2026-08-02: **成功した時だけ**処理済にする。
        #   従来は exit1 (usage limit・API エラー等) でも処理済に入れていたため、
        #   失敗した依頼は二度と拾われず滞留した (8/1 の `_BC_response.md` が実例)。
        #   失敗を憶えない = 次の周回で自然に再試行される (fail-OPEN を作らない)。
        if r.get("status") == "ok":
            with lock:
                done[wt].update(fresh_names)
        else:
            # ★2026-08-03: 実装キューは **走らせる前に** 処理済へ入れていたため、
            #   ここで「再試行する」と書いても実際は二度と拾われなかった
            #   (8/2 の offer_calc 実装が timeout → 10時間放置。8/1 に潰したのと同型が
            #    実装キュー側に残っていた)。**登録を成功時だけにし、失敗は覚えて冷ます**。
            with lock:
                done[wt].difference_update(fresh_names)
                if fail_at is not None:
                    now = time.time()
                    for n in fresh_names:
                        fail_at[(wt, n)] = now
            log(f"[{wt}] ⚠️ 失敗のため処理済にしない "
                f"({RETRY_COOLDOWN_SEC // 60}分後に再試行): {names}")
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
    impl_fail_at: dict[tuple[str, str], float] = {}   # (worktree, file名) → 最後に失敗した時刻
    seen_at: dict[tuple[str, str], float] = {}
    inflight: set[str] = set()          # 今走っている worktree
    guard = threading.Lock()

    # ★多重起動防止は **heartbeat で判定する** (Task Scheduler の Running 状態は幽霊化する)。
    if is_alive():
        log(f"既に生きている watcher がある (heartbeat {heartbeat_age():.0f}秒前) → このインスタンスは終了")
        return 0
    age = heartbeat_age()
    if age is not None:
        log(f"前の watcher は停止していた (heartbeat {age / 60:.0f}分前) → 引き継ぐ")
    beat()
    log(f"watch 開始 (poll={POLL_SEC}s / debounce={DEBOUNCE_SEC}s / 並行={MAX_PARALLEL} / "
        f"対象={list(dw.TARGETS)})")

    while True:
        beat()          # ★生存証明。これが止まった = watcher が死んだ
        try:
            # ★2026-08-09: `_routing/` の草案を **窓口を通さず自動投入**する。
            #   従来は窓口が手で `--inject` するまで相手に届かず、しかも `_routing/` は
            #   draft_triage の対象外だったため **7日間 8件 溜まっても警告が出なかった**。
            #   ここで流せば、以降は下の dispatch がそのまま担当を起こす。
            try:
                import route_inbox as ri
                r = ri.auto_route()
                for name, to in r["injected"]:
                    log(f"routing 自動投入: {to} ← {name}")
                for name in r["unknown"]:
                    log(f"routing 宛先不明 (保留): {name}")
            except Exception as _re:
                log(f"!! routing 自動投入 skip: {type(_re).__name__}: {_re}")

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
                if wt == "hq" and dw.hq_busy():
                    continue          # 窓口が同じ worktree を編集中 → 次の周回で
                with guard:
                    if wt in inflight or len(inflight) >= MAX_PARALLEL:
                        continue
                todo = dw.implement_for(wt)
                _now = time.time()
                fresh = [p for p in todo
                         if p.name not in impl_done[wt]
                         # 直前に失敗した件は冷ますまで再投入しない (hot loop 防止)
                         and _now - impl_fail_at.get((wt, p.name), 0) >= RETRY_COOLDOWN_SEC]
                if not fresh:
                    continue
                names = ", ".join(p.name for p in fresh)
                fresh_names = [p.name for p in fresh]
                with guard:
                    inflight.add(wt)
                    # ★同じ周回で二重に起こさないための印。**失敗したら _run_one が取り消す**
                    #   (従来はここで入れっぱなしにして、失敗しても二度と拾わなかった)
                    impl_done[wt].update(fresh_names)
                threading.Thread(target=_run_one, daemon=True,
                                 args=(wt, names, impl_done, fresh_names, inflight, guard,
                                       "implement", impl_fail_at)).start()
        except Exception as e:                      # 常駐なので落とさない
            log(f"!! 例外 (継続します): {type(e).__name__}: {e}")
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    # ★2026-08-02: 落ちた事実を必ず残す。8/1・8/2 とも **ログに何も無いまま消えていて**
    #   死因を追えなかった。終了は必ず1行書く (次に落ちた時に理由が分かるように)。
    try:
        _rc = main()
    except BaseException as _e:                                # noqa: BLE001
        log(f"!! watch 終了: {type(_e).__name__}: {_e}")
        raise
    log(f"!! watch 終了 (rc={_rc})")
    raise SystemExit(_rc)
