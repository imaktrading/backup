"""リサーチは **売る側の国** で絞る (2026-09-20)。

ユーザー「日本人バイヤーのデータなんて要らんでしょ」「セラーだけ日本にして、取り直しやな」。

実害: 9/18 に取った 1,612件は **買い手の国 (buyerCountry=JP)** で絞られていた。
買い手が日本人かは どうでもよく、むしろ eBay の買い手は大半が米国なので市場の
大部分を捨てていた。結果、米国セラーの英語版が309件 混ざり、ユーザーに
「8は英語版」「77,78,79 英語版」「162〜165,173〜175 英語版」と何度も指摘させた。

実測 (GetItem のセラー国 × 申告言語):
  JP/日本語 591 · US/英語 309 · US/日本語 264 · JP/表記なし 176 · CN/中国語 28
"""
import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))
import market_ledger as M                                     # noqa: E402


PRESET = list(M.PRESETS)[0]


def test_売る側の国で絞る():
    assert "sellerCountry=JP" in M.build_url(PRESET, "SOLD", 90)


def test_ゲームでは絞り続ける():
    """★2026-09-20: 一度「絞らない」に変えたが戻した。

    ユーザー指摘「カタログに無いから自然に落ちるって、カタログ及び引き方の精度が
    低いのに、よく言うわ」。実測: 正式値でない出品267件のうち、カタログまで引けたのは
    **73件 (27%)** だけ。残り194件は判別できないまま画面に出る。
    取りこぼす約10%より、判別できないゴミが267件入る方が害が大きい。
    外すのは カタログと引き方の精度が上がってから。
    """
    assert M.PRESETS[PRESET]                       # 空にしない
    assert "aspect=Game" in M.build_url(PRESET, "SOLD", 90)


def test_買い手の国では絞らない():
    """★ここに buyerCountry を足さないこと。市場の大部分を捨てることになる。"""
    for preset in M.PRESETS:
        for tab in ("SOLD", "ACTIVE"):
            assert "buyerCountry" not in M.build_url(preset, tab, 90)


def test_間違った条件で取り込んだら知らせる():
    """黙って通すと、また英語版が混ざって人が気づくまで分からない。"""
    warn = M.warn_if_wrong_filter([{"条件": "marketplace=EBAY-US&buyerCountry=JP&x=1"}])
    assert "buyerCountry" in warn and "sellerCountry" in warn
    assert M.warn_if_wrong_filter([{"条件": "marketplace=EBAY-US&sellerCountry=JP"}]) == ""
    assert M.warn_if_wrong_filter([]) == ""


def test_取り込みで必ず見る():
    src = open(os.path.join(HQ, "tools", "market_ledger.py"), encoding="utf-8").read()
    body = src.split("def cmd_ingest(")[1].split("\ndef ")[0]
    assert "warn_if_wrong_filter(rows)" in body


def test_条件を変えたら台帳を退避できる():
    """条件が変わったデータを混ぜると、前の条件の行が残り続ける (同じ出品は1行なので)。"""
    src = open(os.path.join(HQ, "tools", "market_ledger.py"), encoding="utf-8").read()
    assert "def cmd_archive(" in src
    assert '"archive": cmd_archive' in src


def test_ゲームの値はeBayの正式値():
    """★2026-09-20 eBay に直接聞いて確認 (Taxonomy API / category 183454 / 候補値168件)。

    Pok… は "Pokémon TCG" の1つだけ、One Piece は "One Piece CCG" の1つだけ。
    Dragon Ball は4つ (CCG / GT TCG / Super Card Game / Z TCG) あり、うちが扱うのは
    Super Card Game (フュージョンワールド) だけ。CCG の中身は実データでも
    イタジャガ・ヒーローズで、別物だった。
    """
    assert M.PRESETS["ポケモン"] == ["Pokémon TCG"]
    assert M.PRESETS["ワンピース"] == ["One Piece CCG"]
    assert M.PRESETS["ドラゴンボール"] == ["Dragon Ball Super Card Game"]


def test_取り込んだファイルは二度と拾わない():
    """★2026-09-20 実害: 買い手の国で絞った 9/18 の469行を退避したのに、
    Downloads に CSV が残っていたせいで 取り込むたびに また入ってきた。
    """
    src = open(os.path.join(HQ, "tools", "market_ledger.py"), encoding="utf-8").read()
    body = src.split("def find_files(")[1].split("\ndef ")[0]
    assert "_ingested()" in body
    assert "def _remember_ingested(" in src
    ing = src.split("def cmd_ingest(")[1].split("\ndef ")[0]
    assert "_remember_ingested(" in ing          # 取り込んだら覚える


def test_入口では絞れないので出口で落とす():
    """★2026-09-20 ユーザー「EB03-026 これを調べたら、2件ともUSセラーだね」
    →「テラピークの抽出も100%ではない。セラー=JPには仕切れない」。

    実測: `sellerCountry=JP` を付けて取っても JP 896 / US 892 / CN 57 / CZ 25 と
    ほぼ半々だった。入口では絞れないので、GetItem のセラー国で出口で落とす。
    URL の指定は **入れたまま**にする (害がない / 将来効けば得 / 経緯が残る)。
    """
    src = open(os.path.join(HQ, "tools", "market_ledger.py"), encoding="utf-8").read()
    assert "def is_jp_seller(" in src
    body = src.split("def by_card(")[1].split("\ndef ")[0]
    # ★2026-09-21 決定を変えた (ユーザー「日本人セラーにしなくていい」): セラー国は GetItem を
    #   約9,000回引かないと分からず、時間をかける価値が無い。絞りは JP_SELLER_ONLY で切替、
    #   既定は切る。代わりに言語の印 (英語版/中国語版/韓国語版) で落とす
    assert "JP_SELLER_ONLY and not is_jp_seller(r, seller)" in body
    assert M.JP_SELLER_ONLY is False
    assert "_OTHER_LANG" in body
    assert "sellerCountry=JP" in M.build_url(PRESET, "SOLD", 90)   # 入口の指定は残す


def test_セラー国が分からなければ数えない():
    """分からない物を残すと、また英語版が混ざる。落とす側に倒す。"""
    assert M.is_jp_seller({"itemId": "ありえないID"}, {}) is False
    assert M.is_jp_seller({"itemId": "1"}, {"1": "JP"}) is True
    assert M.is_jp_seller({"itemId": "1"}, {"1": "US"}) is False
