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
    rows = [{"種別": "Sold", "itemId": "1", "タイトル": "PSA10 Pikachu 020/M-P",
             "売れた数": "3", "平均落札": "$100"},
            {"種別": "Sold", "itemId": "2", "タイトル": "PSA10 Mew 150/165",
             "売れた数": "2", "平均落札": "$50"}]
    # ★日本のセラー / 日本語版 として数える (出口の門を通す)
    got = M.cards_with_flag(rows, ["pokemon_tcg:M-P-020"],
                            lang={"1": "Japanese", "2": "Japanese"},
                            seller={"1": "JP", "2": "JP"})
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


# ---- eBay カタログ形式のタイトルを読む (2026-09-20) ----
# 実測: 番号が読めなかった858行のうち57行がこの形。カタログに当たったのは 40 → 54件。

def test_eBayカタログ形式から弾と番号を読む():
    t = "PSA10 Milcery 110 Art Rare 2024 Pokemon Japanese Sv7-Stellar Miracle マホミル AR"
    assert M.ebay_catalog_no(t) == ("Sv7", "110")


def test_PSA10の10を番号と読まない():
    """最初の実装は全部 -010 になった。"""
    code, num = M.ebay_catalog_no(
        "PSA10 Rowlet 082 Art Rare 2026 Pokemon Japanese M3-Mullifying Zero モクロー")
    assert (code, num) == ("M3", "082")


def test_年を番号と読まない():
    _c, num = M.ebay_catalog_no(
        "PSA10 2025 Marshadow 069 Art Rare Pokemon Japanese M1L-Mega Brave マーシャドー")
    assert num == "069"


def test_この形でない物は読まない():
    assert M.ebay_catalog_no("One Piece Roronoa Zoro Parallel Romance Dawn PSA10") == (None, None)
    assert M.ebay_catalog_no("") == (None, None)


def test_番号として使える形で返す():
    assert M.card_no(
        "PSA10 Kirlia 084 Art Rare 2023 Pokemon Japanese Sv1s-Scarlet Ex キルリア AR") == "SV1S-084"


def test_カタログは大文字小文字を問わずに引く():
    """カタログは SV3a / M2a と小文字混じりで書く。こちらが大文字に潰して当たらなかった。"""
    import sqlite3
    conn = sqlite3.connect(M.CATALOG_DB)
    assert M.lookup_catalog(["SV3A-071"], conn) is not None


def test_弾が枝分かれしている時は和名で決める():
    """SV11 は SV11W / SV11B に割れている。和名が無ければ当てない (推測しない)。"""
    import sqlite3
    conn = sqlite3.connect(M.CATALOG_DB)
    assert M.lookup_by_set_and_no("SV11", "136", "ズルッグ", conn) == "SV11W-136"
    assert M.lookup_by_set_and_no("SV11", "136", "", conn) is None


# ---- カード番号そのもので引く (2026-09-20) ----
# ★ユーザー指摘で発覚: 「カタログ要補充 17件」のうち **16件はカタログに在った**。
#   番号が `212/172` の形の時、弾コードをタイトルから拾えないと候補が空になり、
#   引きもせずに「無い」と言っていた (②引き方の誤り)。17件 → 7件に減った。

def test_番号そのものを候補に残す():
    assert "212/172" in M.product_id_candidates("212/172", "PSA10 Charizard 212/172")
    assert "020/M-P" in M.product_id_candidates("020/M-P", "PSA10 Pikachu 020/M-P")


def test_番号そのもので引ける():
    import sqlite3
    conn = sqlite3.connect(M.CATALOG_DB)
    row = M.lookup_by_number_text("212/172", "PSA10 Charizard 212/172 VSTAR Universe", conn)
    assert row and row[0] == "S12a-212"


def test_決められなければ当てない():
    """★同じ番号の別カードを掴まないこと。

    実例: 020/019 は マリィのモルペコ (SVOM-020) と ゲンガーVMAX が同じ番号で、
    ゲンガーの $2,475 を拾うと「8倍 値上げできる」に見えてしまう。
    """
    import sqlite3
    conn = sqlite3.connect(M.CATALOG_DB)
    # 手がかりが何も無いタイトルでは当てない
    assert M.lookup_by_number_text("020/019", "PSA10 pokemon card", conn) is None
