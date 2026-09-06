"""Regression: 2026-06-17 — GetItem画像取得は DNS/接続エラーで虫食い欠落しないようリトライ。

PSA再仕入れ確認ゲートの「①現物=eBay出品画像」が、環境のDNS瞬断で一部だけ取得失敗し
画像が欠ける事象。fetch_listing_images が ConnectionError をリトライし、失敗を空キャッシュ
しない(次回再試行できる)ことを固定。
"""
import importlib.util
from pathlib import Path

_P = Path(__file__).resolve().parent.parent / "iMakeBayAPI" / "ebay_getitem_images.py"
_spec = importlib.util.spec_from_file_location("ebay_getitem_images_t", _P)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


class _R:
    text = "<PictureURL>http://x/1.jpg</PictureURL><PictureURL>http://x/2.jpg</PictureURL>"


def test_retries_on_connection_error_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_post(*a, **k):
        calls["n"] += 1
        if calls["n"] < 3:
            raise m.requests.exceptions.ConnectionError("getaddrinfo failed")
        return _R()

    monkeypatch.setattr(m.requests, "post", fake_post)
    monkeypatch.setattr(m, "_load_keys", lambda: {"AppID": "", "DevID": "", "AppSecret": "", "AuthToken": ""})
    # ★2026-09-06: 認証を OAuth に寄せたので _access_token も requests.post を使う。
    #   ここで止めないと「GetItem の呼び出し回数」にトークン取得ぶんが混ざる。
    monkeypatch.setattr(m, "_access_token", lambda: "dummy-token")
    monkeypatch.setattr(m.time, "sleep", lambda s: None)
    out = m.fetch_listing_images("999", _cache={})
    assert out == ["http://x/1.jpg", "http://x/2.jpg"]
    assert calls["n"] == 3   # 2回失敗 → 3回目成功


def test_failure_not_cached_as_empty(monkeypatch):
    def always_fail(*a, **k):
        raise m.requests.exceptions.ConnectionError("dns")

    monkeypatch.setattr(m.requests, "post", always_fail)
    monkeypatch.setattr(m, "_load_keys", lambda: {"AppID": "", "DevID": "", "AppSecret": "", "AuthToken": ""})
    # ★2026-09-06: 認証を OAuth に寄せたので _access_token も requests.post を使う。
    #   ここで止めないと「GetItem の呼び出し回数」にトークン取得ぶんが混ざる。
    monkeypatch.setattr(m, "_access_token", lambda: "dummy-token")
    monkeypatch.setattr(m.time, "sleep", lambda s: None)
    cache = {}
    assert m.fetch_listing_images("888", _cache=cache) == []
    assert "888" not in cache   # 失敗は確定キャッシュしない=次回再試行できる


def test_retries_on_read_timeout_then_succeeds(monkeypatch):
    """2026-07-24: 高負荷 run の read timeout も ConnectionError 同様リトライし現物画像を欠かさない。"""
    calls = {"n": 0}

    def fake_post(*a, **k):
        calls["n"] += 1
        if calls["n"] < 3:
            raise m.requests.exceptions.ReadTimeout("timed out")
        return _R()

    monkeypatch.setattr(m.requests, "post", fake_post)
    monkeypatch.setattr(m, "_load_keys", lambda: {"AppID": "", "DevID": "", "AppSecret": "", "AuthToken": ""})
    # ★2026-09-06: 認証を OAuth に寄せたので _access_token も requests.post を使う。
    #   ここで止めないと「GetItem の呼び出し回数」にトークン取得ぶんが混ざる。
    monkeypatch.setattr(m, "_access_token", lambda: "dummy-token")
    monkeypatch.setattr(m.time, "sleep", lambda s: None)
    out = m.fetch_listing_images("777", _cache={})
    assert out == ["http://x/1.jpg", "http://x/2.jpg"]
    assert calls["n"] == 3   # timeout 2回 → 3回目成功(旧実装は Timeout を握り潰し画像空だった)
