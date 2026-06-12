"""Chrome バージョン自動検出 (detect_chrome_major) の offline テスト.

2026-06-13: version_main=148 ハードコード vs Chrome 本体 v149 の mismatch で driver が
「cannot connect to chrome」 を頻発させた事故の恒久対策。 Chrome 実 version を検出して
uc に渡すことで自動更新に追従する。
"""
import pytest

import scrapers._chrome_util as cu

pytestmark = pytest.mark.offline


def _reset():
    cu._cache["detected"] = False
    cu._cache["major"] = None


def test_returns_int_or_none_without_crash():
    _reset()
    v = cu.detect_chrome_major()
    assert v is None or (isinstance(v, int) and v > 0)


def test_result_is_cached(monkeypatch):
    _reset()
    calls = {"n": 0}

    # winreg 呼出を 1 回だけ行い 2 回目はキャッシュを返すこと
    import builtins
    real_import = builtins.__import__

    def counting_import(name, *a, **k):
        if name == "winreg":
            calls["n"] += 1
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", counting_import)
    cu.detect_chrome_major()
    cu.detect_chrome_major()
    cu.detect_chrome_major()
    assert calls["n"] <= 1          # 2 回目以降はキャッシュ (winreg を再 import しない)


def test_fallback_none_on_error(monkeypatch):
    _reset()
    # winreg import を失敗させても None で返り例外を投げないこと
    import builtins
    real_import = builtins.__import__

    def boom_import(name, *a, **k):
        if name == "winreg":
            raise ImportError("no winreg (non-windows)")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", boom_import)
    assert cu.detect_chrome_major() is None
