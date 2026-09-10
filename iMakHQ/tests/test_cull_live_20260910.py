# -*- coding: utf-8 -*-
"""取下げ候補を出品一覧から毎晩作る (2026-09-10 ユーザー「数日 青にならない」).

## なぜ
取下げの候補は funnel (Seller Hub レポート) からしか作られず、レポートは人が手で置く。
夜の処理は毎晩 funnel を回していたが、レポートが4日古いと中断するので
9/9・9/10 は止まり、候補は 9/8 のまま増えなかった。

出品一覧 API で CULL の材料は全部取れる。判定は listing_funnel.classify をそのまま使う。
表示回数が要る行 (PSA10 / 一番くじ) は funnel に値がある時だけ判定し、無ければ候補にしない。
"""
from __future__ import annotations

import io
import os
import sys
import time

import pytest

_HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_HQ, "tools"))


@pytest.fixture(scope="module")
def L():
    import cull_live
    return cull_live


@pytest.fixture(scope="module")
def A():
    import itemid_writeback_audit
    return itemid_writeback_audit


def _row(iid, title, site="US", qty=0, sold=0, watch=0, age=30):
    return {"item_id": iid, "title": title, "site": site, "category": "", "price": 100.0,
            "qty": qty, "sold_qty": sold, "sales90": 0, "watch": watch,
            "impr": 0.0, "impr_total": 0.0, "trend_price": 0.0, "age_days": age}


GSHOCK = "CASIO G-Shock GA-2100 Mens Watch"
PSA = "PSA 10 Pokemon Japanese Promo #269/S-P Leafeon VSTAR 2022"


class TestSiteFromUrl:
    def test_us_and_mirrors(self, A):
        assert A.site_from_url("https://www.ebay.com/itm/1") == "US"
        assert A.site_from_url("https://www.ebay.co.uk/itm/1") == "UK"
        assert A.site_from_url("https://www.ebay.com.au/itm/1") == "AU"
        assert A.site_from_url("https://www.ebay.ca/itm/1") == "CA"
        assert A.site_from_url("https://www.ebay.de/itm/1") == "DE"

    def test_unknown_is_not_us(self, A):
        """判らないドメインを US と言わない (ミラーを落とさない)。"""
        assert A.site_from_url("https://www.ebay.fr/itm/1") == ""
        assert A.site_from_url("") == ""
        assert A.site_from_url(None) == ""


class TestRowsFromLive:
    def test_old_cache_without_sold_is_skipped(self, L):
        """売れた数を持たない旧キャッシュから「売れていない」を作らない。"""
        assert L.rows_from_live({"1": {"avail": 0, "title": "x"}}) == []

    def test_fields(self, L):
        import datetime
        today = datetime.datetime(2026, 9, 10)
        rows = L.rows_from_live({"9": {"avail": 0, "sold": 2, "watch": 1, "site": "US",
                                       "usd": 50.0, "title": "A &amp; B",
                                       "start_time": "2026-09-01T00:00:00.000Z"}}, today)
        r = rows[0]
        assert (r["qty"], r["sold_qty"], r["watch"], r["age_days"]) == (0, 2, 1, 9)
        assert r["title"] == "A & B"

    def test_unreadable_start_is_age_zero(self, L):
        """出品日が読めない = 0 (= 不明。cull_end が対象外にする)。"""
        rows = L.rows_from_live({"9": {"avail": 0, "sold": 0, "watch": 0, "start_time": ""}})
        assert rows[0]["age_days"] == 0


class TestBuildCull:
    def test_no_owner_out_of_stock_is_cull_even_with_watchers(self, L):
        """戻す担当がいない在庫切れは需要に関わらず畳む (2026-08-25 ユーザー確定)。"""
        cull, _ = L.build_cull([_row("1", GSHOCK, watch=4)], [])
        assert [r["item_id"] for r in cull] == ["1"]
        assert "CULL" in cull[0]["flags"]

    def test_in_stock_is_never_cull(self, L):
        cull, _ = L.build_cull([_row("1", GSHOCK, qty=1)], [])
        assert cull == []

    def test_mirror_is_never_cull(self, L):
        cull, _ = L.build_cull([_row("1", GSHOCK, site="UK"), _row("2", GSHOCK + " x", site="")], [])
        assert cull == []

    def test_psa_without_funnel_impressions_is_held(self, L):
        """★本丸。表示回数が判らない PSA を「需要ゼロ」と決めて落とさない。"""
        cull, info = L.build_cull([_row("1", PSA)], [])
        assert cull == [] and info["held"] == 1

    def test_psa_with_zero_demand_in_funnel_is_cull(self, L):
        cull, info = L.build_cull([_row("1", PSA)],
                                  [{"item_id": "1", "impr": "0", "impr_total": "0", "sales90": "0"}])
        assert [r["item_id"] for r in cull] == ["1"] and info["held"] == 0

    def test_psa_with_organic_impressions_is_not_cull(self, L):
        cull, _ = L.build_cull([_row("1", PSA)],
                               [{"item_id": "1", "impr": "2", "impr_total": "5", "sales90": "0"}])
        assert cull == []

    def test_psa_with_watcher_is_not_cull(self, L):
        cull, _ = L.build_cull([_row("1", PSA, watch=1)],
                               [{"item_id": "1", "impr": "0", "impr_total": "0", "sales90": "0"}])
        assert cull == []

    def test_mirror_demand_saves_the_us_parent(self, L):
        """ミラーで付いたウォッチは本物の需要 (listing_funnel.absorb_mirror_demand と同じ)。"""
        rows = [_row("1", PSA), _row("2", PSA, site="UK", watch=1)]
        cull, _ = L.build_cull(rows, [{"item_id": "1", "impr": "0", "impr_total": "0"}])
        assert cull == []


class TestCullEndReadsNewest:
    def test_newer_live_file_wins(self, tmp_path):
        import cull_end as CE
        f = tmp_path / "funnel_20260908.csv"
        f.write_text("item_id,flags\n", encoding="utf-8")
        time.sleep(0.05)
        c = tmp_path / "cull_live_20260910.csv"
        c.write_text("item_id,flags\n", encoding="utf-8")
        os.utime(f, (time.time() - 100, time.time() - 100))
        assert os.path.basename(CE.latest_source(str(tmp_path))) == "cull_live_20260910.csv"

    def test_newer_funnel_wins(self, tmp_path):
        import cull_end as CE
        c = tmp_path / "cull_live_20260910.csv"
        c.write_text("item_id,flags\n", encoding="utf-8")
        os.utime(c, (time.time() - 100, time.time() - 100))
        f = tmp_path / "funnel_20260911.csv"
        f.write_text("item_id,flags\n", encoding="utf-8")
        assert os.path.basename(CE.latest_source(str(tmp_path))) == "funnel_20260911.csv"

    def test_nothing(self, tmp_path):
        import cull_end as CE
        assert CE.latest_source(str(tmp_path)) is None


class TestNightly:
    def test_nightly_batch_builds_it_after_the_funnel(self):
        bat = io.open(os.path.join(_HQ, "tools", "run_hoju_search.bat"), encoding="ascii").read()
        assert "cull_live.py" in bat
        assert bat.index("listing_funnel.py") < bat.index("cull_live.py")
