# -*- coding: utf-8 -*-
"""Sheets の読み取り上限 (429) で目視ツールが落ちないこと (2026-08-15)。

★事故: 🌱ボタン (newcand_confirm) が
  `APIError: [429] Quota exceeded for 'Read requests per minute per user'`
  で途中停止した。原因は2つ:
    (1) **同じ走行で同じタブを2回読んでいた** (sync_status → load_items)。
        読み取り回数がそのまま倍になっていた。
    (2) 429 を **そのまま例外にしていた**。1分待てば必ず回復するのに落ちていた。
  → (1) 1走行のキャッシュ / (2) 待って再試行 の両方を縛る。
"""
from __future__ import annotations

import importlib.util
import os
import sys

_TOOLS = os.path.join(r"C:\dev\iMak", "iMakHQ", "tools")


def _load(name, fname):
    """他プロジェクトの同名 module に汚染されないよう一意名で読む。"""
    spec = importlib.util.spec_from_file_location(name, os.path.join(_TOOLS, fname))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    if _TOOLS not in sys.path:
        sys.path.insert(0, _TOOLS)
    spec.loader.exec_module(mod)
    return mod


_sio = _load("_hq_sheet_io_quota", "sheet_io.py")


def test_quota_error_is_recognized():
    """429 / Quota exceeded を上限エラーと見分けられる (純関数)。"""
    assert _sio.is_quota_error(Exception("APIError: [429]: Quota exceeded for quota metric"))
    assert _sio.is_quota_error(Exception("Quota exceeded"))
    # 上限以外は再試行してはいけない (権限エラーを待ち続けない)
    assert not _sio.is_quota_error(Exception("APIError: [403]: caller does not have permission"))
    assert not _sio.is_quota_error(Exception("WorksheetNotFound"))


def test_read_tab_retries_on_quota(monkeypatch):
    """429 は待って再試行し、回復したら値を返す (落とさない)。"""
    calls = {"n": 0}
    slept = []

    class _WS:
        def get_all_values(self):
            calls["n"] += 1
            if calls["n"] == 1:
                raise Exception("APIError: [429]: Quota exceeded for quota metric 'Read requests'")
            return [["a"], ["b"]]

    class _SH:
        def worksheet(self, tab):
            return _WS()

    monkeypatch.setattr(_sio, "_open", lambda *a, **k: _SH(), raising=False)
    monkeypatch.setattr(_sio._t, "sleep", lambda s: slept.append(s))
    assert _sio.read_tab("dummy") == [["a"], ["b"]]
    assert calls["n"] == 2, "再試行していない"
    assert slept and slept[0] > 0, "待たずに叩き直している (上限が回復しない)"


def test_read_tab_gives_up_and_raises(monkeypatch):
    """回復しなければ黙って空を返さず、ちゃんと例外にする (silent に0件は危険)。"""
    class _WS:
        def get_all_values(self):
            raise Exception("APIError: [429]: Quota exceeded")

    class _SH:
        def worksheet(self, tab):
            return _WS()

    monkeypatch.setattr(_sio, "_open", lambda *a, **k: _SH(), raising=False)
    monkeypatch.setattr(_sio._t, "sleep", lambda s: None)
    try:
        _sio.read_tab("dummy", retries=1)
    except Exception as e:
        assert _sio.is_quota_error(e)
    else:
        raise AssertionError("上限のまま空リストを返している (0件と区別できない)")


def test_newcand_reads_each_tab_once():
    """1走行では同じタブを読み直さない (読み取り回数を倍にしない)。"""
    _load("_hq_prc_quota", "psa_resource_confirm.py")
    N = _load("_hq_newcand_quota", "newcand_confirm.py")
    hits = []
    N.sheet_io.read_tab = lambda tab, *a, **k: (hits.append(tab), [["url"]])[1]
    N._TAB_CACHE.clear()
    for _ in range(3):
        N._read_tab("補URL候補NG")
        N._read_tab("新規出品候補")
    assert hits == ["補URL候補NG", "新規出品候補"], f"同じタブを読み直している: {hits}"
    # 書いたタブだけは捨てる (古い値を使わない)
    N._invalidate_cache("新規出品候補")
    N._read_tab("新規出品候補")
    assert hits.count("新規出品候補") == 2
    assert hits.count("補URL候補NG") == 1
