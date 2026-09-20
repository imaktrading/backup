"""カタログを画像つきで見る画面 (2026-09-20)。

ユーザー「こんな画面構成で、カタログの内容も見てみたいな。カード番号や、キャラ、
ポケモンなのか、ワンピなのか等、絞れて」
「本当にカタログにないのか、引き方に問題があるのか、一発でわかる」。

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

ROWS = [("SV1V-105", "Miriam", "ミモザ", "pokemon_tcg", "拡張パック「バイオレットex」",
         '["https://x/a.png"]', '{"rarity": "SAR", "card_number_text": "105/078"}'),
        ("CLK-007", "Gyarados", "ギャラドス", "pokemon_tcg", "クラシック",
         '["https://d1htnxwo4o0jhw.cloudfront.net/cert/204682933/large/x.jpg"]', "{}")]


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


def test_鑑定画像しか無い物に印を付ける():
    """★ユーザー「91はなんで実物画像なの? カタログ画像ないの?」→ CLK-007 が実際にそうだった。"""
    assert C.is_cert_image("https://d1htnxwo4o0jhw.cloudfront.net/cert/204682933/large/x.jpg")
    assert not C.is_cert_image("https://www.pokemon-card.com/assets/images/x.jpg")
    h = C.html(ROWS, "pokemon_tcg", "")
    assert "鑑定画像" in h


def test_画面に出す物が揃っている():
    h = C.html(ROWS, "pokemon_tcg", "")
    assert "ミモザ" in h                       # 名前
    assert "SV1V-105" in h and "105/078" in h  # 番号
    assert "SAR" in h                          # レアリティ
    assert "ポケモン" in h and "ワンピース" in h  # 商材で分かる
    assert "repeat(5,1fr)" in h                # 売れ筋と同じ 5列
    assert "height:100vh" in h                 # 見出しと絞り込みは動かさない


def test_値は写すだけと書いてある():
    h = C.html(ROWS, "pokemon_tcg", "")
    assert "直すのはカタログの仕事" in h


def test_ボタンから開ける():
    assert "📇 カタログを見る" in PANEL
    assert '"catalog_browse.py"' in PANEL
    assert "カタログを見る" in APP              # 分析・棚 の並びに居る
