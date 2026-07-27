"""Advisor SessionStart hook — 起動時に「現在地」と「未処理 requests」を強制表示する.

なぜ必要か (2026-07-27 制定):
    Advisor は CLAUDE.md に「daily_report を読め」と書いてあっても、指示遵守頼みだと読み飛ばす。
    さらに 2026-07-27 まで参照先 memory が 4/28 で凍結した dir を指しており、3ヶ月前の知識で
    毎回起動していた。→ 物理的に context へ流し込む方式に切替える。

出力するもの:
    1. worktree / branch / uncommitted (自分の位置確認 = グローバル CLAUDE.md の必須アクション)
    2. daily_report.md の最上段 1 ブロック (= 現在地 + 次の一手)
    3. 各 worktree の未処理 requests (_processed / _response が付いていない .md)

出品専任セッションの audit_catchup.py と同じ位置づけ (あちらは CSV 監査の catch-up 専用)。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

MEMORY_DIR = Path(r"C:\Users\imax2\.claude\projects\c--dev-iMak\memory")
DAILY_REPORT = MEMORY_DIR / "daily_report.md"
DATA_ROOT = Path(r"C:\dev\iMak_data")
WORKTREES = ["hq", "catalog", "dedupe", "inventory", "harvest", "revise"]
REPO = Path(r"C:\dev\iMak")

# daily_report の最上段ブロックだけ出す (全文は数千行あるので context を食い潰す)
MAX_REPORT_LINES = 60


def _git(*args: str) -> str:
    try:
        out = subprocess.run(
            ["git", *args], cwd=REPO, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=15,
        )
        return (out.stdout or "").strip()
    except Exception:
        return ""


def _position() -> list[str]:
    root = _git("rev-parse", "--show-toplevel") or "(git 応答なし)"
    branch = _git("branch", "--show-current") or "(不明)"
    dirty = _git("status", "--porcelain")
    n_dirty = len([ln for ln in dirty.splitlines() if ln.strip()])
    lines = [f"- worktree: {root} / branch: {branch}"]
    if branch and branch != "master":
        lines.append(
            f"  ⚠️ Advisor は master 固定が規約。branch={branch} は想定外 → 作業前にユーザーへ報告すること。"
        )
    if n_dirty:
        lines.append(
            f"  ⚠️ uncommitted {n_dirty} 件あり。**出品専任セッションの作業中ファイルかもしれない**。"
            f" `git add -A` は禁止 (自分が触ったファイルだけ明示 add)。"
        )
    else:
        lines.append("  - uncommitted: なし (clean)")
    return lines


def _daily_head() -> list[str]:
    if not DAILY_REPORT.exists():
        return [f"⚠️ daily_report が見つからない: {DAILY_REPORT}"]
    text = DAILY_REPORT.read_text(encoding="utf-8", errors="replace").splitlines()

    # ヘッダ (先頭の '---' まで) を飛ばし、最初の '## ' セクションを1つだけ取る
    out: list[str] = []
    started = False
    for line in text:
        if not started:
            if line.startswith("## "):
                started = True
                out.append(line)
            continue
        if line.startswith("## "):  # 次のセクションに入ったら打切り
            break
        out.append(line)
        if len(out) >= MAX_REPORT_LINES:
            out.append("  …(以降は daily_report.md を直接読むこと)")
            break
    return out or ["(daily_report にセクションが無い)"]


# 「もう閉じている」ことを示す末尾語 (小文字比較)。依頼書 filename 連鎖規約の終端。
CLOSED_SUFFIXES = (
    "_processed", "_response", "_done", "_expired", "_resolved", "_superseded",
    "_ack", "_reply", "_decision", "_verdict", "_closure", "_withdrawn",
    "_cancelled", "_acknowledged", "_confirm", "_applied", "_close",
)
# 何日前まで見るか (古い backlog を毎回出すと context を潰して逆効果)
RECENT_DAYS = 21
MAX_PER_WORKTREE = 12


def _is_closed(path: Path, stems: set[str], worktree: str) -> bool:
    """自分が返すべきものでないか.

    - 終端語で終わる / 後続ファイル (stem + '_...') が存在する = 閉じた依頼
    - worktree dir 内の `hq_` 由来ファイル = **こちらが出した側** (= 相手ボール)。
      返球済なので自分の未処理には出さない。
    """
    low = path.stem.lower()
    if low.endswith(CLOSED_SUFFIXES):
        return True
    if worktree != "hq" and (low.startswith("hq_") or "_hq_" in low):
        return True
    prefix = path.stem + "_"
    return any(s != path.stem and s.startswith(prefix) for s in stems)


def _pending_requests() -> list[str]:
    import time

    cutoff = time.time() - RECENT_DAYS * 86400
    lines: list[str] = []
    total = 0
    for wt in WORKTREES:
        d = DATA_ROOT / wt / "requests"
        if not d.is_dir():
            continue
        files = list(d.glob("*.md"))
        stems = {p.stem for p in files}
        pending = sorted(
            p for p in files
            if not _is_closed(p, stems, wt) and p.stat().st_mtime >= cutoff
        )
        if not pending:
            continue
        total += len(pending)
        shown = [p.name for p in pending[:MAX_PER_WORKTREE]]
        more = len(pending) - len(shown)
        tail = f" …他{more}件" if more else ""
        lines.append(f"- **{wt}** ({len(pending)}件): " + " / ".join(shown) + tail)
    if not lines:
        return [f"- 未処理なし (直近 {RECENT_DAYS} 日)"]
    lines.append(
        f"→ 直近 {RECENT_DAYS} 日で 合計 {total} 件。"
        "**自分の回答待ちで他 worktree を止めない** (相手が先に進める部分を切り出して即返球する)。"
    )
    lines.append(
        "  ※ ここに出るのは「終端語が無く後続も無い」もの。古い backlog は意図的に除外している "
        f"(必要なら requests dir を直接見る)。"
    )
    return lines


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    print("[Advisor への指示] セッション開始。以下が現在地。推測で喋る前にこれを踏まえること。")
    print()
    print("## 1. 自分の位置")
    print("\n".join(_position()))
    print()
    print(f"## 2. 現在地 ({DAILY_REPORT.name} 最上段)")
    print("\n".join(_daily_head()))
    print()
    print("## 3. 未処理 requests (調整ハブの本務)")
    print("\n".join(_pending_requests()))
    print()
    print(
        "※ memory は出品専任と共有 (junction)。書込先も同じ dir。"
        " 区切りごとに commit / push / daily_report 追記 (見出しに [Advisor] 署名・Edit のみ)。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
