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


def test_dbs_url_renewal_rewrite():
    """dbs-cardgame サイトリニューアルの旧→新パス書換 (catalog反映前でもviewerで出す)。"""
    seen = {}

    def opener(src):
        seen["src"] = src
        return (b"IMG", "image/webp")

    old = "https://www.dbs-cardgame.com/fw/jp/images/cards/card/jp/E01-08.webp"
    pr.fetch_external_image(old, opener=opener, sleep=lambda _s: None)
    assert seen["src"] == "https://www.dbs-cardgame.com/fw/images/cards/card/jp/E01-08.webp"
    # 既に新パス/他ホストは無改変
    assert pr._normalize_image_url("https://files.bandai-tcg-plus.com/x/y.png") == \
        "https://files.bandai-tcg-plus.com/x/y.png"


def test_snapshot_cache_serves_locally_after_first_fetch(tmp_path):
    """snapshot方式: 一度 fetch 成功したら以降はローカルから配信(外部に取りに行かない)。"""
    calls = {"n": 0}

    def fetch(url):
        calls["n"] += 1
        return (b"PNGDATA", "image/png")

    url = "https://www.pokemon-card.com/x/y.jpg"
    g1 = pr.get_image_cached(url, cache_dir=tmp_path, fetch=fetch)
    g2 = pr.get_image_cached(url, cache_dir=tmp_path, fetch=fetch)
    assert g1 == (b"PNGDATA", "image/png")
    assert g2 == (b"PNGDATA", "image/png")
    assert calls["n"] == 1                       # 2回目は fetch せずキャッシュ配信(snapshot)


def test_snapshot_cache_miss_failure_not_cached(tmp_path):
    """fetch 失敗(None)はキャッシュしない → 次回再試行できる。"""
    def fetch_fail(url):
        return None

    url = "https://x/dead.png"
    assert pr.get_image_cached(url, cache_dir=tmp_path, fetch=fetch_fail) is None
    # キャッシュに焼かれていない(成功時だけ焼く)
    assert pr.cached_image_get(url, cache_dir=tmp_path) is None


def test_snapshot_cache_key_after_normalize(tmp_path):
    """旧dbs URLでも正規化後URLでキャッシュ → 旧/新どちらの要求でも同じ snapshot にヒット。"""
    calls = {"n": 0}

    def fetch(url):
        calls["n"] += 1
        assert "/fw/images/" in url               # 正規化後で fetch される
        return (b"WEBP", "image/webp")

    old = "https://www.dbs-cardgame.com/fw/jp/images/cards/card/jp/E01-08.webp"
    new = "https://www.dbs-cardgame.com/fw/images/cards/card/jp/E01-08.webp"
    pr.get_image_cached(old, cache_dir=tmp_path, fetch=fetch)
    pr.get_image_cached(new, cache_dir=tmp_path, fetch=fetch)   # 新URL要求も同じキャッシュ
    assert calls["n"] == 1


def test_all_transient_gives_up_after_retries():
    calls = {"n": 0}

    def opener(src):
        calls["n"] += 1
        raise urllib.error.URLError("timed out")

    got = pr.fetch_external_image("http://x/slow.jpg", retries=4, opener=opener, sleep=lambda _s: None)
    assert got is None
    assert calls["n"] == 4                         # retries 回試して諦め
