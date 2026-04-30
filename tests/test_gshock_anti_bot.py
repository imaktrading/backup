#!/usr/bin/env python3
"""Phase 3-D: G-SHOCK catalog scraper の anti-bot resilience テスト.

テスト範囲 (Selenium なし):
  - _is_blocked 検出ロジック (pure function、driver mock で検証)
  - _BLOCK_SIGNALS 全シグナルの hit 確認
  - 実 Akamai 403 ページ風サンプル文字列の hit
"""
from __future__ import annotations
import sys
from pathlib import Path

# iMakCatalog/scrapers を import path に追加.
# 注意: gshock.py の module load が iMakG-shock を sys.path に追加するため、
# 後続テスト (test_phase_d_cache_sharing 等) の `import check_csv` が
# iMakG-shock/check_csv.py を pick して shadowing する事故あり.
# → import 後に iMakG-shock 系 path を sys.path から除去する.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRAPERS = _REPO_ROOT / "iMakCatalog" / "scrapers"
if str(_SCRAPERS) not in sys.path:
    sys.path.insert(0, str(_SCRAPERS))

# 先行 import で gshock.py の sys.path 副作用を発火させる
import gshock as _gshock_preload  # noqa: F401, E402

# import 後に iMakG-shock 系 path を除去 (name shadowing 防止)
_GS_PATHS = [
    str(_REPO_ROOT / "iMakG-shock"),
    str(_REPO_ROOT / "iMakG-shock" / "casio_finder"),
]
for _p in _GS_PATHS:
    while _p in sys.path:
        sys.path.remove(_p)


class _FakeDriver:
    """Selenium driver の最小モック. find_element(By.TAG_NAME, 'body') が
    body_text を持つ要素を返す."""
    def __init__(self, body_text: str = "", raise_on_find: bool = False):
        self._body_text = body_text
        self._raise = raise_on_find

    def find_element(self, by, value):
        if self._raise:
            raise Exception("driver dead")
        class _El:
            def __init__(self, text):
                self.text = text
        return _El(self._body_text)


def _is_blocked(driver):
    """テスト対象を遅延 import (gshock.py の sys.path side effect 回避)."""
    from gshock import _is_blocked as fn
    return fn(driver)


class _DeadDriver:
    """quit() を呼んでも例外を投げない fake driver (URLError test 用)."""
    def quit(self):
        pass


# ============================================================================
# 各 BLOCK signal の hit 確認
# ============================================================================
def test_akamai_permission_to_access():
    """実 Akamai 403 メッセージで block 判定."""
    body = (
        "You don't have permission to access "
        "\"http://www.casio.com/jp/watches/gshock/product.GD-X6900FB-7/\" on this server."
    )
    assert _is_blocked(_FakeDriver(body)) is True


def test_akamai_edgesuite_url():
    """Akamai 403 ページに含まれる errors.edgesuite.net URL で block 判定."""
    body = "https://errors.edgesuite.net/18.45e52e17.1777423027.50ace5ad"
    assert _is_blocked(_FakeDriver(body)) is True


def test_akamai_reference_id():
    """Akamai リファレンス ID 行で block 判定."""
    body = "Reference #18.45e52e17.1777423027.50ace5ad"
    assert _is_blocked(_FakeDriver(body)) is True


def test_generic_access_denied():
    body = "Access Denied. You don't have permission."
    assert _is_blocked(_FakeDriver(body)) is True


def test_cloudflare_challenge():
    body = "Please complete the security check by Cloudflare to continue."
    assert _is_blocked(_FakeDriver(body)) is True


# ============================================================================
# 通常ページ (block なし) は False
# ============================================================================
def test_normal_series_page_not_blocked():
    """正常な CASIO シリーズページ風 body は block 判定されない."""
    body = (
        "CASIO ID\nCASIOオンラインストア\n"
        "G-SHOCK - 6900シリーズ\n並び替え\n新着順\n"
        "DW-6900AKA-4JR\nDW-6900HDS-7JF\n"
    )
    assert _is_blocked(_FakeDriver(body)) is False


def test_normal_product_page_not_blocked():
    body = "DW-6900 ケースサイズ 50 mm 防水 200 m バンド 樹脂"
    assert _is_blocked(_FakeDriver(body)) is False


def test_empty_body_not_blocked():
    """空 body は block ではなく単に未ロード扱い."""
    assert _is_blocked(_FakeDriver("")) is False


# ============================================================================
# driver 例外の defensive 挙動
# ============================================================================
def test_driver_exception_returns_false():
    """driver.find_element が例外を投げたら False (block ではないと判断)."""
    assert _is_blocked(_FakeDriver(raise_on_find=True)) is False


