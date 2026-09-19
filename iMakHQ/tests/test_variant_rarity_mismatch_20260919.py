"""こちらがパラレルで候補が通常版、も外す (2026-09-19)。

実害 (2026-09-19 の目視): 現物「キッド＆キラー SP」に候補「キッド&キラー EB01-003 R」が
並び、人が「違う」を押していた。従来は「候補がパラレルを名乗り、こちらが名乗っていない」
時しか効かず、逆向きを見ていなかった。

★安全側: **両方にレアリティが明記されていて、それが食い違う時だけ**落とす。
  片方にしか書いていない物は落とさない (無在庫では仕入元を失う方が痛い)。
"""
import sys

sys.path.insert(0, r"C:/dev/iMak/iMakHQ/tools")
import psa_hoju_fill as H

f = H.candidate_variant_conflicts


def test_こちらがSPで候補が通常版なら外す():
    assert f("【PSA10】キッド＆キラー SP EB01-003", "キッド&キラー EB01-003 R 日本語版") is True


def test_同じレアリティなら残す():
    assert f("ロロノア・ゾロ(SEC){緑}〈OP06-118〉", "ロロノア・ゾロ OP06-118 SEC") is False


def test_片方にしか書いていなければ残す():
    assert f("PSA10 ピカチュウ 073/071", "PSA10 ピカチュウ 073/071 SR") is False
    assert f("PSA10 ピカチュウ SR", "PSA10 ピカチュウ 073/071") is False


def test_区切りを消費しない():
    """`(SP/SR)` のように並ぶ時、両方を拾うこと (消費すると SP だけになり誤爆する)。"""
    assert H._rarity_tokens("【PSA10】ミス・オールサンデー(SP/SR){紫}") == {"SP", "SR"}
    assert f("【PSA10】ミス・オールサンデー(SP/SR){紫}", "ミス・オールサンデー SR SP") is False


def test_単語の途中は拾わない():
    assert H._rarity_tokens("SPECIAL CARD") == set()
    assert H._rarity_tokens("RR") == {"RR"}          # RR は R ではない


def test_候補だけパラレルは従来どおり外す():
    assert f("PSA10 ルフィ OP01-001", "PSA10 ルフィ OP01-001 パラレル") is True
