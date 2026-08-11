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
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
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
# ★2026-07-30 改訂: HQ も自動実装の対象にする (ユーザー提案「HQ にも分散指示すれば」)。
#   HQ は Advisor と **同じ worktree (C:/dev/iMak)** を共有するため、当初は対象外にしていたが、
#   衝突するのは「窓口が編集している最中」だけ。**窓口が busy flag を立てている間だけ避ける**
#   ことで、残り時間はHQも並列に働ける (= 窓口の手が空いている夜間・待ち時間も回る)。
NO_AUTO_IMPLEMENT: set[str] = set()
# 窓口 (Advisor/出品専任) が同じ worktree を編集中に立てる旗。存在する間 HQ の自動実装を止める。
# 窓口は「編集を始める前に立てて、commit したら消す」。消し忘れても STALE で自動解除する。
HQ_BUSY_FLAG = REVIEW_DIR / "hq_busy.flag"
HQ_BUSY_STALE_SEC = 2 * 3600      # 旗の消し忘れで永久に止まらないよう 2h で自動失効


def hq_busy() -> bool:
    """窓口が C:/dev/iMak を編集中か (= HQ の自動実装を避けるべきか)。"""
    try:
        if not HQ_BUSY_FLAG.exists():
            return False
        if time.time() - HQ_BUSY_FLAG.stat().st_mtime > HQ_BUSY_STALE_SEC:
            HQ_BUSY_FLAG.unlink(missing_ok=True)   # 消し忘れ → 自動解除 (止めっぱなしにしない)
            return False
        return True
    except OSError:
        return False


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


# ★2026-08-01 ユーザー確定の「1丁目1番地」。**セッションが変わっても、誰が担当になっても**
#   必ず効かせるため、headless で起動する全 worktree のプロンプト先頭に入れる。
#   グローバル CLAUDE.md にも同文を置いてあるが、headless は起動プロンプトが行動を支配するので
#   ここに書かないと守られない。文言を変えないこと (変えると担当ごとに解釈が割れる)。
_TRIAGE_RULE = (
    "【🔀 1丁目1番地 — カタログ絡みは必ずこの手順で判定してから直す】\n"
    "  ① カタログのデータは正しいのか\n"
    "  ② 出品くんの引き方は正しいのか\n"
    "  ①が正しいなら → ②を修正 / ②が正しいなら → ①を修正 /\n"
    "  ①②とも誤りなら → 両方直す / ①②とも正しいなら → 直すものは無い(= 出品しない が答え)\n"
    "- **分類はこの4つだけ。5つ目は存在しない。** 判定を書かずに個別修正を始めるな。\n"
    "- 判定基準: **①が正しい**=公式dump/ebay_filter_map から**今その場で計算した値**と一致する\n"
    "  (人が過去に焼いた値を正の根拠にしない) / **②が正しい**=入力が canonical KEY だけ\n"
    "  (タイトル等の自由文を使っていない)。\n"
    "- 回答書の**冒頭に①②の判定を書く**。②が原因ならカタログに依頼を出さず自分側で直す。\n"
    "- 同じ判定が2回出たら、個別のカードを直すのではなく**発生源を直す**。\n"
    "- この手順に条件や例外を足さない。\n\n"
)


