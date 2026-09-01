# -*- coding: utf-8 -*-
"""タイトル → card番号 → catalog候補 を **通しで** 見る回帰テスト (2026-09-01)。

症状: PSA再仕入れ照合の目視ゲート② が「catalog候補なし(未収録→要追加)」で埋まる。
実測 2026-09-01 の走行は 13件とも card番号が空で、**catalog を引きにすら行っていなかった**。

真因は2つ、どちらも引き方 (②) 側:
  1. タイトルからの番号抽出が `(OP|ST|EB|SB|GD)nn-nnn | P-nnn` = ワンピースの書き方だけだった。
     ポケモン (058/095 / 261/SV-P)・ドラゴンボール (FB05-119 / E01-09)・
     ガンダム (GD02-072 / "GD02 #036") が1件も取れない。
  2. 受け取る側の fallback が `[A-Za-z0-9]{1,4}` で、promo の `182/XY-P` (ハイフン) を弾いていた。

★このテストが要る理由: 2026-07-24 (`2306ec3`) に同じ症状を直しているが、直したのは 2 の側だけで、
  そのテストは card番号を **関数に直接渡して**いた。渡す側が壊れたままでも緑になるので、
  実機では一度も通っていなかった。**タイトルから候補が出るまでを通す**のがこのテスト。
"""
import json
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import mercari_psa_resource as mp  # noqa: E402
import psa_resource_gate as G  # noqa: E402
import psa_resource_confirm as prc  # noqa: E402


# 実際に live に出ている PSA10 のタイトル (funnel_20260825 より)。作り話をしない。
REAL = [
    ("PSA 10 Pokemon Japanese Fairy Rise #053/050 Alolan Ninetales-GX", "053/050"),
    ("PSA 10 Pokemon Japanese Sun & Moon-Hidden Fates #231/150 Zoroark", "231/150"),
    ("PSA 10 Pokemon Japanese XY Promo #182/XY-P Aerodactyl-EX 2015", "182/XY-P"),
    ("PSA 10 Pokemon Japanese Promo #196/SV-P Eevee 2024 Card", "196/SV-P"),
    ("PSA 10 Pokemon SV9a #080 Cynthia Garchomp ex Heat Wave Arena", "SV9A-080"),
    ("PSA 10 Dragon Ball Raging Roar #FB03-139 Son Gohan : Youth 2025", "FB03-139"),
    ("PSA 10 Dragon Ball SCG Energy Marker Pack 01 #E01-09 Alternate Art", "E01-09"),
    ("PSA 10 Gundam CCG Dual Impact #GD02-072 Hyaku-Shiki Unit Card", "GD02-072"),
    ("PSA 10 Gundam Japanese #RP-025 Resource 2026 Card", "RP-025"),
    ("Gundam Card Game Dual Impact GD02 #036 Qubeley Pilot Rare PSA 10", "GD02-036"),
    ("PSA 10 One Piece Japanese 500 Years in the Future #OP07-051 Luffy", "OP07-051"),
    ("PSA 10 One Piece TCG Promo Cards #P-115 Boa Hancock Japanese", "P-115"),
    ("One Piece OP02 Paramount War #036 Nami Alternate Art PSA 10", "OP02-036"),
]


@pytest.mark.parametrize("title,want", REAL)
def test_card_number_from_real_titles(title, want):
    assert G._card_number(title) == want


def test_bare_number_alone_is_not_guessed():
    """番号だけ (#093) はどのセットか決まらない。推測しない (fail-closed)。"""
    assert G._card_number("PSA 10 Pokemon Terastal Festival ex #093 Umbreon ex Card") is None
    assert G._card_number("PSA 10 Pokemon Japanese Legendary Heartbeat #082 Togekiss V") is None


def test_one_piece_still_works_unchanged():
    """既に通っていたワンピースを壊していないこと (今回の対象は取れていなかった作品)。"""
    assert G._card_number("PSA 10 One Piece Japanese Standard Battle Winner #ST01-012") == "ST01-012"
    assert G._card_number("PSA 10 One Piece Japanese Premium Booster Vol.2 #PRB02-014") == "PRB02-014"


def test_key_wins_over_title_when_both_are_setcodes(capsys):
    """KEY 優先は 2026-08-01 の規約 (別カードを仕入れる事故の防止)。維持されていること。"""
    got = G._resource_card_number("PSA 10 One Piece #EB01-006 Chopper", "one_piece_tcg:ST01-006_p1")
    assert got == "ST01-006"
    assert "番号不一致" in capsys.readouterr().out


