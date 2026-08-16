"""tests/test_psa_restock - 売れた PSA10 の別個体探しロジック (2026-08-17).

PSA10 は 1 点もの。 売れた同じ現物は買えないので、 補充 = 同じカードの **別個体**。
ここで守りたいのは 2 つ:
  - **別のカードを掴まない** (誤出品に直結)
  - **売れた現物そのものを候補にしない** (買えないので無意味)

ネットワークは叩かない (ebay_sold は応答文字列を渡して parse だけ検証)。
"""
from __future__ import annotations

import pytest

from scrapers import ebay_sold as E
from scrapers import psa_cert as P
from scrapers import psa_restock as R

pytestmark = pytest.mark.offline


# 実際の GetItem 応答 (cert 付き One Piece) を再現した最小 Specifics
OP_SPECIFICS = {
    "Grade": "10",
    "Game": "One Piece Card Game",
    "Card Name": "Portgas D. Ace",
    "Card Number": "P-074",
    "Set": "Promo Cards",
    "Year Manufactured": "2024",
    "Rarity": "Promo",
    "Certification Number": "153420191",
}
PKM_SPECIFICS = {
    "Grade": "10",
    "Game": "Pokémon TCG",
    "Card Name": "Snorlax",
    "Card Number": "310/190",
    "Set": "Scarlet & Violet-Paldean Fates",
    "Year Manufactured": "2023",
}


# --------------------------------------------------------------------------
# is_psa10_card — 対象の入口
# --------------------------------------------------------------------------

def test_is_psa10_card_accepts_graded_card():
    assert R.is_psa10_card(OP_SPECIFICS) is True


def test_is_psa10_card_rejects_grade_9():
    assert R.is_psa10_card(dict(OP_SPECIFICS, Grade="9")) is False


def test_is_psa10_card_rejects_missing_grade():
    s = dict(OP_SPECIFICS)
    del s["Grade"]
    assert R.is_psa10_card(s) is False


def test_is_psa10_card_rejects_without_card_number():
    # 番号が無いとメルカリで引けず、同一カードの確認もできない
    assert R.is_psa10_card(dict(OP_SPECIFICS, **{"Card Number": ""})) is False


def test_is_psa10_card_rejects_non_tcg():
    assert R.is_psa10_card({"Grade": "10", "Card Number": "1", "Game": ""}) is False


# --------------------------------------------------------------------------
# build_keywords — 日本語で引けるキーワードを作れているか
# --------------------------------------------------------------------------

def test_build_keywords_uses_card_number():
    """英語のカード名では日本語の出品は引けない。番号が言語非依存の軸になる."""
    kws = R.build_keywords(R.to_card_identity(OP_SPECIFICS))
    assert kws[0] == "PSA10 P-074"
    assert "Portgas" not in " ".join(kws)


def test_build_keywords_adds_japanese_game_name():
    kws = R.build_keywords(R.to_card_identity(OP_SPECIFICS))
    assert "PSA10 ワンピース P-074" in kws


def test_build_keywords_pokemon_splits_slash_number():
    # "310/190" をそのまま検索語にすると引けない → 前半だけ使う
    kws = R.build_keywords(R.to_card_identity(PKM_SPECIFICS))
    assert kws[0] == "PSA10 310"
    assert "PSA10 ポケモンカード 310" in kws


def test_build_keywords_unknown_game_omits_japanese():
    # 知らないゲームに勝手な日本語を足さない (間違った語で引くくらいなら番号だけ)
    ident = R.to_card_identity(dict(OP_SPECIFICS, Game="Weiss Schwarz"))
    assert R.build_keywords(ident) == ["PSA10 P-074"]


def test_build_keywords_empty_without_card_number():
    # 名前だけで引くと別カードを拾うので探しに行かない
    ident = R.to_card_identity(dict(OP_SPECIFICS, **{"Card Number": ""}))
    assert R.build_keywords(ident) == []


# --------------------------------------------------------------------------
# to_match_info + match_signals — 同一カード判定
# --------------------------------------------------------------------------

def _vision(label, num="074", year="2024"):
    return {"cert": "111111111", "grade": "GEM MT 10", "label": label,
            "card_number": num, "year": year}


def test_same_card_matches_multiple_signals():
    v = _vision("2024 ONE PIECE JP PROMO CARDS PORTGAS D. ACE")
    m = P.match_signals(v, R.to_match_info(R.to_card_identity(OP_SPECIFICS)))
    assert m["count"] >= 2
    assert "subject" in m["signals"]


