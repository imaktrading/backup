# -*- coding: utf-8 -*-
"""Trading API を OAuth に寄せる + 認証切れを黙らせない (2026-09-06).

## なぜ
旧 Auth'n'Auth の `AuthToken` は **約18ヶ月で hard expire** し、更新の口が無い
(発行し直すには人が開発者ポータルを触るしかない)。2026-09-06 に実際に切れていた。

まずいのは切れたことより **黙って空を返していた**こと:

    fetch_listing_images(...) → []      (例外にならない)
    fetch_listing_qty(...)    → None

これを使う 取下げ / 補URL目視の画像 / 価格見直し / 一番くじ再仕入れ が、
動いているつもりで何もしない状態になっていた (fail-OPEN)。
実害: 目視用の画像キャッシュに「画像なし(-)」が15件 焼かれ、そのうち **14件は
認証が直ったら普通に取れた** = 嘘の記録だった。

## 直したこと
  - Trading API は OAuth トークンも受け付ける (X-EBAY-API-IAF-TOKEN)。
    OAuth の refresh_token は自分で更新されるので、期限切れが起きない。
    実測 2026-09-06: itemID 358845054366 で IAF=Success / 旧AuthToken=hard expired。
  - 認証エラーは TradingAuthError にして **broad except に飲ませない**。
"""
from __future__ import annotations

import io
import os
import re
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_API = os.path.join(_ROOT, "iMakeBayAPI")
sys.path.insert(0, _API)
_SRC = io.open(os.path.join(_API, "ebay_getitem_images.py"), encoding="utf-8").read()


@pytest.fixture(scope="module")
def G():
    import ebay_getitem_images
    return ebay_getitem_images


class TestAuthErrorIsLoud:
    def test_expired_token_raises(self, G):
        bad = ("<Ack>Failure</Ack><Errors><ShortMessage>"
               "Auth token is hard expired.</ShortMessage></Errors>")
        with pytest.raises(G.TradingAuthError):
            G._check_auth(bad)

    def test_success_passes_through(self, G):
        G._check_auth("<Ack>Success</Ack><Title>x</Title>")   # 例外にならない

    def test_empty_response_is_not_an_auth_error(self, G):
        """通信失敗と認証切れを混ぜない (通信はリトライで拾う)。"""
        G._check_auth("")
        G._check_auth(None)

    def test_other_failures_are_not_auth_errors(self, G):
        """在庫が無い等の普通の Failure まで止めない。"""
        G._check_auth("<Ack>Failure</Ack><ShortMessage>Item cannot be accessed.</ShortMessage>")


class TestNoSilentEmpty:
    def test_auth_error_escapes_the_broad_except(self):
        """★ここが本丸。except Exception に飲まれると誰も気づかない。"""
        n = _SRC.count("except TradingAuthError:")
        assert n >= 5, "認証切れを外へ出していない関数がある (%d箇所しかない)" % n
        # 素の except Exception より前に置かれていること
        for m in re.finditer(r"except Exception:\n\s+return (\[\]|None)", _SRC):
            head = _SRC[max(0, m.start() - 120):m.start()]
            assert "except TradingAuthError:" in head, \
                "TradingAuthError を先に拾っていない箇所がある"

    def test_every_call_checks_the_response(self):
        """応答を使う前に必ず認証を見る。"""
        assert _SRC.count("_check_auth(") >= 7      # 定義1 + 呼び出し6


class TestOauthOnly:
    def test_legacy_token_is_not_sent_anymore(self):
        """旧 AuthToken を本文に入れない (18ヶ月で死ぬ方に戻さない)。"""
        assert "<eBayAuthToken>" not in _SRC
        assert "X-EBAY-API-IAF-TOKEN" in _SRC

    def test_headers_are_built_in_one_place(self):
        """6か所で組んでいたのを1本にした。片方だけ直す事故を防ぐ。"""
        assert _SRC.count("def _headers(") == 1
        assert _SRC.count("hdr = _headers()") >= 6
        assert "X-EBAY-API-APP-NAME" not in _SRC

    def test_token_is_cached_until_it_nearly_expires(self, G):
        """毎回 refresh を叩かない (2時間ぶんは使い回す)。"""
        i = _SRC.index("def _access_token(")
        body = _SRC[i:_SRC.index("\ndef ", i + 10)]
        assert '_TOK["until"]' in body and "expires_in" in body
