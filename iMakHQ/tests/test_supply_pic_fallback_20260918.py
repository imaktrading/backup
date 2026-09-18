"""目視画面の「🛒仕入元」: G列(写真)が空でも A列(仕入元URL)から出すこと (2026-09-18)。

実害: 写真が未取得の候補 (実測 1,577件中77件) は仕入元の列ごと出ず、現物と PSA を
見比べられなかった (cert 149501652 / 136006234)。
"""
import sys

sys.path.insert(0, r"C:/dev/iMak/iMakHQ/tools")
from post_psa_review import supply_pic_of_row as f


def test_写真があればその1枚目():
    assert f("https://x/a.jpg|https://x/b.jpg", "https://jp.mercari.com/item/m999999999") \
        == "https://x/a.jpg"


def test_写真が空ならメルカリのURLから出す():
    assert f("", "https://jp.mercari.com/item/m99886585588") \
        == "https://static.mercdn.net/item/detail/orig/photos/m99886585588_1.jpg"


def test_どちらも無ければ空_画面は従来どおり():
    assert f("", "") == ""
    assert f("", "ただの文字") == ""
