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


def test_local_catalog_images_served_only_inside_catalog_dir():
    sys.path.insert(0, os.path.join(HERE, "..", "console"))
    import server as S
    assert S._catalog_img_url("https://x/a.png") == "https://x/a.png"
    assert S._catalog_img_url("C:/dev/iMak_data/catalog/_don_images/a.png").startswith("/catalog/img?p=")
    assert S.catalog_img_path("C:/Windows/win.ini") is None
    assert S.catalog_img_path("C:/dev/iMak_data/catalog/../hq/x.png") is None


def test_same_site_official_images_are_relayed_only_for_listed_hosts():
    sys.path.insert(0, os.path.join(HERE, "..", "console"))
    import server as S
    u = "https://www.onepiece-cardgame.com/images/cardlist/card/EB01-015_p1.png"
    assert S._catalog_img_url(u).startswith("/catalog/img?u=")
    assert S._catalog_img_url("https://www.pokemon-card.com/a.jpg") == "https://www.pokemon-card.com/a.jpg"
    assert S.catalog_img_remote("https://evil.example.com/a.png") is None
    assert S.catalog_img_remote("http://www.onepiece-cardgame.com/a.png") is None
