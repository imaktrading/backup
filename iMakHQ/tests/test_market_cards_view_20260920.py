"""よく売れているカードの一覧を画面に出す (2026-09-20)。

ユーザー「よく売れているカードをHTMLで表示して欲しい。何のカードか、何枚売れたか、
いくらで売れたか、内が出せているかどうか。出品君コンソールのリサーチの中に」。

★中身は tools/market_ledger.build_cards が唯一の口。CSV と画面で別々に組まない
  (別々に組むと「CSVとブラウザで数が違う」が起きる)。
"""
import os

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = open(os.path.join(HQ, "console", "static", "app.js"), encoding="utf-8").read()
HTML = open(os.path.join(HQ, "console", "static", "index.html"), encoding="utf-8").read()
SERVER = open(os.path.join(HQ, "console", "server.py"), encoding="utf-8").read()
LEDGER = open(os.path.join(HQ, "tools", "market_ledger.py"), encoding="utf-8").read()


def test_集計は1か所から出す():
    assert "def build_cards(" in LEDGER
    assert "build_cards()" in SERVER                  # 画面も
    assert "build_cards()" in LEDGER.split("def cmd_cards(")[1]   # CSV も


def test_画面に出す4つが揃っている():
    body = APP.split("function mkPaint()")[1].split("function initMarketCards")[0]
    for k in ("和名", "売れた数", "実売中央値", "出品状況"):
        assert k in body, k


def test_出品済と未出品を色で分ける():
    body = APP.split("function mkPaint()")[1].split("function initMarketCards")[0]
    assert "st yes" in body and "st no" in body
    css = open(os.path.join(HQ, "console", "static", "style.css"), encoding="utf-8").read()
    assert ".mk .st.yes" in css and ".mk .st.no" in css


def test_絞り込みがある():
    assert "未出品だけ" in APP and "値上げできる" in APP


def test_置き場所はリサーチの中():
    i = HTML.index("リサーチ (市場で何が売れているか)")
    j = HTML.index("よく売れているカード")
    assert i < j                                       # リサーチのすぐ下


def test_口が生えている():
    assert '/api/research/cards' in SERVER and '/api/research/cards' in APP


# ---- カード画像 (2026-09-20 ユーザー「カード画像で見たいねん」) ----

def test_カタログの画像を出す():
    body = APP.split("function mkPaint()")[1].split("function initMarketCards")[0]
    assert 'r["画像"]' in body and "mkimg" in body


def test_カタログに無ければ要補充と出す():
    body = APP.split("function mkPaint()")[1].split("function initMarketCards")[0]
    assert "要補充" in body
    assert "カタログ要補充" in APP          # 絞り込みにも出す


def test_画像は先頭の1枚を使う():
    import sys
    sys.path.insert(0, os.path.join(HQ, "tools"))
    import market_ledger as M
    assert M.first_image('["https://a.png", "https://b.png"]') == "https://a.png"
    assert M.first_image("") == ""
    assert M.first_image(None) == ""


def test_一覧に画像の欄がある():
    body = LEDGER.split("def build_cards(")[1].split(chr(10) + "def ")[0]
    assert '"画像": first_image(row[4])' in body
