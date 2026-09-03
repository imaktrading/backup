# -*- coding: utf-8 -*-
"""仕入元の id は sheet_io に1か所 (2026-09-03)。

## 実害
SNKRDUNK 仕入の行だけ id が取れず、**2つ同時に落ちた**:
  ① 入稿直前の在庫確認 → 「シートに該当行が無い」で **fail-open** (在庫を見ずに出した)
  ② 入稿後の itemID 書戻し / 広告8% → 付かなかった
対象: cert167145631 / ST18-005 Luffy-Tarou / itemID 820082424467。
itemID がシートに無い出品は **監視くんが取り下げられない** = 一番危ない状態。

## なぜ両方落ちたか
ads_add_new_listings と csv_drop_sold_rows が **同じ正規表現を各自持って**いて、
両方ともメルカリしか知らなかった。仕入元が増えるたび2か所直す作りだった。
"""
import os
import sys

_TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOOLS = os.path.join(_TOOLS, "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import sheet_io                                   # noqa: E402


def test_snkrdunk_is_understood():
    """事故った当の URL。"""
    assert sheet_io.supply_id_from_url(
        "https://snkrdunk.com/apparels/520558/used/49216166") == "49216166"


def test_the_sources_we_already_had_still_work():
    assert sheet_io.supply_id_from_url(
        "https://jp.mercari.com/item/m11746166061") == "m11746166061"
    assert sheet_io.supply_id_from_url(
        "https://jp.mercari.com/shops/product/2JTeKjrSCj9PyYQSZfUvXj") == "2JTeKjrSCj9PyYQSZfUvXj"
    assert sheet_io.supply_id_from_url("https://www.amazon.co.jp/dp/B0FJQKXN88") == "B0FJQKXN88"


def test_no_url_is_empty_not_a_guess():
    """引けない時に推測の id を作らない (誤った行に itemID を書くと最悪)。"""
    assert sheet_io.supply_id_from_url("") == ""
    assert sheet_io.supply_id_from_url("https://example.com/") == ""


def test_both_callers_use_the_shared_one():
    """各自で正規表現を持ち直さない (仕入元が増えた時に片方だけ直る)。"""
    import io as _io
    for f in ("ads_add_new_listings.py", "csv_drop_sold_rows.py"):
        s = _io.open(os.path.join(_TOOLS, f), encoding="utf-8").read()
        assert "sheet_io.supply_id_from_url(" in s, f
        assert "shops/product/)(" not in s, f + " に自前の正規表現が残っている"
