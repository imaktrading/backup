# -*- coding: utf-8 -*-
"""eBaymag をブラウザ無しで読む (2026-09-06 ユーザー指摘「何回もログインボタン押さなあかん」).

## なぜ
eBaymag のログイン cookie は **セッション限り** (has_expires=0) なので、Chrome を
閉じた瞬間に消える。プロファイルを共有しても残らない。画面から拾うたびにブラウザが
立ち上がり、そのたびにログインを求められていた。

cookie を自分で書き出して次回に流し込み、以降は保存した cookie で GraphQL を直接叩く。
ログインは cookie が切れた時だけ。
"""
from __future__ import annotations

import io
import os
import sys

import pytest

_HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOOLS = os.path.join(_HQ, "tools")
sys.path.insert(0, _TOOLS)
_API = io.open(os.path.join(_TOOLS, "ebaymag_api.py"), encoding="utf-8").read()
_DUMP = io.open(os.path.join(_TOOLS, "ebaymag_dump.py"), encoding="utf-8").read()


@pytest.fixture(scope="module")
def A():
    import ebaymag_api
    return ebaymag_api


class TestSiteName:
    def test_known_sites(self, A):
        assert A.site_name(0) == "US" and A.site_name(3) == "UK"
        assert A.site_name(77) == "DE" and A.site_name(2) == "CA"

    def test_unknown_site_is_not_swallowed(self, A):
        """知らない番号を空欄にしない (どこの話か分からなくなる)。"""
        assert A.site_name(999) == "999"


class TestBadSites:
    def test_only_sites_with_problems(self, A):
        node = {"listings": [
            {"site": {"id": 0}, "problems": []},
            {"site": {"id": 3}, "problems": [{"id": "1"}, {"id": "2"}]},
            {"site": {"id": 77}, "problems": []},
        ]}
        assert A.bad_sites(node) == [("UK", 2)]

    def test_no_listings_is_not_an_error(self, A):
        assert A.bad_sites({}) == [] and A.bad_sites({"listings": None}) == []


class TestSummarize:
    def test_counts_products_per_country(self, A):
        nodes = [
            {"listings": [{"site": {"id": 3}, "problems": [{"id": "a"}]}]},
            {"listings": [{"site": {"id": 3}, "problems": [{"id": "b"}]},
                          {"site": {"id": 2}, "problems": [{"id": "c"}]}]},
        ]
        got = A.summarize(nodes)
        assert got["UK"] == 2 and got["CA"] == 1

    def test_two_problems_on_one_site_count_as_one_product(self, A):
        """数えるのは **商品数**。1商品に2つ問題があっても1件。"""
        nodes = [{"listings": [{"site": {"id": 3},
                                "problems": [{"id": "a"}, {"id": "b"}]}]}]
        assert A.summarize(nodes)["UK"] == 1


class TestSafety:
    def test_action_field_is_not_requested(self):
        """★eBaymag 側が 500 を返す項目。取ると全件が落ちる (2026-09-06 実測)。"""
        assert "problems { id severity text field context }" in _API
        assert "context action }" not in _API

    def test_failures_are_not_turned_into_zero(self):
        """数えられなかった時に 0件 として返さない。"""
        i = _API.index("def call(")
        body = _API[i:_API.index("\ndef ", i + 10)]
        assert "raise SystemExit" in body
        assert "ログインが切れています" in body

    def test_csrf_token_is_fetched_as_html(self):
        """★JSON の Accept のまま GET すると meta が無い応答が返る (誤診の元)。"""
        i = _API.index("def csrf_token(")
        body = _API[i:_API.index("\ndef ", i + 10)]
        assert "text/html" in body

    def test_cookies_are_kept_outside_the_repo(self):
        """cookie は鍵と同じ扱い。リポジトリに置かない。"""
        assert "iMak_data" in _DUMP and "COOKIE_FILE" in _DUMP
        assert "credentials" in _DUMP

    def test_session_cookies_get_an_expiry(self):
        """★セッション限りのまま戻すと閉じた瞬間に消える (毎回ログインの原因)。"""
        i = _DUMP.index("def load_cookies(")
        body = _DUMP[i:_DUMP.index("\n\n\n", i)]
        assert 'd["expires"]' in body
