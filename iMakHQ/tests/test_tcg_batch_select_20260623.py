# -*- coding: utf-8 -*-
"""PSA新規バッチの franchise 均等サンプリング (tcg_batch_select) 回帰テスト。

2026-06-23 ユーザー要望: 在庫 Pokemon 大半でも Pokemon/One Piece/Dragon Ball を均等出品。
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "iMakTCG")))
import tcg_batch_select as bs  # noqa: E402


def test_classify_explicit_franchise_words():
    assert bs.classify_franchise("PSA10 ニコ・ロビン 25周年 ワンピース") == "OnePiece"
    assert bs.classify_franchise("PSA10 トランクス エナジーマーカー ドラゴンボールカード") == "DragonBall"
    assert bs.classify_franchise("PSA10フリーザー #1020455 ポケモンカード") == "Pokemon"


def test_classify_by_card_number():
    assert bs.classify_franchise("PSA10 リム OP09-037 SR") == "OnePiece"        # OP系番号
    assert bs.classify_franchise("【PSA10】ジュエリー・ボニー SR-P [OP07-026]") == "OnePiece"
    assert bs.classify_franchise("PSA10 ブロリー エナジーマーカー パラレル") == "DragonBall"


def test_classify_no_false_positive_pokemon():
    # 'POP17' の 'OP' を OnePiece 誤検出しない / ゾロアーク等の Pokemon を OP にしない
    assert bs.classify_franchise("PSA10★ ソーナンス 054/131 ミラー POP17 ポケモンカード") == "Pokemon"
    assert bs.classify_franchise("PSA10 ゾロアークGX 231/150 SSR ポケモンカード") == "Pokemon"
    assert bs.classify_franchise("") == "Pokemon"          # 不明は既定 Pokemon


def test_balanced_sample_round_robin():
    # Pokemon 大半でも OP/DB が均等に入る
    certs = [f"p{i}" for i in range(20)] + [f"o{i}" for i in range(5)] + [f"d{i}" for i in range(3)]
    tmap = {}
    for c in certs:
        if c.startswith("p"): tmap[c] = "ピカチュウ ポケモンカード"
        elif c.startswith("o"): tmap[c] = "ルフィ ワンピース"
        else: tmap[c] = "悟空 ドラゴンボールカード"
    picked = bs.balanced_sample(certs, tmap, 9, shuffle=lambda x: None)  # shuffle無効=決定的
    fr = [bs.classify_franchise(tmap[c]) for c in picked]
    assert len(picked) == 9
    # round-robin Pok→OP→DB → 3/3/3
    assert fr.count("Pokemon") == 3 and fr.count("OnePiece") == 3 and fr.count("DragonBall") == 3


def test_balanced_sample_exhausted_group_filled_by_others():
    # DB が2件しか無い → 残りは Pokemon/OP で埋める (取りこぼさず limit 達成)
    certs = [f"p{i}" for i in range(20)] + [f"o{i}" for i in range(20)] + ["d0", "d1"]
    tmap = {c: ("ポケモン" if c[0] == "p" else "ワンピース" if c[0] == "o" else "ドラゴンボール") for c in certs}
    picked = bs.balanced_sample(certs, tmap, 10, shuffle=lambda x: None)
    fr = [bs.classify_franchise(tmap[c]) for c in picked]
    assert len(picked) == 10
    assert fr.count("DragonBall") == 2            # 在庫分だけ
    assert fr.count("Pokemon") + fr.count("OnePiece") == 8   # 残りは他で充足


def test_balanced_sample_under_limit_returns_all():
    certs = ["p0", "o0"]
    tmap = {"p0": "ポケモン", "o0": "ワンピース"}
    picked = bs.balanced_sample(certs, tmap, 10, shuffle=lambda x: None)
    assert sorted(picked) == ["o0", "p0"]
