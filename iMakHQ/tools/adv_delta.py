"""相手セッションが前回確認以降に何をしたかを差分表示する (出品専任 ⇄ Advisor 両用).

なぜ必要か (2026-07-27 制定):
    Advisor と出品専任は memory / repo を共有しているが、**共有されるのはファイルの実体だけ**で、
    相手の変更が自分の context に自動で入るわけではない。ユーザーに「ADV がこう決めた」と
    毎回伝えさせるのは手間なので、両セッションが自分で相手の差分を取りに行く。

出力するもの (前回実行時点からの差分):
    1. 新しい commit
    2. daily_report.md に増えた「相手の署名」セクション
    3. requests dir で新規作成 / 更新された .md

使い方:
    python adv_delta.py                    # 出品専任として実行 (相手 = Advisor)
    python adv_delta.py --role advisor     # Advisor として実行 (相手 = 出品専任)
    python adv_delta.py --reset            # 差分を出さずに基準点だけ記録

状態は role ごとに別ファイル (C:/dev/iMak_data/hq/.adv_delta_state[_advisor].json)。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(r"C:\dev\iMak")
STATE_DIR = Path(r"C:\dev\iMak_data\hq")
# role → (state file, 相手の署名, 表示ラベル)
ROLES = {
    "listing": (".adv_delta_state.json", "[Advisor]", "ADV"),
    "advisor": (".adv_delta_state_advisor.json", "[出品専任]", "出品専任"),
}
DAILY_REPORT = Path(
    r"C:\Users\imax2\.claude\projects\c--dev-iMak\memory\daily_report.md"
)
DATA_ROOT = Path(r"C:\dev\iMak_data")
WORKTREES = ["hq", "catalog", "dedupe", "inventory", "harvest", "revise"]
MAX_ITEMS = 15


def _git(*args: str) -> str:
    try:
        out = subprocess.run(
            ["git", *args], cwd=REPO, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=20,
        )
        return (out.stdout or "").strip()
    except Exception:
        return ""


def _load_state(state: Path) -> dict:
    if state.exists():
        try:
            return json.loads(state.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_state(state: Path, head: str) -> None:
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(
        json.dumps({"last_commit": head, "last_seen": time.time()}, indent=2),
        encoding="utf-8",
    )


def _new_commits(last: str) -> list[str]:
    if not last:
        return []
    rng = f"{last}..HEAD"
    out = _git("log", "--date=short", "--pretty=%ad %h %s", rng)
    return [ln for ln in out.splitlines() if ln.strip()]


def _peer_sections(since: float, signature: str) -> list[str]:
    """daily_report の「相手の署名」見出しを新しい順に拾う (mtime が since より新しい時だけ)."""
    if not DAILY_REPORT.exists() or DAILY_REPORT.stat().st_mtime <= since:
        return []
    heads = [
        ln for ln in DAILY_REPORT.read_text(encoding="utf-8", errors="replace").splitlines()
        if ln.startswith("## ") and signature in ln
    ]
    return heads[:MAX_ITEMS]


def _touched_requests(since: float) -> list[str]:
    hits: list[str] = []
    for wt in WORKTREES:
        d = DATA_ROOT / wt / "requests"
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.md"), key=lambda x: -x.stat().st_mtime):
            if p.stat().st_mtime > since:
                hits.append(f"{wt}/{p.name}")
            if len(hits) >= MAX_ITEMS:
                return hits
    return hits


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    role = "listing"
    if "--role" in sys.argv:
        i = sys.argv.index("--role")
        if i + 1 < len(sys.argv) and sys.argv[i + 1] in ROLES:
            role = sys.argv[i + 1]
    state_name, signature, label = ROLES[role]
    state_path = STATE_DIR / state_name

    head = _git("rev-parse", "HEAD")
    state = _load_state(state_path)
    reset = "--reset" in sys.argv

    if reset or not state:
        _save_state(state_path, head)
        print(f"[{label}差分] 基準点を記録しました (差分なし)。")
        return 0

    last_commit = state.get("last_commit", "")
    last_seen = float(state.get("last_seen", 0))

    commits = _new_commits(last_commit)
    sections = _peer_sections(last_seen, signature)
    requests = _touched_requests(last_seen)

    if not (commits or sections or requests):
        print(f"[{label}差分] 前回確認以降の変化なし。")
        _save_state(state_path, head)
        return 0

    print(f"[{label}差分] 前回確認以降に共有領域が動いています ({label} の作業の可能性)。")
    if commits:
        print(f"\n## 新しい commit ({len(commits)}件)")
        for c in commits[:MAX_ITEMS]:
            print(f"- {c}")
    if sections:
        print(f"\n## daily_report の {signature} 記入")
        for s in sections:
            print(f"- {s}")
    if requests:
        print(f"\n## requests の新規/更新 ({len(requests)}件)")
        for r in requests:
            print(f"- {r}")
    print("\n→ 自分の担当に影響するものがあれば、作業前に該当ファイルを読むこと。")
    _save_state(state_path, head)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
