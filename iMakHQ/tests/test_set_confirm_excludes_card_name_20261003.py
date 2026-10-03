"""版の確証にカード名を使わない (2026-10-03 P-041_r1 にセブンイレブン版が「確証済み」で並んだ)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import snkrdunk_psa_resource as sp  # noqa: E402

ST18 = ["", "スタートデッキ 紫 モンキー・D・ルフィ【ST-18】", "PURPLE Monkey D. Luffy", "", "P",
        "モンキー・D・ルフィ", "Monkey D. Luffy"]


def test_card_name_in_set_name_does_not_confirm_version():
    assert sp.set_confirm_tokens(ST18) == []
    assert not sp.set_confirmed("ワンピ モンキー・D・ルフィ P-041 PSA10 セブンイレブンプロモ", ST18)


def test_other_set_words_still_confirm():
    h = ["", "ROMANCE DAWN【OP-01】", "Romance Dawn", "", "SEC", "シャンクス", "Shanks"]
    assert sp.set_confirmed("PSA10 シャンクス OP01-120 ROMANCE DAWN", h)


def test_old_hint_without_english_name_still_works():
    h = ["", "ROMANCE DAWN【OP-01】", "Romance Dawn", "", "SEC", "シャンクス"]
    assert sp.set_confirm_tokens(h) == ["ROMANCEDAWN"]
