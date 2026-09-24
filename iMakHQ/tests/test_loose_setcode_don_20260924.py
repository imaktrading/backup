# -*- coding: utf-8 -*-
"""補URL③ 番号未確認の候補: ワンピースの型番違い・ドン!!カードを外す (2026-09-24)。

ユーザー「ジンベエ OP11-021 (リーダーパラレル)。ラベルは 021 だけど候補に 005 が出ている。021 の候補は1枚もない」。
KEY は OP11-021_p で正しかった (②出品くんの引き方)。メルカリに OP11-021 が無く、名前だけで拾った候補に
{ST01-005} のジンベエとドン!!カードが混ざっていた。型番は ポケモンの 001/032・#009 の形しか見ていなかった。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import mercari_psa_resource as mp  # noqa: E402


def ok(t):
    return mp.loose_title_ok(t, "OP11-021", "L", "ジンベエ")


def test_other_setcode_is_dropped():
    assert not ok("〔PSA10鑑定済〕ジンベエ(漫画背景)【C】{ST01-005}")


def test_don_card_is_dropped_for_non_don_target():
    assert not ok("PSA10 ジンベエ ドン!!カード ワンピースカードゲーム 熊本 プロモ")
    assert not ok("〔PSA10鑑定済〕ドン!!カード(SDキャラ/ジンベエ)【-】{-}")
    assert not ok("プレミアムカードコレクション熊本県スペシャル ジンベエ ドンカード psa10")


def test_same_setcode_and_unnumbered_are_kept():
    assert ok("【PSA10】ジンベエ(L★){緑}〈OP11-021〉リーダーパラレル")
    assert ok("PSA10 ジンベエ op11-021 パラレル")
    assert ok("【PSA10】ジンベエ 25th プレミアムカードコレクション")      # 番号なし = 目視に任せる


def test_pokemon_numbers_unchanged():
    assert mp.loose_title_ok("PSA10 ライチュウ S 237/190", "SV4a-237", "S", "ライチュウ")
    assert not mp.loose_title_ok("PSA10 ライチュウ S 001/190", "SV4a-237", "S", "ライチュウ")
