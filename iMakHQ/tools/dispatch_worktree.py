"""窓口セッションから各 worktree の担当を headless 起動して requests を処理させる (Phase2).

背景 (2026-07-27):
    依頼書を投げても、その worktree の Claude セッションをユーザーが起動しない限り止まる。
    「窓口ひとつで全部回す」ため、担当セッションを headless で起動して自分の requests を
    処理させ、結果を窓口が統合する。

★規約との関係 (Worktree 分離ルール):
    窓口が他 worktree のファイルを直接触るのは禁止のまま。このスクリプトがやるのは
    **その worktree の担当セッションを、その worktree 内で起動すること**だけで、
    実作業は担当自身が自分の領域で行う (= 依頼書運用の自動化であって、越境ではない)。
    スクリプト自身も共有領域 (C:/dev/iMak_data) しか読まない。

★品質を落とさないための縛り (headless は対話できない = 誤解に気づけないため):
    - 担当が書けるのは **`_draft.md` まで**。`_response.md` への昇格は窓口がレビューしてから。
      → 誤回答が相手 worktree に流れない。品質の下限が「窓口のレビュー品質」になる。
      ★2026-07-29: 初回運用で「担当が _response.md を直接書いた」と判断したが **これは誤り**だった。
        dispatch ログは `SUMMARY: draft 5件` = 遵守しており、_response.md を書いていたのは
        **ユーザーが別途開いていた対話セッション**だった。機械降格は正規回答を巻き込むため撤回。
        残したのは ①`--disallowedTools` で commit/push/checkout を拒否 (defense in depth)
        ②実行中に出現した `_response.md` の **検出・報告のみ** (rename しない)。

★同時実行に注意 (2026-07-29 実地で踏んだ):
    dispatch は自身の中では直列だが、**dispatch を2本同時に起動すると同じ worktree に
    headless が2つ立つ** (実際 dedupe に2プロセス同時起動が発生)。
    前回の dispatch が走り切る前に次を起動しないこと。**対話セッションが開いている worktree も
    同様に競合しうる**。
    - **証拠添付必須** (実行コマンド + 出力)。証拠の無い主張は窓口が却下する。
    - **確信が無ければ書かせない**。`_question.md` に何が分からないかを書いて止める (fail-closed)。
    - **コード修正 / git commit / 破壊的・不可逆・外向き操作を禁止**。
    - **直列実行**。共有DB・スプシへの同時書込を避ける。
    - 未処理が無い worktree は起動しない (無駄な課金を出さない)。
    - --dry-run で「何を誰に投げるか」だけ確認できる。

使い方:
    python dispatch_worktree.py --dry-run            # 対象と prompt を確認するだけ
    python dispatch_worktree.py inventory            # 監視くんだけ処理させる
    python dispatch_worktree.py --all                # 未処理がある全 worktree を直列処理
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from worktree_board import pending_for  # noqa: E402

DATA_ROOT = Path(r"C:\dev\iMak_data")
REVIEW_DIR = Path(r"C:\dev\iMak\iMakHQ\review_logs")
# worktree → (作業ディレクトリ, branch, 呼称)  ※グローバル CLAUDE.md の表と一致させること
TARGETS = {
    "catalog": (r"C:\dev\iMak_catalog", "feature/uniqlo-ut", "カタログ"),
    "dedupe": (r"C:\dev\iMak_dedupe", "feature/dedupe-phase1", "重複くん"),
    "inventory": (r"C:\dev\iMak_inventory", "feature/inventory-phase1", "監視くん"),
    "harvest": (r"C:\dev\iMak_harvest", "feature/harvest-phase1", "抽出くん"),
    "revise": (r"C:\dev\iMak_revise", "feature/revise-phase1", "リバイスくん"),
}
TIMEOUT_SEC = 1800  # 1 worktree あたりの上限 (30分)

# ★機械的な縛り (2026-07-29 追加)
#   2026-07-29 の初回運用で、prompt に「_response.md は書くな / コード修正・commit するな」と
#   ★付きで明記していたにもかかわらず、担当2つとも **_response.md を直接書き、コードを commit** した。
#   = prompt の言い回しは抑止力にならない (--dangerously-skip-permissions で何でもできるため)。
#   → ① CLI の deny 指定で commit/push を落とす ② 実行後に共有領域を突合して機械的に是正する。
DENY_TOOLS = ["Bash(git commit:*)", "Bash(git push:*)",
              "Bash(git checkout:*)", "Bash(git switch:*)", "Bash(git reset:*)"]


def _requests_dir(wt: str) -> Path:
    return DATA_ROOT / wt / "requests"


def _snapshot(d: Path) -> dict:
    """共有領域 requests dir の現状 (file名 → mtime)。※読むのは共有領域だけ (worktree 分離を守る)."""
    if not d.is_dir():
        return {}
    return {p.name: p.stat().st_mtime for p in d.glob("*.md")}


def _enforce_draft_only(wt: str, before: dict) -> list[str]:
    """dispatch 実行中に増えた `_response.md` を **検出して報告するだけ** (rename しない)。

    ★2026-07-29 撤回の経緯:
      当初は `_response.md` を機械的に `_draft.md` へ降格させる実装にしたが、**前提が誤り**だった。
      「headless 担当が _response を直接書いた」と判断した根拠のファイルは、実際には
      **ユーザーが別途開いていた対話セッション**が書いたものだった (dispatch ログは
      `SUMMARY: draft 5件` = プロトコル遵守)。
      対話セッションと dispatch は**同時に走りうる**ため、機械降格は
      **正規の回答を勝手に draft へ引き戻す**副作用がある。よって rename は廃止し、検出のみ残す。
      → 増えた `_response.md` は「dispatch 由来か対話セッション由来か切り分けよ」の材料として出す。
    """
    d = _requests_dir(wt)
    after = _snapshot(d)
    new = [n for n in after if n not in before or after[n] != before.get(n)]
    return [f"{n} が dispatch 中に出現 (dispatch 由来か対話セッション由来か要確認)"
            for n in sorted(new) if n.endswith("_response.md")]


def _resolve_claude_exe() -> str:
    """claude.CMD shim ではなく実体 .exe を返す (csv_auditor と同じ理由・PATH 欠落対策込み)."""
    found = shutil.which("claude") or ""
    if found.lower().endswith(".exe"):
        return found
    cands = []
    if found:
        cands.append(os.path.join(os.path.dirname(found), "node_modules",
                                  "@anthropic-ai", "claude-code", "bin", "claude.exe"))
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        cands.append(os.path.join(appdata, "npm", "node_modules",
                                  "@anthropic-ai", "claude-code", "bin", "claude.exe"))
    for c in cands:
        if os.path.exists(c):
            return c
    return found


def _build_prompt(wt: str, pending: list[Path]) -> str:
    workdir, branch, label = TARGETS[wt]
    files = "\n".join(f"  - {p}" for p in pending)
    return (
        f"あなたは {label} ({wt}) の担当 Claude セッションです。窓口セッション (出品専任) から "
        f"headless で起動されました。自分の requests を処理してください。\n\n"
        f"【あなたの領域】{workdir} (branch {branch})。他 worktree は読取も含め触らないこと。\n\n"
        f"【処理対象】共有領域の未処理依頼 {len(pending)} 件:\n{files}\n\n"
        "【やること】各依頼を読み、対応判断し、同じ dir に **`<元のfile名>_draft.md`** を書く。\n"
        "- ★**`_response.md` は書くな**。あなたが書けるのは draft まで。正式回答への昇格は窓口が\n"
        "  レビューしてから行う (対話できない headless の誤回答を相手に流さないための構造)。\n"
        "- ★**証拠添付が必須**。主張ごとに『実行したコマンド』と『その出力の要点』を書く。\n"
        "  証拠の無い主張は窓口が却下する。cache 表示や memory の記憶だけで断定しない。\n"
        "- ★**確信が持てないものは書くな**。推測で埋めず `<元のfile名>_question.md` に\n"
        "  『何が分からないか / 何があれば判断できるか』を書いて止める (fail-closed)。\n"
        "  分からないまま draft を書く方が、質問で止まるより遥かに悪い。\n"
        "- 既に古く不要になった依頼は「不要」と理由付きで書いてよい (これも draft)。\n"
        "- 相手が先に進められる部分があるなら『そちらは待ちではない』と明示する。\n\n"
        "【厳守・禁止】\n"
        "- プログラムのコード修正をするな。必要な修正は回答書に**提案として**書くだけ。\n"
        "- git commit / push をするな。branch 切替もするな。\n"
        "- 破壊的・不可逆・外向きの操作 (本番入稿・eBay revision・一括取下げ・DB破壊的更新) をするな。\n"
        "- 共有DB・スプシへの書込もするな (窓口が直列制御しているため)。\n\n"
        "【出力】最後に1行で `SUMMARY: draft N件 / question M件 / 不要 K件` を出力すること。"
    )


def _dispatch(wt: str, dry_run: bool) -> dict:
    mine, _theirs, _drafts = pending_for(wt)
    label = TARGETS[wt][2]
    if not mine:
        print(f"[{label}] 未処理なし → 起動しない")
        return {"worktree": wt, "status": "skip-empty", "n": 0}

    prompt = _build_prompt(wt, mine)
    workdir = TARGETS[wt][0]
    if not os.path.isdir(workdir):
        print(f"[{label}] ⚠️ 作業ディレクトリ不在: {workdir} → skip")
        return {"worktree": wt, "status": "skip-nodir", "n": len(mine)}

    if dry_run:
        print(f"[{label}] dry-run: {len(mine)}件 を投げる予定 (cwd={workdir})")
        for p in mine:
            print(f"    - {p.name}")
        return {"worktree": wt, "status": "dry-run", "n": len(mine)}

    claude_exe = _resolve_claude_exe()
    if not claude_exe or not os.path.exists(claude_exe):
        print("⚠️ claude.exe が見つからない → dispatch 不可")
        return {"worktree": wt, "status": "no-cli", "n": len(mine)}

    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    log_path = REVIEW_DIR / f"dispatch_{stamp}_{wt}.log"
    print(f"[{label}] {len(mine)}件 を headless に委譲 (最大{TIMEOUT_SEC // 60}分)… → {log_path.name}")

    before = _snapshot(_requests_dir(wt))     # ★実行前の共有領域スナップショット
    t0 = time.time()
    try:
        res = subprocess.run(
            [claude_exe, "-p", prompt, "--dangerously-skip-permissions",
             "--disallowedTools", *DENY_TOOLS,
             "--add-dir", str(DATA_ROOT)],
            cwd=workdir, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=TIMEOUT_SEC,
        )
        out = (res.stdout or "") + (("\n[stderr]\n" + res.stderr) if res.stderr else "")
        status = "ok" if res.returncode == 0 else f"exit{res.returncode}"
    except subprocess.TimeoutExpired:
        out, status = "(timeout)", "timeout"
    log_path.write_text(out, encoding="utf-8")

    violations = _enforce_draft_only(wt, before)   # ★事後の機械的是正
    summary = next((ln for ln in reversed(out.splitlines()) if ln.startswith("SUMMARY:")), "")
    print(f"[{label}] {status} / {int(time.time() - t0)}秒 / {summary or '(SUMMARY 行なし)'}")
    for v in violations:
        print(f"  🚨 プロトコル違反: {v}")
    return {"worktree": wt, "status": status, "n": len(mine), "summary": summary,
            "log": str(log_path), "violations": violations}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    names = [a for a in args if not a.startswith("--")]
    if "--all" in args or not names:
        names = list(TARGETS)
    bad = [n for n in names if n not in TARGETS]
    if bad:
        print(f"不明な worktree: {bad} (指定可: {list(TARGETS)})")
        return 2

    results = []
    for wt in names:  # ★直列。共有DB/スプシの同時書込を避ける
        results.append(_dispatch(wt, dry_run))

    print("\n=== dispatch 結果 ===")
    for r in results:
        print(f"- {r['worktree']}: {r['status']} ({r['n']}件) {r.get('summary', '')}")
    all_v = [(r["worktree"], v) for r in results for v in r.get("violations", [])]
    if all_v:
        print(f"\n⚠️ dispatch 中に増えた `_response.md` {len(all_v)}件 (**自動では触っていない**)")
        for wt, v in all_v:
            print(f"  - [{wt}] {v}")
        print("  → dispatch ログの SUMMARY が `draft N件` なら、その _response は"
              "**対話セッション由来**。担当の違反と決めつけないこと。")
    if not dry_run:
        print("\n→ 窓口は各 `_draft.md` / `_question.md` を**読んで検算してから** "
              "`_response.md` に昇格させること (headless の自己申告をそのまま流さない)。")
        print("→ ⚠️ **コード修正 / commit は機械的に防げていない**。deny 指定は commit/push/checkout のみで、"
              "Edit そのものは止めていない (draft を書くのに Write が要るため)。"
              "担当の worktree の変更は、その担当セッションを次に開いた時に確認すること。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