def test_no_false_mismatch_warning_for_pokemon(capsys):
    """KEY='SM8b-231' と title='231/150' は **同じカードの別表記**。誤警告を出さない。

    書き方を見ずに比べていたら、ポケモン全件で「タイトルが誤りの疑い」と出て
    本物の食い違い (ワンピース) が埋もれる。
    """
    got = G._resource_card_number("PSA 10 Pokemon Japanese Hidden Fates #231/150 Zoroark",
                                  "pokemon_tcg:SM8b-231")
    assert got == "SM8B-231", "KEY 優先は変えない"
    assert "番号不一致" not in capsys.readouterr().out


def _mkdb(tmp_path):
    db = str(tmp_path / "cat.sqlite")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE products (product_id TEXT, name_jp TEXT, set_name TEXT, "
                "images TEXT, specs TEXT, language TEXT, name_en TEXT, category TEXT)")
    rows = [
        # promo はハイフン入りのコレクター番号を card_number_text に持つ (実DBと同じ)
        ("XYP-182", "プテラEX", "XY Promo", "[]", json.dumps({"card_number_text": "182/XY-P"}), "ja", "Aerodactyl-EX"),
        ("SV-P-196", "イーブイ", "SV Promo", "[]", json.dumps({"card_number_text": "196/SV-P"}), "ja", "Eevee"),
        ("SM8b-231", "ゾロアークGX", "Hidden Fates", "[]", json.dumps({"card_number_text": "231/150"}), "ja", "Zoroark-GX"),
        ("FB03-139_p1", "孫悟飯：幼年期", "Raging Roar", "[]", json.dumps({}), "ja", "Son Gohan"),
        ("GD02-072", "百式", "Dual Impact", "[]", json.dumps({}), "ja", "Hyaku-Shiki"),
    ]
    con.executemany("INSERT INTO products (product_id,name_jp,set_name,images,specs,language,name_en,category) "
                    "VALUES (?,?,?,?,?,?,?,'tcg')", rows)
    con.commit()
    con.close()
    return db


E2E = [
    ("PSA 10 Pokemon Japanese XY Promo #182/XY-P Aerodactyl-EX 2015", "XYP-182"),
    ("PSA 10 Pokemon Japanese Promo #196/SV-P Eevee 2024 Card", "SV-P-196"),
    ("PSA 10 Pokemon Japanese Sun & Moon-Hidden Fates #231/150 Zoroark", "SM8b-231"),
    ("PSA 10 Dragon Ball Raging Roar #FB03-139 Son Gohan : Youth 2025", "FB03-139_p1"),
    ("PSA 10 Gundam CCG Dual Impact #GD02-072 Hyaku-Shiki Unit Card", "GD02-072"),
]


@pytest.mark.parametrize("title,want_pid", E2E)
def test_end_to_end_title_to_catalog_candidates(tmp_path, title, want_pid):
    """★本命: タイトルを入れたら候補が出るところまで。片側だけ直しても緑にならない。"""
    db = _mkdb(tmp_path)
    card_no = G._card_number(title)
    assert card_no, "タイトルから番号が取れていない (ここが 2026-09-01 の真因)"
    cands = mp.catalog_variants_for_cardno(card_no, _db=db, title_hint=title)
    assert [c["product_id"] for c in cands][:1] == [want_pid], (
        "%s → %s → 候補 %s" % (title[:40], card_no, [c["product_id"] for c in cands]))


def test_no_candidate_message_says_which_side_is_wrong():
    """「候補なし」の文言がカタログのせいに見えないこと。

    番号が読めていないだけなのに「未収録→要追加」と出ていたため、
    この表示を信じると **カタログへ嘘の追加依頼**を出すことになる (1丁目1番地の禁止事項)。
    """
    no_num = prc.build_confirm_html([{"idx": 0, "title": "t", "card_no": "", "psa_image": "",
                                      "candidates": [], "resolved_key": None, "ebay_url": "", "no_image": True}])
    assert "番号が読み取れない" in no_num
    assert "未収録" not in no_num.split("番号が読み取れない")[1][:60]
    has_num = prc.build_confirm_html([{"idx": 0, "title": "t", "card_no": "053/050", "psa_image": "",
                                       "candidates": [], "resolved_key": None, "ebay_url": "", "no_image": True}])
    assert "未収録の可能性" in has_num