def _build_prompt(wt: str, pending: list[Path]) -> str:
    workdir, branch, label = TARGETS[wt]
    files = "\n".join(f"  - {p}" for p in pending)
    return (
        f"あなたは {label} ({wt}) の担当 Claude セッションです。窓口セッション (出品専任) から "
        f"headless で起動されました。自分の requests を処理してください。\n\n"
        f"【あなたの領域】{workdir} (branch {branch})。他 worktree は読取も含め触らないこと。\n\n"
        + _TRIAGE_RULE +
        f"【処理対象】共有領域の未処理依頼 {len(pending)} 件:\n{files}\n\n"
        "【やること】各依頼を読み、対応判断し、同じ dir に **`<元のfile名>_draft.md`** を書く。\n"
        "- ★**`_response.md` は書くな**。あなたが書けるのは draft まで。正式回答への昇格は窓口が\n"
        "  レビューしてから行う (対話できない headless の誤回答を相手に流さないための構造)。\n"
        "- ★**証拠添付が必須**。主張ごとに『実行したコマンド』と『その出力の要点』を書く。\n"
        "  証拠の無い主張は窓口が却下する。cache 表示や memory の記憶だけで断定しない。\n"
        "- ★**確信が持てないものは書くな**。推測で埋めず `<元のfile名>_question.md` に\n"
        "  『何が分からないか / 何があれば判断できるか』を書いて止める (fail-closed)。\n"
        "  分からないまま draft を書く方が、質問で止まるより遥かに悪い。\n"
        "- ★**依頼書の『既に判明していること』は再調査するな。** そこに書いてある事実 "
        "(実測値・突合結果・公式から取った値) は**起票者が既に確認済み**なので、"
        "同じ調査をやり直さない。**答えるのは『聞きたいこと (未回答)』だけ**。\n"
        "  同じ結論に二度たどり着くのは無駄で、しかも起票者より弱い根拠 (再取得なしの推測等) で"
        "上書きすると判断の質が下がる。既知に疑いがあるなら `_question.md` で指摘して止める。\n"
        "- 既に古く不要になった依頼は「不要」と理由付きで書いてよい (これも draft)。\n"
        "- 相手が先に進められる部分があるなら『そちらは待ちではない』と明示する。\n"
        "- ★**他担当への依頼が必要なら、草案を** `C:/dev/iMak_data/_routing/` **に置く**。\n"
        "  file 名は `<YYYY-MM-DD>_<自分>_to_<相手>_<topic>.md` (相手= hq/catalog/dedupe/"
        "inventory/harvest/revise)。**相手の requests/ に直接置くのは禁止**。\n"
        "  投入は窓口が宛先を確認してから行う (担当どうしの相互依頼はループを止められないため)。\n\n"
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
        + _TRIAGE_RULE +
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
        "- 回答書に無いことを『ついでに』直さない。範囲を勝手に広げない。\n"
        "- ★**他担当への依頼が必要なら、草案を** `C:/dev/iMak_data/_routing/` **に置く**\n"
        "  (`<YYYY-MM-DD>_<自分>_to_<相手>_<topic>.md`)。**相手の requests/ に直接置くのは禁止**。\n"
        "  投入は窓口が宛先を確認してから行う。\n\n"
        "【出力】最後に1行で `SUMMARY: 実装N件 / commit M件 / question K件` を出力すること。"
    )


USAGE_LIMIT_FLAG = REVIEW_DIR / "usage_limit_until.txt"
USAGE_LIMIT_FALLBACK_MIN = 60          # 時刻が読めない時の停止時間 (永久停止に倒さない)


def _parse_reset_at(text: str, now=None):
    """`You've hit your limit · resets 8:50pm` から**次の**リセット時刻を出す。

    読めなければ None (呼び手が fallback 分だけ止める)。永久停止には倒さない。
    """
    m = re.search(r"resets\s+(\d{1,2})(?::(\d{2}))?\s*([ap]m)", text or "", re.I)
    if not m:
        return None
    h = int(m.group(1)) % 12
    if m.group(3).lower() == "pm":
        h += 12
    now = now or datetime.now()
    at = now.replace(hour=h, minute=int(m.group(2) or 0), second=0, microsecond=0)
    return at if at > now else at + timedelta(days=1)    # 過ぎていれば翌日


def _note_usage_limit(out: str, now=None) -> bool:
    """出力が usage 上限なら、いつまで止めるかを記録して True."""
    if "hit your limit" not in (out or ""):
        return False
    now = now or datetime.now()
    until = _parse_reset_at(out, now) or (now + timedelta(minutes=USAGE_LIMIT_FALLBACK_MIN))
    try:
        USAGE_LIMIT_FLAG.parent.mkdir(parents=True, exist_ok=True)
        USAGE_LIMIT_FLAG.write_text(until.isoformat(timespec="seconds"), encoding="utf-8")
    except OSError:
        pass                                             # 記録できなくても判定は返す
    return True


