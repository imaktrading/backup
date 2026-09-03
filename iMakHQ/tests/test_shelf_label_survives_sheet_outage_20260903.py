# -*- coding: utf-8 -*-
"""ボタンの件数ラベルが Google の不調で消えない (2026-09-03)。

## 実害
ラベルを出すのに毎回 商品管理シートを読んでいて、Google が 500/503 を返すたび
「対象なし」になっていた (実測 2026-09-03 に2回連続)。**押せるのに押さなくていいと
読める**表示になるのが困る。

カテゴリは日に何度も変わる値ではないので、取れた分をローカルに控えて使う。
"""
import io
import json
import os
import sys

_HQ_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _HQ_TOOLS not in sys.path:
    sys.path.insert(0, _HQ_TOOLS)

import shelf_evict as SE  # noqa: E402


def test_cache_round_trip(tmp_path, monkeypatch):
    p = tmp_path / "cat.json"
    monkeypatch.setattr(SE, "CATEGORY_CACHE", str(p))
    SE._category_cache_save({"111": "TCG", "222": "G-shock"})
    assert SE._category_cache_load() == {"111": "TCG", "222": "G-shock"}


def test_missing_cache_is_empty_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(SE, "CATEGORY_CACHE", str(tmp_path / "nope.json"))
    assert SE._category_cache_load() == {}


def test_broken_cache_is_empty_not_an_error(tmp_path, monkeypatch):
    p = tmp_path / "cat.json"
    with io.open(p, "w", encoding="utf-8") as f:
        f.write("{ これは JSON ではない")
    monkeypatch.setattr(SE, "CATEGORY_CACHE", str(p))
    assert SE._category_cache_load() == {}


def test_label_does_not_read_the_restock_sheet():
    """ラベル計算でスプシの RESTOCK確定 を読まない (503 で落ちるため)。

    守り (再仕入れ予定を落とさない) は押した時に効かせる。
    """
    src = open(os.path.join(_HQ_TOOLS, "shelf_evict.py"), encoding="utf-8").read()
    i = src.index("def count_workload(")
    seg = src[i:]
    assert "restock_pending_ids()" not in seg.split("def ", 2)[0] + seg[:4000].split("\ndef ")[0]
