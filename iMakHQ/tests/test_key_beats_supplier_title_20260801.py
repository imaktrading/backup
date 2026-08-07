"""補URL検索の番号は **KEY(catalog SSOT) を優先**する回帰テスト (2026-08-01)。

実害 (実測):
    商品管理シートの title 列は **仕入元(メルカリ)の出品タイトルをそのまま**持っている
    (同じ列に「カウズ Tシャツ XL」等の生の出品名が並ぶ)。= 他人が書いた自由文。
    `build_card_query` はその自由文から抜いた番号を第一優先にしていたため、
    出品者が番号を書き間違えていると **誤ったカード番号でメルカリを検索**していた。

    2026-08-01 実測 (live PSA 257件中 2件):
      itemID 358761687924  仕入元title 'OP10-012'(=ドラゴン十三號) / KEY 'ST12-012'(=シャーロット・プリン)
      itemID 358761687925  仕入元title 'OP01-008'(=キャベンディッシュ) / KEY 'EB01-056'(=フランペ)
    → 別カードの番号で探すので当然0件 → **「市場に無い」と誤診**していた。

    ★さらに name_jp も汚染されていた。catalog の該当レコードは name_jp が空で、
      `build_card_query` が **誤番号から名前を逆引き**するため、検索語に
      'ドラゴン十三號' / 'キャベンディッシュ' という **別カードの名前**が載っていた。

守るべき性質:
    1. KEY と title の番号が食い違ったら **KEY を採る** ([[catalog_ssot_principle]])
    2. その時 name_jp も **正しい番号で引き直す** (誤番号由来の名前を残さない)
    3. 食い違いは黙って直さず **警告を出す** (出品者の誤記が何件あるか見えるようにする)
    4. KEY が無い / 番号が取れない行は従来どおり (後方互換・fail-closed)
"""
import io
import os
import sys
import contextlib

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
sys.path.insert(0, TOOLS)

import mercari_psa_resource as mp        # noqa: E402
from psa_hoju_fill import build_search_query   # noqa: E402


def _q(target):
    """警告を捨てて query だけ取る。"""
    with contextlib.redirect_stdout(io.StringIO()):
        return build_search_query(target, mp)


def _q_with_log(target):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        q = build_search_query(target, mp)
    return q, buf.getvalue()


PUDDING = {"itemID": "358761687924",
           "title": "PSA10 シャーロット・プリン OP10-012 8058",
           "key": "one_piece_tcg:ST12-012_OP10_SP"}
FLAMPE = {"itemID": "358761687925",
          "title": "PSA10 シャーロット・フランペ OP01-008 7037",
          "key": "one_piece_tcg:EB01-056_OP10_SP"}


def test_key_number_wins_over_supplier_title():
    assert _q(PUDDING)["card_no"] == "ST12-012"
    assert _q(FLAMPE)["card_no"] == "EB01-056"


def test_name_is_not_taken_from_the_wrong_number():
    """誤番号から逆引きした **別カードの名前** が検索語に残らないこと。"""
    q = _q(PUDDING)
    assert "ドラゴン" not in (q["name_jp"] or ""), q["name_jp"]
    assert "ドラゴン" not in q["kw"]
    q2 = _q(FLAMPE)
    assert "キャベンディッシュ" not in (q2["name_jp"] or ""), q2["name_jp"]
    assert "キャベンディッシュ" not in q2["kw"]


def test_keyword_uses_the_key_number():
    assert "ST12-012" in _q(PUDDING)["kw"]
    assert "EB01-056" in _q(FLAMPE)["kw"]
    assert "OP10-012" not in _q(PUDDING)["kw"]
    assert "OP01-008" not in _q(FLAMPE)["kw"]


def test_mismatch_is_reported_not_silently_fixed():
    """黙って直すと出品者の誤記が何件あるか誰も気づけない。"""
    _, log = _q_with_log(PUDDING)
    assert "番号不一致" in log
    assert "ST12-012" in log and "OP10-012" in log


def test_agreeing_title_produces_no_warning():
    """食い違っていない行で警告を出さない (ノイズにしない)。"""
    _, log = _q_with_log({"itemID": "x", "title": "PSA10 なにか OP01-008 0001",
                          "key": "one_piece_tcg:OP01-008"})
    assert "番号不一致" not in log


def test_no_key_falls_back_to_title():
    """KEY が無い行は従来どおり title 由来 (後方互換)。"""
    q = _q({"itemID": "y", "title": "PSA10 なにか OP01-008 0002", "key": ""})
    assert q["card_no"] == "OP01-008"
