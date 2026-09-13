# -*- coding: utf-8 -*-
"""UT の出品画像は **カタログが主役、仕入元は最後** (2026-09-13 ユーザー確定)。

ユーザー「出品者の画像は、使うなら最後の方で使う。メインはカタログ画像を」。
それまでは **メルカリの1枚目だけ**を使っており、カタログ画像は1枚も使っていなかった。

並びはルールで固定し、目視では「使わない画像を外す」だけにする
(毎回 順番を選ばせると 20件×毎回 で目視が重くなる):
  1. 目視で選んだ色の、カタログの表  2. カタログのサブ (背面・着用)  3. メルカリの写真
  他の色の表は入れない / 色見本 (chip) は入れない / 最大12枚
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "iMakHQ" / "tools", ROOT / "iMakMercari", ROOT / "iMakeBayAPI"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import ut_catalog_values as V  # noqa: E402

B = "https://image.uniqlo.com/UQ/ST3/AsianCommon/imagesgoods/480691"
MAIN_BLUE = f"{B}/item/goods_65_480691_3x4.jpg"
MAIN_WHITE = f"{B}/item/goods_00_480691_3x4.jpg"
SUB1 = f"{B}/sub/goods_480691_sub14_3x4.jpg"
SUB2 = f"{B}/sub/goods_480691_sub15_3x4.jpg"
CHIP = f"{B}/chip/goods_65_480691_chip.jpg"
M1 = "https://static.mercdn.net/item/detail/orig/photos/m96908574252_1.jpg"
M2 = "https://static.mercdn.net/item/detail/orig/photos/m96908574252_2.jpg"


def test_catalog_first_seller_last_other_color_and_chip_out():
    got = V.listing_images([MAIN_WHITE, SUB1, MAIN_BLUE, CHIP, SUB2], color_code="65",
                           l1="480691", other_codes=["00", "65"], seller_urls=[M1, M2])
    assert got == [MAIN_BLUE, SUB1, SUB2, M1, M2]


def test_dropped_images_are_left_out():
    got = V.listing_images([MAIN_BLUE, SUB1, SUB2], color_code="65", l1="480691",
                           other_codes=["65"], seller_urls=[M1, M2], drop=[SUB2, M2])
    assert got == [MAIN_BLUE, SUB1, M1]


def test_unknown_color_keeps_every_catalog_image():
    """色の番号が引けない時に表を全部捨てると、カタログ画像が0枚になる。"""
    got = V.listing_images([MAIN_WHITE, SUB1], color_code="", l1="480691",
                           other_codes=["00"], seller_urls=[M1])
    assert got == [MAIN_WHITE, SUB1, M1]


def test_no_catalog_images_falls_back_to_seller():
    assert V.listing_images([], "65", "480691", ["65"], [M1, M2]) == [M1, M2]


def test_capped_at_twelve():
    subs = [f"{B}/sub/goods_480691_sub{i}_3x4.jpg" for i in range(20)]
    got = V.listing_images(subs, "65", "480691", ["65"], [M1])
    assert len(got) == V.MAX_PICTURES == 12
    assert M1 not in got, "上限で切るのは後ろ (仕入元) から"


def test_values_carry_the_image_material():
    """目視の台帳 → 出品に写す値 に、画像の材料と外した画像が載ること。"""
    import io
    src = io.open(ROOT / "iMakMercari" / "ut_catalog_values.py", encoding="utf-8").read()
    i = src.index("def values_for_url(")
    body = src[i:src.index("\ndef ", i + 1)]
    for k in ('"catalog_images"', '"color_codes"', '"img_drop"'):
        assert k in body, k


def test_screen_posts_the_dropped_images():
    import ut_identify as U
    res = U.parse_result({"picks": [{"idx": 3, "pid": "E480691-000", "color": "BLUE",
                                     "drop": [SUB2, "", 5]}]})
    assert res["picks"][0]["drop"] == [SUB2]


def test_generator_uses_catalog_images_for_identified_rows():
    import io
    src = io.open(ROOT / "iMakMercari" / "tshirt_listing.py", encoding="utf-8").read()
    assert "UCV.images_for_listing(" in src


def test_ut_auto_is_scheduled_listing():
    """ユーザー「最初はスケジュールで出品して。そこで内容を確認するから」。"""
    import io
    src = io.open(ROOT / "iMakHQ" / "control_panel.py", encoding="utf-8").read()
    i = src.index('"category": "Tシャツ", "type": "auto"')
    blk = src[i:src.index("    },\n", i)]
    assert '"auto_upload_write": True' in blk
    assert '"auto_upload_schedule": True' in blk
    j = src.index("def _run_auto_full_tail")
    tail = src[j:src.index("\ndef ", j + 1)]
    assert '"--schedule"' in tail


def test_image_picker_is_big_enough_to_judge():
    """ユーザー「出品に使う画像を選ぶとき、画像が小さすぎて判断しづらい」(2026-09-13 試走)。

    初版は 42x56px で、柄も背面も判別できなかった。並びの小さい画像を大きくし、
    画面いっぱいに並べてそこで外せる (下の画像と連動する) ボタンを付けた。
    """
    import io
    import re
    src = io.open(ROOT / "iMakHQ" / "tools" / "ut_identify.py", encoding="utf-8").read()
    m = re.search(r"\.imgpick img\{width:(\d+)px;height:(\d+)px", src)
    assert m and int(m.group(1)) >= 100 and int(m.group(2)) >= 130, m and m.groups()
    assert "function zoomPick(" in src and "zoomPick(event,this)" in src


# ── 1枚目だけ人が指定する (2026-09-13 試走) ──────────────────────────────
# ユーザー「画像の順番を指定するところだけど、1枚目だけ指定させて」。
# 押した画像を先頭に置き、残りはルールの順のまま。押さなければ今までどおりカタログの表が先頭。

def test_first_image_moves_to_the_front_rest_keep_rule_order():
    got = V.listing_images([MAIN_BLUE, SUB1, SUB2], "65", "480691", ["65"], [M1, M2], first=SUB2)
    assert got == [SUB2, MAIN_BLUE, SUB1, M1, M2]


def test_seller_photo_can_be_first():
    got = V.listing_images([MAIN_BLUE, SUB1], "65", "480691", ["65"], [M1, M2], first=M2)
    assert got[0] == M2 and got[1:] == [MAIN_BLUE, SUB1, M1]


def test_dropped_or_unknown_first_is_ignored():
    """外した画像や候補に無い URL を1枚目にしない (外したのに先頭に来る事故を作らない)。"""
    base = V.listing_images([MAIN_BLUE, SUB1], "65", "480691", ["65"], [M1])
    assert V.listing_images([MAIN_BLUE, SUB1], "65", "480691", ["65"], [M1],
                            drop=[SUB1], first=SUB1)[0] == MAIN_BLUE
    assert V.listing_images([MAIN_BLUE, SUB1], "65", "480691", ["65"], [M1],
                            first="https://example.com/x.jpg") == base


def test_first_survives_the_twelve_cap():
    subs = [f"{B}/sub/goods_480691_sub{i}_3x4.jpg" for i in range(20)]
    got = V.listing_images(subs, "65", "480691", ["65"], [M1], first=M1)
    assert got[0] == M1 and len(got) == 12


def test_screen_posts_main_and_parse_keeps_only_valid():
    import ut_identify as U
    res = U.parse_result({"picks": [
        {"idx": 1, "pid": "E1", "color": "BLUE", "drop": [], "main": M1},
        {"idx": 2, "pid": "E1", "color": "BLUE", "drop": [M1], "main": M1},   # 外した物は1枚目にしない
        {"idx": 3, "pid": "E1", "color": "BLUE", "main": "not a url"}]})
    by = {p["idx"]: p for p in res["picks"]}
    assert by[1]["main"] == M1 and "main" not in by[2] and "main" not in by[3]


def test_values_and_screen_carry_img_main():
    import io
    src = io.open(ROOT / "iMakMercari" / "ut_catalog_values.py", encoding="utf-8").read()
    assert 'v["img_main"]' in src and 'first=v.get("img_main")' in src
    ui = io.open(ROOT / "iMakHQ" / "tools" / "ut_identify.py", encoding="utf-8").read()
    assert "function setFirst(" in ui and '"img_main": p["main"]' in ui
