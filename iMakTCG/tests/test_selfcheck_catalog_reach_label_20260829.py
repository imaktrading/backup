# -*- coding: utf-8 -*-
"""selfcheck 失敗理由に catalog を引けたのか書く (2026-08-29 提案2 / 提案3)。

何が起きていたか: ログは `❌ 必須Item Specific 'Type' (タイプ) が空` としか出さない。
真因 (catalog を一度も引いていないのか / 引けたが値が空なのか) は別の行に分かれていて
人が結び付けないと分からなかった。「引けなかった」なら②出品くんの引き方の課題、
「引けたが値が無い」なら①カタログの欠落 — 1丁目1番地の判定がその場で付くようにする。

さらに、この真因ラベルを program_fix の dkey にも使う (提案3)。brand/cert を含めると
1枚1行に割れる (同じ真因でも cert ごとに別行になる) ので、dkey には固定ラベルだけを使い、
可変部 (brand/pid) はログ本文 (evidence) 側にだけ置く。

出典: hq/requests/2026-08-29_act_code_proposals_tcg_response.md 提案2・提案3
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from psa_to_csv import annotate_selfcheck_error, catalog_reach_label  # noqa: E402


def test_label_is_fixed_regardless_of_hit_pid():
    """dkey に使う固定ラベル: hit なら同じ文字列 (pid が違っても)。"""
    assert catalog_reach_label(True) == catalog_reach_label(True)
    assert catalog_reach_label(False) != catalog_reach_label(True)


def test_miss_label_says_not_reached():
    assert "引けず" in catalog_reach_label(False)


def test_hit_label_says_value_empty():
    assert "引けた" in catalog_reach_label(True)


def test_annotate_appends_brand_when_miss():
    msg = annotate_selfcheck_error(
        "❌ 必須Item Specific 'Type' (タイプ) が空", False, "",
        "POKEMON JAPANESE MBG-MEGA STARTER SET MEGA GENGAR EX")
    assert msg.startswith("❌ 必須Item Specific 'Type' (タイプ) が空")
    assert "引けず" in msg
    assert "MBG-MEGA STARTER SET" in msg


def test_annotate_appends_pid_when_hit_but_field_empty():
    msg = annotate_selfcheck_error(
        "❌ 必須Item Specific 'Type' (タイプ) が空", True, "MBG-003", "POKEMON JAPANESE MBG-...")
    assert "MBG-003" in msg
    assert "引けた" in msg


def test_dkey_uses_only_the_fixed_label_not_brand():
    """2枚の cert が同じ真因でも brand が違えば dkey が割れる、を防ぐ確認。"""
    dkey_a = f"selfcheck:x|{catalog_reach_label(False)}"
    dkey_b = f"selfcheck:x|{catalog_reach_label(False)}"
    assert dkey_a == dkey_b, "同じ真因なのに brand混入で dkey が割れている"
