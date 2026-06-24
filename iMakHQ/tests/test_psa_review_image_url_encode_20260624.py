# -*- coding: utf-8 -*-
"""PSA Review の /img/ proxy がスペース入りURLを %エンコードして fetch する回帰テスト。

2026-06-24: One Piece 'Other Product Card/' フォルダ等の catalog 画像URLにスペースが含まれ、
urllib.request が InvalidURL('control characters') で落ちて画像が出ない真因。fetch直前に
%エンコードする (_encode_image_url) ことを固定。既エンコード済URLは二重エンコードしない。
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tools")))
import post_psa_review as pr  # noqa: E402

_SPACED = "https://files.bandai-tcg-plus.com/card_image/OP-EN/Other Product Card/P-001_d.png"
_ENCODED = "https://files.bandai-tcg-plus.com/card_image/OP-EN/Other%20Product%20Card/P-001_d.png"


def test_space_is_percent_encoded():
    out = pr._encode_image_url(_SPACED)
    assert " " not in out
    assert "Other%20Product%20Card" in out
    assert out == _ENCODED


def test_already_encoded_not_double_encoded():
    """%エンコード済URLを再度通しても %25 への二重エンコードが起きない。"""
    assert pr._encode_image_url(_ENCODED) == _ENCODED


def test_plain_url_unchanged():
    u = "https://example.com/a/b/c.png?x=1&y=2"
    assert pr._encode_image_url(u) == u


def test_empty_passthrough():
    assert pr._encode_image_url("") == ""


def test_opener_encodes_before_urlopen(monkeypatch):
    """_default_image_opener が encode 済URLで Request を作る (urllib に生スペースを渡さない)。"""
    seen = {}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"IMG"
        headers = {"Content-Type": "image/png"}

    def fake_urlopen(req, timeout=15):
        seen["url"] = req.full_url
        return _Resp()

    monkeypatch.setattr(pr.urllib.request, "urlopen", fake_urlopen)
    data, ctype = pr._default_image_opener(_SPACED)
    assert data == b"IMG" and ctype == "image/png"
    assert " " not in seen["url"]
    assert seen["url"] == _ENCODED
