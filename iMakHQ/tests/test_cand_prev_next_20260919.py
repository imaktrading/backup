"""仕入候補は「前へ / 次へ」で送れること (2026-09-19)。

ユーザー「仕入候補はスクロールバーでめくるでしょ？それがやりづらいから、次へ、前へに」。
枠 (430px) に候補1件がちょうど収まるので、1件ずつ送る。
"""
import sys

sys.path.insert(0, r"C:/dev/iMak/iMakHQ/tools")
import psa_resource_confirm as P

ITEMS = [{"idx": 0, "itemID": "1", "card_no": "001/100", "title": "テスト",
          "ref_image": "", "ebay_url": "https://x",
          "candidates": [{"url": "https://a", "price": 100, "name": "候補A"},
                         {"url": "https://b", "price": 200, "name": "候補B"}]}]


def test_前へ次へのボタンが出る():
    h = P.build_restock_html(ITEMS)
    assert "↑ 前へ" in h and "次へ ↓" in h
    assert "candStep(this,-1)" in h and "candStep(this,1)" in h


def test_何件中何件目かを出す():
    h = P.build_restock_html(ITEMS)
    assert "class='cpos'" in h
    assert "candPos" in h                      # スクロールでも位置を追う


def test_端ではボタンを押せなくする():
    src = open(r"C:/dev/iMak/iMakHQ/tools/psa_resource_confirm.py", encoding="utf-8").read()
    body = src.split("function candPos(box)")[1].split("function candStep")[0]
    assert "disabled" in body
