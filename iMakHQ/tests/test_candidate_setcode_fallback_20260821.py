# -*- coding: utf-8 -*-
"""post_psa_review — set_code が取れない時に候補ゼロで打ち切らない (2026-08-21).

回答書: `2026-08-20_hq_act_proposals_ebay_norm_and_act_lock_response.md` (C)

実害 (実機で lookup を叩いた出力):
    lookup_one_piece('ONE PIECE JAPANESE FILM RED: ENCORE PACK','004','NEW GENESIS')
      ⚠️ set_code 抽出失敗 → None
    catalog には在る (ST11-004_p1 / name_en='New Genesis')。PSA実写と公式画像を
    両方 download して照合済 = 同一カード。
    `expected` が無い経路は missing_models に「auto候補無=該当なし 要調査」と書くので、
    **catalog に在るカードでも毎回 catalog 依頼になる**。

    lookup_pokemon('POKEMON JAPANESE CLL-TRADING CARD GAME CLASSIC ...','002','CHARMELEON')
      ⚠️ Pokemon set_code 抽出失敗 → None
    brand の先頭に CLL と書いてあるのに読めていなかった。

守りたい性質:
  - 候補が0件にならないこと
  - 弱い当てずっぽうを `expected` に昇格させないこと (`weak_promo_guess` は不変)
"""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import post_psa_review as R  # noqa: E402


class TestPokemonSetCodeExtraction:
    def test_cll_is_read_from_brand_head(self):
        brand = ("POKEMON JAPANESE CLL-TRADING CARD GAME CLASSIC "
                 "CHARIZARD & HO-OH EX DECK")
        assert R._extract_set_code(brand, "pokemon_tcg") == "CLL"

    def test_clk_and_clf_too(self):
        assert R._extract_set_code("POKEMON JAPANESE CLK-CLASSIC DECK", "pokemon_tcg") == "CLK"
        assert R._extract_set_code("POKEMON JAPANESE CLF-CLASSIC DECK", "pokemon_tcg") == "CLF"

    def test_alphanumeric_codes_still_win(self):
        """英数字混在の code を 3文字規則に食わせない (順序が意味を持つ)。"""
        assert R._extract_set_code("POKEMON JAPANESE SV8A-TERASTAL FEST EX",
                                   "pokemon_tcg") == "SV8A"

    def test_no_hyphen_no_guess(self):
        assert R._extract_set_code("POKEMON JAPANESE WEB", "pokemon_tcg") is None


def _fake_db(tmp_path, rows):
    """products テーブルだけの最小 DB。(category, product_id, name_en, images)"""
    p = tmp_path / "products.sqlite"
    con = sqlite3.connect(str(p))
    con.execute("CREATE TABLE products (category TEXT, product_id TEXT, "
                "name_en TEXT, name TEXT, images TEXT)")
    con.executemany("INSERT INTO products VALUES (?,?,?,?,?)",
                    [(c, pid, en, en, "") for c, pid, en in rows])
    con.commit()
    con.close()
    return p


# FILM RED の実データ (2026-08-21 catalog 実測: 番号004 の 208行のうち完全一致は6行)
_FILM_RED = [("one_piece_tcg", "ST11-004", "New Genesis"),
             ("one_piece_tcg", "ST11-004_D", "New Genesis"),
             ("one_piece_tcg", "ST11-004_P", "New Genesis"),
             ("one_piece_tcg", "ST11-004_ST16", "New Genesis"),
             ("one_piece_tcg", "ST11-004_p1", "New Genesis"),
             ("one_piece_tcg", "ST11-004_p2", "New Genesis"),
             # 同じ番号だが別のカード (名前が違う) = 候補に混ぜない
             ("one_piece_tcg", "OP01-004", "Trafalgar Law"),
             ("one_piece_tcg", "OP02-004", "Nami"),
             ("one_piece_tcg", "EB01-004", "New World")]


class TestSetCodeMissFallback:
    @pytest.fixture()
    def db(self, tmp_path, monkeypatch):
        monkeypatch.setattr(R, "CATALOG_DB", _fake_db(tmp_path, _FILM_RED))

    def test_film_red_surfaces_the_st11_004_family(self, db):
        """set_code が無くても ST11-004 系が候補に出る (= 人が選べる)。"""
        cands = R._get_candidates("one_piece_tcg", None, "004",
                                  brand="ONE PIECE JAPANESE FILM RED: ENCORE PACK",
                                  subject="NEW GENESIS")
        pids = [c[0] for c in cands]
        assert pids, "候補ゼロで打ち切っている"
        for want in ("ST11-004", "ST11-004_p1", "ST11-004_p2",
                     "ST11-004_D", "ST11-004_P", "ST11-004_ST16"):
            assert want in pids, f"{want} が候補に出ていない: {pids}"

    def test_other_cards_with_the_same_number_are_not_mixed_in(self, db):
        """番号だけ同じで **名前が違う** カードは混ぜない (人が選べなくなる)。"""
        cands = R._get_candidates("one_piece_tcg", None, "004",
                                  brand="ONE PIECE JAPANESE FILM RED: ENCORE PACK",
                                  subject="NEW GENESIS")
        pids = [c[0] for c in cands]
        assert "OP01-004" not in pids and "OP02-004" not in pids, pids
        # ※'New World' (EB01-004) はこの fallback の対象外 (完全一致でない) だが、
        #   優先度3 のキャラ名検索が 'New' で拾うので候補には出る。
        #   それは 2026-08-19 からの既存挙動で、ここでは変えない。

    def test_no_subject_means_no_fallback(self, db):
        """Subject が無ければ名前で絞れない = この経路は使わない (fail-closed)。"""
        cands = R._get_candidates("one_piece_tcg", None, "004",
                                  brand="ONE PIECE JAPANESE FILM RED: ENCORE PACK",
                                  subject="")
        assert [c[0] for c in cands] != ["ST11-004"], "名前検証なしで絞ってはいけない"


class TestWeakGuessIsUnchanged:
    """弱い promo fallback を `expected` に昇格させない挙動は変えない。"""

    def test_weak_promo_guess_still_rejects_low_score(self):
        assert R.weak_promo_guess("... promo fallback) pid=OP07-118 score=10 ...")

    def test_weak_promo_guess_accepts_high_score(self):
        assert not R.weak_promo_guess("... promo fallback) pid=OP07-118 score=300 ...")
