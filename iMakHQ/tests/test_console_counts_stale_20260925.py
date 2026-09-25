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


def test_every_badge_recounts_only_its_part():
    """押した後は、そのボタンの項目だけ数え直す (全部だと約3分)。ユーザー「短縮できることはやろう」。"""
    import sys
    sys.path.insert(0, os.path.join(HQ, "console"))
    sys.path.insert(0, HQ)
    import server
    import control_panel as cp
    for s in cp.SCRIPTS:
        b = s.get("badge")
        if b:
            assert server.count_keys_for(b) is not None, b      # 全ボタンに割り当てがある
    assert server.count_keys_for("hoju_swap") == ["hoju"]
    assert server.count_keys_for(None) is None                   # バッジの無いボタンは全部数え直す


def test_catalog_index_matches_sql():
    """番号の目次で引いても、SQL (大文字小文字を区別しない完全一致 or 前方一致) と同じ行になる。"""
    import sys
    sys.path.insert(0, os.path.join(HQ, "tools"))
    import mercari_psa_resource as mp
    idx = {"pids": sorted([("OP11-021", 1, "op"), ("OP11-021_P", 2, "op"), ("OP11-0219", 3, "op"),
                           ("OP11-02", 4, "op"), ("ST01-005", 5, "op")])}
    idx["keys"] = [p[0] for p in idx["pids"]]
    # LIKE 'OP11-021_%' は後ろに1文字以上 (SQL の _ は任意の1文字なので OP11-0219 も入る = 従来どおり)
    assert sorted(mp._index_lookup(idx, "op11-021")) == [1, 2, 3]
    assert mp._index_lookup(idx, "OP11-021", "other") == []
