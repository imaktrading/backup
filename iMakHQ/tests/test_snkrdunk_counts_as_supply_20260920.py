"""スニダンも「新しい供給」に数える。ただし出しすぎない (2026-09-20)。

ユーザー確定「スニダンもいるのでは? 目視した同じものを何回も出してくるのを
やめてもらいたいだけです」。

- スニダンは仕入元なので、**新しい商品が出たら**もう一度目視に出す
- 同じカードの別個体 (`/apparels/NNN/used/xxxx` の xxxx 違い) は出さない
- 過去の記録にスニダンが無い行は数えない。数えると初日に
  **復活が 12件 → 43件** に増えた (比べる材料が無いのに「増えた」と言えない)
"""
import sys

sys.path.insert(0, r"C:/dev/iMak/iMakHQ/tools")
import psa_hoju_fill as H

SD = "https://snkrdunk.com/apparels/761394/used/"
SD2 = "https://snkrdunk.com/apparels/999999/used/"
M = "https://jp.mercari.com/item/"


def test_スニダンの新しい商品は出す():
    assert H._has_new_supply([SD + "1"], [SD + "1", SD2 + "9"]) is True


def test_スニダンの個体違いは出さない():
    assert H._has_new_supply([SD + "1"], [SD + "2"]) is False


def test_記録にスニダンが無ければ数えない():
    """初日に43件が一斉に戻るのを防ぐ。メルカリ側は今までどおり比べる。"""
    assert H._has_new_supply([M + "m1"], [M + "m1", SD + "1"]) is False
    assert H._has_new_supply([M + "m1"], [M + "m1", M + "m2", SD + "1"]) is True


def test_キャッシュからスニダンのURLを拾う():
    e = {"snkrdunk": {"card_url": SD + "1",
                      "psa10_listings": [{"url": SD + "2"}, {"url": SD + "3"}]}}
    got = set(H._cache_snkrdunk_urls(e))
    assert got == {SD + "1", SD + "2", SD + "3"}
    assert set(H._cache_candidate_urls(e)) == got          # 候補にも入る
    assert set(H._cache_strict_candidate_urls(e)) == got   # card_id 引き = 番号特定済み


def test_スニダンが無いキャッシュでも壊れない():
    assert H._cache_snkrdunk_urls({}) == []
    assert H._cache_snkrdunk_urls({"snkrdunk": {"_error": "card_not_found"}}) == []
