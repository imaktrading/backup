"""PSA Subject の照合: ハイフン名が消えないこと / 空振りを「照合した」と言わないこと。

2026-09-19 (依頼 2026-09-17_act_code_proposals_tcg.md 提案2・3)。
実害: `FA/HO-OH GX TO HAVE SEEN BTL.RNBW.` から HO-OH が消え、「名前でも引けない =
未収録」と誤断定して catalog へ誤依頼 (cert160479905 が2日連続で GAP 除外)。
"""
import sys

sys.path.insert(0, r"C:/dev/iMak/iMakHQ/tools")
from psa_preflight import _subject_tokens, name_checked


def test_ハイフン名は繋げた形で残る():
    toks = _subject_tokens("FA/HO-OH GX TO HAVE SEEN BTL.RNBW.")
    assert "HOOH" in toks
    assert "HO" not in toks and "OH" not in toks   # 2文字の断片は何にでも当たるので出さない


def test_ハイフンが区切りの時は分けた形も残る():
    toks = _subject_tokens("SHINING MAGIKARP-HOLO 25TH ED")
    assert "MAGIKARP" in toks                      # 分けた形
    assert "MAGIKARPHOLO" in toks                  # 繋げた形 (どちらが正かは catalog が決める)


def test_ピリオド入りの名前も残る():
    assert "MR9" in _subject_tokens("MR.9 & GALDINO")


def test_セット名の語しか残らなければ照合したと言わない():
    """Brand に無い語が1つも無い = 空振り。catalog に「未収録」と送ってはいけない。"""
    assert name_checked("SUN & MOON", "POKEMON JAPANESE SUN & MOON") is False
    assert name_checked("FA/HO-OH GX", "POKEMON JAPANESE SUN & MOON") is True