# ============================================================================
# 実本走ログから抽出した block 文字列で hit
# ============================================================================
def test_real_run_block_text():
    """2026-04-29 本走ログの DW-6900 GD-X6900FB-7 ブロック時の body 風.

    元ログ:
      You don't have permission to access "http://www.casio.com/jp/watches/gshock/product.GD-X6900FB-7/" on this server.
      Reference #18.45e52e17.1777423027.50ace5ad
      https://errors.edgesuite.net/18.45e52e17.1777423027.50ace5ad
    """
    body = (
        'You don\'t have permission to access "http://www.casio.com/jp/watches/gshock/product.GD-X6900FB-7/" on this server.\n'
        "Reference #18.45e52e17.1777423027.50ace5ad\n"
        "https://errors.edgesuite.net/18.45e52e17.1777423027.50ace5ad"
    )
    assert _is_blocked(_FakeDriver(body)) is True


# ============================================================================
# update_all_series の subset filter 受付確認 (driver なし、API 検証のみ)
# ============================================================================
def test_update_all_series_accepts_series_filter():
    """update_all_series が series_filter kwarg を受け付ける (signature 確認)."""
    import inspect
    from gshock import update_all_series
    sig = inspect.signature(update_all_series)
    assert "series_filter" in sig.parameters, (
        "update_all_series が series_filter kwarg を受け取れない"
    )


# ============================================================================
# URLError 捕獲 (2026-04-30 Phase 3-D follow-up)
# ============================================================================
def test_restart_driver_returns_none_on_persistent_failure(monkeypatch):
    """_start_driver が常に URLError を投げる時、_restart_driver は最終 None を返す.

    背景: 2026-04-29 β night1 で chromedriver CDN 取得失敗の URLError が caller まで
    伝播して process crash. 修正後は 3 回 retry → halt 通知 (None) で graceful exit.
    """
    import urllib.error
    import gshock

    call_count = {"n": 0}

    def fake_start():
        call_count["n"] += 1
        raise urllib.error.URLError("getaddrinfo failed [test simulation]")

    # _start_driver を全回 fail に置換 (time.sleep も短縮して test 高速化)
    monkeypatch.setattr(gshock, "_start_driver", fake_start)
    monkeypatch.setattr(gshock.time, "sleep", lambda _s: None)

    result = gshock._restart_driver(_DeadDriver())
    assert result is None, "URLError 連続発火時は None を返すべき"
    assert call_count["n"] == 3, f"3 回 retry されるべき (実際: {call_count['n']})"


def test_restart_driver_returns_driver_on_first_success(monkeypatch):
    """_start_driver が成功する場合は通常通り driver を返す (retry 不要)."""
    import gshock

    fake_driver_obj = object()
    call_count = {"n": 0}

    def fake_start():
        call_count["n"] += 1
        return fake_driver_obj

    monkeypatch.setattr(gshock, "_start_driver", fake_start)
    monkeypatch.setattr(gshock.time, "sleep", lambda _s: None)

    result = gshock._restart_driver(_DeadDriver())
    assert result is fake_driver_obj
    assert call_count["n"] == 1, "成功時は 1 回呼び出しのみ"


def test_restart_driver_recovers_on_second_attempt(monkeypatch):
    """1 回失敗 → 2 回目成功で driver を返す (途中 recovery)."""
    import urllib.error
    import gshock

    fake_driver_obj = object()
    call_count = {"n": 0}

    def fake_start():
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise urllib.error.URLError("transient DNS error [test]")
        return fake_driver_obj

    monkeypatch.setattr(gshock, "_start_driver", fake_start)
    monkeypatch.setattr(gshock.time, "sleep", lambda _s: None)

    result = gshock._restart_driver(_DeadDriver())
    assert result is fake_driver_obj
    assert call_count["n"] == 2


# Standalone runner
if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    cases = [
        ("Akamai 'permission to access'",  test_akamai_permission_to_access),
        ("Akamai edgesuite.net URL",       test_akamai_edgesuite_url),
        ("Akamai Reference #",             test_akamai_reference_id),
        ("generic Access Denied",          test_generic_access_denied),
        ("Cloudflare challenge",           test_cloudflare_challenge),
        ("normal series page → not blocked", test_normal_series_page_not_blocked),
        ("normal product page → not blocked", test_normal_product_page_not_blocked),
        ("empty body → not blocked",       test_empty_body_not_blocked),
        ("driver exception → False",       test_driver_exception_returns_false),
        ("実本走 GD-X6900FB-7 block 文字列", test_real_run_block_text),
        ("update_all_series series_filter kwarg", test_update_all_series_accepts_series_filter),
        # 注: 以下 3 ケースは pytest monkeypatch 必須で standalone runner からは省略
    ]
    fails = 0
    for name, fn in cases:
        try:
            fn()
            print(f"  ✓ {name}")
        except AssertionError as e:
            print(f"  ✗ FAIL: {name}: {e}")
            fails += 1
    if fails == 0:
        print(f"\n✅ All {len(cases)} anti-bot tests passed.")
    else:
        print(f"\n❌ {fails} failed.")
        sys.exit(1)
