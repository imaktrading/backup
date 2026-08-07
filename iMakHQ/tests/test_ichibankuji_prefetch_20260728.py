"""一番くじ 候補先読みキャッシュの回帰テスト (2026-07-28).

「目視は自分のタイミングでやりたいが、候補は定期的に作っておいてほしい」(ユーザー要望)。
検索と目視が1関数に繋がっていたのを分離した。壊れやすい点を固定する:
  1. 先読み(prefetch)が目視UIを開いたり書込をしたりしない
  2. キャッシュが新しい対象は再検索しない (= ボタンが即表示になる根拠)
  3. 鮮度判定が fail-closed (日付欠落/不正/未来日は「古い」扱い)
"""
import datetime
import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import ichibankuji_restock as I  # noqa: E402


def _d(days):
    return (datetime.date.today() - datetime.timedelta(days=days)).isoformat()


def test_cache_freshness_window():
    today = datetime.date.today().isoformat()
    assert I._identify_cache_fresh({"date": today}, today) is True
    assert I._identify_cache_fresh({"date": _d(I.IDENTIFY_CACHE_DAYS)}, today) is True
    assert I._identify_cache_fresh({"date": _d(I.IDENTIFY_CACHE_DAYS + 1)}, today) is False


def test_cache_freshness_is_fail_closed():
    today = datetime.date.today().isoformat()
    assert I._identify_cache_fresh({}, today) is False
    assert I._identify_cache_fresh({"date": ""}, today) is False
    assert I._identify_cache_fresh({"date": "not-a-date"}, today) is False
    assert I._identify_cache_fresh(None, today) is False
    future = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    assert I._identify_cache_fresh({"date": future}, today) is False


def test_prefetch_does_not_open_ui_or_write():
    """先読みは無人。目視UI(serve_and_collect)もスプシ書込も呼ばない。"""
    src = inspect.getsource(I.pass_prefetch)
    for ng in ("serve_and_collect", "update_cell", "batch_update", "pass_expand", "pass_write"):
        assert ng not in src


def test_identify_reuses_cache_without_driver(monkeypatch, tmp_path):
    """全件キャッシュ済なら driver を起こさない (= 待たされない / BAN リスクも増やさない)。"""
    cache_file = tmp_path / "c.json"
    monkeypatch.setattr(I, "IDENTIFY_CACHE", str(cache_file))
    today = datetime.date.today().isoformat()
    I._identify_cache_save({"111": {"row": 5, "item_id": "111", "title": "t", "prize": "A賞",
                                    "ref_image": "img", "candidates": [{"url": "u", "price": 1}],
                                    "date": today}})

    def _boom():
        raise AssertionError("キャッシュがあるのに driver を起動した")

    monkeypatch.setattr(I, "_make_driver", _boom)
    items = I._identify_scrape([{"row": 5, "item_id": "111", "title": "t"}], cand_n=10)
    assert len(items) == 1
    assert items[0]["candidates"] == [{"url": "u", "price": 1}]
    assert "date" not in items[0]      # UI に渡す形は従来どおり (date は混ぜない)


def test_stale_cache_triggers_research(monkeypatch, tmp_path):
    cache_file = tmp_path / "c.json"
    monkeypatch.setattr(I, "IDENTIFY_CACHE", str(cache_file))
    I._identify_cache_save({"111": {"row": 5, "item_id": "111", "title": "t", "prize": "",
                                    "ref_image": "", "candidates": [], "date": _d(30)}})
    called = {"n": 0}

    class _Drv:
        def set_page_load_timeout(self, *_a):
            pass

        def quit(self):
            pass

    def _mk():
        called["n"] += 1
        return _Drv()

    monkeypatch.setattr(I, "_make_driver", _mk)
    monkeypatch.setattr(I, "fetch_listing_images", lambda *_a: ["ref"])
    monkeypatch.setattr(I, "_ebay_title", lambda *_a: "eBay title")
    monkeypatch.setattr(I, "build_keyword", lambda *_a: ("kw", "A賞"))
    monkeypatch.setattr(I, "kw_search", lambda *_a: [{"href": "u2", "price": 2, "image": "i"}])

    items = I._identify_scrape([{"row": 5, "item_id": "111", "title": "t"}], cand_n=10)
    assert called["n"] == 1
    assert items[0]["candidates"][0]["url"] == "u2"
