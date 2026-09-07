# -*- coding: utf-8 -*-
"""C:Set のズレ直しが 旧 AuthToken のままで死んでいた (2026-09-07)。

旧 Auth'n'Auth の AuthToken は 2026-09-06 に hard expire した。同日に
`ebay_getitem_images` は OAuth (X-EBAY-API-IAF-TOKEN) へ寄せたが、**この道具は漏れていた**。
GetItem が毎回 `Auth token is hard expired` で空を返すので、
「出品中で C:Set がカタログと違う行」を **1件も見つけられない** 状態だった
(エラーは cache に焼かれるだけで、件数は 0 と出る)。

鍵の持ち方を2か所に分けたのが原因なので、口を1つにして再発を止める。
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakHQ", "tools")))
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakeBayAPI")))

import live_set_revise as L      # noqa: E402


def test_getitem_uses_the_oauth_header_helper():
    src = inspect.getsource(L.fetch_live)
    assert "_oauth_headers(" in src
    assert "eBayAuthToken" not in src, "旧 AuthToken を本文に入れない (18ヶ月で切れて更新の口が無い)"


def test_auth_failure_raises_instead_of_returning_empty():
    """認証で落ちたら例外。空で返すと「ズレ0件」と嘘の結論になる。"""
    src = inspect.getsource(L.fetch_live)
    assert "_check_auth(" in src


def test_headers_come_from_one_place():
    """ヘッダは ebay_getitem_images の口を借りる (鍵を2か所に分けない)。"""
    src = inspect.getsource(L._oauth_headers)
    assert "ebay_getitem_images" in src and "_headers(" in src


def test_check_auth_delegates_to_the_same_judgement():
    src = inspect.getsource(L._check_auth)
    assert "ebay_getitem_images" in src
