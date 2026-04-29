"""fril_scraper stock-detection regression test.

2026-04-30 検体収集 (TEST_LOW row 652-661、Takaaki さん目視ラベル):
  - Sold/deleted (3 件): 「お探しのページは見つかりませんでした」 (404 page、~80KB)
  - In_stock   (7 件): 「購入に進む」 button (~220KB)

判定軸:
  1. body に DELETED_PHRASE → SOLD/DELETED
  2. body に IN_STOCK_PHRASE → IN_STOCK
  3. どちらもなし → 判定不能 (None)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SAMPLES_DIR = ROOT / "debug" / "fril_samples"


SOLD_HTML_FILES = [
    "row652_aa5c5975561c8cf81f2f2164b539de8d.html",
    "row653_49660ff11a42190b7b11dafb7b454c93.html",
    "row654_8fc43d3d656fd1824e30d3f948d497a8.html",
]

IN_STOCK_HTML_FILES = [
    "row655_a194e9a0b640de89bfce4edf25943eb4.html",
    "row656_b7f9424846abfb16f4e0dc1ff53d8a9a.html",
    "row657_5650c47c58c93189284aa53d0d09834f.html",
    "row658_e13bc293409131a0a7aab5174398ee65.html",
    "row659_3b5cbace76e645b2fdd023b048635802.html",
    "row660_11a6540561c182c9fe7f4c71967ea6c3.html",
    "row661_38bc3c4cc0dd72bc625a871ce9315d8e.html",
]


@pytest.fixture(scope="module")
def samples_available():
    if not SAMPLES_DIR.exists():
        pytest.skip(f"Fril samples not found at {SAMPLES_DIR}")
    return SAMPLES_DIR


@pytest.mark.parametrize("filename", SOLD_HTML_FILES)
def test_offline_fril_sold(samples_available, filename):
    """検体 3 件 (404 page): SOLD 判定."""
    from scrapers.fril_scraper import _detect_stock  # noqa: PLC0415
    path = samples_available / filename
    if not path.exists():
        pytest.skip(f"sample missing: {path.name}")
    html = path.read_text(encoding="utf-8", errors="replace")
    verdict, reason = _detect_stock(html)
    assert verdict is False, (
        f"{filename}: detection returned ({verdict}, {reason}), expected False (SOLD/DELETED)."
    )
    assert reason == "deleted_page"


@pytest.mark.parametrize("filename", IN_STOCK_HTML_FILES)
def test_offline_fril_in_stock(samples_available, filename):
    """検体 7 件 (購入に進む button あり): IN_STOCK 判定."""
    from scrapers.fril_scraper import _detect_stock  # noqa: PLC0415
    path = samples_available / filename
    if not path.exists():
        pytest.skip(f"sample missing: {path.name}")
    html = path.read_text(encoding="utf-8", errors="replace")
    verdict, reason = _detect_stock(html)
    assert verdict is True, (
        f"{filename}: detection returned ({verdict}, {reason}), expected True (IN_STOCK)."
    )
    assert reason == "buy_button"


def test_fril_constants_present():
    """新ロジックの判定軸定数が module に存在することを担保."""
    from scrapers.fril_scraper import DELETED_PHRASE, IN_STOCK_PHRASE
    assert DELETED_PHRASE == "お探しのページは見つかりませんでした"
    assert IN_STOCK_PHRASE == "購入に進む"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
