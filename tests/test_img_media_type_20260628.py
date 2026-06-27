# -*- coding: utf-8 -*-
"""画像 media_type 判定 回帰テスト (2026-06-28)。

バグ: Claude API に渡す画像 media_type が image/jpeg 固定 → eBay画像(PNG混在)で
「jpeg と指定されたが実体は png」400 で全 API失敗(relist画像流用でPNGが来て露呈)。
修正: マジックバイトで実形式判定。共通関数は ebay_getitem_images.img_media_type(軽量)。
(pre-commit collect する tests/ に配置。重い mercari モジュールは import しない)
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakeBayAPI")))

from ebay_getitem_images import img_media_type  # noqa: E402

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 20
_GIF = b"GIF89a" + b"\x00" * 20
_WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 12


def test_media_type_by_magic_bytes():
    assert img_media_type(_PNG) == "image/png"
    assert img_media_type(_JPEG) == "image/jpeg"
    assert img_media_type(_GIF) == "image/gif"
    assert img_media_type(_WEBP) == "image/webp"


def test_media_type_png_not_mislabeled_jpeg():
    """eBay の .PNG が jpeg 扱いされない(400根治の核心)。"""
    assert img_media_type(_PNG) != "image/jpeg"


def test_media_type_unknown_defaults_jpeg():
    assert img_media_type(b"randombytes-not-an-image") == "image/jpeg"
