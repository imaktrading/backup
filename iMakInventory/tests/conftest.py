"""テスト共通設定.

メルカリ判定は 2026-10-03 から「API → 読めなければ Chrome」の順。既存テストは Chrome 側
(_check_404 / _detect_via_selenium) を差し替えて検証しているので、API が本物の通信を
しないよう既定で止める。API 自体のテストは test_mercari_api_detection.py で行う。
"""
import pytest


@pytest.fixture(autouse=True)
def _no_real_mercari_api(monkeypatch, request):
    if request.node.get_closest_marker("mercari_api"):
        return
    try:
        import scrapers.mercari_scraper as m
    except Exception:
        return
    monkeypatch.setattr(m, "MERCARI_API_ENABLED", False)


def pytest_configure(config):
    config.addinivalue_line("markers", "mercari_api: メルカリ API 判定を止めずに使うテスト")
