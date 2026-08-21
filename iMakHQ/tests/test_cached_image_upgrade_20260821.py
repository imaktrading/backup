# -*- coding: utf-8 -*-
"""キャッシュから出した PSA 画像も /large/ に上げる (2026-08-21).

★実害: /large/ 化は **scrape 経路にしか入っていなかった**。
  2026-08-14 より前にキャッシュされた cert は /small/(380x640) のまま
  PicURL に載り、eBay のズーム (1600px 以上が必要) が効かない。
  実例 2026-08-20: cert140936782 ジラーチGX $781.98。高額行ほど効く。

  8/15 に「キャッシュ hit でも代替画像を当てる」を入れた時と同じ型の見落とし
  (読み出し口に入れないと、既にキャッシュにある分は素通りする)。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, r"C:\dev\iMak\iMakTCG")

import psa_to_csv as P                                          # noqa: E402

SMALL = "https://d1htnxwo4o0jhw.cloudfront.net/cert/1/small/abc.jpg"
LARGE = SMALL.replace("/small/", "/large/")


class TestPureUpgrade:
    def test_実在すれば差し替える(self):
        assert P.upgrade_psa_images([SMALL], lambda u: True) == [LARGE]

    def test_実在しなければ元のまま(self):
        """★404 を PicURL に載せると『画像なし』でもっと悪くなる."""
        assert P.upgrade_psa_images([SMALL], lambda u: False) == [SMALL]

    def test_別ホストは触らない(self):
        other = "https://example.com/small/x.jpg"
        assert P.upgrade_psa_images([other], lambda u: True) == [other]


class TestCachePath:
    def test_キャッシュの値を上げて書き戻す(self):
        cache = {"1": {"CardImageUrl": SMALL, "CardImageUrlFront": SMALL}}
        saved = {}
        P._url_exists = lambda u, timeout=8: True
        P._save_psa_cache = lambda c: saved.update(c)
        got = P._upgrade_cached_images("1", cache["1"], cache)
        assert got["CardImageUrl"] == LARGE and got["CardImageUrlFront"] == LARGE
        assert saved["1"]["CardImageUrl"] == LARGE      # 次回は HEAD を飛ばさない

    def test_smallが無ければ何もしない(self):
        """毎回 HEAD を投げない (キャッシュ hit の意味が無くなる)."""
        calls = []
        P._url_exists = lambda u, timeout=8: calls.append(u) or True
        d = {"CardImageUrl": LARGE}
        assert P._upgrade_cached_images("1", d, {}) is d
        assert calls == []
