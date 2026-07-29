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

import ctypes
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from worktree_board import implement_for, pending_for  # noqa: E402

DATA_ROOT = Path(r"C:\dev\iMak_data")
REVIEW_DIR = Path(r"C:\dev\iMak\iMakHQ\review_logs")
# worktree → (作業ディレクトリ, branch, 呼称)  ※グローバル CLAUDE.md の表と一致させること
TARGETS = {
    "catalog": (r"C:\dev\iMak_catalog", "feature/uniqlo-ut", "カタログ"),
    "dedupe": (r"C:\dev\iMak_dedupe", "feature/dedupe-phase1", "重複くん"),
    "inventory": (r"C:\dev\iMak_inventory", "feature/inventory-phase1", "監視くん"),
    "harvest": (r"C:\dev\iMak_harvest", "feature/harvest-phase1", "抽出くん"),
    "revise": (r"C:\dev\iMak_revise", "feature/revise-phase1", "リバイスくん"),
    # ★HQ(出品専任) は **Advisor と同じ worktree (C:/dev/iMak)** を共有している (既知の灰色地帯)。
    #   他の5つと違い専用 worktree が無いため、headless が Advisor と同じフォルダ・同じ .git/index で動く。
    #   それでも入れる理由: HQ 宛の依頼が誰にも読まれず 43h 止まった (2026-07-29)。
    #   縛り: draft のみ / commit は --disallowedTools で拒否 / コード修正は prompt で禁止。
    #   → 未コミットの編集が現れたら `git status` で気づける。恒久策は HQ 専用 worktree の切出し。
    "hq": (r"C:\dev\iMak", "master", "出品専任(HQ)"),
}
TIMEOUT_SEC = 1800  # 1 worktree あたりの上限 (30分)

# ★機械的な縛り (2026-07-29 追加)
#   2026-07-29 の初回運用で、prompt に「_response.md は書くな / コード修正・commit するな」と
#   ★付きで明記していたにもかかわらず、担当2つとも **_response.md を直接書き、コードを commit** した。
#   = prompt の言い回しは抑止力にならない (--dangerously-skip-permissions で何でもできるため)。
#   → ① CLI の deny 指定で commit/push を落とす ② 実行後に共有領域を突合して機械的に是正する。
DENY_TOOLS = ["Bash(git commit:*)", "Bash(git push:*)",
              "Bash(git checkout:*)", "Bash(git switch:*)", "Bash(git reset:*)"]

# ★2026-07-30 実装モード。窓口が `_response.md` に「実装 GO」と書いた案件を担当が実装する。
#   背景: 実装が「人がそのセッションを開くまで」動かず、GO を出した案件が全部滞留していた
#   (ユーザーは窓口経由で回す運用なので、各 worktree を開く前提そのものが成り立たない)。
#   下書きモードとの違いは **コード修正と git commit を許す**こと。ただし:
#     - push / checkout / switch / reset は引き続き禁止 (履歴と他セッションを壊さない)
#     - commit は **許可する**。未 commit のまま放置する方が危険 (branch 操作で消える。
#       2026-04/05 に同型事故3回)。「書いたら commit まで」が安全側。
IMPLEMENT_DENY_TOOLS = ["Bash(git push:*)", "Bash(git checkout:*)",
                        "Bash(git switch:*)", "Bash(git reset:*)"]
# HQ は Advisor と **同じ worktree (C:/dev/iMak)** を共有しており、窓口自身が編集中のことが
# 多い。headless に同じ作業ツリーを触らせると衝突するので、自動実装の対象外にする。
NO_AUTO_IMPLEMENT = {"hq"}


LOCK_PATH = REVIEW_DIR / "dispatch.lock"
LOCK_STALE_SEC = 3 * 3600      # 3h 以上古い lock は死んだプロセスの残骸とみなす (最後の砦)


def _pid_alive(pid: int) -> bool:
    """PID が生きているか。**分からない時は「生きている」と答える** (安全側 = lock を奪わない).

    ★`os.kill(pid, 0)` は使わない。Windows の CPython では OpenProcess + **TerminateProcess** に
      なるため、「生存確認のつもりで相手を殺す」。ここは Win32 API で問い合わせるだけにする。
    """
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True                      # 居るが触れない = 生きている
        return True

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    ERROR_INVALID_PARAMETER = 87             # = そんな PID は存在しない
    k32 = ctypes.windll.kernel32
    handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return k32.GetLastError() != ERROR_INVALID_PARAMETER
    try:
        code = ctypes.c_ulong()
        if k32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return code.value == STILL_ACTIVE
        return True                          # 問い合わせ自体に失敗 → 安全側
    finally:
        k32.CloseHandle(handle)


