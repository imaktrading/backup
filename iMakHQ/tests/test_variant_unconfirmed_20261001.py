"""補URL探索: 絵柄が複数ある番号の候補を捨てずに「版未確認」で目視に回す (2026-10-01)。

ユーザー「目視で決めたらいい」。あわせて:
  - 出品名の版の印 (手配書 / SP / スーパーパラレル / コミパラ) を読む
  - 「ONE PIECE」「カードゲーム」をセットの手がかりに数えない
  - 記念セット・大会配布などの版の検索語に「パラレル」を付けない
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import mercari_psa_resource as mp  # noqa: E402
import psa_resource_gate as gate  # noqa: E402
import snkrdunk_psa_resource as sp  # noqa: E402


def test_item_print_reads_sp_words_before_parallel():
    assert sp._item_print("PSA10 バギー 手配書 WANTED SP OP09-051") == "SPC"
    assert sp._item_print("PSA10 ルフィ スーパーパラレル OP05-119") == "SPC"
    assert sp._item_print("PSA10 ルフィ スペシャルカード") == "SPC"
    assert sp._item_print("Buggy R-SPC [OP09-051]") == "SPC"
    assert sp._item_print("PSA10 ゾロ パラレル EB04-007") == "P"
    assert sp._item_print("PSA10 バギー コミパラ OP09-051") == "MANGA"
    assert sp._item_print("PSA10 バギー OP09-051") == ""
    # SP は単独の語だけ (別の単語の一部は読まない)
    assert sp._item_print("PSA10 ASPIRE OP09-051") == ""


def test_generic_one_piece_words_do_not_confirm_set():
    toks = sp.set_confirm_tokens(["ONE PIECE カードゲーム", "", ""])
    assert "ONEPIECE" not in toks and "カードゲーム" not in toks
    assert sp.set_confirmed("PSA10 状態A ONE PIECE ワンピースカードゲーム", ["ONE PIECE カードゲーム", "", ""]) is False


def test_print_word_not_parallel_for_non_booster_versions():
    hint_jump = ["", "最強ジャンプ5月号応募者全員サービス", "", "alt_art", "C", ""]
    assert mp.print_word_for_key("one_piece_tcg:ST17-003_p1", hint_jump) == ""
    hint_pack = ["", "ブースターパック 新たなる皇帝【OP-09】", "", "alt_art", "R", ""]
    assert mp.print_word_for_key("one_piece_tcg:OP09-051_p1", hint_pack) == "パラレル"
    hint_sp = ["", "ブースターパック 新たなる皇帝【OP-09】", "", "alt_art", "SPカード", ""]
    assert mp.print_word_for_key("one_piece_tcg:OP09-051_p3", hint_sp) == "SP"


def _it(price, href, name):
    return {"price": price, "href": href, "name": name}


def test_variant_unconfirmed_candidates_keeps_compatible_drops_contradicting():
    items = [
        _it(5000, "u1", "PSA10 バギー OP09-051 パラレル"),          # 違う版と書いてある → 外す
        _it(6000, "u2", "PSA10 バギー 手配書 SP OP09-051"),        # 欲しい版の印 → 残す
        _it(7000, "u3", "PSA10 バギー OP09-051"),                  # 印なし → 残す (人が決める)
        _it(8000, "u4", "PSA9 バギー 手配書 SP OP09-051"),         # PSA10 でない → 外す
        _it(9000, "u5", "PSA10 バギー OP09-050"),                  # 番号違い → 外す
        _it(9500, "u6", "PSA10 バギー コミパラ OP09-051"),         # 漫画の版 → 外す
    ]
    hint_sp = ["", "ブースターパック 新たなる皇帝【OP-09】", "", "alt_art", "SPカード", ""]
    got = mp.variant_unconfirmed_candidates(items, "OP09-051", hint_sp)
    assert [t[1] for t in got] == ["u2", "u3"]


def test_variant_unconfirmed_candidates_unknown_version_keeps_all_same_number():
    items = [_it(5000, "u1", "PSA10 バギー OP09-051 パラレル"), _it(6000, "u2", "PSA10 バギー OP09-051")]
    got = mp.variant_unconfirmed_candidates(items, "OP09-051", ["", "", "", "", "", ""])
    assert [t[1] for t in got] == ["u1", "u2"]


def test_visual_candidates_show_variant_cands_flagged_and_not_verified():
    mr = {"best": None, "cands": [], "all_cands": [],
          "variant_cands": [[6000, "https://jp.mercari.com/item/m1", "PSA10 バギー 手配書 SP OP09-051"]]}
    out = gate._build_visual_candidates(mr, {}, card_no=None)
    assert len(out) == 1
    assert out[0]["variant_unconfirmed"] is True and out[0]["variant_ok"] is False


def test_visual_candidates_respect_exclusions_for_variant_cands():
    u = "https://jp.mercari.com/item/m1"
    mr = {"variant_cands": [[6000, u, "PSA10 バギー SP OP09-051"]]}
    assert gate._build_visual_candidates(mr, {}, card_no=None, exclude=[u]) == []