def usage_limited_until(now=None):
    """まだ止めているべきなら解除時刻。止める必要が無ければ None.

    ★fail-open: flag が読めない/壊れている時は None (= 動かす)。
      止める側に倒すと、誰も気づかないまま全 worktree が永久停止する。
    """
    try:
        until = datetime.fromisoformat(USAGE_LIMIT_FLAG.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    now = now or datetime.now()
    if now >= until:
        USAGE_LIMIT_FLAG.unlink(missing_ok=True)         # 解除は自動 (人の操作を要らなくする)
        return None
    return until


def _active_session(wt: str):
    """その worktree で稼働中の Claude セッション (対話含む)。判定不能なら None.

    ★fail-open 側に倒す: beacon が読めない/壊れている時に「居る」と答えると、
      全 worktree の dispatch が黙って止まる (2026-07-29 の孤児 lock で3時間全停止した前例)。
      二重起動の害より「誰も動かない」害の方が大きい。
    """
    try:
        import session_beacon
        return session_beacon.active_session(wt)
    except Exception:                                    # noqa: BLE001
        return None


def _dispatch(wt: str, dry_run: bool, mode: str = "draft") -> dict:
    label = TARGETS[wt][2]
    # ★上限中は claude.exe を起こさない (起こしても 53バイトのログが増えるだけ)
    until = usage_limited_until()
    if until and not dry_run:
        print(f"[{label}] ⛔ usage 上限中 (〜{until:%H:%M}) → 起動しない")
        return {"worktree": wt, "status": "skip-usage-limit", "n": 0}
    if mode == "implement":
        if wt in NO_AUTO_IMPLEMENT:
            return {"worktree": wt, "status": "skip-no-auto-impl", "n": 0}
        if wt == "hq" and hq_busy():
            # 窓口が同じ worktree を編集中 → 同時編集で壊すので今回は見送る (次の周回で再挑戦)
            return {"worktree": wt, "status": "skip-hq-busy", "n": 0}
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

    # ★2026-08-10: **人が開いた対話セッション**が同じ worktree に居るなら headless を立てない。
    #   dispatch_<wt>.lock は headless 同士しか見ておらず、対話セッションは lock を取らないため
    #   hub から見ると「誰も居ない」。実害: catalog で 12:09〜 対話が処理中の裏で headless が
    #   12:35-37 に3コミットし、二重作業 + 誤コミットを誘発した (CLAUDE.md「1 worktree 1 branch」抵触)。
    live = _active_session(wt)
    if live:
        print(f"[{label}] 対話セッションが稼働中 (pid={live.get('pid')} / {live.get('at')}) "
              f"→ headless を立てない")
        return {"worktree": wt, "status": "skip-session-live", "n": len(mine)}

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

    # ★utilization 上限に当たったら、リセットまで**全 worktree の dispatch を止める**。
    #   2026-08-10 実測: 17:45 に上限到達 → 20:49 まで3時間、15秒間隔で叩き続けて
    #   **176本が「You've hit your limit」だけの 53バイトログ**になった (実走23本に対して)。
    #   トークンは食わない (弾かれている) が、claude.exe を732回起こしており PC が無駄に回る。
    if _note_usage_limit(out):
        print(f"[{label}] ⛔ usage 上限。リセットまで dispatch を止めます")
        return {"worktree": wt, "status": "usage-limit", "n": len(mine), "summary": "",
                "log": str(log_path), "violations": []}

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
    # 窓口が C:/dev/iMak を編集する前後に立てる/降ろす旗 (HQ の自動実装との同時編集を避ける)。
    if "--busy" in args:
        REVIEW_DIR.mkdir(parents=True, exist_ok=True)
        HQ_BUSY_FLAG.write_text(f"{os.getpid()} {datetime.now().isoformat()}\n", encoding="utf-8")
        print(f"🚧 HQ busy 旗を立てた ({HQ_BUSY_FLAG.name})。HQ の自動実装は止まる"
              f" (最長 {HQ_BUSY_STALE_SEC // 3600}h で自動失効)")
        return 0
    if "--free" in args:
        HQ_BUSY_FLAG.unlink(missing_ok=True)
        print("✅ HQ busy 旗を降ろした。HQ の自動実装が再開する")
        return 0
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
