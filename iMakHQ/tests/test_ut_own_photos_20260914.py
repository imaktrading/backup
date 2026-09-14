# -*- coding: utf-8 -*-
"""仕入元の写真は、その出品自身の写真だけを使う (2026-09-14)。

ユーザー「目視の仕入元の画像、余計なの入ってない？」。抽出くんの写真列に、その出品の写真の後ろに
出品者のアイコンと ほかの商品のサムネイルが続いていた (目視20件中19件 / 中間タブ 618行中390行)。
出品画像はカタログの後ろに仕入元の写真を足すので、そのままだと別の商品の写真が eBay に載る。
"""
import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))
sys.path.insert(0, r"C:\dev\iMak\iMakMercari")

import ut_catalog_values as UCV  # noqa: E402
import ut_identify as U  # noqa: E402

SRC = "https://jp.mercari.com/item/m93825825680"
# 2026-09-14 実データの並び (自分3枚 → アイコン → ほかの商品)
PHOTOS = [
    "https://static.mercdn.net/item/detail/orig/photos/m93825825680_1.jpg?1785145104",
    "https://static.mercdn.net/item/detail/orig/photos/m93825825680_2.jpg?1785145104",
    "https://static.mercdn.net/item/detail/orig/photos/m93825825680_3.jpg?1785145104",
    "https://static.mercdn.net/images/member_photo_noimage_thumb.png",
    "https://static.mercdn.net/thumb/item/webp/m77504242885_1.jpg?1743313667",
    "https://static.mercdn.net/thumb/item/webp/m41406630250_1.jpg?1789275620",
]


def test_mercari_keeps_only_its_own_photos():
    assert UCV.own_item_photos(SRC, PHOTOS) == PHOTOS[:3]


def test_other_sites_keep_their_photos_but_drop_mercari_extras():
    fril = ["https://img.fril.jp/img/708054315/l/2360068344.jpg?1725070031",
            "https://static.mercdn.net/thumb/members/webp/110556606.jpg?1697437780",
            "https://static.mercdn.net/thumb/item/webp/m59786217375_1.jpg?1786751342"]
    assert UCV.own_item_photos("https://item.fril.jp/a194e9a0b640de89bfce4edf25943eb4", fril) == fril[:1]
    assert UCV.own_item_photos("https://a", ["a.jpg", "b.jpg", "a.jpg"]) == ["a.jpg", "b.jpg"]


def test_listing_images_cannot_pick_up_other_items():
    imgs = UCV.listing_images([], seller_urls=UCV.own_item_photos(SRC, PHOTOS))
    assert all("m93825825680" in u for u in imgs)


def test_rows_written_to_the_sheet_carry_only_own_photos():
    r = [""] * 30
    r[U.C_URL], r[U.C_PHOTOS] = SRC, "|".join(PHOTOS)
    assert U.high_row(r)[U.C_PHOTOS] == "|".join(PHOTOS[:3])


def test_review_screen_request_and_listing_all_filter():
    src = open(U.__file__, encoding="utf-8").read()
    assert src.count("photos = _own_photos(r)") == 2          # 目視画面 / カタログにない の依頼
    tl = open(r"C:\dev\iMak\iMakMercari\tshirt_listing.py", encoding="utf-8").read()
    assert 'photo_urls = "|".join(UCV.own_item_photos(target["url"]' in tl
