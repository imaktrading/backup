# -*- coding: utf-8 -*-
"""重複チェック直前の live cache は **年齢に関係なく取り直す** (2026-09-11 実害)。

6時間以内なら「最新」とみなしていたため、キャッシュを作った後の出品を知らないまま
「最新」と表示していた。実害: 19:53 の走行が 20:06 に出品した SB02-001 (820113987395) を、
20:13 の走行の重複チェック (1,026件のキャッシュ) が見逃した → eBay が重複で拒否 →
1件目で止まる設計なので **同じ走行の他10件も出品されなかった**。
年齢はキャッシュの新しさを保証しない。間に出品があれば中身は古い。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))
import dup_guard as D     # noqa: E402


def _setup(monkeypatch, fetched):
    calls = {"fetch": 0, "save": 0}
    monkeypatch.setattr(D, "cache_age_hours", lambda *a, **k: 0.1)      # 6分前 = 「新しい」
    monkeypatch.setattr(D, "_load_live_cache", lambda: {"old": "cached"})
    monkeypatch.setattr(D, "_load_live_skus", lambda: {})

    def _fetch():
        calls["fetch"] += 1
        return fetched

    monkeypatch.setattr(D, "_ebay_active_titles", _fetch)
    monkeypatch.setattr(D, "_save_live_cache", lambda *a, **k: calls.__setitem__("save", calls["save"] + 1))
    return calls


def test_既定は今までどおり年齢で省く(monkeypatch):
    calls = _setup(monkeypatch, ({"820113987395": "t"}, {}))
    titles, _s, ok = D.ensure_fresh_live_cache()
    assert ok and titles == {"old": "cached"} and calls["fetch"] == 0


def test_forceなら新しくても取り直す(monkeypatch):
    calls = _setup(monkeypatch, ({"820113987395": "t"}, {}))
    titles, _s, ok = D.ensure_fresh_live_cache(force=True)
    assert ok and "820113987395" in titles
    assert calls["fetch"] == 1 and calls["save"] == 1


def test_取り直せなければ失敗を返す(monkeypatch):
    """取れなかったのに「最新」と言わない。パネルは非ゼロを見て警告を出す。"""
    _setup(monkeypatch, (None, None))
    _t, _s, ok = D.ensure_fresh_live_cache(force=True)
    assert ok is False


def test_重複チェック直前の手順はforceで呼ぶ():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "tools", "dup_guard.py"), encoding="utf-8").read()
    blk = src[src.index('if "--refresh-cache" in args:'):]
    blk = blk[:blk.index('if "--audit" in args:')]
    assert "ensure_fresh_live_cache(force=True)" in blk
