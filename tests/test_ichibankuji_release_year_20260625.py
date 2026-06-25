# -*- coding: utf-8 -*-
"""一番くじ 発売年 scrape の回帰テスト (2026-06-25)。

旧実装は『ページ最初の YYYY年MM月』を拾い、ニュース/期間/別日付を誤取得しうる
(ユーザー指摘: 公式に「店頭販売：YYYY年MM月DD日」あり=正規の発売日)。
_parse_release_year が **店頭販売 を最優先**、次にオンライン販売、最後に最初のYYYY年、を固定。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "iMak_ichibankuji"))
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakeBayAPI")))

import ichibankuji_to_csv as gen  # noqa: E402


def test_prefers_store_sale_date_over_first_year():
    """先に別の年(ニュース等)が出ても、店頭販売の年を採る。"""
    txt = "お知らせ 2024年01月15日 更新\n店頭販売：2026年02月28日(土)\nオンライン販売：2026年03月23日"
    assert gen._parse_release_year(txt) == "2026"


def test_store_sale_with_separators():
    """get_text(separator) で ：と日付が割れても拾う。"""
    txt = "店頭販売\n：\n2026年02月28日"
    assert gen._parse_release_year(txt) == "2026"


def test_fallback_online_then_first_year():
    assert gen._parse_release_year("オンライン販売：2025年07月10日") == "2025"
    assert gen._parse_release_year("発売 2023年05月 ほか") == "2023"


def test_empty():
    assert gen._parse_release_year("") == ""
    assert gen._parse_release_year("年も月もない文字列") == ""
