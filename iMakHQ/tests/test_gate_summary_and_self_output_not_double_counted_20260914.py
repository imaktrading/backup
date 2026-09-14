# -*- coding: utf-8 -*-
"""監査くんの error 誤検出 (2026-09-14, act_code_proposals_mercari 提案4)。

9/13 の走行: digest は `error: 3件` だったが、中身の3行中2件は誤検出だった。
  1) `❌ 3AI合意: BLOCK (#7)`                         ← 本物
  2) `結果: ✅ GO 0 / 🟡 保留 0 / ❌ NO-GO 0 / ⬜ 不明 10` ← 誤検出 (GATEサマリー・全部0)
  3) `📄 生成ログ signal: error: 2件`                  ← 誤検出 (監査くん自身の前パス出力)

原因: `_is_error_summary_line` が「除外」「エラー」の2パターンしか除外せず、GATEサマリー行が
素通り。`_LINE_COUNT_RE` は「件」を見るが GATEサマリー行に「件」が無いため
「件数表記なし=そのまま数える」に落ちていた。監査くん自身の出力行も除外していなかった。

依頼書: hq/requests/2026-09-13_act_code_proposals_mercari.md 提案4
回答書: hq/requests/2026-09-13_act_code_proposals_mercari_response.md
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


_REAL_LOG_20260913 = (
    "    ❌ 3AI合意: BLOCK (#7)\n"
    "\n"
    "  結果: ✅ GO 0 / 🟡 保留 0 / ❌ NO-GO 0 / ⬜ 不明 10\n"
    "  📄 生成ログ signal: error: 2件\n"
)


def test_gate_zero_summary_and_self_output_not_counted():
    """本物は1件 (#7 の3AI合意BLOCK)。GATEサマリー(全部0)と自己出力は数えない。"""
    assert _n(ca.scan_log_lines(_REAL_LOG_20260913)) == 1


def test_gate_summary_with_nonzero_nogo_is_recognized_as_summary_line():
    """GATEサマリー行は _ERROR_SUMMARY_RES に含まれる (明細と二重カウントしない前提)。"""
    line = "  結果: ✅ GO 2 / 🟡 保留 0 / ❌ NO-GO 3 / ⬜ 不明 5"
    assert ca._is_error_summary_line(line)


def test_gate_summary_zero_nogo_is_not_a_signal():
    line = "  結果: ✅ GO 5 / 🟡 保留 0 / ❌ NO-GO 0 / ⬜ 不明 10"
    assert ca.scan_log_lines(line) == []


def test_self_output_line_alone_produces_nothing():
    """監査くん自身の出力行だけなら何も検出しない (再走査で自分を数えない)。"""
    assert ca.scan_log_lines("  📄 生成ログ signal: error: 5件, HOLD/gate: 1件") == []


def test_genuine_block_line_still_detected():
    """本物の 3AI BLOCK 行は引き続き検出される (over-fix で消していないか)。"""
    assert ca.scan_log_lines("    ❌ 3AI合意: BLOCK (#7)") == ["error: 1件"]
