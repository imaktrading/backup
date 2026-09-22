"""カタログを見る: file:/// で開くとブラウザがコンソールへの問い合わせを止める (2026-09-22)。
画面はコンソールの /catalog から配り、問い合わせ先は同じ出所 (/api/catalog) にする。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import catalog_browse as C                                    # noqa: E402

SERVER = open(os.path.join(HERE, "..", "console", "server.py"), encoding="utf-8").read()


def test_console_serves_catalog_page_same_origin():
    assert 'u.path == "/catalog"' in SERVER
    assert 'CB.page(api="/api/catalog")' in SERVER
    assert 'var API = "/api/catalog"' in C.page(api="/api/catalog")


def test_opens_console_url_not_file():
    src = open(C.__file__, encoding="utf-8").read()
    assert '+ "/catalog"' in src
