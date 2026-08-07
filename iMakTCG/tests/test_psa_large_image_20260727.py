# -*- coding: utf-8 -*-
"""PSA 画像を取得時点で /large/ に上げる (2026-07-27)。

## なぜ
`/small/` は **380x640**。これが 3箇所で効いていた:
1. **eBay 商品画像(PicURL)** — 380px ではズームが効かず、PSA スラブの状態が見えない
   (eBay はズームに 1600px 以上を推奨)。高額カードほど購入判断されにくい。
2. **Vision の同定** — ★(パラレル)1個や card_number の細部が潰れる。実際 Perona
   `OP01-077_p4`(★なし) と `_p5`(★あり) は /small/ では判別不能 → 目視 NONE → 出品機会を落とした。
   `/large/`(1140x1920) で ★ が読めて `_p5` と確定できた。
3. **PSA グレード** — `GEM MT 10` / `MINT 9` の判読。誤出品6件はこれで確定させた。

psa_cache / viewer / PicURL / Vision は同じ URL を共有するので **取得時点で上げれば全部に効く**。

## fail-safe
`/large/` が無い cert がありうる。**実在確認できた時だけ**差し替える
(PicURL が 404 だと eBay 側で「画像なし」= 元より悪い)。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from psa_to_csv import psa_large_variant, upgrade_psa_images  # noqa: E402

SMALL_F = "https://d1htnxwo4o0jhw.cloudfront.net/cert/206545912/small/EkY1R9nGw0Oat9d5j9-nUg.jpg"
SMALL_B = "https://d1htnxwo4o0jhw.cloudfront.net/cert/206545912/small/7fR4a7AZMkSi_T9txRcaSQ.jpg"
LARGE_F = SMALL_F.replace("/small/", "/large/")
LARGE_B = SMALL_B.replace("/small/", "/large/")


def test_large_variant():
    assert psa_large_variant(SMALL_F) == LARGE_F
    assert psa_large_variant(LARGE_F) is None                 # 既に large
    assert psa_large_variant("https://example.com/small/x.jpg") is None   # 別ホスト
    assert psa_large_variant("") is None
    assert psa_large_variant(None) is None


def test_upgrade_when_large_exists():
    """★表・裏とも /large/ に上がる(= PicURL も Vision も高解像度になる)。"""
    seen = []

    def exists(u):
        seen.append(u)
        return True

    assert upgrade_psa_images([SMALL_F, SMALL_B], exists) == [LARGE_F, LARGE_B]
    assert seen == [LARGE_F, LARGE_B]


def test_keeps_small_when_large_missing():
    """/large/ が無ければ元のまま(PicURL に 404 を載せない)。"""
    assert upgrade_psa_images([SMALL_F], lambda u: False) == [SMALL_F]


def test_mixed_availability():
    def exists(u):
        return "EkY1R9" in u          # 表だけ large あり
    assert upgrade_psa_images([SMALL_F, SMALL_B], exists) == [LARGE_F, SMALL_B]


def test_non_psa_urls_untouched():
    """999.png ダミーや catalog 公式画像は素通り(存在確認もしない)。"""
    dummy = "https://raw.githubusercontent.com/imaktrading/imaktrading.github.io/main/999.png"
    calls = []
    assert upgrade_psa_images([dummy], lambda u: calls.append(u) or True) == [dummy]
    assert calls == []


def test_empty():
    assert upgrade_psa_images([], lambda u: True) == []
    assert upgrade_psa_images(None, lambda u: True) == []
