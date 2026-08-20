# -*- coding: utf-8 -*-
"""一番くじの補URL補充 — 検索語の作り方 (2026-08-20 新設).

★KEY (カタログ品番) は使わない。一番くじにカタログは無く、live 37件の KEY は
  `item:m6168…` のような **仕入元URL由来** (25件) か空 (12件) で、
  「同じ賞の別個体」を探す起点にならない。品番を作って埋める作業を増やす意味がない。
  代わりに仕入元タイトルをそのまま検索語にする。同じ物かの担保は **目視** が持つ。

実データ37件で検証した結果、この3つを踏まないと検索語が壊れる:
  - 「ドラゴンボールA賞」= 賞が日本語に直付け
  - 「角巻わため賞」= キャラ名が賞名 (賞として扱ってはいけない)
  - 「A賞 シャンクス MASTERLISE」= 造形ライン名がキャラ名の位置に来る
"""
from __future__ import annotations

import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))

import kuji_hoju_fill as K                                      # noqa: E402


class TestPrizeAndCharacter:
    def test_letter_prize_after_space(self):
        assert K.parse_title("一番くじ 幽遊白書 C賞 飛影") == ("飛影", "C賞")

    def test_letter_prize_glued_to_japanese(self):
        """★「ドラゴンボールA賞」= 前に空白が無い形。これを外すと賞が取れない."""
        c, p = K.parse_title("一番くじ　ドラゴンボールA賞 孫悟空&クリリン")
        assert p == "A賞" and c == "孫悟空&クリリン"

    def test_special_prize(self):
        assert K.parse_title("一番くじ 幽遊白書 ラストワン賞 妖狐蔵馬") == ("妖狐蔵馬", "ラストワン賞")

    def test_named_prize_is_the_character(self):
        """★「角巻わため賞」= キャラ名が賞名。賞として扱わず、キャラとして拾う."""
        assert K.parse_title("角巻わため賞 角巻わため フィギュア") == ("角巻わため", "")

    def test_character_after_the_prize_wins(self):
        """賞の後ろを優先。前優先だと作品名の一部を拾ってしまう."""
        assert K.parse_title("ジョジョの奇妙な冒険 東方定助 A賞 MASTERLISE")[0] == "東方定助"

    def test_sculpt_line_names_are_not_characters(self):
        assert K.parse_title("D賞キラークイーンMASTERLISE")[0] == "キラークイーン"

    def test_japanese_words_beat_numbers(self):
        assert K.parse_title("メカゴジラ (1993)一番くじMACHINE CHRONICLE A賞")[0] == "メカゴジラ"


class TestQuery:
    def test_with_prize(self):
        assert K.build_query("A賞 シャンクス MASTERLISE EXPIECE") == "一番くじ シャンクス A賞"

    def test_without_prize_falls_back_to_character(self):
        """★賞が無い出品 (アクスタ等) は キャラまでで検索する."""
        q = K.build_query("呪術廻戦 一番くじ 乙骨憂太ビッグアクリルスタンド")
        assert q.startswith("一番くじ 乙骨憂太")

    def test_nothing_usable_gives_no_query(self):
        """検索語が作れない = 探索不能。推測で検索しない."""
        assert K.build_query("") == ""
        assert K.build_query("一番くじ") == ""


class TestTargets:
    HDR = [""] * 34

    def _row(self, item_id="820", cat="一番くじ", sold="", title="A賞 シャンクス", aux=0):
        r = [""] * 34
        r[0] = "https://jp.mercari.com/item/m1"
        r[1], r[2], r[3] = item_id, title, sold
        r[17] = cat
        for k in range(aux):
            r[K.P.AUX0 + k] = "https://jp.mercari.com/item/m%d" % (k + 90)
        return r

    def test_live_row_with_no_backups_is_a_target(self):
        got = K.select_targets([self.HDR, self._row()])
        assert len(got) == 1 and got[0]["n_backups"] == 0
        assert got[0]["query"] == "一番くじ シャンクス A賞"

    def test_full_row_is_skipped(self):
        assert K.select_targets([self.HDR, self._row(aux=5)]) == []

    def test_partially_filled_row_is_still_a_target(self):
        """★5本まで足す (user 確定 2026-08-20)."""
        got = K.select_targets([self.HDR, self._row(aux=2)])
        assert len(got) == 1 and got[0]["n_backups"] == 2

    def test_unlisted_and_sold_and_other_category_are_skipped(self):
        rows = [self.HDR, self._row(item_id=""), self._row(sold="売切"),
                self._row(cat="TCG")]
        assert K.select_targets(rows) == []


class TestCandidateFiltering:
    def test_own_url_is_dropped(self):
        c = [{"href": "https://jp.mercari.com/item/m1"},
             {"href": "https://jp.mercari.com/item/m2"}]
        got = K.drop_own_urls(c, "https://jp.mercari.com/item/m1", [])
        assert [x["href"] for x in got] == ["https://jp.mercari.com/item/m2"]

    def test_existing_backups_are_dropped(self):
        c = [{"href": "https://jp.mercari.com/item/m2"}]
        assert K.drop_own_urls(c, "", ["https://jp.mercari.com/item/m2"]) == []

    def test_duplicates_are_collapsed(self):
        c = [{"href": "https://jp.mercari.com/item/m2"},
             {"href": "https://jp.mercari.com/item/m2/"}]
        assert len(K.drop_own_urls(c, "", [])) == 1


class TestOnlyTheVisualPathWrites:
    def test_this_tool_has_a_visual_ui(self):
        """★補URLを書いてよいのは目視UIを持つツールだけ (2026-08-03 ユーザー指示)。

        検索は文字列一致なので別のくじ・別の賞が混ざる。目視が唯一の担保。
        `test_no_unconfirmed_aux_url_20260803` の許可リストに載せた根拠がこれ。
        """
        assert hasattr(K, "build_html") and hasattr(K, "run_review")

    def test_nothing_is_written_without_a_choice(self):
        """選ばれた候補が0件なら書かない (無回答を『たぶん合っている』に倒さない)."""
        import inspect
        src = inspect.getsource(K.main)
        assert "選ばれた候補が0件" in src and "return 0" in src


class TestScreen:
    ITEM = {"row": 5, "itemID": "820", "title": "A賞 シャンクス", "n_backups": 1,
            "query": "一番くじ シャンクス A賞", "supply_url": "https://x/1",
            "candidates": [{"href": "https://jp.mercari.com/item/m9", "name": "一番くじ シャンクス",
                            "price": 1750, "img": "https://x/i.jpg"}]}

    def test_candidates_are_selectable_with_price_and_name(self):
        h = K.build_html([self.ITEM])
        assert 'type="checkbox"' in h and "1,750" in h and "一番くじ シャンクス" in h

    def test_the_query_is_shown_so_a_bad_one_is_visible(self):
        assert "一番くじ シャンクス A賞" in K.build_html([self.ITEM])

    def test_no_candidates_says_so(self):
        assert "候補が見つかりませんでした" in K.build_html([dict(self.ITEM, candidates=[])])
