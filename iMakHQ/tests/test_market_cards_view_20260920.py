"""よく売れているカードの一覧 (2026-09-20)。

ユーザー「よく売れているカードというボタンを作って、押したら別で HTML が立ち上がる
ようにして。コンソールが汚れるやろ」「カード画像で見たいねん」。

★集計は tools/market_ledger.build_cards が唯一の口。CSV も HTML も同じものを使う
  (別々に組むと「CSVと画面で数が違う」が起きる)。
"""
import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))
import market_ledger as M                                     # noqa: E402

APP = open(os.path.join(HQ, "console", "static", "app.js"), encoding="utf-8").read()
PANEL = open(os.path.join(HQ, "control_panel.py"), encoding="utf-8").read()
LEDGER = open(os.path.join(HQ, "tools", "market_ledger.py"), encoding="utf-8").read()

ROWS = [{"番号": "020/M-P", "product_id": "M-P-020", "和名": "ピカチュウ", "英名": "Pikachu",
         "画像": "https://x/a.png", "ゲーム": "pokemon_tcg", "出品状況": "未出品",
         "売れた数": 166, "出品本数": 5, "実売中央値": 202.5, "うちの値段": "",
         "比べてよい実売": "", "差額": "", "上限仕入れ値(円)": 15000,
         "市場のタイトル例": "PSA10 Pikachu 020/M-P"},
        {"番号": "088/063", "product_id": "M1L-088", "和名": "メガルカリオex", "英名": "",
         "画像": "", "ゲーム": "pokemon_tcg", "出品状況": "出品済",
         "売れた数": 13, "出品本数": 3, "実売中央値": 218.31, "うちの値段": 207.98,
         "比べてよい実売": 218.31, "差額": 10.33, "上限仕入れ値(円)": 16000,
         "市場のタイトル例": "PSA10 Mega Lucario ex 088/063"}]
SUMMARY = {"カード": 2, "出品済": 1, "未出品": 1, "番号が読めなかった販売": 1345,
           "カタログを引けた": 2, "引けなかった": 0, "実売より安い": 1, "取り逃し合計": 10.33}


def test_集計は1か所から出す():
    assert "def build_cards(" in LEDGER
    assert "build_cards()" in LEDGER.split("def cmd_cards(")[1]     # CSV
    assert "build_cards()" in LEDGER.split("def cmd_html(")[1]      # HTML


def test_HTMLに4つが揃っている():
    h = M.cards_html(ROWS, SUMMARY)
    assert "ピカチュウ" in h                      # 何のカードか
    assert ">166<" in h                           # 何個売れたか
    assert "$202.50" in h                         # いくらで売れたか
    assert "未出品" in h and "出品済" in h        # うちが出せているか


def test_画像を出す_無ければ要補充():
    h = M.cards_html(ROWS, SUMMARY)
    assert "https://x/a.png" in h
    assert "要補充" in h                          # 画像が無い方


def test_絞り込みが入っている():
    h = M.cards_html(ROWS, SUMMARY)
    for f in ("未出品だけ", "出品済だけ", "値上げできる", "カタログ要補充"):
        assert f in h, f


def test_画像は先頭の1枚():
    assert M.first_image('["https://a.png", "https://b.png"]') == "https://a.png"
    assert M.first_image("") == ""
    assert M.first_image(None) == ""


def test_ボタンから別画面で開く():
    """★コンソールに埋め込まない (ユーザー「コンソールが汚れるやろ」)。"""
    assert "🃏 よく売れているカード" in PANEL
    assert '"market_ledger.py", "html"' in PANEL
    assert "よく売れているカード" in APP            # 分析・棚 の並びに居る
    assert "mk-table" not in APP                    # 埋め込んだ表は残っていない
