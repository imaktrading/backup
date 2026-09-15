# -*- coding: utf-8 -*-
"""実寸表が無い UT / GU に、汎用サイズ表の写真を 2枚目に1枚付ける (2026-09-14)。

ユーザー「1.png だけじゃなくて、UT なら v3 を入れた方がトラブルない」→「目安だからね」(1枚にまとめる)
→「そうしよか」(メンズ・ユニセックスのレギュラーだけ)。
- 表の数字はカタログの実寸 (メンズ・ユニセックス) の中央値。22% の商品は1インチ以上ずれるので、
  種類が違う (レディース・キッズ・オーバーサイズ) 商品には付けない
- 実寸表がある商品には付けない (数字が食い違って揉める)
- 写真は1出品12枚まで。サイズ表の枠を先に空け、2枚目 (ユーザー「サイズ表は、２枚目がよくない？」)
- 画像を置けなくても出品は止めない
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "iMakMercari", ROOT / "iMakeBayAPI"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import ut_catalog_values as V  # noqa: E402
import ut_sizechart_image as SC  # noqa: E402

CHART = "https://raw.githubusercontent.com/imaktrading/imaktrading.github.io/main/tshirt_sizechart_ut_gu.png"


def _v(**kw):
    v = {"size_jp": "M", "size_chart": [], "fit": "Regular", "specs": {"Department": "Men"},
         "catalog_images": [f"https://image.uniqlo.com/x/goods_09_480693_{i}.jpg" for i in range(14)],
         "color_codes": {}, "color_name": "", "l1": "480693"}
    v.update(kw)
    return v


def test_chart_only_for_men_or_unisex_regular_without_actual_chart():
    assert V.chart_applies(_v())
    assert V.chart_applies(_v(specs={"Department": "Unisex Adults"}))
    assert not V.chart_applies(_v(specs={"Department": "Women"}))
    assert not V.chart_applies(_v(fit="Oversized"))
    assert not V.chart_applies(_v(fit=""))
    actual = [{"size": "M", "length": "28", "shoulder": "18", "chest": "21", "sleeve": "18"}]
    assert not V.chart_applies(_v(size_chart=actual))


def test_chart_is_second_and_the_limit_is_kept():
    imgs = V.images_for_listing(_v(), ["https://static.mercdn.net/item/detail/orig/photos/m1_1.jpg"], chart_url=CHART)
    assert imgs[1] == CHART and len(imgs) == V.MAX_PICTURES
    assert imgs.count(CHART) == 1
    main = V.images_for_listing(_v(img_main="https://image.uniqlo.com/x/goods_09_480693_5.jpg"), [], chart_url=CHART)
    assert main[0].endswith("_5.jpg") and main[1] == CHART      # 目視で選んだ1枚目の次


def test_no_chart_when_not_applicable_or_no_url():
    assert CHART not in V.images_for_listing(_v(specs={"Department": "Women"}), [], chart_url=CHART)
    assert CHART not in V.images_for_listing(_v(), [], chart_url="")
    assert V.listing_images(["a.jpg"], second=[CHART]) == ["a.jpg", CHART]
    assert V.listing_images(["a.jpg", "b.jpg"], second=[CHART]) == ["a.jpg", CHART, "b.jpg"]
    assert V.listing_images([], second=[CHART]) == [CHART]


def test_chart_is_not_on_ebay_picture_host_20260915():
    """eBay は eBay に置いた画像 (i.ebayimg.com) と外の URL を1出品に混ぜると弾く。
    実害 (2026-09-15): サイズ表だけ eBay に置いていて、🤖自動 17件が 0件出品。"""
    assert "ebayimg" not in SC.CHART_URL and SC.CHART_URL.startswith("https://")
    assert not hasattr(SC, "upload")    # eBay の画像置き場に上げる道を残さない


def test_url_returned_only_when_github_matches_local():
    with open(SC.CHART_PATH, "rb") as f:
        same = f.read()
    quiet = dict(log=lambda *_: None)
    assert SC.ensure_chart_url(fetch=lambda u: same, **quiet) == SC.CHART_URL
    assert SC.ensure_chart_url(fetch=lambda u: b"old picture", **quiet) == ""   # 描き直して上げ直していない


def test_failure_does_not_stop_listing():
    assert SC.ensure_chart_url(fetch=lambda u: None, log=lambda *_: None) == ""
    boom = lambda u: (_ for _ in ()).throw(RuntimeError("down"))   # noqa: E731
    assert SC.ensure_chart_url(fetch=boom, log=lambda *_: None) == ""


def test_chart_image_exists_and_generator_uses_it():
    assert Path(SC.CHART_PATH).is_file()
    src = (ROOT / "iMakMercari" / "tshirt_listing.py").read_text(encoding="utf-8")
    assert "UCV.chart_applies(cat_v)" in src and "chart_url=_chart" in src
