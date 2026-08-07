# -*- coding: utf-8 -*-
"""刷新タイトルの固有名詞の壊れを入稿前に止める (2026-08-03)。

実際に刷新プレビューで出た事故:
    'Kirara Hoshi' → 'Kirawra Hoshi'  綴りが壊れた (誤記 → SNAD リスク)
    'Yoko Kurama'  → 'Kurama'         妖狐が落ちて別キャラと紛れる
生成は Claude なので固有名詞を書き換えることがある。公式名は日本語で英題と直接
突き合わせられないため、**前回出していたタイトル**(= 実際に出品できていた)を基準に差分を見る。
綴り違いは意図的にやる理由が無いので止める / 語落ちは 80字制限で正当に起こるので警告のみ。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import ichibankuji_restock as K


def _kinds(old, new):
    return [k for k, _ in K.title_drift_warnings(old, new)]


def test_typo_in_proper_noun_is_flagged():
    w = K.title_drift_warnings(
        "Ichiban Kuji Jujutsu Kaisen I Prize Kirara Hoshi Masterlise Figure Bandai New",
        "Ichiban Kuji Jujutsu Kaisen I Prize Kirawra Hoshi Masterlise EXPIECE Figure New")
    assert [k for k, _ in w] == ["typo"]
    assert "Kirara" in w[0][1] and "Kirawra" in w[0][1]


def test_dropped_word_is_warning_not_typo():
    w = K.title_drift_warnings(
        "Ichiban Kuji Yu Yu Hakusho Last One Prize Yoko Kurama Masterlise Figure Bandai",
        "Ichiban Kuji Yu Yu Hakusho Last One Kurama Masterlise Figure Anime & Manga New")
    assert [k for k, _ in w] == ["dropped"] and "Yoko" in w[0][1]


def test_unchanged_title_has_no_warning():
    t = "Ichiban Kuji JoJo's Bizarre Adventure B Prize Crazy Diamond Masterlise New"
    assert K.title_drift_warnings(t, t) == []


def test_boilerplate_words_are_ignored():
    """Bandai/New/Japan 等の定型語の入替は固有名詞の壊れではない。"""
    assert K.title_drift_warnings(
        "Ichiban Kuji Foo Bar Figure Bandai New Japan",
        "Ichiban Kuji Foo Bar Figure Anime Manga New") == []


def test_edit_distance_is_capped_and_symmetric():
    assert K._edit_distance("kirara", "kirawra") == 1
    assert K._edit_distance("abc", "xyz") >= 3
    assert K._edit_distance("", "") == 0


# ---- 長音の表記ゆれは誤記ではない (2026-08-03) ----
# 実害: row121 'Yoko Kurama'(妖狐) → 'Youko Kurama' を綴り違いとして HOLD し、
# 正しい出品を止めてしまった。畳むのは日本語の長音パターンだけ('ou'→'o'/'uu'→'u')。

def test_long_vowel_romaji_variant_is_not_a_typo():
    assert K.title_drift_warnings("Prize Yoko Kurama Figure",
                                  "Prize Youko Kurama Figure") == []
    assert K.title_drift_warnings("Prize Yuki Figure", "Prize Yuuki Figure") == []
    assert K.title_drift_warnings("Prize Ryo Figure", "Prize Ryou Figure") == []


def test_english_words_are_not_collapsed():
    """'oo'/'oh' は畳まない = 英単語の誤記を見逃さない。"""
    assert [k for k, _ in K.title_drift_warnings("Sailor Moon Figure",
                                                 "Sailor Mon Figure")] == ["typo"]
    assert K._romaji_key("book") == "book"


def test_real_typo_still_caught_after_the_relaxation():
    assert [k for k, _ in K.title_drift_warnings(
        "Prize Kirara Hoshi Figure", "Prize Kirawra Hoshi Figure")] == ["typo"]
