# -*- coding: utf-8 -*-
"""目視画面の 🅰 カタログ画像: カタログが PC の中のファイルで持つ公式画像も出す (2026-10-14)。

ユーザー「カタログにも画像ない」(キラ・ヤマト ST04-010_p1)。画面の /img はネットの URL しか取れず、
公式から取ったカードは全部「画像なし」になっていた。置き場の外のファイルは配らない。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "iMakeBayAPI"))

import psa_resource_confirm as P  # noqa: E402


def test_local_catalog_image_is_served(tmp_path, monkeypatch):
    root = tmp_path / "_official_images"
    (root / "gundam_tcg").mkdir(parents=True)
    f = root / "gundam_tcg" / "ST04-010_p1.webp"
    f.write_bytes(b"WEBPDATA")
    monkeypatch.setattr(P, "CATALOG_IMG_ROOT", os.path.normcase(os.path.normpath(str(root))))
    assert P._fetch_image(str(f)) == (b"WEBPDATA", "image/webp")


def test_file_outside_catalog_root_is_not_served(tmp_path, monkeypatch):
    root = tmp_path / "_official_images"
    root.mkdir()
    other = tmp_path / "secret.png"
    other.write_bytes(b"x")
    monkeypatch.setattr(P, "CATALOG_IMG_ROOT", os.path.normcase(os.path.normpath(str(root))))
    assert P._catalog_local_image(str(other)) is None
    assert P._catalog_local_image(str(root / ".." / "secret.png")) is None


def test_url_is_not_treated_as_local():
    assert P._catalog_local_image("https://www.gundam-gcg.com/jp/images/cards/card/ST04-010_p1.webp") is None
