# -*- coding: utf-8 -*-
"""ガチャ: 食玩 (シールウエハース等) を扱えるようにした (2026-08-21).

回答書 `2026-08-21_gacha_food_toy_disclaimer_response.md`:
  生成器は **カプセルトイ前提が3か所に焼いてある**ので、食玩を無印で流すと
  「嘘の説明で出品される」。切り替えるのは3点 + コンディションの一文:
    ① タイトル      Capsule Toy / Gashapon を使わない
    ② GACHA.txt     カプセルの2文を出さず、食玩の一文に差し替え
    ③ 年齢確認      gashapon.jp では取れない → **全件 目視**
    ④ 冒頭の `All original packaging ... present and intact.` も差し替え
       (菓子を抜くため外装を開けるので、同じ説明文の中で矛盾する = SNAD の材料)

どの行が食玩かは **中間スプシ S列の印だけ**で決める (タイトルから当てない)。
"""
from __future__ import annotations

import os
import sys

import pytest

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))

import gacha_official as O                                       # noqa: E402
import gacha_to_csv as G                                         # noqa: E402


def _row(url="https://item.rakuten.co.jp/auc-yuyou/g1/",
         title="ワンピース シールウエハース 全22種セット バンダイ",
         pics="https://x/a.jpg", price="2820", cat="カプセルトイ",
         item_id="", mark=""):
    r = [""] * 19
    r[0], r[1], r[2], r[6], r[12], r[17] = url, item_id, title, pics, price, cat
    r[G.FOOD_TOY_COL] = mark
    return r


class TestS列の印だけで食玩を決める:
    def test_空欄は通常のカプセルトイ(self):
        assert G.food_toy_mark("") is False
        assert G.food_toy_mark("   ") is False

    def test_食玩と書いてあれば食玩(self):
        assert G.food_toy_mark("食玩") is True
        assert G.food_toy_mark(" 食玩 ") is True

    def test_読めない印は出さない(self):
        """★fail-closed: 『たぶん通常』に倒すとカプセル前提のまま食玩が出る."""
        assert G.food_toy_mark("あり") is None
        assert G.food_toy_mark("○") is None

    def test_行に印が載る(self):
        assert G.parse_row(_row(mark="食玩"))["food_toy"] is True
        assert G.parse_row(_row(mark=""))["food_toy"] is False

    def test_読めない印の行は落ちる(self):
        assert G.parse_row(_row(mark="あり")) is None

    def test_S列が無い古い行は通常扱い(self):
        """列が増える前の行 (18列しかない) を壊さない."""
        r = _row()[:18]
        assert G.parse_row(r)["food_toy"] is False

    def test_タイトルの菓子の語では判定しない(self):
        """★『チョコ』はキャラ名にも出る。印が無ければ通常のまま."""
        it = G.parse_row(_row(title="チョコエッグ 全5種セット フルタ", mark=""))
        assert it["food_toy"] is False


class Test1_タイトル:
    def test_食玩にカプセルの語を使わない(self):
        t = G.build_title("One Piece Sticker Wafer", 22, "Bandai", "Sticker", food_toy=True)
        assert "Capsule" not in t and "Gashapon" not in t and "Gacha" not in t
        assert len(t) <= 80

    def test_食玩は食玩の語で出る(self):
        t = G.build_title("One Piece Sticker Wafer", 22, "Bandai", food_toy=True)
        assert "Shokugan" in t

    def test_題材は先頭のまま(self):
        t = G.build_title("Dragon Ball Card Wafer", 20, "Bandai", food_toy=True)
        assert t.startswith("Dragon Ball Card Wafer")

    def test_題材が長くてもカプセルの語に落ちない(self):
        """★80字が苦しい時の最後の砦にも `Capsule Toy` が焼いてあった."""
        t = G.build_title("A" * 60, 22, "Bandai", "Sticker Wafer", food_toy=True)
        assert "Capsule" not in t and len(t) <= 80

    def test_通常のカプセルトイは今まで通り(self):
        t = G.build_title("Isekai Neko Fantasy Cat", 5, "Takara Tomy A.R.T.S", "Mini Figure")
        assert "Gacha Capsule Toy" in t

    def test_呼び方(self):
        assert G.capsule_term("Bandai") == "Gashapon Capsule Toy"
        assert G.capsule_term("Bandai", True) == G.FOOD_TOY_TERM
        assert "Capsule" not in G.capsule_term("Takara Tomy", True)


