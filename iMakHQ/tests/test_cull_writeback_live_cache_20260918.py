"""取り下げた出品は live キャッシュからも消すこと (2026-09-18)。

キャッシュは数分〜2時間 使い回すので、消さないとその間ずっと「出品中」に見え、
同じ出品が候補に並び続ける (画面の件数も減らない)。
"""
import sys

sys.path.insert(0, r"C:/dev/iMak/iMakHQ/tools")
from cull_writeback import drop_from_live_cache


def test_取り下げた分は行ごと消す():
    c = {"111": {"avail": 1}, "222": {"avail": 1}}
    assert drop_from_live_cache(c, ["111"]) == 1
    assert c == {"222": {"avail": 1}}


def test_キャッシュに無い番号は数えない():
    c = {"111": {"avail": 1}}
    assert drop_from_live_cache(c, ["999", "", None]) == 0
    assert c == {"111": {"avail": 1}}
