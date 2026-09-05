# -*- coding: utf-8 -*-
"""eBaymag の画面を最後まで送って落とす道具 (2026-09-06 ユーザー要望).

> magのポリシー一覧、画面スクロールしないとコピー取れないけど、自動でコピーできるツールない？

守る性質:
  1. スクロールで何度も同じ行を拾うので、**重複を落として順番は保つ**
  2. ログイン前の画面を黙って保存しない (保存してから気づくのを防ぐ)
  3. 監視くんの eBay ログインプロファイルを使わない (巡回の生命線を壊さない)
  4. Chrome の version を数値で固定しない (全worktree横断ルール 2026-06-13)
"""
from __future__ import annotations

import io
import os
import sys

import pytest

_HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOOLS = os.path.join(_HQ, "tools")
sys.path.insert(0, _TOOLS)
_SRC = io.open(os.path.join(_TOOLS, "ebaymag_dump.py"), encoding="utf-8").read()


@pytest.fixture(scope="module")
def M():
    import ebaymag_dump
    return ebaymag_dump


class TestMergeSeen:
    def test_drops_repeats_and_keeps_order(self, M):
        got = M.merge_seen(["見出し\nA\nB", "B\nC", "C\nD"])
        assert got == ["見出し", "A", "B", "C", "D"]

    def test_ignores_blank_lines(self, M):
        assert M.merge_seen(["A\n   \n\nB"]) == ["A", "B"]

    def test_empty_input_is_not_an_error(self, M):
        assert M.merge_seen([]) == [] and M.merge_seen([None, ""]) == []


class TestMergeRows:
    def test_same_value_in_two_rows_survives(self, M):
        """★列が潰れないこと。行ごと丸ごとで重複を見る。

        文字として畳んでいた最初の版では、どの行にも出る「7」「いいえ」が
        消えて、180件のポリシーの時間と返品可が全部落ちた。
        """
        got = M.merge_rows([
            [["DDP-A-P09 / 0613 / JP", "7", "いいえ"],
             ["DDP-A-P11 / 8FC3 / JP", "7", "いいえ"]],
        ])
        assert got == [["DDP-A-P09 / 0613 / JP", "7", "いいえ"],
                       ["DDP-A-P11 / 8FC3 / JP", "7", "いいえ"]]

    def test_the_same_row_seen_twice_is_dropped(self, M):
        """スクロールで同じ行を何度も拾うので、行が丸ごと同じなら1本にする。"""
        r = ["DDP-A-P24 / BE87 / JP", "7", "いいえ", "7"]
        assert M.merge_rows([[r], [r], [r]]) == [r]

    def test_blank_rows_are_skipped(self, M):
        assert M.merge_rows([[["", "  ", ""]]]) == []

    def test_newlines_inside_a_cell_do_not_break_the_row(self, M):
        got = M.merge_rows([[["D\nDDP-A-P09 / 0613 / JP", "7"]]])
        assert got == [["D DDP-A-P09 / 0613 / JP", "7"]]


class TestLoggedOutDetection:
    def test_login_url_is_caught(self, M):
        assert M.looks_logged_out("https://ebaymag.com/login", "whatever")
        assert M.looks_logged_out("https://ebaymag.com/users/sign_in", "x")

    def test_other_sites_are_not_logged_in(self, M):
        """★認証の途中を「入れた」と読まない (2026-09-06 実際に誤判定した)。"""
        assert M.looks_logged_out(
            "https://accounts.google.com/v3/signin/challenge/pwd?TL=x", "パスワード")
        assert M.looks_logged_out("https://signin.ebay.com/signin?ru=x", "")

    def test_blank_page_is_caught(self, M):
        """真っ白 = 読み込めていない。空を「取れた」と言わない。"""
        assert M.looks_logged_out("https://ebaymag.com/policies", "")

    def test_real_page_passes(self, M):
        assert not M.looks_logged_out(
            "https://ebaymag.com/policies",
            "Shipping policy\nDDP-A-P11 / 8FC3 / JP\nDDP-A-P24 / BE87 / JP")


class TestOutputName:
    def test_name_says_which_screen(self, M):
        import datetime
        n = M.out_name("https://ebaymag.com/policies?tab=shipping",
                       datetime.datetime(2026, 9, 6, 8, 30, 0))
        assert n == "ebaymag_policies_tab_shipping_20260906_083000"

    def test_home_gets_a_name_too(self, M):
        assert M.out_name("https://ebaymag.com/").startswith("ebaymag_home_")


class TestSafety:
    def test_does_not_touch_the_watcher_login_profile(self):
        """監視くんの eBay プロファイルは巡回の生命線。共有しない。"""
        # 触らない理由は docstring に書いてよい。**使う場所**に無いことを見る。
        code = "\n".join(ln for ln in _SRC.splitlines()
                         if not ln.lstrip().startswith("#"))
        i = code.index("PROFILE = ")
        assert "chrome_profile_ebaymag" in code[i:i + 200]
        assert "user-data-dir=%s" in code and "iMakInventory" not in code[i:]

    def test_chrome_version_is_not_hardcoded(self):
        """version_main に数値を焼くと Chrome 更新で起動不能になる。"""
        import re
        assert not re.search(r"version_main\s*=\s*\d", _SRC)
        assert "detect_chrome_major()" in _SRC
