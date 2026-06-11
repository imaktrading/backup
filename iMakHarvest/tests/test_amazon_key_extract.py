"""KEY (型番) title 抽出のテスト.

2026-06-12: 型番が日本語に直接隣接する title ("GWG-B1000-1AJFメンズ") で \b 境界が
効かず KEY 空欄になっていた回帰防止。 "G-SHOCK" 等 series 語の誤抽出も防ぐ。
"""
import pytest

from scrapers.amazon_item_detail import _extract_product_id_estimated_from_title as ex


@pytest.mark.parametrize("title,expected", [
    # ★ 日本語直結 (= 空欄になっていた実データ)
    ("[カシオ] 腕時計 ジーショック 【国内正規品】 GWG-B1000-1AJFメンズ ブラック", "GWG-B1000-1AJF"),
    ("[カシオ] 腕時計 ジーショック 【国内正規品】 GWG-B1000-1A4JFメンズ レッド", "GWG-B1000-1A4JF"),
    ("[カシオ] 腕時計 ジーショック 【国内正規品】 MTG-B3000-1AJFメンズ ブラック", "MTG-B3000-1AJF"),
    ("[カシオ] 腕時計 ジーショック 【国内正規品】 GWG-B1000-3AJFメンズ カーキー", "GWG-B1000-3AJF"),
    ("[カシオ] 腕時計 ジーショック 【国内正規品】 DW-6900NNJ-1JRメンズ ブラック", "DW-6900NNJ-1JR"),
    # ハイフン無し
    ("[カシオ] 腕時計 ジーショック 【国内正規品】 GRAVITYMASTER 電波ソーラー GWA11001A3JF ブラック", "GWA11001A3JF"),
    # 空白区切り (= 既存正常ケースの非回帰)
    ("[カシオ] 腕時計 G-SHOCK AW-591-2AJF メンズ", "AW-591-2AJF"),
    ("G-Shock GA-700UC メンズ腕時計 One Size", "GA-700UC"),
    # series 語混在 → 型番側を取る ("G-SHOCK" を取らない)
    ("[カシオ] 腕時計 G-SHOCK 【国内正規品】 GMW-B5000GD-9JF メンズ", "GMW-B5000GD-9JF"),
    # 型番が無い → 空文字 ("G-SHOCK" を誤抽出しない)
    ("[カシオ] 腕時計 G-SHOCK ジーショック メンズ", ""),
    ("", ""),
])
def test_extract_model_from_title(title, expected):
    assert ex(title) == expected