class Test2_説明文の出し分け:
    BASE = G.load_description()

    def test_カプセルトイはカプセルの2文が出る(self):
        h = G.select_variant(self.BASE, "capsule")
        assert "Capsule-free" in h and "Mini-book" in h

    def test_食玩にはカプセルの2文を出さない(self):
        h = G.select_variant(self.BASE, "foodtoy")
        assert "Capsule-free" not in h and "Mini-book" not in h

    def test_食玩には菓子の一文を出す(self):
        h = G.select_variant(self.BASE, "foodtoy")
        assert "The snack is not included." in h

    def test_開封すると書いてある(self):
        """★『開封する』は必須 (回答書 §1)。黙って抜くと SNAD の材料."""
        h = G.select_variant(self.BASE, "foodtoy")
        assert "opened" in h

    def test_カプセルトイに菓子の一文を出さない(self):
        h = G.select_variant(self.BASE, "capsule")
        assert "The snack is not included." not in h

    def test_見出しも入れ替わる(self):
        assert "Gashapon (Capsule Toy) Items" in G.select_variant(self.BASE, "capsule")
        assert "Food-Toy (Shokugan) Items" in G.select_variant(self.BASE, "foodtoy")

    def test_印は出力に残らない(self):
        for v in G.VARIANTS:
            assert "data-when" not in G.select_variant(self.BASE, v)

    def test_品目に関係ない文は両方に出る(self):
        for v in G.VARIANTS:
            h = G.select_variant(self.BASE, v)
            assert "Shipping &amp; Estimated Delivery" in h
            assert "Customs and Duties Policy" in h

    def test_知らない品目は止める(self):
        """★黙って全部落とすと注意節ごと空で出る."""
        with pytest.raises(ValueError):
            G.select_variant(self.BASE, "unknown")


class Test4_コンディションの一文:
    BASE = G.load_description()

    def test_食玩に未開封と読める文を出さない(self):
        """★『外装は開けた』と同じ説明文の中で矛盾する (回答書 §3)."""
        h = G.select_variant(self.BASE, "foodtoy")
        assert "All original packaging, tags, and included accessories are present" not in h

    def test_食玩は開封済と書く(self):
        h = G.select_variant(self.BASE, "foodtoy")
        assert "has been opened" in h

    def test_カプセルトイは今まで通り(self):
        h = G.select_variant(self.BASE, "capsule")
        assert "All original packaging, tags, and included accessories are present" in h

    def test_どちらも新品とは書く(self):
        for v in G.VARIANTS:
            assert "<b>Brand New</b>" in G.select_variant(self.BASE, v)


class Testテンプレが壊れたら止める:
    def test_品目別の文が消えていたら中止(self, tmp_path, monkeypatch):
        d = tmp_path / "iMakHQ"
        (d / "tools").mkdir(parents=True)
        (d / "GACHA.txt").write_text("<p>no markers</p>", encoding="utf-8")
        monkeypatch.setattr(G, "SCRIPT_DIR", str(d / "tools"))
        with pytest.raises(SystemExit):
            G.load_description()

    def test_本物のテンプレは通る(self):
        assert "data-when" in G.load_description()


class Test3_年齢確認は食玩だと自動で取れない:
    def test_食玩は公式ページを引かない(self):
        """★gashapon.jp はカプセルトイの商品DB。JAN で引くと別商品を掴む."""
        assert O.official_url("4570118099358", "gashapon.jp", food_toy=True) == ""

    def test_通常は今まで通り引く(self):
        u = O.official_url("4570118099358", "gashapon.jp")
        assert u.startswith("https://gashapon.jp/products/detail.php?jan_code=")

    def test_食玩はlookupが空(self):
        assert O.lookup({"desc_jp": "JAN: 4570118099358", "food_toy": True}) == {}

    def test_食玩は必ず目視に回る(self):
        assert G.needs_review({"food_toy": True, "age_official": "15才以上"}) is True
        assert G.needs_review({"food_toy": True,
                               "official": {"age": "15才以上"}}) is True

    def test_通常は公式で15才以上なら目視を飛ばす(self):
        assert G.needs_review({"food_toy": False, "age_official": "15才以上"}) is False
        assert G.needs_review({"official": {"age": "15才以上"}}) is False

    def test_年齢が取れない通常品は目視に回る(self):
        assert G.needs_review({"food_toy": False, "age_official": ""}) is True


class Test生成される1行:
    def test_食玩の行はタイトルも説明文も食玩になる(self):
        it = G.parse_row(_row(mark="食玩"))
        it["character_en"] = ""
        row = G.build_row(it, {"series_en": "One Piece Sticker Wafer",
                               "maker_en": "Bandai",
                               "title_subject": "One Piece Sticker Wafer"},
                          G.load_description())
        assert "Capsule" not in row["*Title"] and "Gashapon" not in row["*Title"]
        assert "The snack is not included." in row["*Description"]
        assert "Capsule-free" not in row["*Description"]
        assert "data-when" not in row["*Description"]

    def test_通常の行は今まで通り(self):
        it = G.parse_row(_row(title="ちいさな アニマル スツール 2 全5種セット ディーアイエス",
                              mark=""))
        it["character_en"] = ""
        row = G.build_row(it, {"series_en": "Animal Stool", "maker_en": "Takara Tomy",
                               "title_subject": "Animal Stool"},
                          G.load_description())
        assert "Capsule Toy" in row["*Title"]
        assert "Capsule-free" in row["*Description"]
        assert "The snack is not included." not in row["*Description"]
