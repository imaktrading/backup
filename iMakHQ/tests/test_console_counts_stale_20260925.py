# -*- coding: utf-8 -*-
"""数え直しが打ち切られて昨日の件数が出たままだった (2026-09-25)。

ユーザー「11件と出ていたので実行したけど、目視HTMLが出てこない」「数えなおし後の11件やで」。
counts.py が 240秒で打ち切られ続け、console_counts.json は 9/24 17:32 のまま (入れ替え 11件・実際 0件)。
"""
import os
import re

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_counts_timeout_has_room():
    src = open(os.path.join(HQ, "console", "server.py"), encoding="utf-8").read()
    i = src.index("def refresh_counts")
    t = int(re.search(r"timeout=(\d+)", src[i:i + 2000]).group(1))
    assert t >= 480


def test_stale_counts_are_shown_loudly():
    js = open(os.path.join(HQ, "console", "static", "app.js"), encoding="utf-8").read()
    html = open(os.path.join(HQ, "console", "static", "index.html"), encoding="utf-8").read()
    assert 'id="counts-alert"' in html
    assert "counts-alert" in js and "件数が古い" in js


def test_catalog_variants_are_memoized():
    import sys
    sys.path.insert(0, os.path.join(HQ, "tools"))
    import mercari_psa_resource as mp
    calls = []
    orig = mp._catalog_variants_for_cardno
    mp._catalog_variants_for_cardno = lambda *a, **k: calls.append(a) or [{"product_id": "X"}]
    mp._VARIANTS_CACHE.clear()
    try:
        a = mp.catalog_variants_for_cardno("ZZ9-999", category="t")
        a[0]["product_id"] = "changed"                       # 呼び出し側が書き換えても
        b = mp.catalog_variants_for_cardno("ZZ9-999", category="t")
        assert len(calls) == 1 and b[0]["product_id"] == "X"  # 覚えた値は変わらない
    finally:
        mp._catalog_variants_for_cardno = orig
        mp._VARIANTS_CACHE.clear()
