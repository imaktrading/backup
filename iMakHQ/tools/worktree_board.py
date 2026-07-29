"""全 worktree の状況を1画面に出す — 出品専任/Advisor の一元窓口用ボード.

なぜ必要か (2026-07-27 制定):
    ユーザーは監視くん/重複くん/カタログ等と直接やり取りせず、対話中のセッションを窓口にしたい。
    しかし窓口側が各 worktree の状態を知るのに毎回 requests dir を手で漁っていた。

★重要な制約 (グローバル CLAUDE.md「Worktree 分離ルール」):
    **他 worktree のフォルダ (C:/dev/iMak_inventory 等) は読取も禁止**。
    このスクリプトは **共有データ領域 (C:/dev/iMak_data/) だけ**を見る。
    調整に必要な情報 (依頼・回答・その連鎖) は全部そこに出るので、実務上これで足りる。

出力: worktree ごとに
    - 未処理 (自分が返すべき) requests
    - 相手ボール (こちらが出して回答待ち) の依頼
    - 直近の動き (最終更新ファイルと経過時間)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

DATA_ROOT = Path(r"C:\dev\iMak_data")
# 表示名 (ユーザーの呼称に合わせる: 監視くん/抽出くん)
WORKTREES = [
    ("hq", "HQ (自分宛の受領箱)"),
    ("catalog", "カタログ"),
    ("dedupe", "重複くん"),
    ("inventory", "監視くん"),
    ("harvest", "抽出くん"),
    ("revise", "リバイス"),
]
CLOSED_SUFFIXES = (
    "_processed", "_response", "_done", "_expired", "_resolved", "_superseded",
    "_ack", "_reply", "_decision", "_verdict", "_closure", "_withdrawn",
    "_cancelled", "_acknowledged", "_confirm", "_applied", "_close",
)
RECENT_DAYS = 21
MAX_SHOW = 8


def _is_outbound(stem: str, worktree: str) -> bool:
    """こちら (HQ/Advisor) が出した側か = 相手ボール."""
    low = stem.lower()
    return worktree != "hq" and (low.startswith("hq_") or "_hq_" in low)


def _is_closed(path: Path, stems: set[str]) -> bool:
    if path.stem.lower().endswith(CLOSED_SUFFIXES):
        return True
    prefix = path.stem + "_"
    return any(s != path.stem and s.startswith(prefix) for s in stems)


# headless 担当が書く中間成果物。窓口がレビューして `_response.md` に昇格させる。
# **依頼として再 dispatch してはいけない**ので pending とは別枠に分ける。
DRAFT_SUFFIXES = ("_draft", "_question")


def pending_for(worktree: str, recent_days: int = RECENT_DAYS):
    """(自分が返すべき, 相手ボール, 窓口レビュー待ち) の Path list を返す."""
    d = DATA_ROOT / worktree / "requests"
    if not d.is_dir():
        return [], [], []
    cutoff = time.time() - recent_days * 86400
    files = [p for p in d.glob("*.md") if p.stat().st_mtime >= cutoff]
    stems = {p.stem for p in files}
    mine, theirs, drafts = [], [], []
    for p in sorted(files, key=lambda x: -x.stat().st_mtime):
        if p.stem.lower().endswith(DRAFT_SUFFIXES):
            drafts.append(p)
            continue
        if _is_closed(p, stems):
            continue
        (theirs if _is_outbound(p.stem, worktree) else mine).append(p)
    return mine, theirs, drafts


# ★2026-07-30: 実装が「人がそのセッションを開くまで」動かない問題の解消。
# 窓口が draft を検算して `_response.md` に **実装 GO** と書いても、response は「決着済」
# 扱いなので二度と dispatch されず、**誰も実装しないまま滞留**していた。
# (ユーザー指摘:「閉じていいと言ったから立ち上げてない」= セッションを開く前提が崩れている)
# → GO と書かれた response を **実装キュー**として拾い、担当に実装させる。
# ★マーカーは **明示トークン1つだけ**にする (2026-07-30)。
#   最初「実装 GO」等の自然文で拾ったら、**7/22・7/26 の完了済み回答まで実装キューに入った**。
#   誤って再実装させると破壊になりうるので、窓口が意図的に書いた時だけ動くようにする。
#   窓口はこのトークンを、実装させたい `_response.md` の本文に1行入れる。
IMPLEMENT_MARKERS = ("[IMPLEMENT-GO]",)
# 実装完了の印。担当がこれを書いたらキューから外れる (証拠付きの完了報告を兼ねる)。
IMPLEMENT_DONE_SUFFIXES = ("_done", "_applied")


def implement_for(worktree: str, recent_days: int = RECENT_DAYS):
    """実装させるべき `_response.md` を返す (窓口が GO を書いたもの / 未完了のみ)。

    条件 (すべて満たすもののみ):
      - `*_response.md` である (= 窓口が検算して昇格させた正式回答)
      - 本文に実装 GO の印がある (IMPLEMENT_MARKERS)
      - `<stem>_done.md` / `_applied.md` がまだ無い
    """
    d = DATA_ROOT / worktree / "requests"
    if not d.is_dir():
        return []
    cutoff = time.time() - recent_days * 86400
    files = [p for p in d.glob("*.md") if p.stat().st_mtime >= cutoff]
    stems = {p.stem for p in files}
    out = []
    for p in sorted(files, key=lambda x: -x.stat().st_mtime):
        if not p.stem.lower().endswith("_response"):
            continue
        if any(f"{p.stem}{sfx}" in stems for sfx in IMPLEMENT_DONE_SUFFIXES):
            continue
        try:
            body = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if any(m in body for m in IMPLEMENT_MARKERS):
            out.append(p)
    return out


def _age(ts: float) -> str:
    h = (time.time() - ts) / 3600
    if h < 1:
        return f"{int(h * 60)}分前"
    if h < 48:
        return f"{int(h)}時間前"
    return f"{int(h / 24)}日前"


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    cutoff = time.time() - RECENT_DAYS * 86400
    print(f"# worktree ボード (直近{RECENT_DAYS}日 / 共有領域のみ)\n")
    grand_mine = grand_theirs = 0

    for wt, label in WORKTREES:
        d = DATA_ROOT / wt / "requests"
        if not d.is_dir():
            continue
        files = [p for p in d.glob("*.md") if p.stat().st_mtime >= cutoff]
        mine, theirs, drafts = pending_for(wt, RECENT_DAYS)
        latest = max((p.stat().st_mtime for p in files), default=0)

        if not (mine or theirs or drafts):
            state = f"動きなし (最終 {_age(latest)})" if latest else "動きなし"
            print(f"## {label} — {state}")
            print()
            continue

        grand_mine += len(mine)
        grand_theirs += len(theirs)
        print(f"## {label} — 自分が返す {len(mine)}件 / 相手待ち {len(theirs)}件"
              f" / レビュー待ち {len(drafts)}件 (最終 {_age(latest)})")
        for p in drafts[:MAX_SHOW]:
            print(f"- 🟡 **レビュー待ち(headless下書き)** {p.name} ({_age(p.stat().st_mtime)})")
        for p in mine[:MAX_SHOW]:
            print(f"- 🔴 **要返球** {p.name} ({_age(p.stat().st_mtime)})")
        if len(mine) > MAX_SHOW:
            print(f"  …他{len(mine) - MAX_SHOW}件")
        for p in theirs[:MAX_SHOW]:
            print(f"- ⏳ 相手ボール {p.name} ({_age(p.stat().st_mtime)})")
        if len(theirs) > MAX_SHOW:
            print(f"  …他{len(theirs) - MAX_SHOW}件")
        print()

    # ★事務員 (clerk) の死活監視 (2026-07-30)。
    #   事務員は「異常を見つける係」なので、**事務員自身が死ぬと誰も気づけない**。
    #   増員しても解決しない (同じ仕事の人数が増えるだけ) ので、外側から生存を見る。
    #   7/28-7/30 の夜間 cron が exit 0 のまま空振りしていた件と同型の失敗を防ぐ。
    reports = sorted((DATA_ROOT / "clerk" / "reports").glob("*_patrol.md"),
                     key=lambda p: p.stat().st_mtime) if (DATA_ROOT / "clerk" / "reports").is_dir() else []
    if not reports:
        print("⚠️ 事務巡回のレポートが1件も無い — 事務員が動いていない疑い\n")
    else:
        last = reports[-1]
        hours = (time.time() - last.stat().st_mtime) / 3600
        mark = "⚠️ " if hours > 24 else ""
        print(f"{mark}事務巡回: 最終 {_age(last.stat().st_mtime)} ({last.name})"
              + (" — **24h 以上動いていない**" if hours > 24 else "") + "\n")

    print(f"---\n**合計: 要返球 {grand_mine}件 / 相手ボール {grand_theirs}件**")
    if grand_mine:
        print("→ 要返球を先に片付ける。**自分の回答待ちで他 worktree を止めない**。")
    if grand_theirs:
        print("→ 相手ボールが長く動いていなければ督促するか、"
              "headless で当該 worktree を起動して処理させる (Phase2)。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
