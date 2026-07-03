"""部品/アクセサリ除外フィルタのテスト (= 時計本体のみ残す).

2026-07-03: メンズ抽出に MTG-B3000「交換用バンド」単体が混入 (is_gshock はブランド
一致で通過)。 時計本体でない部品を keep gate で除外する。 本体の型番名に含まれる
"メタルベゼル・バンドモデル" 等は誤除外しないこと。
"""
import pytest

from scrapers.amazon_search_http import is_accessory_part


@pytest.mark.parametrize("title,expected", [
    # ★ 実データ (= 混入していた交換用バンド)
    ("[カシオ]ジーショック 【国内正規品】 MTG-B3000 シリーズ 交換用 バンド BANDGS5", True),
    # 明示 part marker
    ("[カシオ] G-SHOCK 交換用ベルト DW-5600 ブラック", True),
    ("CASIO G-SHOCK 液晶保護フィルム 2枚セット", True),
    ("純正 替えバンド GA-2100用 ブラック", True),
    # 腕時計表記なし + アクセサリ名詞 → 部品
    ("[CASIO] G-SHOCK レザーバンド ブラック", True),
    # --- 時計本体 (= 除外しない) ---
    # 型番名に "メタルベゼル・バンドモデル" を含むが本体 (腕時計表記あり)
    ("[カシオ] 腕時計 ジーショック 【国内正規品】 メタルベゼル・バンドモデル GM-2110D-7AJF", False),
    ("[カシオ] 腕時計 ジーショック 【国内正規品】 DW-6900CMG-3JF メンズ", False),
    ("[カシオ] 腕時計 G-SHOCK GA-2100-1A1JF ブラック", False),
    # 腕時計表記なしだがアクセサリ名詞もなし (= 端的な本体title) → fail-safe で keep
    ("[カシオ] G-SHOCK GA-2100-1A1JF ブラック", False),
    ("", False),
])
def test_is_accessory_part(title, expected):
    assert is_accessory_part(title) is expected
