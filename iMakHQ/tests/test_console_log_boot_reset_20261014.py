"""サーバーを入れ替えた後、開いたままの画面が前の回のログを出し続けない (2026-10-14)。"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def test_server_returns_boot_id_and_page_rewinds():
    srv = open(os.path.join(HERE, "..", "console", "server.py"), encoding="utf-8").read()
    js = open(os.path.join(HERE, "..", "console", "static", "app.js"), encoding="utf-8").read()
    assert '"boot": BOOT_ID' in srv
    assert "d.boot !== logBoot" in js and "logAfter = 0" in js
