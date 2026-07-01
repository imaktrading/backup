"""open_sheet の transient retry regression (2026-06-18).

bug: open_sheet が gspread.authorize→open_by_key を retry なしで呼び、 sheets.googleapis.com の
getaddrinfo failed (DNS blip) 1 回で例外送出 → 公式 monitor step NG → cycle 全体 ❌ + 全 listing
在庫不明 (= fail-closed だが監視欠落)。 03:00 cycle で実発生。 transient は backoff retry する。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import sheet_updater as S  # noqa: E402


class _FakeSheet:
    pass


def _patch_common(monkeypatch):
    monkeypatch.setattr(S.os.path, "exists", lambda p: True)
    monkeypatch.setattr(S.Credentials, "from_service_account_file", staticmethod(lambda *a, **k: object()))
    monkeypatch.setattr(S, "_OPEN_SHEET_BACKOFFS", (0, 0, 0, 0))  # test は sleep しない


def test_transient_then_success(monkeypatch):
    """getaddrinfo failed が 2 回 → 3 回目で成功 → retry で開ける。"""
    _patch_common(monkeypatch)
    calls = {"n": 0}
    sentinel = _FakeSheet()

    class _GC:
        def open_by_key(self, key):
            return sentinel

    def fake_authorize(creds):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise ConnectionError("HTTPSConnectionPool: Failed to resolve 'sheets.googleapis.com' "
                                  "(getaddrinfo failed)")
        return _GC()

    monkeypatch.setattr(S.gspread, "authorize", fake_authorize)
    assert S.open_sheet() is sentinel
    assert calls["n"] == 3


def test_google_api_503_retries_then_success(monkeypatch):
    """Google Sheets API 503 (gspread APIError) → transient 扱いで retry → 成功 (2026-07-02 regression)。

    07-02 03:00 cycle が open_by_key で `APIError: [503]: The service is currently unavailable`
    1 回 → monitor step NG になった。 5xx/429 は Google 側一時障害なので backoff retry で救済する。
    """
    _patch_common(monkeypatch)
    calls = {"n": 0}
    sentinel = _FakeSheet()

    class _GC:
        def open_by_key(self, key):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise RuntimeError("APIError: APIError: [503]: The service is currently unavailable.")
            return sentinel

    monkeypatch.setattr(S.gspread, "authorize", lambda creds: _GC())
    assert S.open_sheet() is sentinel
    assert calls["n"] == 3  # 503 を 2 回 retry して 3 回目で成功


def test_bare_status_number_not_false_matched(monkeypatch):
    """業務文言中の裸の数字 (例 'row 503') は transient 誤判定しない (bracketed のみ拾う)。"""
    assert S._is_transient_net_error(Exception("row 503 updated / 429 rows total")) is False
    assert S._is_transient_net_error(Exception("APIError: [503]: unavailable")) is True


def test_non_transient_raises_immediately(monkeypatch):
    """認証エラー等 transient でない例外は retry せず即 raise。"""
    _patch_common(monkeypatch)
    calls = {"n": 0}

    def fake_authorize(creds):
        calls["n"] += 1
        raise ValueError("invalid service account credentials")

    monkeypatch.setattr(S.gspread, "authorize", fake_authorize)
    with pytest.raises(ValueError):
        S.open_sheet()
    assert calls["n"] == 1  # retry していない


def test_persistent_transient_raises_after_max(monkeypatch):
    """DNS が継続ダウン → 全 attempt 失敗で最終的に raise (= 諦める)。"""
    _patch_common(monkeypatch)
    calls = {"n": 0}

    def fake_authorize(creds):
        calls["n"] += 1
        raise ConnectionError("getaddrinfo failed")

    monkeypatch.setattr(S.gspread, "authorize", fake_authorize)
    with pytest.raises(ConnectionError):
        S.open_sheet()
    assert calls["n"] == len(S._OPEN_SHEET_BACKOFFS)  # 全 attempt 試行
