# -*- coding: utf-8 -*-
"""relist PicURL 組立 回帰テスト (2026-06-28)。

バグ: relist で eBay EPS画像に自前 extra_pics(999.png/banner)を混ぜ "mixture of Self Hosted
and EPS pictures" で eBay 拒否(バッグ relist 失敗)。修正: relist は extra 無し。
(pre-commit collect する tests/。軽量 ebay_getitem_images から import)
"""
import os, sys
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakeBayAPI")))
from ebay_getitem_images import build_pic_url  # noqa: E402

_EPS = ["https://i.ebayimg.com/a.jpg", "https://i.ebayimg.com/b.jpg"]
_EXTRA = ["https://self.host/999.png", "https://self.host/banner.jpg"]


def test_relist_drops_self_hosted_extra():
    """relist時は extra(自前ホスト)を付けない=EPS混在エラー回避。"""
    out = build_pic_url(_EPS, _EXTRA, relist_mode=True)
    assert "self.host" not in out
    assert out == "https://i.ebayimg.com/a.jpg|https://i.ebayimg.com/b.jpg"


def test_normal_keeps_extra():
    out = build_pic_url(["https://m/1.jpg"], _EXTRA, relist_mode=False)
    assert "self.host/999.png" in out and "self.host/banner.jpg" in out


def test_cap_24():
    imgs = [f"u{i}" for i in range(30)]
    assert len(build_pic_url(imgs, [], relist_mode=True).split("|")) == 24
