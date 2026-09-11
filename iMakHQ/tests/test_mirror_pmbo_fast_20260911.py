# -*- coding: utf-8 -*-
"""Pm/Bo ボタンが遅い (2026-09-11 ユーザー「手でやったらすぐなのに」).

実測で分かった遅さの原因:
- 押すと「数える」で全部取り → OK → 「実行」でまた全部取り直していた
- 一覧の読み方が終了済みの出品まで拾い、185回 失敗していた
- 状態表が1ページ欠けると残りが「付いていない」扱い → 成功済みに 1,454回 送り直した
- サイズ表記が通らないミラーに毎回送って落ちる (206回)
- 1件ずつ直列 (~2.8秒/件)
"""
from __future__ import annotations

import datetime
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, r"C:\dev\iMak\iMakeBayAPI")
import mirror_promo_bestoffer as M  # noqa: E402


def _item(iid, site="UK", status="Active", bo=None):
    b = "" if bo is None else "<BestOfferDetails><BestOfferEnabled>%s</BestOfferEnabled></BestOfferDetails>" % bo
    return ("<Item><ItemID>%s</ItemID><ListingDetails><ViewItemURL>https://www.ebay.com/itm/%s"
            "</ViewItemURL></ListingDetails><SellingStatus><ListingStatus>%s</ListingStatus>"
            "</SellingStatus><Site>%s</Site>%s<Title>t%s</Title></Item>" % (iid, iid, status, site, b, iid))


def _page(items, pages=1):
    return ("<Ack>Success</Ack><PaginationResult><TotalNumberOfPages>%d</TotalNumberOfPages>"
            "</PaginationResult><ItemArray>%s</ItemArray>" % (pages, "".join(items)))


class TestParseSellerList:
    def test_site_comes_from_site_element_not_url(self):
        """GetSellerList の ViewItemURL はミラーでも ebay.com (2026-09-11 実測)."""
        got = M.parse_seller_list(_page([_item("1", "Canada"), _item("2", "Australia"),
                                         _item("3", "UK"), _item("4", "US")]))
        assert [(g["item_id"], g["site"]) for g in got] == [
            ("1", "ca"), ("2", "au"), ("3", "uk"), ("4", "")]

    def test_ended_listing_is_not_returned(self):
        """★終了済みに送って 185回 落ちていた."""
        got = M.parse_seller_list(_page([_item("1", status="Completed"), _item("2")]))
        assert [g["item_id"] for g in got] == ["2"]

    def test_best_offer_flag(self):
        got = M.parse_seller_list(_page([_item("1", bo="true"), _item("2"), _item("3", bo="false")]))
        assert [g["best_offer"] for g in got] == [True, False, False]


class _Fx:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def post(self, call, inner, tok, site="0"):
        import re
        p = int(re.search(r"<PageNumber>(\d+)", inner).group(1))
        self.calls.append(p)
        seq = self.pages[p]
        return seq.pop(0) if isinstance(seq, list) else seq

    def token(self):
        return "tok"

    def refresh(self):
        pass


class TestFetchListings:
    def test_failed_page_is_retried(self, monkeypatch):
        monkeypatch.setattr(M.time, "sleep", lambda s: None)
        fx = _Fx({1: _page([_item("1")], 2),
                  2: ["<Ack>Failure</Ack>", _page([_item("2")], 2)]})
        items, missing = M.fetch_listings(fx, M.TradingToken(fx))
        assert [i["item_id"] for i in items] == ["1", "2"] and missing == []

    def test_page_that_never_comes_is_reported_and_its_items_are_not_sent(self, monkeypatch):
        """★本丸。欠けたページの出品を「付いていない」と見なして送り直さない."""
        monkeypatch.setattr(M.time, "sleep", lambda s: None)
        fx = _Fx({1: _page([_item("1")], 2), 2: "<Ack>Failure</Ack>"})
        items, missing = M.fetch_listings(fx, M.TradingToken(fx))
        assert [i["item_id"] for i in items] == ["1"] and missing == [2]
        todo = M.plan(items, advertised=set())
        assert todo["uk"]["bo"] == ["1"]

    def test_first_page_missing_stops(self, monkeypatch):
        import pytest
        monkeypatch.setattr(M.time, "sleep", lambda s: None)
        fx = _Fx({1: "<Ack>Failure</Ack>"})
        with pytest.raises(RuntimeError):
            M.fetch_listings(fx, M.TradingToken(fx))


