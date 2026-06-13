"""_chrome_util.detect_chrome_major のテスト (= version_main 自動検出の健全性)."""
from scrapers import _chrome_util


def test_detect_returns_int_or_none():
    v = _chrome_util.detect_chrome_major()
    assert v is None or (isinstance(v, int) and v > 0)


def test_snkrdunk_reexports_shared_detector():
    # snkrdunk_official は後方互換で detect_chrome_major_version を re-export している
    from scrapers import snkrdunk_official as SO
    assert SO.detect_chrome_major_version is _chrome_util.detect_chrome_major