def test_different_card_fails_the_gate():
    # 番号違いの別カードを掴まない
    v = _vision("2024 ONE PIECE JP PROMO CARDS MONKEY D. LUFFY", num="119", year="2023")
    m = P.match_signals(v, R.to_match_info(R.to_card_identity(OP_SPECIFICS)))
    assert m["count"] < 2


def test_pokemon_card_number_normalized_for_match():
    # eBay "310/190" と ラベル "310" が一致扱いになる
    v = _vision("2023 POKEMON JAPANESE PALDEAN FATES SNORLAX", num="310", year="2023")
    m = P.match_signals(v, R.to_match_info(R.to_card_identity(PKM_SPECIFICS)))
    assert "card_number" in m["signals"]


# --------------------------------------------------------------------------
# is_same_individual — 売れた現物を候補にしない
# --------------------------------------------------------------------------

def test_same_cert_is_same_individual():
    assert R.is_same_individual("153420191", "153420191") is True


def test_different_cert_is_another_individual():
    assert R.is_same_individual("153420191", "153420192") is False


def test_missing_cert_is_not_treated_as_same():
    # 判定材料が無いのに「同じ現物」と決めつけない (別ゲートで落ちる)
    assert R.is_same_individual("", "153420191") is False
    assert R.is_same_individual("153420191", "") is False


# --------------------------------------------------------------------------
# ebay_sold — 純関数
# --------------------------------------------------------------------------

def test_group_line_items_dedupes_by_item_id():
    orders = [
        {"creationDate": "2026-08-01T00:00:00.000Z",
         "lineItems": [{"legacyItemId": "111", "title": "A", "quantity": 1}]},
        {"creationDate": "2026-08-07T00:00:00.000Z",
         "lineItems": [{"legacyItemId": "111", "title": "A", "quantity": 2}]},
    ]
    got = E.group_line_items(orders)
    assert len(got) == 1
    assert got[0]["quantity"] == 3
    assert got[0]["sold_at"] == "2026-08-07"  # 最新の売却日


def test_group_line_items_sorted_newest_first():
    orders = [
        {"creationDate": "2026-06-01T00:00:00.000Z",
         "lineItems": [{"legacyItemId": "111", "title": "A"}]},
        {"creationDate": "2026-08-01T00:00:00.000Z",
         "lineItems": [{"legacyItemId": "222", "title": "B"}]},
    ]
    assert [o["item_id"] for o in E.group_line_items(orders)] == ["222", "111"]


def test_group_line_items_skips_rows_without_item_id():
    orders = [{"creationDate": "2026-08-01T00:00:00.000Z",
               "lineItems": [{"title": "A"}, {"legacyItemId": "", "title": "B"}]}]
    assert E.group_line_items(orders) == []


def test_parse_get_item_extracts_specifics():
    xml = ("<GetItemResponse><Ack>Success</Ack><Item><Title>PSA 10 Ace</Title>"
           "<ItemSpecifics>"
           "<NameValueList><Name>Card Name</Name><Value>Portgas D. Ace</Value></NameValueList>"
           "<NameValueList><Name>Grade</Name><Value>10</Value></NameValueList>"
           "</ItemSpecifics></Item></GetItemResponse>")
    got = E.parse_get_item(xml)
    assert got["ok"] is True
    assert got["title"] == "PSA 10 Ace"
    assert got["specifics"]["Card Name"] == "Portgas D. Ace"


def test_parse_get_item_unescapes_entities():
    xml = ("<Ack>Success</Ack><Title>Scarlet &amp; Violet</Title>"
           "<NameValueList><Name>Set</Name><Value>Paldean &amp; Fates</Value></NameValueList>")
    got = E.parse_get_item(xml)
    assert got["title"] == "Scarlet & Violet"
    assert got["specifics"]["Set"] == "Paldean & Fates"


def test_parse_get_item_joins_multi_values():
    xml = ("<Ack>Success</Ack><NameValueList><Name>Features</Name>"
           "<Value>Holo</Value><Value>Alt Art</Value></NameValueList>")
    assert E.parse_get_item(xml)["specifics"]["Features"] == "Holo/Alt Art"


def test_parse_get_item_failure_is_not_ok():
    got = E.parse_get_item("<Ack>Failure</Ack><Errors><ShortMessage>x</ShortMessage></Errors>")
    assert got["ok"] is False


def test_parse_get_item_empty_is_not_ok():
    got = E.parse_get_item("")
    assert got["ok"] is False and got["specifics"] == {}
