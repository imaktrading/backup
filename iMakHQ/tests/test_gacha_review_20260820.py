# -*- coding: utf-8 -*-
"""ガチャの目視確認 — 対象年齢は人が見た物だけ出す (2026-08-20 新設).

対象年齢はどこからも機械的に取れないことを実測で確認した:
  - 楽天の商品ページ HTML: `対象年齢` の記載 0件
  - メーカー公式 (タカラトミーアーツ): ページは在るが中身も画像も JS 描画
印字は台紙の写真の中にしかない。だから人が見る。

★fail-closed が要点: 「15才以上」と押した物 **だけ** が出品に回る。
  未回答・読めない・15才未満は出さない。回答が来なければその回は0件。
"""
from __future__ import annotations

import json
import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))

import gacha_review as R                                        # noqa: E402

ITEMS = [
    {"url": "u1", "title_jp": "A 全5種セット", "pieces": 5, "cost_jpy": 2820,
     "maker_jp": "エール", "pics": ["https://x/a.jpg", "https://x/b.jpg"]},
    {"url": "u2", "title_jp": "B 全4種セット", "pieces": 4, "cost_jpy": 2550,
     "maker_jp": "", "pics": ["https://x/c.jpg"]},
]


class TestOnlyConfirmedItemsAreListed:
    def test_only_15plus_passes(self):
        led = {"u1": {"age": "15+"}, "u2": {"age": "under15"}}
        assert [i["url"] for i in R.confirmed(ITEMS, led)] == ["u1"]

    def test_unreadable_is_not_listed(self):
        assert R.confirmed(ITEMS, {"u1": {"age": "unreadable"}}) == []

    def test_unanswered_is_not_listed(self):
        """★回答が無い = 出さない。無回答を『たぶん大丈夫』に倒さない."""
        assert R.confirmed(ITEMS, {}) == []

    def test_an_empty_ledger_lists_nothing(self):
        assert R.confirmed(ITEMS, None) == []


class TestChosenPhotosAreUsed:
    def test_selected_photos_replace_the_originals(self):
        led = {"u1": {"age": "15+", "pics": ["https://x/b.jpg"]}}
        assert R.confirmed(ITEMS, led)[0]["pics"] == ["https://x/b.jpg"]

    def test_no_selection_keeps_the_original_photos(self):
        led = {"u1": {"age": "15+", "pics": []}}
        assert R.confirmed(ITEMS, led)[0]["pics"] == ["https://x/a.jpg", "https://x/b.jpg"]

    def test_the_original_item_is_not_mutated(self):
        led = {"u1": {"age": "15+", "pics": ["https://x/b.jpg"]}}
        R.confirmed(ITEMS, led)
        assert ITEMS[0]["pics"] == ["https://x/a.jpg", "https://x/b.jpg"]


class TestTheSameItemIsNotAskedTwice:
    def test_answered_items_are_not_asked_again(self):
        done, ask = R.split_answered(ITEMS, {"u1": {"age": "15+"}})
        assert [i["url"] for i in done] == ["u1"]
        assert [i["url"] for i in ask] == ["u2"]

    def test_a_no_answer_also_counts_as_answered(self):
        """15才未満・読めないも聞き直さない (毎回同じ物を出さない)."""
        done, ask = R.split_answered(ITEMS, {"u1": {"age": "unreadable"}})
        assert [i["url"] for i in done] == ["u1"]

    def test_everything_is_asked_when_nothing_is_recorded(self):
        done, ask = R.split_answered(ITEMS, {})
        assert done == [] and len(ask) == 2


class TestWhatWasNotListedIsReported:
    def test_reasons_are_counted(self):
        led = {"u1": {"age": "under15"}}
        got = R.skipped_reasons(ITEMS, led)
        assert got["15才未満 (出せません)"] == 1 and got["未回答"] == 1

    def test_listed_items_are_not_counted(self):
        assert R.skipped_reasons(ITEMS, {"u1": {"age": "15+"}, "u2": {"age": "15+"}}) == {}


class TestTheScreen:
    def test_three_buttons_per_item(self):
        h = R.build_html(ITEMS)
        for v in ("'15+'", "'under15'", "'unreadable'"):
            assert h.count(v) >= 2

    def test_photos_are_selectable(self):
        h = R.build_html(ITEMS)
        assert h.count("type=\"checkbox\"") == 3          # 2枚 + 1枚

    def test_official_link_is_shown_when_known(self):
        items = [dict(ITEMS[0], official_url="https://www.takaratomy-arts.co.jp/x")]
        assert "公式ページを開く" in R.build_html(items)

    def test_missing_official_link_is_stated_not_hidden(self):
        assert "公式リンク未取得" in R.build_html(ITEMS)

    def test_titles_are_escaped(self):
        h = R.build_html([dict(ITEMS[0], title_jp="<script>x</script>")])
        assert "<script>x</script>" not in h


class TestLedgerIo:
    def test_roundtrip(self, tmp_path):
        p = str(tmp_path / "led.json")
        R.save_ledger({"u1": {"age": "15+"}}, p)
        assert R.load_ledger(p)["u1"]["age"] == "15+"

    def test_missing_file_is_not_an_error(self, tmp_path):
        assert R.load_ledger(str(tmp_path / "nope.json")) == {}

    def test_a_broken_file_is_not_an_error(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not json", encoding="utf-8")
        assert R.load_ledger(str(p)) == {}
