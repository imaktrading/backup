"""tests/test_mercari_image_urls - _extract_image_urls の商品画像フィルタ検証.

2026-09-14 HQ 依頼 (2026-09-14_ut_mercari_photos_include_other_items):
フォールバック selector (img[src*='static.mercdn.net']) がページ内の
mercdn.net 画像を全部拾い、出品者アイコン (thumb/members/) や他商品サムネ
(thumb/item/webp/) が G列に混入していた (618行中390行)。
_extract_image_urls() は返す前に商品本体画像パターンのみへ絞る。
"""
from __future__ import annotations

import pytest

from scrapers.mercari_item_detail import _extract_image_urls


pytestmark = pytest.mark.offline


class _MockImg:
    def __init__(self, src: str):
        self._src = src

    def get_attribute(self, name: str):
        if name == "src":
            return self._src
        return None


class _MockDriver:
    """find_elements のみモック。最初にヒットした selector の要素を返す."""

    def __init__(self, elements_by_selector: dict):
        self._elements_by_selector = elements_by_selector

    def find_elements(self, by, value):
        return self._elements_by_selector.get(value, [])


class _MockDriverDelayed:
    """主 selector への呼出しが `empty_calls` 回続いた後、 写真を返す
    (カルーセルが説明文より遅れて描画されるケースを再現)."""

    def __init__(self, primary_selector: str, photos: list, empty_calls: int):
        self._primary_selector = primary_selector
        self._photos = photos
        self._empty_calls = empty_calls
        self._calls = 0

    def find_elements(self, by, value):
        if value != self._primary_selector:
            return []
        self._calls += 1
        if self._calls <= self._empty_calls:
            return []
        return self._photos


OWN_PHOTO_1 = "https://static.mercdn.net/item/detail/orig/photos/m93825825680_1.jpg?123"
OWN_PHOTO_2 = "https://static.mercdn.net/item/detail/orig/photos/m93825825680_2.jpg?123"
OTHER_ITEM_THUMB = "https://static.mercdn.net/thumb/item/webp/m77504242885_1.jpg?456"
MEMBER_ICON = "https://static.mercdn.net/thumb/members/webp/110556606.jpg?789"
MEMBER_NOIMAGE_ICON = "https://static.mercdn.net/images/member_photo_noimage_thumb.png"


class TestExtractImageUrlsFiltersToOwnProductPhotos:
    def test_primary_selector_own_photos_only_unaffected(self):
        driver = _MockDriver({
            ".slick-list button mer-item-thumbnail": [
                _MockImg(OWN_PHOTO_1), _MockImg(OWN_PHOTO_2),
            ],
        })
        assert _extract_image_urls(driver) == [OWN_PHOTO_1, OWN_PHOTO_2]

    def test_fallback_selector_mixed_with_other_item_and_icon_is_filtered(self):
        # 先頭3 selector が0件 → フォールバック selector がページ全体の
        # mercdn.net 画像 (自分 + 他商品サムネ + アイコン) を拾う
        driver = _MockDriver({
            "img[src*='static.mercdn.net']": [
                _MockImg(OWN_PHOTO_1),
                _MockImg(MEMBER_NOIMAGE_ICON),
                _MockImg(MEMBER_ICON),
                _MockImg(OTHER_ITEM_THUMB),
                _MockImg(OWN_PHOTO_2),
            ],
        })
        assert _extract_image_urls(driver) == [OWN_PHOTO_1, OWN_PHOTO_2]

    def test_no_own_photo_match_returns_empty_not_fallback_to_all(self):
        # 絞った結果が0件 → フォールバックで他人の写真に戻さない (fail-closed)
        driver = _MockDriver({
            "img[src*='static.mercdn.net']": [
                _MockImg(MEMBER_ICON),
                _MockImg(OTHER_ITEM_THUMB),
            ],
        })
        assert _extract_image_urls(driver, wait_sec=0) == []

    def test_no_elements_found_returns_empty(self):
        driver = _MockDriver({})
        assert _extract_image_urls(driver, wait_sec=0) == []


class TestExtractImageUrlsWaitsForLateRender:
    """2026-09-16 HQ 依頼: 目視候補553件中22件が写真URL列0本だった。
    うち複数件は同じ URL を再訪問すると普通に写真が取れた = カルーセルが
    説明文より遅れて描画される一発 find のタイミング負け (`_extract_description`
    (8/17) と同じ形)。 出現を待ってから諦めるようにした。"""

    def test_retries_until_photos_render(self):
        driver = _MockDriverDelayed(
            ".slick-list button mer-item-thumbnail",
            [_MockImg(OWN_PHOTO_1), _MockImg(OWN_PHOTO_2)],
            empty_calls=2,
        )
        assert _extract_image_urls(driver, wait_sec=1.0) == [OWN_PHOTO_1, OWN_PHOTO_2]

    def test_gives_up_after_wait_sec_and_returns_empty(self):
        driver = _MockDriverDelayed(
            ".slick-list button mer-item-thumbnail",
            [_MockImg(OWN_PHOTO_1)],
            empty_calls=10_000,  # 待っている間ずっと空 (=タイムアウトで諦める)
        )
        assert _extract_image_urls(driver, wait_sec=0.3) == []
