# -*- coding: utf-8 -*-
"""ありえない仕入値の候補は ①探す の段階で外す (2026-09-04)。

## なぜ
ユーザー指示「この段階で、セラーフィルタ含めて仕入れるに値するものにしておくべき」。

実例: 2026-09-04 の ①探す で SNKRDUNK が S12A-126 に **¥1,111,111** を出していた。
そのまま最安として採られると「再仕入れ可」と判定され、cost-plus で $11,707 の行になる
(9/3 に実際に作られ、入稿直前に人が気づいて止めた)。

基準は pricing_engine.cost_sanity の1か所。ここに数字を書かない。
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (os.path.join(_ROOT, "iMakHQ", "tools"), os.path.join(_ROOT, "iMakeBayAPI")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from psa_resource_gate import combine                          # noqa: E402


def _snk(*prices):
    return {"available": True, "psa10_price_jpy": prices[0],
            "psa10_listings": [{"price": p, "url": "https://snkrdunk.com/%d" % i}
                               for i, p in enumerate(prices)]}


def test_absurd_snkrdunk_price_is_not_a_supply():
    """それしか無ければ「再仕入れ可」にしない。"""
    r = combine(None, _snk(1111111))
    assert r["resourceable"] is False
    assert r["cheapest_jpy"] is None
    assert r["snkrdunk_count"] == 0


def test_the_sane_one_survives_when_mixed():
    """異常な出品だけ外す。正常な出品まで巻き添えにしない。"""
    r = combine(None, _snk(1111111, 14800))
    assert r["resourceable"] is True
    assert r["cheapest_jpy"] == 14800
    assert r["snkrdunk_count"] == 1


def test_absurd_mercari_price_is_not_a_supply():
    r = combine((1111111, "https://jp.mercari.com/item/m1", "n"), None)
    assert r["resourceable"] is False
    assert r["mercari_jpy"] is None


def test_normal_prices_are_untouched():
    r = combine((9500, "https://jp.mercari.com/item/m1", "n"), None)
    assert r["resourceable"] is True and r["cheapest_jpy"] == 9500


def test_absurd_price_never_reaches_the_aux_urls():
    """補URL は『最安が売切れた時の代替』。買えない値段を予備に数えない。"""
    cands = [(1111111, "https://jp.mercari.com/item/bad", "n"),
             (9500, "https://jp.mercari.com/item/ok", "n")]
    r = combine(cands[1], None, mercari_cands=cands)
    urls = [a["url"] for a in r["aux_urls"]]
    assert "https://jp.mercari.com/item/bad" not in urls
    assert "https://jp.mercari.com/item/ok" in urls


def test_unknown_price_is_not_judged_here():
    """価格不明はここでは落とさない (別経路で落ちる)。嘘の理由を付けない。"""
    r = combine(None, {"available": True, "psa10_price_jpy": None,
                       "psa10_listings": [{"price": None, "url": "https://snkrdunk.com/z"}]})
    assert r["snkrdunk_count"] == 1
