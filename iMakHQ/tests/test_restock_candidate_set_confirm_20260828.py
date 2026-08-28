# -*- coding: utf-8 -*-
"""再仕入れ検索が「番号一致だけ」で別カードを候補にしないこと (2026-08-28)。

実害: 視覚確証で人が「違う」と判定した4件 (SM10-076 / OP06-093 = mercari,
SV1S-106 / SB02-053 = snkrdunk)。どれも **番号は合っているのに別カード**だった。
同じ走行で OP01-061 だけは「変種確証不可→候補出さず」と正しく落ちていた。

判定 (1丁目1番地): **②(引き方)の誤り。** カタログ依頼は出していない。
  ①の実測 (2026-08-28 catalog products.sqlite): 4KEY とも set 名が入っており正しい。
    SM10-076=拡張パック「ダブルブレイズ」/ SV1S-106=拡張パック「スカーレットex」/
    OP06-093=BOOSTER PACK -WINGS OF THE CAPTAIN- / SB02-053=MANGA BOOSTER 02
  ②の誤り: mercari は目視候補 (all_cands) を variant_hint 無し = **番号一致だけ**で
    積んでいた。snkrdunk は一致が1件なら set を確証せず採っていた。さらに確証トークンに
    「拡張」「パック」「BOOSTER PACK」等 **どのセットにも出る語**が混じっており、
    別セットでも確証済に見えていた。

直したのは採用条件そのもの (個別の潰し込みではない):
  **番号一致 かつ set 確証** の両方。確証材料が無ければ候補を出さない
  (= OP01-061 と同じ fail-closed)。取りこぼしは受け入れる (出品の正確性が上位)。

依頼書: hq/requests/2026-08-28_restock_search_returned_wrong_cards.md
回答書: 同 _response.md ([IMPLEMENT-GO])

snkrdunk の fixture は 2026-08-28 に実 API (/en/v1/search) から取った実観測 name。
`(decoy)` と注記した行だけが、採用条件を試すために足した同番号・別セットの偽候補。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import mercari_psa_resource as mp  # noqa: E402
import snkrdunk_psa_resource as sp  # noqa: E402

# --- catalog の実測 hint (2026-08-28 products.sqlite) -------------------------
# card_meta_for_key の戻り = [set_name, get_info, set_name_ebay, variant_type, rarity, name_jp]
HINT = {
    "SM10-076": ["拡張パック「ダブルブレイズ」", "", "Sm10: Double Blaze", "", "R", "カビゴン"],
    "SV1S-106": ["拡張パック「スカーレットex」", "", "Sv1s: Scarlet Ex", "", "UR", "コライドンex"],
    "OP06-093": ["BOOSTER PACK -WINGS OF THE CAPTAIN- [OP-06]", "双璧の覇者【OP-06】",
                 "Wings of the Captain", "", "SR", "ペローナ"],
    "SB02-053": ["MANGA BOOSTER 02 [SB02]", "MANGA BOOSTER 02[SB02]", "Manga Booster 02",
                 "", "SR", "フリーザ"],
    "OP01-061": ["", "ROMANCE DAWN【OP-01】", "Romance Dawn", "", "L", "カイドウ"],
}

# --- snkrdunk /en/v1/search の実観測レスポンス (2026-08-28) -------------------
SEARCH = {
    "SM10-076": [
        (11, 'Snorlax R [SM10 076/095](Expansion Pack "Double Blaze")'),
        (12, 'Snorlax R [SM10 076/095](Expansion Pack "Tag All Stars")'),   # (decoy)
    ],
    "SV1S-106": [
        (21, 'Koraidon ex UR[SV1S 106/078](Scarlet & Violet Expansion Pack "Scarlet ex")'),
        (22, "Koraidon ex HR [SVI EN 254/198](Scarlet & Violet)"),
        (23, 'Koraidon ex UR[SV1S 106/078](Expansion Pack "Violet ex")'),    # (decoy)
    ],
    "SB02-053": [
        (31, 'Frieza SR* [SB02-053](FUSION WORLD "MANGA BOOSTER 02")'),
        (32, 'Frieza SR [SB02-053](FUSION WORLD "MANGA BOOSTER 02")'),
        (33, 'Frieza SR* :Participation Prize [SB02-053](Promotional Crad '
             '"CHAMPIONSHIP 2025-2026 JAPAN FINALS")'),
        (34, 'Frieza SR* [SB02-053][EN](FUSION WORLD "MANGA BOOSTER 02")'),
        (35, 'Frieza SR [SB02-053][EN](FUSION WORLD "MANGA BOOSTER 02")'),
    ],
    "OP06-093": [
        (41, "Perona SR [OP06-093] (Flagship Battle Top 8 Souvenirs) for Japan"),
        (42, 'Perona SR-SPC :Japanese pattern Art [OP06-093](Booster Pack '
             '"THE AZURE SEA\'S SEVEN")'),
        (43, "Perona SR-P [OP06-093] (Booster Pack Wings of Captain)"),
        (44, "Perona SR [OP06-093](Flagship Battle Top 8 Souvenirs) for Asia"),
        (45, "Perona SR [OP06-093] (Booster Pack Wings of Captain)"),
    ],
    "OP01-061": [
        (51, "Kaido L-P [OP01-061] (Booster Pack ROMANCE DAWN)"),
        (52, "Kaido L [OP01-061] (Booster Pack ROMANCE DAWN)"),
    ],
}
# 4KEY のうち snkrdunk が正解として選ぶべき id (人が現物と照合した変種)
SNKR_EXPECTED = {"SM10-076": 11, "SV1S-106": 21, "SB02-053": 32, "OP06-093": 45}


def _payload(key):
    return {"streetwears": [{"id": i, "productNumber": "", "name": n}
                            for i, n in SEARCH[key]]}


def _m(name, price=30000, href=None):
    return {"name": name, "price": price, "href": href or f"https://jp.mercari.com/item/{price}"}


# --- 採用条件そのもの --------------------------------------------------------
class Test確証トークン:
    def test_どのセットにも出る語は確証にしない(self):
        """「拡張」「パック」で確証できてしまうと、別セットの同番号が確証済になる。"""
        assert sp.set_confirm_tokens(["拡張パック「ダブルブレイズ」", "", "Sm10: Double Blaze"]) == \
            ["ダブルブレイズ", "DOUBLEBLAZE"]
        assert "拡張" not in sp.set_confirm_tokens(HINT["SV1S-106"])
        assert "BOOSTERPACK" not in sp.set_confirm_tokens(HINT["OP06-093"])

    def test_セット記号は確証にしない(self):
        """OP06 等はカード番号に必ず入っているので、確証すると番号一致と同義になる。"""
        assert "OP06" not in sp.set_confirm_tokens(HINT["OP06-093"])
        assert "SB02" not in sp.set_confirm_tokens(HINT["SB02-053"])

    def test_hintが無ければ確証材料ゼロ(self):
        assert sp.set_confirm_tokens(None) == []
        assert sp.set_confirm_tokens(["", "", ""]) == []
        # set 名が一般語だけ = 確証できない (promo 等)。番号一致だけになるので採らない側へ。
        assert sp.set_confirm_tokens(["", "", "Promo"]) == []

    def test_表記ゆれのTHEを吸収する(self):
        """catalog `WINGS OF THE CAPTAIN` と snkrdunk `Wings of Captain` は同じセット。"""
        assert "WINGSOFCAPTAIN" in sp.set_confirm_tokens(HINT["OP06-093"])
        assert sp.set_confirmed("Perona SR [OP06-093] (Booster Pack Wings of Captain)",
                                HINT["OP06-093"]) is True


# --- SNKRDUNK 側 -------------------------------------------------------------
class TestSnkrdunk:
    def test_4KEYとも正しい1枚に決まる(self):
        for key, want in SNKR_EXPECTED.items():
            got = sp.parse_search_for_card(_payload(key), key, variant_hint=HINT[key])
            assert got == want, f"{key}: {got} != {want}"

    def test_別セットの同番号は選ばれない(self):
        """decoy (同番号・別セット) と実在の別配布 (Flagship / Championship 参加賞) の両方。"""
        wrong = {"SM10-076": {12}, "SV1S-106": {22, 23},
                 "SB02-053": {31, 33, 34, 35}, "OP06-093": {41, 42, 43, 44}}
        for key, bad in wrong.items():
            got = sp.parse_search_for_card(_payload(key), key, variant_hint=HINT[key])
            assert got not in bad, f"{key}: 別カード {got} を採った"

    def test_hint無しは番号が一致しても採らない(self):
        for key in SNKR_EXPECTED:
            assert sp.parse_search_for_card(_payload(key), key) is None, key

    def test_一致が1件でもset未確証なら採らない(self):
        """「市場に1件しか無い」は「それが自分の変種」の根拠にならない。"""
        one = {"streetwears": [{"id": 99, "productNumber": "",
                                "name": "Snorlax R [SM10 076/095]"}]}     # set 名なし
        assert sp.parse_search_for_card(one, "SM10-076", variant_hint=HINT["SM10-076"]) is None

    def test_OP01_061は今までどおり候補を出す条件を満たす時だけ採る(self):
        """揃える先。set 名 (ROMANCE DAWN) が出品名に在れば採り、無ければ採らない。"""
        assert sp.parse_search_for_card(_payload("OP01-061"), "OP01-061",
                                        variant_hint=HINT["OP01-061"]) == 52
        bare = {"streetwears": [{"id": 53, "productNumber": "", "name": "Kaido L [OP01-061]"}]}
        assert sp.parse_search_for_card(bare, "OP01-061", variant_hint=HINT["OP01-061"]) is None


# --- メルカリ側 --------------------------------------------------------------
class TestMercari:
    def test_別セットの同番号は候補にしない(self):
        """SM10-076 の市場表記 076/095 は、別セットの出品名にも出る。"""
        items = [_m("PSA10 ポケモンカード 拡張パック タッグオールスターズ カビゴン 076/095", 12000),
                 _m("PSA10 ポケモンカード 拡張パック ダブルブレイズ カビゴン 076/095", 30000)]
        got = mp.pick_psa10_candidates(items, "SM10-076", HINT["SM10-076"],
                                       limit=8, market_no="076/095")
        assert [t[0] for t in got] == [30000], got

    def test_別セットしか無い時は候補ゼロ(self):
        """実害の形そのもの。旧実装は「拡張」「パック」が当たるので確証済として採っていた。"""
        items = [_m("PSA10 ポケモンカード 拡張パック タッグオールスターズ カビゴン 076/095", 12000)]
        assert mp.pick_psa10_candidates(items, "SM10-076", HINT["SM10-076"],
                                        limit=8, market_no="076/095") == []

    def test_目視候補も番号一致だけでは積まない(self):
        """all_cands (視覚確証に並べる枠) の作り方。以前はここが variant_hint 無しだった。"""
        items = [_m("PSA10 ポケモンカード カビゴン 076/095", 9000)]      # set 名なし
        assert mp.pick_psa10_candidates(items, "SM10-076", HINT["SM10-076"],
                                        limit=8, market_no="076/095") == []

    def test_hint無しは番号が一致しても候補ゼロ(self):
        items = [_m("PSA10 ポケモンカード 拡張パック ダブルブレイズ カビゴン 076/095", 30000)]
        assert mp.pick_psa10_candidates(items, "SM10-076", None,
                                        limit=8, market_no="076/095") == []

    def test_正しいセットは今までどおり拾う(self):
        items = [_m("PSA10 ワンピースカード 双璧の覇者 ペローナ OP06-093 SR", 40000)]
        got = mp.pick_psa10_candidates(items, "OP06-093", HINT["OP06-093"])
        assert [t[0] for t in got] == [40000], got

    def test_kw確証も同じ基準(self):
        """kw_variant_confident と _variant_matches が食い違うと、確証済なのに候補ゼロになる。"""
        assert mp.kw_variant_confident("PSA10 カビゴン 076/095", HINT["SM10-076"]) is False
        assert mp.kw_variant_confident("PSA10 ダブルブレイズ カビゴン 076/095",
                                       HINT["SM10-076"]) is True
        assert mp.kw_variant_confident("PSA10 拡張パック カビゴン 076/095",
                                       HINT["SM10-076"]) is False
