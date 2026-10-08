# -*- coding: utf-8 -*-
"""メルカリの購入履歴は Edge の拡張から受け取る (2026-10-09 ユーザー「.bat でログインし直すのはアナログ過ぎ」)。"""
import datetime as dt
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import mercari_purchases as MP

PAGE = ('<a href="/transaction/m111"><span>PSA10 ピカチュウ</span><span>2026/10/08 21:05</span></a>'
        '<a href="/transaction/m222"><span>PSA10 ミュウ</span><span>2026/10/07 10:00</span></a>')
NOW = dt.datetime(2026, 10, 9, 8, 0, 0)


def test_save_and_load(tmp_path):
    p = str(tmp_path / "c.json")
    r = MP.save_from_extension({"html": PAGE}, now=NOW, path=p)
    assert r["n"] == 2 and not r["login_required"]
    at, login, items = MP.load_cache(p)
    assert at == NOW and not login and items[0]["id"] == "m111"
    assert items[0]["at"] == dt.datetime(2026, 10, 8, 21, 5)


def test_cache_state():
    assert MP.cache_state(None, False, NOW) == "stale"
    assert MP.cache_state(NOW - dt.timedelta(minutes=10), False, NOW) == "use"
    assert MP.cache_state(NOW - dt.timedelta(hours=2), False, NOW) == "stale"
    assert MP.cache_state(NOW, True, NOW) == "login"
    assert MP.cache_state(NOW - dt.timedelta(minutes=1), False, NOW, since=NOW) == "stale"   # 頼む前の控え


def _fake(monkeypatch, tmp_path, body_after_open):
    p = str(tmp_path / "c.json")
    monkeypatch.setattr(MP, "CACHE", p)
    opened = []

    def opener(url):
        opened.append(url)
        if body_after_open is not None:
            MP.save_from_extension(body_after_open, now=NOW)
    return opened, opener


def test_fetch_opens_edge_and_uses_reply(monkeypatch, tmp_path):
    opened, opener = _fake(monkeypatch, tmp_path, {"html": PAGE})
    items = MP.fetch_purchases(wait=6, opener=opener, sleep=lambda s: None, now=lambda: NOW)
    assert opened == [MP.URL + "#imak-buys"] and len(items) == 2


def test_fetch_uses_fresh_cache_without_opening(monkeypatch, tmp_path):
    opened, opener = _fake(monkeypatch, tmp_path, None)
    MP.save_from_extension({"html": PAGE}, now=NOW - dt.timedelta(minutes=5))
    assert len(MP.fetch_purchases(opener=opener, now=lambda: NOW)) == 2 and opened == []


def test_fetch_login_required_raises(monkeypatch, tmp_path):
    _o, opener = _fake(monkeypatch, tmp_path, {"login_required": True})
    with pytest.raises(RuntimeError, match="ログイン"):
        MP.fetch_purchases(wait=6, opener=opener, sleep=lambda s: None, now=lambda: NOW)


def test_fetch_no_reply_raises(monkeypatch, tmp_path):
    _o, opener = _fake(monkeypatch, tmp_path, None)
    with pytest.raises(RuntimeError, match="Edge の拡張"):
        MP.fetch_purchases(wait=6, opener=opener, sleep=lambda s: None, now=lambda: NOW)


def test_extension_is_registered():
    m = json.load(open(os.path.join(HERE, "..", "tools", "sellerhub_grab", "manifest.json"), encoding="utf-8"))
    js = [c for c in m["content_scripts"] if "mercari_buys.js" in c["js"]]
    assert js and "https://jp.mercari.com/mypage/purchases*" in js[0]["matches"]
