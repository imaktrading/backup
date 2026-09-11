# -*- coding: utf-8 -*-
"""UT 探索が「UT ではない物」を拾わない / 叩き済みを叩き直さない (2026-09-11).

1. 公式は無地の手袋・ストール・アートブックも category "ut graphic tees" に置いている
   (class "accessories" / subcategory "others")。探索で拾った 602件のうち 194件がこれだった。
   → **class が tops の物だけ** UT とする。
2. 隣の番号を歩く時、叩き済みで UT でなかった番号を「塊の中」扱いにしていたため、
   再実行のたびに 6つ先まで叩き直していた。→ 叩き済みは空振りとして数える。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scrapers"))

import uniqlo_ut_discover as D  # noqa: E402


def _detail_json(cls: str, gender: str = "MEN") -> str:
    return json.dumps({"result": {
        "name": "x", "genderName": gender,
        "breadcrumbs": {"class": {"name": cls}, "category": {"name": "ut graphic tees"},
                        "subcategory": {"name": "others"}}}})


def test_accessories_under_ut_category_are_not_ut(monkeypatch):
    monkeypatch.setattr(D, "_get", lambda *a, **k: _detail_json("accessories"))
    monkeypatch.setattr(D._raw_store, "save", lambda *a, **k: None)
    D._DETAIL_CACHE.clear()
    assert D.detail("E409202-000") is None, "ファンクショングローブ を UT として拾った"


def test_tops_under_ut_category_are_ut(monkeypatch):
    monkeypatch.setattr(D, "_get", lambda *a, **k: _detail_json("tops"))
    monkeypatch.setattr(D._raw_store, "save", lambda *a, **k: None)
    D._DETAIL_CACHE.clear()
    assert D.detail("E485254-000") is not None


def test_neighbors_do_not_reprobe_known_misses(monkeypatch):
    """起点の前後6つずつが叩き済み (空振り) なら、公式を1回も叩かない."""
    calls = []
    monkeypatch.setattr(D, "detail", lambda pid: calls.append(pid))
    monkeypatch.setattr(D, "save_state", lambda st: None)
    monkeypatch.setattr(D.time, "sleep", lambda s: None)
    seed = 481118
    probed = [f"E{seed + d:06d}-000" for d in range(-D.WALK_MISS, D.WALK_MISS + 1) if d]
    st = {"probed": probed}
    D.from_neighbors({f"E{seed}-000"}, {f"E{seed}-000"}, st, lambda *a: None)
    assert calls == [], f"叩き済みを叩き直した: {calls}"
