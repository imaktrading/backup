"""カタログを画像つきで見る画面 (2026-09-20)。

ユーザー「こんな画面構成で、カタログの内容も見てみたいな。カード番号や、キャラ、
ポケモンなのか、ワンピなのか等、絞れて」
→ 続けて「開ける前に条件入れないとダメでしょ。開けてから絞り込みたい」。
→ 「本当にカタログにないのか、引き方に問題があるのか、一発でわかる」。

★これは 1丁目1番地 (①カタログのデータ / ②出品くんの引き方) の判定道具。
  0件で返れば ①、出てくれば ②。実例: 212/172 は「カタログ未収録」と出していたが、
  引いてみると **在った** (= ②こちらの引き方の問題だった)。
"""
import os
import sqlite3
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))
import catalog_browse as C                                    # noqa: E402

PANEL = open(os.path.join(HQ, "control_panel.py"), encoding="utf-8").read()
APP = open(os.path.join(HQ, "console", "static", "app.js"), encoding="utf-8").read()
SERVER = open(os.path.join(HQ, "console", "server.py"), encoding="utf-8").read()


def test_番号や名前で絞れる():
    conn = sqlite3.connect(C.DB)
    assert len(C.fetch(conn, "", "105/078", 50)) > 0          # 番号
    assert len(C.fetch(conn, "", "ピカチュウ", 50)) > 0        # 名前


def test_商材で絞れる():
    conn = sqlite3.connect(C.DB)
    rows = C.fetch(conn, "one_piece_tcg", "", 20)
    assert rows and all(r[3] == "one_piece_tcg" for r in rows)


def test_カタログに無ければ0件で返る():
    """★0件 = 本当に無い。出てくれば引き方の問題。"""
    conn = sqlite3.connect(C.DB)
    assert C.fetch(conn, "", "ZZZ-999-ありえない番号", 20) == []


def test_引けると分かる実例():
    """★「未収録」と出していた 212/172 は カタログに在った (= ②引き方の問題)。"""
    conn = sqlite3.connect(C.DB)
    assert len(C.fetch(conn, "", "212/172", 20)) > 0


def test_鑑定画像しか無い物に印を付ける():
    """★ユーザー「91はなんで実物画像なの? カタログ画像ないの?」→ CLK-007 が実際にそうだった。"""
    assert C.is_cert_image("https://d1htnxwo4o0jhw.cloudfront.net/cert/204682933/large/x.jpg")
    assert not C.is_cert_image("https://www.pokemon-card.com/assets/images/x.jpg")
    assert "鑑定画像" in C.page()


def test_開いてから絞り込める():
    """★ユーザー「開ける前に条件入れないとダメでしょ。開けてから絞り込みたい」。

    カタログは10万件あって1枚の HTML には収まらないので、画面から出品くんに聞く。
    """
    h = C.page()
    assert "/api/catalog" in h                    # 開いたまま聞きに行く
    assert 'id="q"' in h and 'id="games"' in h    # 絞り込みも商材も画面の中
    assert "ポケモン" in h and "ワンピース" in h
    assert "repeat(5,1fr)" in h                   # 売れ筋と同じ 5列
    assert "height:100vh" in h                    # 見出しと絞り込みは動かさない
    assert "0件" in h                             # 無い時に そう言う
    i = PANEL.index('"catalog_browse.py"')
    assert '"params": []' in PANEL[i:i + 400]     # 開く前に条件を聞かない


def test_引くのは1か所から():
    """画面も CLI も tools/catalog_browse.fetch を通す (二重に組まない)。"""
    assert "/api/catalog" in SERVER
    assert "CB.fetch(conn, game, q, limit)" in SERVER


def test_値は写すだけと書いてある():
    assert "直すのはカタログの仕事" in C.page()


def test_ボタンから開ける():
    assert "📇 カタログを見る" in PANEL
    assert '"catalog_browse.py"' in PANEL
    assert "カタログを見る" in APP                 # 分析・棚 の並びに居る


# ---- 画像は日本語版を選ぶ (2026-09-20 ユーザー「114、115 英語版」) ----

def test_日本語版の画像を選ぶ():
    """★出品もセラーも日本語版で正しいのに、表に出る画像が英語版のカードだった。

    原因は **こちらの引き方** (①ではなく②)。カタログは日本語版も持っていて、
      [0] .../OP-EN/OP06/OP06-022_d.png   ← 英語版
      [1] .../OP-JA/OP06/OP06-022.png     ← 日本語版
    なのに先頭を無条件で使っていた。実測 (ワンピース): 先頭が英語版 4,760件のうち
    **4,591件は2枚目以降に日本語版がある**。日本語版が1枚も無いのは169件だけ。
    """
    assert C.first_image('["https://x/OP-EN/a.png", "https://x/OP-JA/a.png"]') \
        == "https://x/OP-JA/a.png"


def test_日本語版が無ければ仕方なく先頭():
    assert C.first_image('["https://x/OP-EN/only.png"]') == "https://x/OP-EN/only.png"


def test_ドラゴンボールの形も英語版と分かる():
    """DBFW-EN / EN_FW_ の形。"""
    assert C._is_en_image("https://x/card_image/DBFW-EN/FB09/EN_FW_FB09-001_Leader.png")
    assert not C._is_en_image("https://x/card_image/DBFW-JA/FB09/FW_FB09-001.png")


def test_ポケモンの画像は素通し():
    u = "https://www.pokemon-card.com/assets/images/card_images/large/M-P/048258.jpg"
    assert C.first_image('["%s"]' % u) == u
