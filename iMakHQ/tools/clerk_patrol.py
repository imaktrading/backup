"""事務員 (clerk) — 判断しない巡回役。集計・異常検出・督促候補の抽出だけをする.

なぜ必要か (2026-07-30 ユーザー提案「ADV,HQ 以外に事務員を配置したら」):
    dispatch を並列化して担当の処理量を上げた結果、**窓口(Advisor)に事務作業が集中**した。
    - 各 worktree の滞留集計 / 完了報告の証拠チェック / cron ログの巡回 / 督促候補の洗い出し
    これらは **判断を含まない**ので、窓口が抱える必要がない。分離して自動巡回にする。

★事務員がやらないこと (窓口の領分。ここを侵すと品質の下限が崩れる):
    - GO/NG の判断、下書きの昇格 (`_response.md` を書く)
    - コード修正・commit・スプシ/DB への書込
    - 他 worktree への依頼書投入 (督促は「候補」を挙げるだけ。出すのは窓口)

出力: C:/dev/iMak_data/clerk/reports/YYYY-MM-DD_HHMM.md (窓口はこれだけ読めばよい)
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dispatch_worktree as dw  # noqa: E402

CLERK_DIR = Path(r"C:\dev\iMak_data\clerk")
REPORT_DIR = CLERK_DIR / "reports"
TOOLS = Path(__file__).resolve().parent
TIMEOUT_SEC = 900


def build_prompt(stamp: str) -> str:
    return (
        "あなたは iMak Trading Japan の **事務員 (clerk)** です。窓口 (Advisor) の事務作業を"
        "肩代わりするために自動起動されました。\n\n"
        "【最重要】あなたは **判断しません**。集計・検出・候補の抽出だけを行います。\n"
        "  - GO/NG を決めない / 下書きを昇格させない (`_response.md` を書かない)\n"
        "  - コードを直さない / commit しない / スプシ・DB に書かない\n"
        "  - 他 worktree の requests dir に依頼書を置かない (督促は『候補』を挙げるだけ)\n"
        "  判断が要ると思ったら、**そのまま『窓口判断が要る』と書いて渡す**こと。\n\n"
        "【やること】次の5つを実行し、結果を1つのレポートにまとめる。\n"
        f"0. **下書きの仕分け: `python {TOOLS / 'draft_triage.py'}`** ← 最初にこれ。\n"
        "   規則ベースで『🔴窓口必須』と『⚪定型』に分かれる。**あなたはこの分類を変えない**"
        "(規則の出力をそのまま転記する)。\n"
        "   ★レポートの『窓口が今すぐ見るべきもの』には **窓口必須のものだけ**を書く。\n"
        "     定型は件数と一覧だけ別枠に置く。塊で30件出すと窓口が着手できない"
        "(2026-07-30 に5回連続で同じ30件を出して1件も処理されなかった)。\n"
        f"1. 滞留の集計: `python {TOOLS / 'worktree_board.py'}`\n"
        f"2. 完了報告の検査: `python {TOOLS / 'done_check.py'} --since={stamp[:10]}`\n"
        "   (当日分が無ければ `--since=2026-07-30` 以降で見る)\n"
        "3. cron/ログの巡回: `C:/dev/iMak/iMakHQ/review_logs/` と "
        "`C:/dev/iMak/iMakHQ/run_logs/` の**直近24時間**のファイルを見て、\n"
        "   - `returncode=` が 0 でないもの\n"
        "   - `[warn]` `⚠` `🚨` `Traceback` `error` を含むもの\n"
        "   - **本来生成されるはずのログが無い**もの (例: 夜間 cron のログが当日分だけ欠けている)\n"
        "   を拾う。★『ログが無い』は見落としやすいが、**silent failure の唯一の兆候**なので必ず見る。\n"
        "4. 督促候補: 共有領域 `C:/dev/iMak_data/*/requests/` で、こちらが出した依頼のうち\n"
        "   **3日以上 応答 (`_draft` / `_response` / `_done`) が無いもの**を列挙する。\n\n"
        "【出力】次の1ファイルだけを書く (他には何も書かない):\n"
        f"  `{REPORT_DIR / (stamp + '_patrol.md')}`\n\n"
        "書式:\n"
        "```markdown\n"
        "# 事務巡回 <日時>\n"
        "## ⚠️ 窓口が今すぐ見るべきもの (N件)   ← 無ければ「なし」と書く\n"
        "- **窓口必須の下書き**と、cron/ログ異常、督促候補だけ。定型はここに書かない\n"
        "- …(異常の要点と、どのファイルを見れば分かるか)\n"
        "## 定型 (既定処理で流せる / N件)\n"
        "- draft_triage の ⚪ 定型 をそのまま列挙 (件名 + 既定処理)。判断を書き足さない\n"
        "## 滞留サマリ\n"
        "- worktree ごとに 未処理 / レビュー待ち / 実装キュー の件数\n"
        "## 完了報告\n"
        "- 証拠OK N件 / 要確認 N件 (要確認は file 名と理由)\n"
        "## cron・ログ異常\n"
        "- 異常があれば file と該当行。無ければ「異常なし (確認した範囲: …)」\n"
        "## 督促候補\n"
        "- 相手 / 依頼書名 / 経過日数 / 直近の動き\n"
        "```\n\n"
        "【厳守】\n"
        "- **実行したコマンドと出力の要点**を根拠として書く。憶測で書かない。\n"
        "- 異常が無いなら「異常なし」と**確認した範囲を明記して**書く。空欄にしない。\n"
        "- 長く書かない。窓口が30秒で読める分量にする。\n\n"
        "【出力】最後に1行で `SUMMARY: 要対応N件 / 滞留M件 / 督促候補K件` を出力すること。"
    )


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (CLERK_DIR / "requests").mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")

    claude_exe = dw._resolve_claude_exe()
    if not claude_exe or not os.path.exists(claude_exe):
        print("⚠️ claude.exe が見つからない → 事務巡回 不可")
        return 1

    log_path = dw.REVIEW_DIR / f"clerk_patrol_{stamp}.log"
    print(f"▶ 事務巡回 開始 ({stamp}) → {log_path.name}")
    # 事務員はコードを触らないので、書込系は全部禁止しておく (deny は多重防御)
    deny = ["Bash(git commit:*)", "Bash(git push:*)", "Bash(git checkout:*)",
            "Bash(git switch:*)", "Bash(git reset:*)"]
    try:
        # ★事務員は cwd (共有領域) の外にある **HQ の tools と logs** を読む必要がある。
        #   --add-dir を渡さないと worktree_board.py / done_check.py を実行できず、
        #   review_logs / run_logs の巡回もできない (= 何も出せないまま終わる)。
        res = subprocess.run(
            [claude_exe, "-p", build_prompt(stamp), "--dangerously-skip-permissions",
             "--disallowedTools", *deny,
             "--add-dir", str(dw.DATA_ROOT),
             "--add-dir", r"C:\dev\iMak\iMakHQ"],
            cwd=str(CLERK_DIR), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=TIMEOUT_SEC,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        out = (res.stdout or "") + (("\n[stderr]\n" + res.stderr) if res.stderr else "")
        status = "ok" if res.returncode == 0 else f"exit{res.returncode}"
    except subprocess.TimeoutExpired:
        out, status = "(timeout)", "timeout"
    dw.REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    log_path.write_text(out, encoding="utf-8")
    summary = next((ln for ln in reversed(out.splitlines()) if ln.startswith("SUMMARY:")), "")
    print(f"事務巡回 {status} / {summary or '(SUMMARY 行なし)'}")
    report = REPORT_DIR / f"{stamp}_patrol.md"
    print(f"レポート: {report if report.exists() else '(未生成 — ログを確認)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
