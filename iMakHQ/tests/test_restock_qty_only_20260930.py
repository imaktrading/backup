# -*- coding: utf-8 -*-
"""PSA 再仕入れ ② は今ある出品の在庫を 0→1 に戻すだけ (2026-09-30 ユーザー確定)。

9/30 の6件で比べると、作り直した Revise CSV はタイトル・Item Specifics・値段が今の出品と同じで、
変わるのは写真と鑑定番号だけ (個体ごとに変わるのは説明文に書いてある) = 作り直しは資源の無駄。
"""
import os
import sys

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
sys.path.insert(0, TOOLS)

import psa_restock_build as B  # noqa: E402


def test_restock_items_follow_gates():
    rows = [{"itemID": "1"}, {"itemID": "2"}, {"itemID": "3"}, {"itemID": "4"}]
    inp = {"certs": ["c1", "c3", "c4"], "cost": {"c1": 5000.0, "c3": 7000.0}}
    got = B.restock_items(rows, inp, [("3", "上げられない台帳")], {"1": "c1", "2": "c2", "3": "c3", "4": "c1"})
    assert got == [("1", 5000.0)]          # 2=門で落ちた / 3=見送り / 4=同じ cert は1回


def test_default_is_qty_restore_not_csv():
    src = open(os.path.join(TOOLS, "psa_restock_build.py"), encoding="utf-8").read()
    i = src.index("def main():")
    body = src[i:src.index("def main_csv():")]
    assert '"--csv" in sys.argv' in body and "return main_csv()" in body
    assert "ReviseFixedPriceItem" in body and "SR.build_item_xml(iid, price, profile)" in body
    assert "psa_restock_csv.py" not in body          # 既定では作り直さない
    assert "SR.ebay_status(fx, U, iid, tok)" in body  # 送った後に読み直す
    assert 'site != "US"' in body                     # ミラーは触らない
    assert "psa_restock_writeback.py" in body         # ③ を続けて回す
