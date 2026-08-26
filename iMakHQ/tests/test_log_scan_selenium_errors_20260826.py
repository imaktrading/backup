# -*- coding: utf-8 -*-
"""監査くんの log スキャンが Selenium の失敗を拾う (2026-08-26).

8/26 の走行は `Error: Message: invalid session id` が 18行あるのに log_signals は空で、
その日の監査は「異常なし」から始まった (実際は 20件中 19件が落ちていた)。
`_SCAN_PATS` の error パターンが `❌|Traceback|ERROR` (大文字固定) しか見ておらず、
実ログの `Error:` (先頭大文字) / `Stacktrace:` (Selenium は Traceback を出さない) に
1つも当たっていなかった。

依頼書: hq/requests/2026-08-26_act_code_proposals_tcg.md 提案1
回答書: hq/requests/2026-08-26_act_code_proposals_tcg_response.md (4)
"""
import os
import sys

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import csv_auditor as ca  # noqa: E402


def _n(sig, label="error"):
    for s in sig:
        if s.startswith(label + ":"):
            return int(s.split(":")[1].replace("件", "").strip())
    return 0


def test_selenium_invalid_session_is_counted():
    """8/26 の実ログの形。1行でも数える。"""
    log = ("  取得中(確認用): #161047028\n"
           "    Error: Message: invalid session id: session deleted\n"
           "Stacktrace:\n"
           "\tGetHandleVerifier [0x00007FF6] (No symbol)\n")
    sig = ca.scan_log_lines(log)
    assert _n(sig) >= 2, f"Error: / Stacktrace: を数えていない → {sig}"


def test_lowercase_error_prefix_is_counted():
    assert _n(ca.scan_log_lines("  error: connection reset\n")) == 1


def test_plain_japanese_success_lines_are_not_counted():
    """`失敗` は正常系にも出るので、文脈なしでは数えない。"""
    log = ("  失敗しても続行します\n"
           "  ⏭️ 失敗時は次の cert へ\n"
           "  ✅ 生成完了: 17件\n")
    assert ca.scan_log_lines(log) == [], "正常系の日本語を error と数えている"


def test_scrape_failure_with_context_is_counted():
    assert _n(ca.scan_log_lines("  取得中(確認用): #123 → 失敗\n")) == 1


def test_zero_count_lines_are_still_dropped():
    """`N件=0` ルールは壊さない (2026-08-19 の既存判断)。"""
    assert ca.scan_log_lines("❌ エラー: 0件\n") == []
    assert _n(ca.scan_log_lines("❌ エラー: 3件\n")) == 1


def test_real_20260826_log_is_not_silent():
    """実ログが残っていれば、そこでも 0 にならないこと。"""
    p = os.path.join(os.path.dirname(_TOOLS), "run_logs", "____20260826_190930.log")
    if not os.path.exists(p):
        return                                  # ログは git 管理外 → 在る時だけ見る
    import io
    txt = io.open(p, encoding="utf-8", errors="replace").read()
    assert _n(ca.scan_log_lines(txt)) >= 18, "18行の invalid session id を数えていない"
