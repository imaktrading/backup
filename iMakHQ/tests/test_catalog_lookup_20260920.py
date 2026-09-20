"""カタログの引き方は tools/catalog_lookup.py が唯一の口 (2026-09-20)。

ユーザー「カタログの引き方に関して、ノウハウを蓄積しておかないとね」。
それまで引き方は market_ledger.py の中にしか無く、他の道具は自前で引いていた。

★このテストは **引き方の落とし穴を1つずつ覚えておく**ためのもの。
  同じ失敗を繰り返さないよう、直した理由を1件ずつ残す。
"""
import os
import sqlite3
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))
import catalog_lookup as CL                                   # noqa: E402


def _conn():
    return sqlite3.connect(CL.DB)


# ---- 番号を読む時の落とし穴 ----

def test_PSA10の10を番号と読まない():
    assert CL.ebay_catalog_no(
        "PSA10 Rowlet 082 Art Rare 2026 Pokemon Japanese M3-Mullifying Zero") == ("M3", "082")


def test_年を番号と読まない():
    _c, num = CL.ebay_catalog_no(
        "PSA10 2025 Marshadow 069 Art Rare Pokemon Japanese M1L-Mega Brave")
    assert num == "069"


def test_eBayライブの日付を番号と読まない():
    assert CL.card_no("ebay Live 07/25-021 [PSA10] Mega Gengar MA 230/193") == "230/193"


def test_番号そのものを候補に残す():
    assert "212/172" in CL.candidates("212/172", "PSA10 Charizard 212/172")


# ---- 引く順番 ----

def test_大文字小文字は問わない():
    """カタログは SV3a / M2a と小文字混じりで書く。大文字に潰すと当たらない。"""
    assert CL.lookup(["SV3A-071"], _conn()) is not None


def test_弾が枝分かれしている時は和名で決める():
    """SV11 は SV11W / SV11B に割れている。"""
    assert CL.by_set_and_no("SV11", "136", "ズルッグ", _conn()) == "SV11W-136"
    assert CL.by_set_and_no("SV11", "136", "", _conn()) is None


def test_英語のセット名から弾コードを当てる():
    """市場のタイトルは弾コードを書かず "VSTAR Universe" だけのことが多い。"""
    assert CL.set_code_from_title("PSA10 Charizard 212/172 VSTAR Universe", _conn()) == "S12a"


def test_カード番号そのもので引く():
    row = CL.by_number_text("212/172", "PSA10 Charizard 212/172 VSTAR Universe", _conn())
    assert row and row[0] == "S12a-212"


def test_英語のカード名で決める():
    """★市場のタイトルは英語なので ここが一番効く。name_en は 22,435/22,492件 ある。"""
    assert CL.by_number_text("009/032", "PSA10 Articuno 009/032 Classic", _conn())[0] == "CLK-009"
    assert CL.by_number_text("004/038", "PSA10 Radiant Greninja 004/038", _conn())[0] == "SVF-004"


def test_決められなければ当てない():
    """★020/019 は マリィのモルペコ と ゲンガーVMAX が同じ番号。
    ゲンガーの $2,475 を拾うと「8倍 値上げできる」に見えてしまう。
    """
    assert CL.by_number_text("020/019", "PSA10 pokemon card", _conn()) is None


def test_通しで引ける():
    t = "PSA10 GEM MINT Articuno 009/032 Pokemon TCG Classic"
    row = CL.lookup(CL.candidates(CL.card_no(t), t), _conn(), t)
    assert row and row[0] == "CLK-009"


# ---- 画像の落とし穴 ----

def test_英語版でない最初の1枚を選ぶ():
    """ワンピース / ドラゴンボールは [0]英語版 [1]日本語版 の並びが多い。"""
    assert CL.first_image('["https://x/OP-EN/a.png", "https://x/OP-JA/a.png"]') \
        == "https://x/OP-JA/a.png"
    assert CL.first_image('["https://x/OP-EN/only.png"]') == "https://x/OP-EN/only.png"


def test_鑑定画像しか無い物が分かる():
    """これは ①カタログ側の不足 (CLK-007)。"""
    assert CL.is_cert_image("https://d1htnxwo4o0jhw.cloudfront.net/cert/204682933/large/x.jpg")


# ---- 口は1つ ----

def test_引き方は1か所から():
    """他の道具は自前で引かない (同じ失敗を各所で繰り返すため)。"""
    for name in ("market_ledger.py", "catalog_browse.py"):
        src = open(os.path.join(HQ, "tools", name), encoding="utf-8").read()
        assert "import catalog_lookup" in src, name
