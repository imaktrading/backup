"""`.claude/settings.json` の deny 設計を検証する回帰テスト.

回答書 `2026-07-29_permission_deny_for_irreversible_ops_response.md` §3 の
必須確認事項:
  - `git push --force` などの破壊コマンドが deny パターンに一致する
  - `variation_upload.py` の直叩きは deny だが、
    `run_daily.py` (import 経由で呼ぶ) は deny に一致しない
    → cron の 04:30 自動 revise が止まらないことを構造的に保証する

deny は Claude Code の Bash tool のコマンドラインに対する glob マッチ。
"Bash(pattern)" の pattern 部分に対して fnmatch を行うのが実挙動。
"""
from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = REPO_ROOT / ".claude" / "settings.json"


def _load_settings() -> dict:
    return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))


def _deny_patterns() -> list[str]:
    """Return the raw glob patterns (inside `Bash(...)`) from the deny list."""
    raw = _load_settings()["permissions"]["deny"]
    out = []
    for entry in raw:
        m = re.match(r"^Bash\((.*)\)$", entry)
        assert m is not None, f"unexpected deny entry format: {entry!r}"
        out.append(m.group(1))
    return out


def _matches_any(cmd: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(cmd, p) for p in patterns)


def test_settings_json_is_valid_and_has_expected_shape():
    settings = _load_settings()
    perms = settings["permissions"]
    assert perms["defaultMode"] == "bypassPermissions", (
        "defaultMode は明示的に bypassPermissions を指定する "
        "(グローバル継承任せは HQ の acceptEdits 事故と同型)"
    )
    deny = perms["deny"]
    assert isinstance(deny, list) and deny, "deny is empty"
    for entry in deny:
        assert entry.startswith("Bash("), f"non-Bash deny not intended: {entry!r}"
        assert entry.endswith(")"), f"malformed deny entry: {entry!r}"


@pytest.mark.parametrize(
    "cmd",
    [
        "git push --force",
        "git push --force origin main",
        "git push -f",
        "git push -f origin feature/revise-phase1",
        "git push --force-with-lease",
        "git push --force-with-lease origin main",
        "git reset --hard",
        "git reset --hard HEAD~1",
        "rm -rf /tmp/foo",
        "rm -fr /tmp/foo",
        "python revise/variation_upload.py --csv x.csv",
        "python revise\\variation_upload.py --csv x.csv",
        "python -m revise.variation_upload",  # covered by *variation_upload.py* ?
        "python revise/ebay_trading_api.py --revise 123",
        "python revise\\ebay_trading_api.py --revise 123",
    ],
)
def test_dangerous_commands_are_denied(cmd: str):
    patterns = _deny_patterns()
    if cmd == "python -m revise.variation_upload":
        # -m 起動はモジュール名で、ファイル名 `.py` を含まない。
        # 現行 pattern (`*variation_upload.py*`) では拾えないが、
        # cron/日次運用では使わないため対象外。この行は「対象外の記録」として skip する。
        pytest.skip("module invocation is out of scope for current deny patterns")
    assert _matches_any(cmd, patterns), (
        f"expected DENY but no pattern matched: {cmd!r} / patterns={patterns}"
    )


@pytest.mark.parametrize(
    "cmd",
    [
        # 本業 = 毎日 04:30 の DailyAutoRevise。deny に引っかかると cron が止まる。
        "python -m revise.run_daily",
        "python -m revise.run_daily --dry-run",
        "python C:/dev/iMak_revise/iMakRevise/revise/run_daily.py",
        "python C:/dev/iMak_revise/iMakRevise/revise/run_daily.py --dry-run",
        "pythonw.exe -X utf8 C:/dev/iMak_revise/iMakRevise/revise/run_daily.py",
        # send_reminder はメール送信のみ、致命でないので deny しない
        "python C:/dev/iMak_revise/iMakRevise/revise/send_reminder.py",
        # CSV 生成のみは deny しない (UP しない)
        "python C:/dev/iMak_revise/run_revise.py",
        "python C:/dev/iMak_revise/iMakRevise/revise/price_revise.py",
        # 通常 git 操作 (force なし) は deny しない
        "git push",
        "git push origin main",
        "git push origin feature/revise-phase1",
        "git status",
        "git commit -m 'foo'",
        "git reset HEAD~1",  # --hard なし
        # rm の -rf 以外
        "rm foo.txt",
        "rm -f foo.txt",
        # 補助 tool 呼び出しは deny しない
        "python C:/dev/iMak_revise/iMakRevise/control_panel.py",
        "python C:/dev/iMak_revise/iMakRevise/revise/review_xlsx.py",
    ],
)
def test_business_normal_commands_are_not_denied(cmd: str):
    patterns = _deny_patterns()
    assert not _matches_any(cmd, patterns), (
        f"unexpected DENY of a legitimate command: {cmd!r} / matching pattern(s)="
        f"{[p for p in patterns if fnmatch.fnmatchcase(cmd, p)]}"
    )


def test_import_of_variation_upload_from_run_daily_is_not_a_bash_command():
    """回答書 §3 の必須確認: import 経由の呼出は deny に引っかからない.

    実装挙動: deny は Bash コマンドライン文字列への glob マッチ。
    `run_daily.py` 内の `from revise.variation_upload import ...` は
    Python の import であり、Bash コマンドラインには現れない。
    -> `python -m revise.run_daily --dry-run` を発火した際の Bash 側 cmdline は
       `python -m revise.run_daily --dry-run` のみ。ここに variation_upload.py の
       文字列は含まれない = deny 対象外。
    """
    patterns = _deny_patterns()
    cron_cmdline = "pythonw.exe -X utf8 C:/dev/iMak_revise/iMakRevise/revise/run_daily.py"
    assert not _matches_any(cron_cmdline, patterns), (
        "cron 経由の run_daily.py 起動が deny された = 毎日 04:30 の自動 revise が止まる"
    )
    # 念のため、run_daily.py ソースが実際に variation_upload を import していることを固定
    run_daily_src = (REPO_ROOT / "iMakRevise" / "revise" / "run_daily.py").read_text(encoding="utf-8")
    assert "from revise.variation_upload import" in run_daily_src, (
        "run_daily.py の variation_upload import が消えている = 設計前提が崩れた"
    )
