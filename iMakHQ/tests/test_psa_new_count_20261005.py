"""新規に出せる PSA の枚数 (2026-10-05 ユーザー「今日やることの下に、注文仕入れ待ち0件みたいに」)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import psa_new_count as N  # noqa: E402


def _row(url="u1", iid="", sold="", cert="111", no_go="", cat="TCG", price="¥5,000", key="k1"):
    r = [""] * 35
    r[0], r[1], r[3], r[5], r[8], r[10], r[17], r[34] = url, iid, sold, price, cert, no_go, cat, key
    return r


def test_counts_only_listable_rows():
    rows = [["h"], _row(), _row(cert="222", sold="○"), _row(cert="333", iid="999"),
            _row(cert="444", cat="G-shock"), _row(cert="555", url="taken"), _row(cert="666", price=""),
            _row(cert="777", key="listed")]
    got = N.count_rows(rows, listed_cert=set(), listed_keys={"listed"}, taken_urls={"taken"},
                       already_listed=lambda c, k, cs, ks: "key" if k in ks else "",
                       norm_url=lambda u: u, pick_cost=lambda r: (r[5] or r[12] or r[13]) or None)
    assert got == {"n": 1, "listed": 1, "taken": 1, "sold": 1, "no_go": 0, "nocost": 1}


def test_console_shows_it_in_today_strip():
    here = os.path.join(os.path.dirname(__file__), "..", "console")
    assert '"psa_new": lambda' in open(os.path.join(here, "counts.py"), encoding="utf-8").read()
    assert "新規に出せる PSA" in open(os.path.join(here, "static", "app.js"), encoding="utf-8").read()
