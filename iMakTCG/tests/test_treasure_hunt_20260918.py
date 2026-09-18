"""トレジャーハント: 市場で売れているのに出していないカードを最優先にする。

2026-09-18 ユーザー確定 (「それ最優先でいいのでは。名付けてトレジャーハント」)。
一覧は iMakHQ/tools/market_ledger.py targets が作る demand_market.csv。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tcg_batch_select as T


def _csv(tmp_path, rows):
    p = tmp_path / "demand_market.csv"
    body = ["番号,product_id,和名"] + rows
    p.write_text("\n".join(body), encoding="utf-8-sig")
    return str(p)


def test_一覧が無ければ空_並べ順は今まで通り(tmp_path):
    assert T.load_treasure_ids(str(tmp_path / "ない.csv")) == set()


def test_product_idを大文字で読む(tmp_path):
    p = _csv(tmp_path, ["020/M-P,M-P-020,ピカチュウ", "P-043,p-043,ルフィ"])
    assert T.load_treasure_ids(p) == {"M-P-020", "P-043"}


def test_カタログを引けなかった行は入れない(tmp_path):
    p = _csv(tmp_path, ["080/073,,", "020/M-P,M-P-020,ピカチュウ"])
    assert T.load_treasure_ids(p) == {"M-P-020"}


def test_トレジャーが先頭に来る():
    certs = ["A", "B", "C"]
    titles = {c: "PSA10 Pokemon" for c in certs}

    def popular_of(c):
        return c == "B"                       # 人気キャラは B
    popular_of.known = lambda c: True
    popular_of.treasure = lambda c: c == "C"  # トレジャーは C
    out = T.balanced_sample(certs, titles, 3, popular_of=popular_of,
                            cost_of=lambda c: 1000, explore=0.0, shuffle=lambda g: None)
    assert out[0] == "C"                      # 人気キャラより前
