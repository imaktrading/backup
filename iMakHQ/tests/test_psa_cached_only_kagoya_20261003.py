"""PSA 新規を KAGOYA で動かす (2026-10-03 ユーザー OK)。

KAGOYA には Cloudflare を押す人がいないので、Chrome を開かず先取り済みの cert だけで進む。
目視の画面は ssh で中継している番号 (IMAK_REVIEW_PORT) だけで立てる。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
sys.path.insert(0, os.path.join(HERE, "..", "..", "iMakTCG"))
sys.path.insert(0, os.path.join(HERE, "..", "..", "iMakeBayAPI"))

import post_psa_review as R  # noqa: E402
import psa_to_csv as P  # noqa: E402


def test_cached_only_mode_only_when_env_is_1():
    assert P.cached_only_mode({"PSA_CACHED_ONLY": "1"}) is True
    assert P.cached_only_mode({}) is False
    assert P.cached_only_mode({"PSA_CACHED_ONLY": "0"}) is False


def test_cache_miss_without_driver_is_skipped_not_fetched(monkeypatch):
    """先取りに無い cert は Chrome 無しでは取りに行かず None (= 出さない)。"""
    monkeypatch.setattr(P, "_load_psa_cache", lambda: {})
    assert P.get_psa_data(None, "999999999") is None


def test_review_port_fixed_on_kagoya():
    assert R.review_ports({"IMAK_REVIEW_PORT": "18765"}) == [18765]


def test_review_ports_default_unchanged():
    assert R.review_ports({}) == list(range(R.SERVER_PORT, R.SERVER_PORT + 10))
