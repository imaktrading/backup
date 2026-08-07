"""KEY のカテゴリ接頭辞から card番号を取れること (2026-07-28 の回帰).

KEY が bare('SV5a-083') から prefixed('pokemon_tcg:SV5a-083') に移行した際、
番号抽出が split("_")[0] のままだったため 'pokemon' を拾い **数字なし→番号取得失敗** になっていた。
症状は silent: 例外もエラーも出ず「探索不能」として skip されるだけなので、
補URL が永久に埋まらず / RESTOCK ゲートが供給を見落とす方向に倒れる。
実測 (2026-07-28): 補URL対象 127件中 **93件が探索不能** → 修正後 2件。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import psa_hoju_fill as P  # noqa: E402
import psa_resource_gate as G  # noqa: E402

PREFIXED = [
    ("pokemon_tcg:SV5a-083", "SV5A-083"),
    ("one_piece_tcg:OP09-004", "OP09-004"),
    ("dragonball_scg:FB04-008", "FB04-008"),
    ("pokemon_tcg:S-P-122", "S-P-122"),
    ("pokemon_tcg:MC-746", "MC-746"),
]


def test_hoju_extracts_number_from_prefixed_key():
    for key, want in PREFIXED:
        assert P._card_no_from_key(key) == want, key


def test_gate_extracts_number_from_prefixed_key():
    for key, want in PREFIXED:
        assert G._key_card_number(key) == want, key


def test_bare_key_still_works():
    """移行期は bare と prefixed が混在する。後方互換を落とさないこと。"""
    assert P._card_no_from_key("SV5a-083") == "SV5A-083"
    assert G._key_card_number("OP11-106") == "OP11-106"


def test_variant_suffix_is_still_stripped():
    """'_p1' 等の変種suffix除去は従来どおり (接頭辞と両方ある場合も)。"""
    assert P._card_no_from_key("one_piece_tcg:ST04-005_OP08") == "ST04-005"
    assert G._key_card_number("one_piece_tcg:OP11-106_p2") == "OP11-106"


def test_url_keys_are_still_rejected():
    """url-key は番号でない。接頭辞処理で誤って通してはいけない (fail-closed)。"""
    for k in ("item:m12345", "shops:2JU39AvCn2DuPTsNCHT9TH"):
        assert P._card_no_from_key(k) == ""
        assert G._key_card_number(k) is None


def test_no_digits_returns_empty():
    assert P._card_no_from_key("pokemon_tcg:UNKNOWN") == ""
    assert G._key_card_number("pokemon_tcg:UNKNOWN") is None
