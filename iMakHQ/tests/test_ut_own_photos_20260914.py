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


def test_rows_without_photos_go_last():
    """写真の無い行は目視の後ろに回す (2026-09-16 ユーザー「後半画像無しが多い」)。

    実測: 目視候補 553件のうち写真なし 24件。並びが ①出品済みKEY無し → ②売れ筋 → ③その他 だけで
    写真の有無を見ていなかったため、売れ筋の写真なし行が上位に混ざり、
    先頭20件のうち10件が「見比べられない行」になっていた。
    """
    import ut_identify as U
    def row(title, photos):
        r = [""] * 40
        r[U.C_URL] = "https://jp.mercari.com/item/x"
        r[U.C_TITLE] = title
        r[U.C_PHOTOS] = photos
        return r
    rows = [(1, row("鬼滅 UT XL", ""), "tab"),            # 売れ筋だが写真なし
            (2, row("その他 UT M", "https://a/1.jpg"), "tab")]
    got = [t[0] for t in U.order_rows(rows, demand=[])]
    assert got == [2, 1]
    assert U.has_photo(row("x", "https://a/1.jpg|"))
    assert not U.has_photo(row("x", " | "))


def test_no_photo_card_still_opens_mercari():
    """写真が無い行でも押す物を出す (メルカリで開く)。"""
    import os
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "tools", "ut_identify.py"), encoding="utf-8").read()
    assert "メルカリで開く" in src
    assert "ph.nophoto" in src