def _lock_owner_pid(wt=None) -> int | None:
    """lock file の先頭に書いた PID。読めない/壊れていれば None (= 判定不能)."""
    try:
        head = _lock_path(wt).read_text(encoding="utf-8").split()
    except OSError:
        return None
    try:
        return int(head[0]) if head else None
    except ValueError:
        return None


def _lock_path(wt=None):
    """lock file の path。wt を渡すと **worktree ごとの lock** (2026-07-30).

    従来は全 worktree で1本の lock を共有していたため、**担当が直列にしか動けず待ち行列**が
    できていた (実測: 出品専任が監視くんの後ろで数分待たされる)。担当は別々の worktree で
    動き、headless は共有DB/スプシへの書込を禁止しているので、**並行しても衝突しない**。
    防ぎたいのは「同じ worktree に2本立つ」ことだけなので、lock を worktree 単位に割る。
    """
    return LOCK_PATH if not wt else REVIEW_DIR / f"dispatch_{wt}.lock"


def acquire_lock(wt=None) -> bool:
    """dispatch の多重起動を **プロセス跨ぎ**で防ぐ (常駐 watcher と cron が併走するため).

    2026-07-29: 同じ worktree に headless が2本同時起動する事故を起こした。
    タスク側の MultipleInstances だけでは「watcher 起動」と「cron 起動」の衝突は防げない。

    ★2026-07-29 夕: **孤児 lock で全 worktree が3時間止まった**。
      watcher タスクが再起動され、lock を持っていた前世代 pythonw (PID 11632) が
      release_lock() を通らずに死亡 → 生きているプロセスは1つも無いのに lock だけが残り、
      以後すべての周回が「他の dispatch 実行中」で空回り。時間切れ (3h) まで誰も動けなかった。
      → **所有者 PID の生存を確認**し、死んでいれば時間を待たずに奪う。
        時間ベースの stale 判定は、PID が読めない/判定不能な場合の保険として残す。
    """
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    path = _lock_path(wt)
    if path.exists():
        age = time.time() - path.stat().st_mtime
        owner = _lock_owner_pid(wt)
        # PID 不明 (= 判定不能) は「生きている」扱い。誤って奪って二重起動する方が害が大きい。
        owner_alive = True if owner is None else _pid_alive(owner)
        if owner_alive and age < LOCK_STALE_SEC:
            return False
        why = "所有者プロセス不在 (孤児)" if not owner_alive else f"{int(age)}秒経過 (stale)"
        print(f"(古い lock を破棄: {why} / owner={owner} / {path.name})")
        path.unlink(missing_ok=True)   # 孤児 or stale → 奪う
    try:
        with open(path, "x", encoding="utf-8") as f:
            f.write(f"{os.getpid()} {datetime.now().isoformat()}\n")
        return True
    except FileExistsError:
        return False


def release_lock(wt=None) -> None:
    _lock_path(wt).unlink(missing_ok=True)


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


def _build_implement_prompt(wt: str, responses: list) -> str:
    """実装モードの prompt。GO 済の正式回答を **実装して commit まで**やらせる。"""
    workdir, branch, label = TARGETS[wt]
    files = "\n".join(f"  - {p}" for p in responses)
    return (
        f"あなたは {label} ({wt}) の担当 Claude セッションです。窓口から headless で起動されました。\n"
        f"**窓口が検算して『実装 GO』を出した案件を実装してください。**\n\n"
        f"【あなたの領域】{workdir} (branch {branch})。他 worktree は読取も含め触らないこと。\n\n"
        f"【対象】{len(responses)} 件:\n{files}\n\n"
        "【やること】\n"
        "1. 各回答書を読み、**指示された実装をそのまま行う**。設計を勝手に変えない。\n"
        "   回答書に条件・追加要求 (テスト化・件数実測 等) が書いてあれば **必ず満たす**。\n"
        "2. **テストを書く**。回帰テストの無い実装は未完成とみなす。\n"
        "3. **テストを全部通す** (自 worktree の pytest)。1つでも赤いなら commit しない。\n"
        "4. **git commit する** (自分が触ったファイルだけ明示 add。`git add -A` は禁止)。\n"
        "   commit message に『何を・なぜ』と回答書の file 名を書く。\n"
        "5. 完了したら共有領域に **`<回答書のfile名>_done.md`** を書く。中身は証拠:\n"
        "   - commit hash / 変更した file:line\n"
        "   - **テスト実行コマンドとその出力の要点** (何件 pass したか)\n"
        "   - 回答書の追加要求をどう満たしたか\n"
        "   - 実装できなかった部分があれば **明示**する (黙って落とさない)\n\n"
        "【厳守・禁止】\n"
        "- **git push / checkout / switch / reset は禁止**。commit だけしてよい。\n"
        "- 破壊的・不可逆・外向きの操作 (本番入稿・eBay revision・一括取下げ・DB破壊的更新・"
        "スプシの一括書換) は禁止。\n"
        "- **判断に迷ったら実装せず** `<回答書のfile名>_question.md` に何が分からないかを書いて止める。\n"
        "  推測で実装する方が、質問で止まるより遥かに悪い。\n"
        "- 回答書に無いことを『ついでに』直さない。範囲を勝手に広げない。\n\n"
        "【出力】最後に1行で `SUMMARY: 実装N件 / commit M件 / question K件` を出力すること。"
    )


