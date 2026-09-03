# -*- coding: utf-8 -*-
"""UT の補URL — 予備の仕入元を貯める (2026-09-03)。

## なぜ
中古アパレルの出品が止まったのは、**仕入元がすぐ売り切れて出品作業が無駄になった**から。
PSA で補URL を作ってからその問題は消えたので、同じ仕組みを UT に持ち込む。

## UT 固有の落とし穴 (実測 2026-09-03)
1. **子供服が大量に混ざる**。「怪獣8号 UT」の検索結果20件が 120〜150cm で埋まり、
   大人 XL が1件も残らなかった。キッズを弾かないと取りこぼす。
2. **中古が混ざる**。「やや傷や汚れあり」「目立った傷や汚れなし」は使えない。
   UT は新品未使用に限る (中古だと個体ごとの現物写真が要り、仕入元が変わるたび
   画像の差し替えが必要になる)。
3. サイズは **JP のまま**照合する (メルカリの出品タイトルが JP 表記)。
   US 換算は eBay に出す時だけ。
"""
import os
import sys

_HQ_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _HQ_TOOLS not in sys.path:
    sys.path.insert(0, _HQ_TOOLS)

import ut_hoju_fill as U  # noqa: E402


def test_kids_sizes_are_rejected():
    """子供服を大人サイズと同じ枠で数えない。"""
    for t in ("UNIQLO UT 怪獣8号 Tシャツ 130cm", "UNIQLO 怪獣8号 UT Tシャツ 150サイズ",
              "怪獣8号 コラボ 半袖 Tシャツ★子供服 140cm 黒★限定品 UT",
              "ユニクロUT〔140〕推しの子 コラボ B小町 Tシャツ 半袖"):
        assert U.jp_size_of(t) == "KIDS", t


def test_adult_sizes_are_read():
    assert U.jp_size_of("推しの子 UT Tシャツ B小町 ユニクロ ブラックXXL") == "XXL"
    assert U.jp_size_of("UNIQLO UT ONE PIECE FILM RED Tシャツ XL") == "XL"
    assert U.jp_size_of("ユニクロ UT 攻殻機動隊ARISE 半袖Tシャツ Sサイズ") == "S"
    assert U.jp_size_of("【ユニクロ】UNIQLOUTゼルダの伝説 半袖Tシャツ【L】コラボ♡白") == "L"


def test_ll_and_2xl_are_the_same_as_xxl():
    assert U.jp_size_of("ユニクロ UT Tシャツ LL") == "XXL"
    assert U.jp_size_of("ユニクロ UT Tシャツ 2XL") == "XXL"


def test_unknown_size_is_blank():
    assert U.jp_size_of("UNIQLO UT ONE PIECE FILM RED Tシャツ") == ""
    assert U.jp_size_of("") == ""


def test_size_match_is_fail_closed():
    assert U.size_matches("XL", "XL") is True
    assert U.size_matches("XL", "L") is False
    assert U.size_matches("XL", "") is False        # 読めない → 使わない
    assert U.size_matches("", "XL") is False
    assert U.size_matches("XL", "KIDS") is False


def test_us_conversion_is_only_for_ebay():
    assert U.us_size_of("XL") == "L"
    assert U.us_size_of("XXL") == "XL"
    assert U.us_size_of("S") == "XS"
    assert U.us_size_of("KIDS") == ""


def test_used_items_are_rejected():
    """UT は新品未使用に限る。中古だと個体ごとの現物写真が要る。"""
    assert U.usable_candidate("新品、未使用", "送料込み", 770, False) is True
    assert U.usable_candidate("やや傷や汚れあり", "送料込み", 912, False) is False
    assert U.usable_candidate("目立った傷や汚れなし", "送料込み", 912, False) is False


def test_shipping_and_seller_rules_match_psa():
    assert U.usable_candidate("新品、未使用", "着払い", 999, False) is False
    assert U.usable_candidate("新品、未使用", "送料込み", 36, False) is False   # 評価が少ない個人
    assert U.usable_candidate("新品、未使用", "送料込み", None, True) is True   # Shops は評価不問
    assert U.usable_candidate("新品、未使用", "送料込み", None, False) is False  # 読めない個人


def test_keyword_keeps_the_work_name_and_drops_boilerplate():
    kw = U.build_keyword("推しの子 UT　Tシャツ（半袖）B小町　ユニクロ　ブラックXXL")
    assert "推しの子" in kw and "B小町" in kw
    assert "XXL" not in kw              # サイズは後で照合する
    assert "ブラック" not in kw          # 色も入れない
    assert kw.endswith("UT Tシャツ")


def test_keyword_stays_short():
    """語を足すほど0件に近づく。実測: 6語で0件 / 4語で20件 (2026-09-03)。"""
    kw = U.build_keyword("ドラゴンボール　悟空ブラック　キャラクターtシャツ　ビッグプリント　2XL")
    assert kw == "ドラゴンボール 悟空 UT Tシャツ"
    assert len(kw.split()) <= 4


def test_keyword_is_blank_when_nothing_distinctive_remains():
    assert U.build_keyword("") == ""
    assert U.build_keyword("ユニクロ UT Tシャツ 半袖") == ""


def test_existing_aux_urls_are_kept():
    """空き枠にだけ足す。既存を消さない (冪等)。"""
    assert U.merge_aux(["a", "b"], ["c"]) == ["a", "b", "c"]
    assert U.merge_aux(["a"], ["a", "b"]) == ["a", "b"]          # 重複しない
    assert U.merge_aux(["a", "b", "c", "d", "e"], ["f"]) == ["a", "b", "c", "d", "e"]


def test_writes_only_after_the_visual_check():
    """補URL は目視を通ってからしか書かない (機械の絞り込みだけでは決められない)。"""
    src = open(os.path.join(_HQ_TOOLS, "ut_hoju_fill.py"), encoding="utf-8").read()
    i = src.index("def confirm(")
    j = src.index("write_aux_urls")
    assert i < j, "書込が confirm の外にある"
    assert "restock_confirm(items)" in src[i:j], "目視ビューアを通っていない"
    # search は貯めるだけ (スプシに書かない)
    s = src.index("def search(")
    assert "write_aux_urls" not in src[s:i]
