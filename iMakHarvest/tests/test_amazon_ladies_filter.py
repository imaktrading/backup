"""レディース除外フィルタのテスト (= メンズ scope 維持).

2026-06-12: メンズ preset でも variant 展開で GMA-P2100 / GMD-S5600 等の
レディース系 50件が混入したため keep gate で除外。 兼用 (メンズ併記) は残す。
"""
import pytest

from scrapers.amazon_search_http import is_ladies_only


@pytest.mark.parametrize("title,expected", [
    # ★ 実データ (= 混入していた純レディース)
    ("[カシオ] 腕時計 ジーショック 【国内正規品】 ミッドサイズモデル GMA-P2100-7AJF レディース ホワイト", True),
    ("[カシオ] 腕時計 ジーショック 【国内正規品】 GMD-S5610PP-4JF レディース ピンク", True),
    ("[カシオ] 腕時計 ジーショック 【国内正規品】 GLX-S5600-1JF レディース ブラック", True),
    # 兼用 (= メンズ併記) → 除外しない
    ("[カシオ] 腕時計 G-SHOCK メンズ レディース 兼用 DW-5600 ブラック", False),
    ("[カシオ] G-SHOCK 男性 女性 GA-2100 ブラック", False),
    # メンズ → 除外しない
    ("[カシオ] 腕時計 ジーショック 【国内正規品】 GWG-B1000-1AJF メンズ ブラック", False),
    # 性別タグなし → 除外しない (= fail-safe で keep)
    ("[カシオ] 腕時計 G-SHOCK GA-2100-1A1JF ブラック", False),
    ("", False),
])
def test_is_ladies_only(title, expected):
    assert is_ladies_only(title) is expected
