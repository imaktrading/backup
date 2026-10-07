# -*- coding: utf-8 -*-
"""目視で OK しても出品の手前で落ち、毎回目視に戻っていた2件 (2026-10-07)。

ユーザー「新規の目視で何回も出てくる奴は？」「普通、新規の目視には１回しか出ないはずでしょ」
"""
import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(HQ)
sys.path.insert(0, os.path.join(HQ, "tools"))
sys.path.insert(0, os.path.join(ROOT, "iMakeBayAPI"))

import listing_validator as V  # noqa: E402
import psa_variant_gate as G  # noqa: E402


def _r(pid, rarity, lang, alias=None, vt="starter_deck"):
    return {"product_id": pid, "specs": {"rarity": rarity, "variant_type": vt},
            "language": lang, "alias_of": alias}


def test_gundam_plus_label_picks_the_plus_row_body():
    # cert 122484177 ST04-010 COMMON+: 公式のパラレル行はレアリティ C のまま 7本 → 決められなかった
    good = [_r("ST04-010_bp", "C+", "en"), _r("ST04-010_bp_JP", "C+", "ja", alias="ST04-010_p1")] + \
           [_r("ST04-010_p%d" % i, "C", None, vt="alt_art") for i in (1, 2, 3, 4, 5, 7)]
    ok = [r["product_id"] for r in good]
    b = "GUNDAM JAPANESE SEED STRIKE"
    assert G.narrow_gundam_plus(b, "KIRA YAMATO COMMON+", good, ok) == ["ST04-010_p1"]
    # 英語版のラベルなら英語の行
    assert G.narrow_gundam_plus("GUNDAM SEED STRIKE", "KIRA YAMATO COMMON+", good, ok) == ok  # en/ja 2本 → 絞らない
    # 「+」の無いラベルは触らない
    assert G.narrow_gundam_plus(b, "KIRA YAMATO COMMON", good, ok) == ok


def test_film_red_encore_pack_promo_passes_selfcheck():
    # cert 84299672 新時代 ST11-004_p1: PSA brand にセット記号が無い配布プロモ
    errs = V.validate_title_against_psa(
        "PSA 10 One Piece Promo Cards #ST11-004 New Genesis 2023 Super Rare",
        "ONE PIECE JAPANESE FILM RED: ENCORE PACK", "004", "Promo Cards")
    assert errs == []
    # 番号が違えば今までどおり落とす
    assert V.validate_title_against_psa(
        "PSA 10 One Piece Promo Cards #ST11-005 New Genesis",
        "ONE PIECE JAPANESE FILM RED: ENCORE PACK", "004", "Promo Cards")


def test_repeat_counts_lists_certs_answered_before():
    import post_psa_review as P
    vc = {"122484177": {"choice": "OK", "product_id": "ST04-010", "times": 5},
          "84299672": {"choice": "OK", "product_id": "ST11-004_p1", "times": 2},
          "111": {"choice": "NONE"}}
    t = [{"cert": "84299672"}, {"cert": "122484177"}, {"cert": "111"}, {"cert": "999"}]
    assert P.repeat_counts(t, vc) == [("122484177", 5), ("84299672", 2)]
    assert P.repeat_counts([{"cert": "999"}], vc) == []
