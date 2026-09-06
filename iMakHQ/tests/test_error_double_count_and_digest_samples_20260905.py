# -*- coding: utf-8 -*-
"""監査くんの error 二重カウント + digest 実文サンプル (2026-09-05)。

9/05 の走行: 仕入値が上限を超えた行は**2件**だけなのに、
`❌ 除外(出品しない): 2件` (集計) + `❌ エラー: 2件` (集計) + 明細2行 が
全部「1行=1件」で足され `error: 4件` になった (実際の2倍)。
digest にも当たった行の実文が無く、Act が毎回ログを読み直していた。

依頼書: hq/requests/2026-09-05_act_code_proposals_tcg.md 提案1
回答書: hq/requests/2026-09-05_act_code_proposals_tcg_response.md
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


_REAL_LOG = (
    "❌ 除外(出品しない): 2件 (行 [4, 6])\n"
    "❌ 仕入値が上限を超えている ¥72,999 (上限 ¥70,000)\n"
    "❌ 仕入値が上限を超えている ¥75,000 (上限 ¥70,000)\n"
    "❌ エラー: 2件\n"
)


def test_summary_plus_detail_is_not_double_counted():
    """集計2行+明細2行 = 実害は2件。4件に水増ししない。"""
    assert _n(ca.scan_log_lines(_REAL_LOG)) == 2


def test_summary_only_still_counts_by_line_unchanged():
    """明細が無い時 (集計行だけ) は従来どおり行数で数える (既存挙動維持)。"""
    txt = "  ❌ 除外(出品しない): 3件 (行 [4, 9, 12])"
    assert ca.scan_log_lines(txt) == ["error: 1件"]


def test_detail_only_without_summary_still_counts_by_line():
    """集計行が無い独立エラー (Traceback 等) は今までどおり1行=1件。"""
    assert ca.scan_log_lines("Traceback (most recent call last):") == ["error: 1件"]


def test_zero_count_summary_lines_still_produce_nothing():
    txt = "❌ 除外(出品しない): 0件 (行 [])\n❌ エラー: 0件\n"
    assert ca.scan_log_lines(txt) == []


def test_digest_carries_raw_signal_lines_for_act():
    """digest.log_signal_lines に当たった行の実文(先頭3件・各80字)が載る。"""
    d = ca._build_ng_digest("tcg", [], ca.scan_log_lines(_REAL_LOG), [], ca._signal_line_samples(_REAL_LOG))
    assert d["log_signal_lines"], "実文サンプルが空 = Act がログを読み直す羽目になる"
    assert len(d["log_signal_lines"]) <= 3
    assert all(len(s) <= 80 for s in d["log_signal_lines"])
    assert any("仕入値が上限を超えている" in s or "除外" in s for s in d["log_signal_lines"])


def test_build_ng_digest_defaults_log_signal_lines_when_omitted():
    """既存呼出 (4引数) は壊さない。"""
    d = ca._build_ng_digest("tcg", [("sku1", "msg1")], ["error: 2件"], [])
    assert d["log_signal_lines"] == []
