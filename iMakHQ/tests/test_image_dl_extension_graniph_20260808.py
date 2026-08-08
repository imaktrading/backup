# -*- coding: utf-8 -*-
"""画像DL拡張の graniph ルール (2026-08-08).

なぜ専用ルールが要るか (実測):
    graniph の商品ページは Shopify ではなく、汎用フォールバック (表示中の <img> を全部拾う)
    に任せると **クーポンバナーとフィード画像も一緒に落ちる**
    (`/item-detail/019002010001` = 商品10枚 + バナー2枚)。
    商品画像は URL 構造で確実に判別できる:
      https://cf.graniph.com/images/item/product_image/<9桁品番>.<3桁カラー>.-_<n>.jpg

    原寸は 1125x1575。`_l` / `_org` / `product_image_l` / `?width=2000` は全部 403 なので
    「もっと大きい版がある」前提のコードを書かない (実測済み)。

固定する挙動:
  1. 品番+カラーが一致する商品画像だけ拾う
  2. バナー / フィード画像を拾わない
  3. 別カラーの画像を拾わない (色違いが混ざると出品画像として誤り)
  4. 連番順に並ぶ (_2 が _10 より後ろに来ない = 文字列ソートしていない)
  5. 0件なら 0件として返す (バナーで埋めない = fail-closed)
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

JS = Path(r"C:\dev\iMak\tools\image_dl_extension\background.js")

# 実測サンプル (2026-08-08 に実際にページから取れた URL)
PRODUCT = [
    f"https://cf.graniph.com/images/item/product_image/019002010.001.-_{n}.jpg"
    for n in range(1, 11)
]
NOISE = [
    "https://cf.graniph.com/images/common/couponpresent_bnr_800-220_app.png",
    "https://cf.graniph.com/images/feed/20260807_2buy_re_2170-210.jpg",
    "https://cf.graniph.com/images/item/product_image/019002010.002.-_1.jpg",  # 別カラー
    "https://cf.graniph.com/images/item/product_image/019002099.001.-_1.jpg",  # 別品番
]


def _pattern(code: str) -> re.Pattern:
    """JS と同じ正規表現を Python で組む (JS 側の書式が変わったら test_js_rule_exists が落ちる)."""
    return re.compile(
        r"https?://[^\"'\s<>)\\]*?/images/item/product_image/"
        + code.replace(".", r"\.") + r"\.-_(\d+)\.(?:jpe?g|png|webp|avif)", re.I)


def _collect(html: str, code: str) -> list[str]:
    hit: dict[int, str] = {}
    for m in _pattern(code).finditer(html):
        hit[int(m.group(1))] = m.group(0).split("?")[0]
    return [hit[k] for k in sorted(hit)]


# ---- 1〜3: 拾うもの / 拾わないもの ------------------------------------------


def test_picks_only_product_images_of_that_item_and_color():
    html = " ".join(f'"{u}"' for u in PRODUCT + NOISE)
    got = _collect(html, "019002010.001")
    assert got == PRODUCT, "商品画像だけを、品番+カラー一致で拾えていない"


def test_banner_and_feed_are_not_picked():
    html = " ".join(f'"{u}"' for u in NOISE)
    assert _collect(html, "019002010.001") == [], "バナー/フィードを拾っている"


def test_other_color_is_not_picked():
    """色違いが混ざると出品画像として誤り (SNAD リスク)。"""
    html = f'"{NOISE[2]}"'
    assert _collect(html, "019002010.001") == []


# ---- 4: 並び順 --------------------------------------------------------------


def test_numeric_order_not_string_order():
    """_10 が _2 より前に来ない。文字列ソートだと 1,10,2,... になる。"""
    html = " ".join(f'"{u}"' for u in reversed(PRODUCT))
    got = _collect(html, "019002010.001")
    nums = [int(re.search(r"_(\d+)\.jpg$", u).group(1)) for u in got]
    assert nums == sorted(nums) == list(range(1, 11))


# ---- 5: 0件は0件 ------------------------------------------------------------


def test_zero_hits_returns_empty_not_fallback():
    assert _collect("<html>画像なし</html>", "019002010.001") == []


# ---- JS 側が同じ作りになっていること ----------------------------------------


@pytest.mark.skipif(not JS.is_file(), reason="拡張が無い環境")
def test_js_rule_exists_and_is_host_scoped():
    src = JS.read_text(encoding="utf-8")
    assert "graniph" in src, "JS に graniph ルールが無い"
    assert "/item-detail/" in src, "ページURLから品番+カラーを取る実装になっていない"
    assert "product_image" in src, "商品画像 path で絞っていない"
    assert "GRANIPH_PATTERN" in src, "テストと対応づける目印が消えている"
    # host 判定があること (全サイトで graniph ルールが走ると他店で0件になる)
    assert re.search(r"graniph\\?\.com\$", src), "hostname を graniph.com に限定していない"


@pytest.mark.skipif(not JS.is_file(), reason="拡張が無い環境")
def test_js_sorts_numerically():
    src = JS.read_text(encoding="utf-8")
    assert re.search(r"sort\(\(a,\s*b\)\s*=>\s*a\s*-\s*b\)", src), \
        "連番を数値で並べ替えていない (文字列ソートだと 1,10,2 になる)"
