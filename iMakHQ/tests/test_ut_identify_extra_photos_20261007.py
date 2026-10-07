"""UT 目視: 「同じ物」の候補の写真 / 自分で探したURLの写真も出品画像に選べる (2026-10-07 ユーザー)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "iMakMercari"))
import ut_catalog_values as U  # noqa: E402
import ut_identify as UI  # noqa: E402


def test_parse_keeps_extra_and_catalog_photos():
    res = UI.parse_result({"picks": [{"idx": 1, "pid": "P", "color": "", "design": True,
                                      "extra": ["https://a/1.jpg", "bad", 3], "xcat": ["https://a/1.jpg"]}]})
    assert res["picks"][0]["extra"] == ["https://a/1.jpg"] and res["picks"][0]["xcat"] == ["https://a/1.jpg"]


def test_extra_photos_go_after_catalog_before_seller_and_can_be_first():
    imgs = U.listing_images(["https://c/1.jpg"], seller_urls=["https://m/1.jpg"], extra=["https://x/1.jpg"])
    assert imgs == ["https://c/1.jpg", "https://x/1.jpg", "https://m/1.jpg"]
    imgs = U.listing_images(["https://c/1.jpg"], extra=["https://x/1.jpg"], first="https://x/1.jpg")
    assert imgs[0] == "https://x/1.jpg"


def test_image_inputs_written_once(tmp_path):
    assert UI.write_image_inputs({"P": ["https://x/1.jpg"]}, str(tmp_path), now="t") == 1
    assert UI.write_image_inputs({"P": ["https://x/1.jpg"]}, str(tmp_path), now="t") == 0
