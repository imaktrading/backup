"""tcg_promo_name の回帰テスト — PSA Subject→promo名 抽出+casing安全化が「変にならない」固定。

実 psa_cache の Subject サンプルで検証 (2026-06-24)。崩れる例(25TH/COLL./FA/ 等)も含める。
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))
import tcg_promo_name as pn  # noqa: E402


def test_clean_distribution_promos():
    """綺麗な配布元説明: キャラ名を除いた残差が Title Case で出る。"""
    assert pn.propose_promo("MONKEY D. LUFFY ICHIBAN KUJI PURCHASE BONUS", "Monkey.D.Luffy") \
        == "Ichiban Kuji Purchase Bonus"
    assert pn.propose_promo("MONKEY D. LUFFY 7-ELEVEN CAMPAIGN", "Monkey D. Luffy") \
        == "7-Eleven Campaign"
    assert pn.propose_promo("VEGETA ULTIMATE BATTLE WINNER", "Vegeta") == "Ultimate Battle Winner"
    assert pn.propose_promo("NAMI STANDARD BATTLE WINNER", "Nami") == "Standard Battle Winner"


def test_hyphen_and_setcode_preserved():
    """ハイフン語/set code が崩れない (H2-Cell / FB02 大文字保持)。"""
    assert pn.propose_promo("CELL H2-CELL GAMES CAMPAIGN", "Cell") == "H2-Cell Games Campaign"
    assert pn.propose_promo("DEATH BALL FB02 SPECIAL ALTERNATE ART", "Death Ball") \
        == "FB02 Special Alternate Art"


def test_ordinal_and_abbrev_and_artprefix():
    """25TH→25th / COLL.→Collection / 先頭 FA/ ノイズ除去 — 変にならない。"""
    # "FA/PIKACHU 25TH ANNIVERSARY COLL." → Pikachu除去 → 残差 "FA/ 25TH ANNIVERSARY COLL."
    got = pn.propose_promo("FA/PIKACHU 25TH ANNIVERSARY COLL.", "Pikachu")
    assert "25th" in got and "Anniversary" in got and "Collection" in got
    assert "25Th" not in got and "Coll." not in got           # 崩れ casing が無い
    assert "/" not in got


def test_no_residual_returns_blank():
    """Subject がキャラ名だけ = 配布元説明なし → '' (付けない)。"""
    assert pn.propose_promo("CAMIE", "Camie") == ""
    assert pn.propose_promo("RORONOA ZORO", "Roronoa Zoro") == ""


def test_cardnumber_stripped():
    """残差にカード番号トークンが混ざっても除去される。"""
    assert pn.propose_promo("LUFFY P-001 ICHIBAN KUJI", "Luffy", card_number="P-001") \
        == "Ichiban Kuji"


def test_art_prefix_only_is_blank():
    """アート種別 prefix だけ (FA/AA) = 配布元説明でない → ''。"""
    assert pn.propose_promo("PIKACHU FA", "Pikachu") == ""


def test_empty_inputs():
    assert pn.propose_promo("", "X") == ""
    assert pn.normalize_promo("") == ""
    assert pn.extract_residual("", "X") == ""


def test_no_fabrication_garbage():
    """記号だけの残差は捏造とみなし '' (変な title を作らない)。"""
    assert pn.normalize_promo("/ - .") == ""