class TestRecentlyFailedForGood:
    NOW = datetime.datetime(2026, 9, 11, 12, 0)

    def _ln(self, iid, res, days_ago):
        ts = (self.NOW - datetime.timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S")
        return json.dumps({"ts": ts, "site": "uk", "item_id": iid, "result": res})

    def test_size_error_is_skipped_for_a_week(self):
        lines = [self._ln("1", 'NG: "XS,S,M" is not a valid value for Size.', 2),
                 self._ln("2", 'NG: "XS,S,M" is not a valid value for Size.', 8)]
        assert M.recently_failed_for_good(lines, self.NOW) == {"1"}

    def test_last_result_wins(self):
        """直って OK になった物は送る対象に戻る."""
        lines = [self._ln("1", 'NG: "X" is not a valid value for Size.', 3), self._ln("1", "OK", 1)]
        assert M.recently_failed_for_good(lines, self.NOW) == set()

    def test_transient_errors_are_not_skipped(self):
        lines = [self._ln("1", "NG: System error. Unable to process your request.", 1)]
        assert M.recently_failed_for_good(lines, self.NOW) == set()

    def test_broken_lines_are_ignored(self):
        assert M.recently_failed_for_good(["{", "", "null"], self.NOW) == set()


class TestSendBestOffers:
    def test_runs_in_parallel(self, tmp_path, monkeypatch):
        monkeypatch.setattr(M, "PROGRESS_LOG", str(tmp_path / "p.jsonl"))
        peak, cur, lock = [0], [0], threading.Lock()

        def send(_fx, tok, key, i):
            with lock:
                cur[0] += 1
                peak[0] = max(peak[0], cur[0])
            time.sleep(0.05)
            with lock:
                cur[0] -= 1
            return "OK"
        fx = _Fx({})
        ok_by, ng, _na = M.send_best_offers(fx, M.TradingToken(fx),
                                            [("uk", str(n)) for n in range(8)], workers=4, send=send)
        assert ok_by == {"uk": 8} and ng == 0 and peak[0] > 1

    def test_one_exception_does_not_stop_the_rest(self, tmp_path, monkeypatch):
        monkeypatch.setattr(M, "PROGRESS_LOG", str(tmp_path / "p.jsonl"))

        def send(_fx, tok, key, i):
            if i == "2":
                raise TimeoutError("read timed out")
            return "OK"
        fx = _Fx({})
        ok_by, ng, _na = M.send_best_offers(fx, M.TradingToken(fx),
                                            [("uk", "1"), ("uk", "2"), ("ca", "3")], workers=2, send=send)
        assert ok_by == {"uk": 1, "ca": 1} and ng == 1
        logged = [json.loads(ln) for ln in open(tmp_path / "p.jsonl", encoding="utf-8")]
        assert len(logged) == 3, "1件ごとの記録が抜けている"

    def test_unavailable_category_is_not_a_failure_and_not_a_success(self, tmp_path, monkeypatch):
        monkeypatch.setattr(M, "PROGRESS_LOG", str(tmp_path / "p.jsonl"))
        fx = _Fx({})
        ok_by, ng, na = M.send_best_offers(fx, M.TradingToken(fx), [("ca", "1")], workers=1,
                                           send=lambda *a: M.BO_UNAVAILABLE)
        assert ok_by == {} and ng == 0 and na == 1


class TestAdAlreadyExists:
    def test_already_exists_is_not_a_failure(self, monkeypatch):
        """RUNNING 以外のキャンペーンの広告は見えず、毎回「既にある」で落ちていた (6件)."""
        class R:
            status_code = 207

            def json(self):
                return {"responses": [
                    {"listingId": "1", "statusCode": 201},
                    {"listingId": "2", "statusCode": 400,
                     "errors": [{"message": "An ad for listing ID 2 already exists."}]},
                    {"listingId": "3", "statusCode": 400, "errors": [{"message": "boom"}]}]}
        monkeypatch.setattr(M.requests, "post", lambda *a, **k: R())
        got = dict(M.add_ads("t", "uk", ["1", "2", "3"]))
        assert got["1"] == "OK" and got["2"] == M.AD_EXISTS and got["3"].startswith("NG")


class TestFetchPagesInParallel:
    def test_all_pages_in_order(self, monkeypatch):
        monkeypatch.setattr(M.time, "sleep", lambda s: None)
        fx = _Fx({p: _page([_item(str(p))], 6) for p in range(1, 7)})
        items, missing = M.fetch_listings(fx, M.TradingToken(fx))
        assert [i["item_id"] for i in items] == ["1", "2", "3", "4", "5", "6"] and missing == []


class TestNightly:
    def test_nightly_batch_runs_it_before_the_step_that_can_abort(self):
        """★2026-09-11 ユーザー「夜間自動にしよう」。step 1 は失敗すると :done へ飛ぶので、その前に置く."""
        import io
        bat = io.open(os.path.join(os.path.dirname(__file__), "..", "tools", "run_hoju_search.bat"),
                      encoding="ascii").read()
        i = bat.index("mirror_promo_bestoffer.py --write")
        assert i < bat.index("psa_hoju_fill.py search --limit=30")


class TestWarning20135:
    """★2026-09-11 本丸: eBay は「このカテゴリはベストオファー非対応」を **Warning** で返す。
    Warning を一律 OK にしていたので、付いていない 261件を毎回「成功」と数えて送り直していた
    (1件に6回)。"""

    class Fx:
        def __init__(self, xml):
            self.xml = xml

        def post(self, *a, **k):
            return self.xml

    W = ("<Ack>Warning</Ack><Errors><SeverityCode>Warning</SeverityCode><ErrorCode>21919456"
         "</ErrorCode></Errors><Errors><SeverityCode>Warning</SeverityCode><ErrorCode>20135"
         "</ErrorCode><LongMessage>Best offer feature is unavailable</LongMessage></Errors>")

    def test_20135_is_not_ok(self):
        assert M.enable_best_offer(self.Fx(self.W), "t", "ca", "1") == M.BO_UNAVAILABLE

    def test_other_warnings_are_still_ok(self):
        x = ("<Ack>Warning</Ack><Errors><SeverityCode>Warning</SeverityCode>"
             "<ErrorCode>21919456</ErrorCode></Errors>")
        assert M.enable_best_offer(self.Fx(x), "t", "ca", "1") == "OK"

    def test_unavailable_is_skipped_for_30_days(self):
        now = datetime.datetime(2026, 9, 11, 12, 0)

        def ln(days):
            ts = (now - datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
            return json.dumps({"ts": ts, "item_id": "1", "result": M.BO_UNAVAILABLE})
        assert M.recently_failed_for_good([ln(20)], now) == {"1"}
        assert M.recently_failed_for_good([ln(31)], now) == set()

    def test_token_refresh_happens_once_for_parallel_expiry(self):
        class Fx:
            n = 0

            def token(self):
                return "tok%d" % self.n

            def refresh(self):
                self.n += 1
        t = M.TradingToken(Fx())
        t.force(stale="tok0")
        t.force(stale="tok0")          # 2本目が同じ失効値で来ても取り直さない
        assert t.refreshed == 1 and t.get() == "tok1"
