"""ギフトセット/ペアウォッチ除外フィルタのテスト (= 単品本体のみ残す).

2026-07-26 user 指示: メンズ抽出に ギフトセット (バンドル SKU) と ペアウォッチ
(2 型番同梱) が混入 (直販・G-shock・メンズで keep gate を通過)。 複合 SKU は
catalog の ID 一致 lookup に写像不能 + 仕入元/価格が単品と別のため除外する。
単品の腕時計本体 (2 型番を含まない) は誤除外しないこと。
"""
import pytest

from scrapers.amazon_search_http import is_gift_or_pair_set


@pytest.mark.parametrize("title,expected", [
    # ★ 実データ (= 2026-07-26 混入分)
    ("[カシオ] 腕時計 【国内正規品】 ジーショック 【ペアウォッチ】 GA-2100-1A1JF / GMA-S2100BA-4AJF", True),
    ("[カシオ] 腕時計 【国内正規品】 ジーショック×ベビージー 【ペアウォッチ】 GW-M5610U-2JF / BGD-5650-2JF", True),
    ("G-SHOCK GW-M5610U-1CJF ギフト セット カシオ 電波ソーラー 腕時計 国内正規品 メンズ ブラック", True),
    ("G-SHOCK GA-100B-7AJF ギフト セット カシオ 腕時計 国内正規品 メンズ ホワイト", True),
    # 表記ゆれ (スペースなし)
    ("[カシオ] G-SHOCK ペアウォッチ DW-5600 / BGD-5000", True),
    ("[カシオ] G-SHOCK ギフトセット DW-5600 メンズ", True),
    # --- 単品本体 (= 除外しない) ---
    ("[カシオ] 腕時計 ジーショック 【国内正規品】 電波ソーラー GW-2310U-1JF メンズ ブラック", False),
    ("[カシオ] 腕時計 ジーショック 【国内正規品】 MUDMASTER 電波ソーラー GWG-100-1AJF メンズ ブラック", False),
    ("[カシオ] 腕時計 G-SHOCK GA-2100-1A1JF ブラック", False),
    ("", False),
])
def test_is_gift_or_pair_set(title, expected):
    assert is_gift_or_pair_set(title) is expected
