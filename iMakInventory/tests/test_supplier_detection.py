"""regression test: _domain_of の protocol-missing 許容 + detect_supplier 確実性.

今朝の monitor 巡回で row 317/319 が "amazon.co.jp/dp/..." (protocol 抜け) で
supplier=other 判定 → 在庫検出 silent skip した事象 (Phase 7 #3) の再発防止。
漏れ NG 原則のためコード側で URL を normalize する。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_domain_of_handles_missing_protocol():
    """protocol 抜けでも netloc を返す (https:// を仮 prepend)."""
    from sheet_updater import _domain_of
    assert _domain_of("amazon.co.jp/dp/B0BNHK3NKF/?coliid=X") == "amazon.co.jp"
    assert _domain_of("jp.mercari.com/item/m12345") == "jp.mercari.com"
    assert _domain_of("fril.jp/item/123") == "fril.jp"


def test_domain_of_with_protocol_unchanged():
    """通常の https:// 付き URL も従来通り netloc 返す."""
    from sheet_updater import _domain_of
    assert _domain_of("https://www.amazon.co.jp/dp/B0BNHK3NKF") == "www.amazon.co.jp"
    assert _domain_of("https://jp.mercari.com/item/m1") == "jp.mercari.com"
    assert _domain_of("http://example.com/path") == "example.com"


def test_domain_of_empty_or_whitespace():
    """空文字 / 空白のみ → 空文字 (例外ではなく)."""
    from sheet_updater import _domain_of
    assert _domain_of("") == ""
    assert _domain_of("   ") == ""


def test_detect_supplier_with_protocol_missing_url():
    """protocol 抜け URL でも supplier 判定が通る (regression for row 317/319)."""
    from sheet_updater import _domain_of, detect_supplier
    # row 317/319 と同じ pattern
    url = "amazon.co.jp/dp/B0BNHK3NKF/?coliid=I13SSEFLJ0MI43"
    assert detect_supplier(_domain_of(url)) == "amazon"
    # mercari 同様
    url2 = "jp.mercari.com/item/m12345"
    assert detect_supplier(_domain_of(url2)) == "mercari"
    # fril 同様
    url3 = "fril.jp/item/12345"
    assert detect_supplier(_domain_of(url3)) == "fril"


def test_detect_supplier_unknown_domain_returns_other():
    """不明 domain は 'other' を返す (この場合 monitor_listings で URL alert 集計対象)."""
    from sheet_updater import _domain_of, detect_supplier
    assert detect_supplier(_domain_of("https://abc.example.com/foo")) == "other"
    assert detect_supplier(_domain_of("abc.example.com/foo")) == "other"


def test_monitor_listings_imports_domain_of_from_sheet_updater():
    """monitor_listings は重複定義を持たず sheet_updater から import している.
    SSOT 化の確認 (Phase 7 #3 で集約)。
    """
    import monitor_listings
    from sheet_updater import _domain_of as su_domain_of
    # monitor_listings 経由のシンボルが sheet_updater のものと同一
    assert monitor_listings._domain_of is su_domain_of


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
