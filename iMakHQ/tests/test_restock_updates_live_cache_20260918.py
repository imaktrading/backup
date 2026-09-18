"""補充した出品は live キャッシュにも反映する = ボタンの件数が減ること (2026-09-18)。

実害: 18:50 の走行で 358712610416 を在庫1に戻したのに、キャッシュは avail=0 のままで
「押しても件数が減りませんでした (1件 → 1件)」が出た。キャッシュは2時間使うので、
その間ずっと同じ1件を「送る分」と表示し続ける。
"""
import sys

sys.path.insert(0, r"C:/dev/iMak/iMakHQ/tools")
from sold_restock import update_live_cache


def test_revise_は同じ番号で在庫を上書き():
    c = {"358712610416": {"avail": 0, "sku": "m371", "site": "US"}}
    update_live_cache(c, "358712610416", "358712610416", 1)
    assert c["358712610416"]["avail"] == 1
    assert c["358712610416"]["sku"] == "m371"        # ほかの列は壊さない


def test_出し直しは新しい番号に移す():
    c = {"111": {"avail": 0, "sku": "m371"}}
    update_live_cache(c, "111", "222", 1)
    assert "111" not in c                            # 古い番号は残さない
    assert c["222"] == {"avail": 1, "sku": "m371"}


def test_キャッシュに無い出品でも足せる():
    c = {}
    update_live_cache(c, "999", "999", 1)
    assert c["999"]["avail"] == 1
