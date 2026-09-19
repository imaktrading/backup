"""売れ筋一覧に「出品済/未出品」の印を付け、値段は同じ商品どうしだけ比べる (2026-09-20)。

ユーザー指示「売れ筋一覧に出品済、未出品のFLGがあれば、いいんだよね。
で、特定できずが何件あるかの集計かな」。

★値段の突き合わせは **番号だけでやると別物を掴む**。実測:
  - シャンクス OP09-004: うち $272 / 市場に "Promo Championship 2025" $37,000
  - ルフィ OP05-119: うち $150 / 市場に "SEC SP" $1,001、英語版 $675、パラレル $900
  - 満身創痍 ST01-012: 市場に "1st Anniversary 尾田サイン入り" $9,330
  だから ①カタログの product_id が両側で一致 ②印 (言語/サイン/記念/パラレル/大会賞品)
  が同じ ③レアリティが同じ、の3つを満たす行だけを中央値に使う。
"""
import sys

sys.path.insert(0, r"C:/dev/iMak/iMakHQ/tools")
import market_ledger as M


def test_出品済と未出品を分ける():
    rows = [{"種別": "Sold", "タイトル": "PSA10 Pikachu 020/M-P", "売れた数": "3", "平均落札": "$100"},
            {"種別": "Sold", "タイトル": "PSA10 Mew 150/165", "売れた数": "2", "平均落札": "$50"}]
    got = M.cards_with_flag(rows, ["pokemon_tcg:M-P-020"])
    flag = {k: have for k, _v, have in got}
    assert flag["020/M-P"] is True
    assert flag["150/165"] is False


def test_英語版や中国語版は比べない():
    ours = "PSA 10 One Piece Japanese Nami #OP08-106 Super Rare"
    assert M.same_product(ours, "Nami (SP) OP08-106 PSA10 English") is False
    assert M.same_product(ours, "PSA10 Boa Hancock ST03-013 Chinese") is False


def test_サインや記念や大会賞品は比べない():
    ours = "PSA 10 One Piece Japanese Luffy #ST01-012"
    assert M.same_product(ours, "PSA10 Luffy ST01-012 1st Anniversary with Signature Oda") is False
    assert M.same_product(
        ours, "PSA10 Shanks SR final-T Best32 OP09-004 Promo Championship 2025") is False


def test_レアリティが違えば比べない():
    """うちの eBay タイトルは語で綴る ("Super Rare") ので、そこも拾う。"""
    assert M._rarity("PSA 10 Shanks OP09-004 Super Rare") == {"SR"}
    assert M.same_product("PSA 10 Luffy OP05-119 Secret Rare",
                          "PSA10 Luffy Sec Sp OP05-119") is False


def test_同じ物なら比べる():
    ours = "PSA 10 Pokemon Japanese Mega Brave #088/063 Mega Lucario ex Super Rare 2025"
    assert M.same_product(ours, "PSA10 Mega Lucario ex SAR 2025 088/063 Mega Brave Japanese") is True
