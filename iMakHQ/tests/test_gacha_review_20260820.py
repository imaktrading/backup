# -*- coding: utf-8 -*-
"""ガチャの目視確認 — 人が見て決めた物だけ出す (2026-08-20).

なぜ人が見るか (実測):
  - 対象年齢 (米国 CPSIA) はどこからも機械的に取れない。楽天の商品ページHTMLに
    `対象年齢` の記載は0件、メーカー公式も中身は JS 描画。印字は台紙の写真の中
  - G列の写真は **744枚中 667枚が店のページ部品** (header/menu/バナー)。
    商品写真が1枚でもある行は93行中11行。機械には選り分けられない
→ G列は1枚も間引かず全部見せて、人が写真を選び、出品可否を決める。

fail-closed: 「出品する」を押した物だけが CSV に載る。未回答は出さない。
"""
from __future__ import annotations

import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))

import gacha_review as R                                        # noqa: E402

ITEMS = [
    {"url": "u1", "title_jp": "A 全5種セット", "pieces": 5, "cost_jpy": 2820,
     "maker_jp": "エール", "series_jp": "A",
     "pics": ["https://x/parts/header/menu0.jpg", "https://x/cabinet/item.jpg"]},
    {"url": "u2", "title_jp": "B 全4種セット", "pieces": 4, "cost_jpy": 2550,
     "maker_jp": "", "series_jp": "B", "pics": []},
]


class TestOnlyWhatThePersonApprovedIsListed:
    def test_list_passes(self):
        led = {"u1": {"decision": "list", "pics": ["https://x/cabinet/item.jpg"]}}
        assert [i["url"] for i in R.confirmed(ITEMS, led)] == ["u1"]

    def test_skip_does_not_pass(self):
        led = {"u1": {"decision": "skip", "reason": "対象年齢が読めない"}}
        assert R.confirmed(ITEMS, led) == []

    def test_unanswered_does_not_pass(self):
        """★答えが無い = 出さない。無回答を『たぶん大丈夫』に倒さない."""
        assert R.confirmed(ITEMS, {}) == []

    def test_approved_with_no_photo_does_not_pass(self):
        """写真0枚では出品できない (fail-closed)."""
        assert R.confirmed(ITEMS, {"u1": {"decision": "list", "pics": []}}) == []


class TestPhotosAreTheOnesThePersonPicked:
    def test_picked_photos_replace_the_g_column(self):
        led = {"u1": {"decision": "list", "pics": ["https://x/cabinet/item.jpg"]}}
        assert R.confirmed(ITEMS, led)[0]["pics"] == ["https://x/cabinet/item.jpg"]

    def test_official_photos_are_appended_after_the_picked_ones(self):
        led = {"u1": {"decision": "list", "pics": ["https://x/a.jpg"],
                      "official_pics": ["https://off/1.jpg"]}}
        assert R.confirmed(ITEMS, led)[0]["pics"] == ["https://x/a.jpg", "https://off/1.jpg"]

    def test_official_only_is_enough(self):
        led = {"u1": {"decision": "list", "pics": [],
                      "official_pics": ["https://off/1.jpg"]}}
        assert R.confirmed(ITEMS, led)[0]["pics"] == ["https://off/1.jpg"]

    def test_the_original_item_is_not_mutated(self):
        before = list(ITEMS[0]["pics"])
        R.confirmed(ITEMS, {"u1": {"decision": "list", "pics": ["https://x/a.jpg"]}})
        assert ITEMS[0]["pics"] == before


class TestReasonsAreKept:
    def test_the_written_reason_is_reported(self):
        led = {"u1": {"decision": "skip", "reason": "台紙に対象年齢が写っていない"}}
        assert ("A 全5種セット", "台紙に対象年齢が写っていない") in R.skipped_reasons(ITEMS, led)

    def test_skip_without_a_reason_says_so(self):
        got = dict(R.skipped_reasons(ITEMS, {"u1": {"decision": "skip", "reason": ""}}))
        assert got["A 全5種セット"] == "出品しない (理由の記入なし)"

    def test_unanswered_is_reported_as_unanswered(self):
        assert dict(R.skipped_reasons(ITEMS, {}))["A 全5種セット"] == "未回答"

    def test_listed_items_are_not_reported(self):
        led = {"u1": {"decision": "list", "pics": ["p"]}, "u2": {"decision": "list", "pics": ["p"]}}
        assert R.skipped_reasons(ITEMS, led) == []


class TestTheSameItemIsNotAskedTwice:
    def test_answered_items_are_skipped(self):
        done, ask = R.split_answered(ITEMS, {"u1": {"decision": "list"}})
        assert [i["url"] for i in done] == ["u1"] and [i["url"] for i in ask] == ["u2"]

    def test_skip_also_counts_as_answered(self):
        done, _ = R.split_answered(ITEMS, {"u1": {"decision": "skip"}})
        assert [i["url"] for i in done] == ["u1"]


class TestOfficialPageImages:
    HTML = ('<img src="/wp/uploads/item_front.jpg">'
            '<img src="https://off.jp/ico_cart.png">'
            '<img src="/common/logo.png">'
            '<img src="https://off.jp/wp/uploads/item_back.jpg">')

    def test_product_images_are_taken_and_made_absolute(self):
        got = R.official_image_urls(self.HTML, "https://off.jp/items/x.html")
        assert "https://off.jp/wp/uploads/item_front.jpg" in got
        assert "https://off.jp/wp/uploads/item_back.jpg" in got

    def test_icons_and_logos_are_dropped(self):
        got = R.official_image_urls(self.HTML, "https://off.jp/items/x.html")
        assert not any("ico_" in u or "logo" in u for u in got)

    def test_a_js_rendered_page_gives_nothing(self):
        """★タカラトミーアーツ等は HTML に画像が無い。空を返す (推測しない)."""
        assert R.official_image_urls("<div id=app></div>", "https://x/") == []

    def test_no_html_gives_nothing(self):
        assert R.official_image_urls("", "https://x/") == []

    def test_a_non_url_is_not_fetched(self):
        assert R.fetch_official_images("") == []
        assert R.fetch_official_images("なし") == []


class TestTheScreen:
    def test_every_g_column_photo_is_shown(self):
        """★間引かない。店の部品も含めて全部出す (人が選ぶ)."""
        h = R.build_html(ITEMS)
        assert h.count('type="checkbox"') == 2
        assert "parts/header/menu0.jpg" in h

    def test_a_row_without_photos_says_so(self):
        assert "G列に写真がありません" in R.build_html([ITEMS[1]])

    def test_official_url_and_reason_fields_exist(self):
        h = R.build_html(ITEMS)
        assert h.count('class="off"') == 2 and h.count('class="rsn"') == 2

    def test_both_buttons_exist(self):
        h = R.build_html(ITEMS)
        assert h.count("'list'") >= 2 and h.count("'skip'") >= 2

    def test_a_search_link_helps_find_the_official_page(self):
        assert "公式を検索" in R.build_html(ITEMS)

    def test_titles_are_escaped(self):
        h = R.build_html([dict(ITEMS[0], title_jp="<script>x</script>")])
        assert "<script>x</script>" not in h


class TestLedgerIo:
    def test_roundtrip(self, tmp_path):
        p = str(tmp_path / "led.json")
        R.save_ledger({"u1": {"decision": "list"}}, p)
        assert R.load_ledger(p)["u1"]["decision"] == "list"

    def test_missing_or_broken_file_is_not_an_error(self, tmp_path):
        assert R.load_ledger(str(tmp_path / "nope.json")) == {}
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        assert R.load_ledger(str(bad)) == {}
