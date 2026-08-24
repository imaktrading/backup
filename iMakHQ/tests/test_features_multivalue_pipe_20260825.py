# -*- coding: utf-8 -*-
"""Features の複数値を eBay に「2値」で届ける (2026-08-25)。

## 何が起きていたか
catalog の `features_ebay` が list (例 `['Promo', 'Alternative Art']`) の時、
出品くんは読点で1つに繋いで CSV に書いていた。eBay 側の実物を GetItem で読むと

    <Name>Features</Name><Value>Promo, Alternative Art</Value>

= **1値の自由文**として入っていた。eBay の Features は複数値を持てる項目で、正規値39個に
`Promo` も `Alternative Art` も在るが `Promo, Alternative Art` は無い。
つまり買い手の絞り込みに1つも当たらない状態だった (実測: itemID 820035999901)。

さらに同じ文字列がタイトルにもそのまま入り、
`PSA 10 Gundam Japanese Heero Yuy #ST02-010 Common Promo, Alternative Art 2026`
が US 1件 + eBaymag ミラー3件 出ていた。

## 直し方
- CSV の区切りは **縦棒 `|`** (eBay 入稿CSVの複数値の区切り)
- タイトルに入れるのは **先頭1値だけ** (読点を持ち込まない / 80字枠を食わない)
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TCG = os.path.join(_ROOT, "iMakTCG")
if _TCG not in sys.path:
    sys.path.insert(0, _TCG)

import tcg_listing_fields as F  # noqa: E402

_SRC = os.path.join(_TCG, "tcg_listing_fields.py")


def _src():
    with open(_SRC, encoding="utf-8") as fh:
        return fh.read()


def test_csv_separator_is_pipe_not_comma():
    """複数値の区切りが読点に戻ったら落とす (eBay が1値として持ってしまう)。"""
    src = _src()
    assert '"|".join(_vals)' in src, "Features の複数値は縦棒で繋ぐ"
    assert '", ".join(_vals)' not in src, (
        "読点で繋ぐと eBay は1値の自由文として持ち、正規値の絞り込みに当たらない "
        "(2026-08-25 実測: itemID 820035999901)")


def test_title_takes_only_first_feature():
    """タイトルには先頭1値だけ。読点も縦棒も持ち込まない。"""
    fields = {
        "C:Game": "Gundam Card Game", "C:Language": "Japanese",
        "C:Set": "Promo Cards", "C:Card Number": "ST02-010",
        "C:Character": "Heero Yuy", "C:Rarity": "Common",
        "C:Features": "Promo|Alternative Art",
        "C:Year Manufactured": "2026",
    }
    title = F.build_title_from_fields(fields)
    assert "Promo" in title
    assert "Alternative Art" not in title, "2つ目以降の値はタイトルに入れない"
    assert "|" not in title and ", " not in title, f"区切り記号がタイトルに漏れている: {title!r}"


def test_title_unaffected_when_single_feature():
    """1値だけの時の見え方は今までどおり (回帰させない)。"""
    fields = {
        "C:Game": "Pokemon", "C:Language": "Japanese",
        "C:Set": "VMAX Climax", "C:Card Number": "003/184",
        "C:Character": "Pikachu V", "C:Features": "Alternative Art",
    }
    title = F.build_title_from_fields(fields)
    assert "Alternative Art" in title