def _dispatch(wt: str, dry_run: bool, mode: str = "draft") -> dict:
    label = TARGETS[wt][2]
    if mode == "implement":
        if wt in NO_AUTO_IMPLEMENT:
            return {"worktree": wt, "status": "skip-no-auto-impl", "n": 0}
        todo = implement_for(wt)
        if not todo:
            return {"worktree": wt, "status": "skip-empty", "n": 0}
        mine, prompt = todo, _build_implement_prompt(wt, todo)
    else:
        mine, _theirs, _drafts = pending_for(wt)
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
    _tag = "impl" if mode == "implement" else "draft"
    log_path = REVIEW_DIR / f"dispatch_{stamp}_{wt}_{_tag}.log"
    print(f"[{label}] {len(mine)}件 を headless に委譲 ({_tag} / 最大{TIMEOUT_SEC // 60}分)… "
          f"→ {log_path.name}")

    before = _snapshot(_requests_dir(wt))     # ★実行前の共有領域スナップショット
    t0 = time.time()
    # ★CREATE_NO_WINDOW: 親が pythonw (コンソール無し) だと claude.exe が**自前のコンソール窓を作る**。
    #   常駐 watcher から起動すると画面に黒窓が出っぱなしになる (2026-07-29 ユーザー報告)。
    #   窓が出ると閉じられ、閉じると子プロセスが 0xC000013A で死ぬ (昨夜の cron 事故と同型) ので必ず抑止する。
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        _deny = IMPLEMENT_DENY_TOOLS if mode == "implement" else DENY_TOOLS
        res = subprocess.run(
            [claude_exe, "-p", prompt, "--dangerously-skip-permissions",
             "--disallowedTools", *_deny,
             "--add-dir", str(DATA_ROOT)],
            cwd=workdir, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=TIMEOUT_SEC,
            creationflags=no_window,
        )
        out = (res.stdout or "") + (("\n[stderr]\n" + res.stderr) if res.stderr else "")
        status = "ok" if res.returncode == 0 else f"exit{res.returncode}"
    except subprocess.TimeoutExpired:
        out, status = "(timeout)", "timeout"
    log_path.write_text(out, encoding="utf-8")

    # 実装モードでは `_response.md` の出現は正常 (窓口が書いたものを実装しただけ) なので検査しない
    violations = [] if mode == "implement" else _enforce_draft_only(wt, before)
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

    if not dry_run and not acquire_lock():
        print("他の dispatch が実行中 (lock あり) → 何もしない")
        return 0
    try:
        results = []
        for wt in names:  # ★直列。共有DB/スプシの同時書込を避ける
            results.append(_dispatch(wt, dry_run))
    finally:
        if not dry_run:
            release_lock()

    print("\n=== dispatch 結果 ===")
    for r in results:
        print(f"- {r['worktree']}: {r['status']} ({r['n']}件) {r.get('summary', '')}")
    # 無人 (cron) 実行だと画面に何も残らないため、実行サマリを必ずファイルに落とす。
    # 窓口は次に開いた時にこれを見れば「誰が何件処理したか」が分かる。
    if not dry_run:
        try:
            REVIEW_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
            lines = [f"# dispatch 実行サマリ {stamp}", ""]
            for r in results:
                lines.append(f"- {r['worktree']}: {r['status']} ({r['n']}件) {r.get('summary', '')}")
                for v in r.get("violations", []):
                    lines.append(f"    ⚠️ {v}")
            total = sum(r["n"] for r in results)
            lines += ["", f"合計 {total}件 を委譲。draft は窓口レビュー後に `_response.md` へ昇格すること。"]
            (REVIEW_DIR / f"dispatch_summary_{stamp}.md").write_text(
                "\n".join(lines), encoding="utf-8")
        except OSError as e:
            print(f"(サマリ書込に失敗: {e})")
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
