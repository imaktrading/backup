# -*- coding: utf-8 -*-
"""補URL の在庫確認: 速くして、溢れた分は次回いちばん先に (2026-09-16)。

実測 (2026-09-16 19:00 の走行): 対象 75本のうち **6本が未確認のまま通過**
(「⏱ 時間切れ (300秒) — 残り6本は確認せず通します」)。
中身は 1本ごとに「詳細ページを開く → **必ず3秒待つ**」で、1本約4秒 = 300秒で約70本が限界だった。
判定に要るのは詳細ページのボタンだけなので、出たら待たない。
それでも溢れた分は覚えて、次回の先頭で確認する (毎回 同じ尻尾が残らないように)。
"""
import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))

import hoju_url_from_dupes as H  # noqa: E402

SRC = open(os.path.join(HQ, "tools", "hoju_url_from_dupes.py"), encoding="utf-8").read()


def test_previously_skipped_urls_go_first():
    assert H.verify_order(["a", "b", "c"], ["c"]) == ["c", "a", "b"]
    assert H.verify_order(["a", "b"], ["zzz"]) == ["a", "b"]      # 今回の対象に無い物は無視
    assert H.verify_order([], ["a"]) == []


def test_it_stops_waiting_once_the_button_shows():
    """判定に要るボタンが出たら待たない (旧: 必ず3秒待っていた)。"""
    assert "VERIFY_MARKERS" in SRC and "checkout-button" in SRC and "bid-button" in SRC
    assert "_t.sleep(3)" not in SRC                               # 固定待ちは無い
    assert "now() - _w0 < VERIFY_MAX_WAIT" in SRC


def test_leftovers_are_remembered_and_cleared():
    assert "save_pending_verify(rest)" in SRC                     # 溢れた分を覚える
    assert "save_pending_verify([])" in SRC                       # 全部確認できたら空にする
    assert "次回いちばん先に確認します" in SRC                     # ログにもそう出す
