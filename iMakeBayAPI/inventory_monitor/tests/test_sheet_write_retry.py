"""シート書込の一時障害 retry (2026-09-25).

19:00 cycle: 在庫の読取は全件成功したのに、SKU 詳細への書込 (batch_update) が Google の
502 (HTML のエラーページ = gspread 上は "[-1]") 1回で例外 → monitor step NG → 報告は
「scrape phase 自体が動作不能」。書込にも retry を掛け、HTML 形の 5xx も一時障害と判定する。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import sheet_updater as S  # noqa: E402

_REAL_502 = ("APIError: [-1]: <!DOCTYPE html>\n<html lang=en>\n  <title>Error 502 (Server Error)!!1</title>\n"
             "  <p><b>502.</b> <ins>That's an error.</ins>\n  <p>The server encountered a temporary error "
             "and could not complete your request.<p>Please try again in 30 seconds.")


class _APIError(Exception):
    pass


def test_html_502_is_transient():
    assert S._is_transient_net_error(_APIError(_REAL_502))


def test_permission_error_is_not_transient():
    assert not S._is_transient_net_error(_APIError("APIError: [403]: The caller does not have permission"))


def test_write_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(S, "_OPEN_SHEET_BACKOFFS", (0, 0, 0, 0))
    calls = {"n": 0}

    def _fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _APIError(_REAL_502)
        return "ok"

    assert S._write_with_retry(_fn, "t") == "ok" and calls["n"] == 3


def test_write_gives_up_after_all_attempts(monkeypatch):
    monkeypatch.setattr(S, "_OPEN_SHEET_BACKOFFS", (0, 0, 0, 0))
    with pytest.raises(_APIError):
        S._write_with_retry(lambda: (_ for _ in ()).throw(_APIError(_REAL_502)), "t")


def test_non_transient_raises_immediately(monkeypatch):
    monkeypatch.setattr(S, "_OPEN_SHEET_BACKOFFS", (0, 0, 0, 0))
    calls = {"n": 0}

    def _fn():
        calls["n"] += 1
        raise _APIError("APIError: [403]: The caller does not have permission")

    with pytest.raises(_APIError):
        S._write_with_retry(_fn, "t")
    assert calls["n"] == 1


def test_all_batch_updates_go_through_retry():
    src = (ROOT / "sheet_updater.py").read_text(encoding="utf-8")
    bare = [ln for ln in src.splitlines() if ".batch_update(" in ln and "_write_with_retry" not in ln]
    assert bare == []
