# -*- coding: utf-8 -*-
"""PSA Review の /img/ proxy が transient(DNS/timeout)でリトライする回帰テスト。

2026-06-23: pokemon-card.com 等の DNS一時失敗(getaddrinfo)で画像が「ちょいちょい出ない」
真因 = proxy にリトライ無し。transient はリトライ、HTTPError(404)は即諦める、を固定する。
"""
import os
import sys
import urllib.error

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tools")))
import post_psa_review as pr  # noqa: E402


def test_retry_succeeds_after_transient_dns():
    calls = {"n": 0}

    def opener(src):
        calls["n"] += 1
        if calls["n"] < 3:                       # 2回 transient(DNS)失敗
            raise urllib.error.URLError("getaddrinfo failed")
        return (b"IMGDATA", "image/png")          # 3回目で成功

    got = pr.fetch_external_image("http://x/y.png", opener=opener, sleep=lambda _s: None)
    assert got == (b"IMGDATA", "image/png")
    assert calls["n"] == 3                         # リトライして取得


def test_http_error_not_retried():
    calls = {"n": 0}

    def opener(src):
        calls["n"] += 1
        raise urllib.error.HTTPError("http://x", 404, "Not Found", {}, None)

    got = pr.fetch_external_image("http://x/dead.webp", opener=opener, sleep=lambda _s: None)
    assert got is None
    assert calls["n"] == 1                         # 404 は恒久 → 1回で諦め(無駄打ちしない)


def test_all_transient_gives_up_after_retries():
    calls = {"n": 0}

    def opener(src):
        calls["n"] += 1
        raise urllib.error.URLError("timed out")

    got = pr.fetch_external_image("http://x/slow.jpg", retries=4, opener=opener, sleep=lambda _s: None)
    assert got is None
    assert calls["n"] == 4                         # retries 回試して諦め
