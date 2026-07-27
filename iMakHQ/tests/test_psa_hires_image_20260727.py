# -*- coding: utf-8 -*-
"""目視用 PSA 画像を高解像度(/large/)で出す + 無ければ /small/ に落ちる (2026-07-27)。

★動機(実例): cert153420191 Perona は `/small/`(380x640) だと右下のレアリティ表記が潰れて
`OP01-077_p4`(★なし) と `OP01-077_p5`(★あり) を判別できず、目視「該当なし(NONE)」→
出品機会を落としていた。`/large/`(1140x1920) に上げたら ★ が読めて **p5 と確定**できた。
= 解像度が歩留まりに直結する。ただし /large/ が無い cert もありうるので **必ず /small/ へ fallback**
(画像が出ない = 目視不能 = さらに悪い)。
"""
import os
import sys
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import post_psa_review as ppr  # noqa: E402

SMALL = "https://d1htnxwo4o0jhw.cloudfront.net/cert/204357846/small/tWnXwtC10kOuBRt5GYo0mA.jpg"
LARGE = "https://d1htnxwo4o0jhw.cloudfront.net/cert/204357846/large/tWnXwtC10kOuBRt5GYo0mA.jpg"


def test_psa_hires_url():
    assert ppr.psa_hires_url(SMALL) == LARGE
    assert ppr.psa_hires_url(LARGE) is None                      # 既に large
    assert ppr.psa_hires_url("https://example.com/a/small/x.jpg") is None   # 別ホスト
    assert ppr.psa_hires_url("") is None


def test_fetch_prefers_large():
    """★まず /large/ を取りに行く。"""
    seen = []

    def opener(u):
        seen.append(u)
        return (b"IMG", "image/jpeg")

    got = ppr.fetch_external_image(SMALL, opener=opener, sleep=lambda s: None)
    assert got == (b"IMG", "image/jpeg")
    assert seen == [LARGE], "large を先に試すこと"


def test_fetch_falls_back_to_small_on_404():
    """/large/ が無い cert では /small/ に落ちる(画像を出さないのが最悪)。"""
    seen = []

    def opener(u):
        seen.append(u)
        if "/large/" in u:
            raise urllib.error.HTTPError(u, 404, "nf", None, None)
        return (b"SMALLIMG", "image/jpeg")

    got = ppr.fetch_external_image(SMALL, opener=opener, sleep=lambda s: None)
    assert got == (b"SMALLIMG", "image/jpeg")
    assert seen == [LARGE, SMALL], "large→small の順で試すこと"


def test_non_psa_url_is_untouched():
    """PSA 以外(catalog 公式画像等)は従来どおり1本だけ取りに行く。"""
    seen = []

    def opener(u):
        seen.append(u)
        return (b"X", "image/png")

    src = "https://www.onepiece-cardgame.com/images/cardlist/card/OP01-077_p5.png"
    ppr.fetch_external_image(src, opener=opener, sleep=lambda s: None)
    assert seen == [src]


def test_transient_error_still_retries():
    """一時エラーはリトライする(既存挙動を壊さない)。"""
    calls = {"n": 0}

    def opener(u):
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("dns")
        return (b"OK", "image/jpeg")

    got = ppr.fetch_external_image(SMALL, opener=opener, sleep=lambda s: None)
    assert got == (b"OK", "image/jpeg")
