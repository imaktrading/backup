# -*- coding: utf-8 -*-
"""補URL探索で、消えている出品 (API が 404 = None) に Chrome を開かない (2026-10-03)。

消えている物は「買えない」と分かっている。Chrome で詳細を開くのは API の通信が失敗した時だけ。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import mercari_psa_resource as m  # noqa: E402


class _Api:
    def __init__(self, raise_):
        self.raise_ = raise_

    def item(self, _id):
        return ("item", self.raise_)

    def product(self, _id):
        return ("product", self.raise_)


def _src(raise_, kind):
    s = m._ApiSource.__new__(m._ApiSource)
    s.api = _Api(raise_)
    s.fallen = False
    s.kind = {"https://jp.mercari.com/item/m1": kind,
              "https://jp.mercari.com/shops/product/abc": kind}

    def _run(coro):
        if coro[1]:
            raise RuntimeError("通信失敗")
        return None                                    # 404 = 消えている
    s._run = _run
    opened = []

    class _Chrome:
        def driver(self):
            opened.append(1)
            return None
    s.chrome = _Chrome()
    return s, opened


def _patch(monkeypatch, remembered):
    monkeypatch.setattr(m.time, "sleep", lambda *_: None)
    monkeypatch.setattr(m, "remember_not_buyable", lambda u, why: remembered.append(u))
    monkeypatch.setattr(m, "_detail_supply_check", lambda drv, href, min_reviews=100: (True, "", 0))


def test_gone_item_and_shops_do_not_open_chrome(monkeypatch):
    rem = []
    _patch(monkeypatch, rem)
    for kind, url in (("item", "https://jp.mercari.com/item/m1"),
                      ("shops", "https://jp.mercari.com/shops/product/abc")):
        s, opened = _src(False, kind)
        assert s.supply_filter([(1000, url)]) == []
        assert opened == []
    assert len(rem) == 2


def test_api_failure_still_uses_chrome(monkeypatch):
    rem = []
    _patch(monkeypatch, rem)
    s, opened = _src(True, "item")
    assert s.supply_filter([(1000, "https://jp.mercari.com/item/m1")]) == [(1000, "https://jp.mercari.com/item/m1")]
    assert opened == [1]
    assert rem == []
