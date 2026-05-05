"""tests/test_extraction_filter - should_skip_color_size の TCG 検出テスト.

Phase 1d-3: 色/サイズ判定不要カテゴリ (TCG 等) を skip して AI コスト削減。
"""
from __future__ import annotations

import pytest

from scrapers.extraction_filter import (
    SKIP_COLOR_SIZE_KEYWORDS,
    should_skip_color_size,
)


pytestmark = pytest.mark.offline


# --------------------------------------------------------------------------
# TCG 検出 (skip 対象)
# --------------------------------------------------------------------------
class TestShouldSkipColorSizeTCG:
    @pytest.mark.parametrize("title", [
        "2025 ONE PIECE JP タシギ 公式イベント賞",
        "ステューシー SR-SPC OP07-085 PSA10",
        "極美品　サボ リーダーパラレル OP05-001 PSA10 Lパラ",
        "2023 ONE PIECE モンキー・D・ルフィ #033　PSA9",
        "ワンピース ロビン アジア限定 日本未発売 PSA10 ニコ•ロビン",
        "PSA10】ワンピースカード　カヤ　スタンダードバトル優勝記念品",
        "ポケモンカード リザードン VMAX 美品",
        "ポケカ 25th アニバーサリー BOX",
        "遊戯王 青眼の白龍 シークレット",
        "デュエマ ボルメテウス・ホワイト・ドラゴン",
        "デュエル・マスターズ デッドリースケアクロウ",
        "デュエルマスターズ パック",  # 中黒なし版
        "ヴァイスシュヴァルツ ホロライブ プロモ",
    ])
    def test_tcg_titles_should_skip(self, title):
        assert should_skip_color_size(title=title, description="") is True

    @pytest.mark.parametrize("description", [
        "PSA9 鑑定済み",
        "BGS 9.5 評価",
        "BGS10 完璧グレード",
        "CGC 9.5 鑑定済",
        "リーダーパラレルカード",
        "公式イベント賞品",
        "ワンピースカードゲームの公式 promo",
    ])
    def test_tcg_in_description_should_skip(self, description):
        assert should_skip_color_size(title="商品", description=description) is True

    def test_real_world_dry_run_tcg_examples(self):
        """実 dry-run で観測された 6 件 TCG が全部 skip される."""
        cases = [
            ("2025 ONE PIECE JP タシギ 公式イベント賞", ""),
            ("ステューシー SR-SPC OP07-085", "PSA10"),
            ("極美品　サボ リーダーパラレル OP05-001 PSA10 Lパラ", ""),
            ("2023 ONE PIECE モンキー・D・ルフィ #033　PSA9", ""),
            ("ワンピース ロビン アジア限定 日本未発売 PSA10 ニコ•ロビン", ""),
            ("PSA10】ワンピースカード　カヤ", ""),
        ]
        for title, desc in cases:
            assert should_skip_color_size(title, desc) is True, (
                f"TCG 検出失敗: title={title!r}, desc={desc!r}"
            )


# --------------------------------------------------------------------------
# 非 TCG (skip しない)
# --------------------------------------------------------------------------
class TestShouldSkipColorSizeNonTCG:
    @pytest.mark.parametrize("title", [
        "【モンベル】ライトシェルパーカー フルジップ クリマプラス 刺繡ロゴ XL",
        "mont-bell モンベル O.D.パーカー ネイビー XL",
        "新品　モンベル　ライトシェルパーカ Men's　赤　登山",
        "⭐️美品　モンベル　EXライト ウインドジャケット Men's　XL",
        "mont-bell モンベル 1103247 O.D. アノラックパーカーXL",
        "【未使用】montbell O.D.アノラック オレンジ XL",
        "UNIQLO Tシャツ Mサイズ ブラック",
        "Porter ショルダーバッグ ブラウン",
        "G-SHOCK GA-110 ブラック",
    ])
    def test_non_tcg_should_not_skip(self, title):
        assert should_skip_color_size(title=title, description="") is False

    def test_montbell_real_world_examples(self):
        """実 dry-run の montbell 7 件が全部 skip されない (色/サイズ抽出継続)."""
        cases = [
            "【モンベル】ライトシェルパーカー フルジップ クリマプラス 刺繡ロゴ XL",
            "mont-bell モンベル O.D.パーカー ネイビー XL",
            "新品　モンベル　ライトシェルパーカ Men's　赤　登山　ナイロン　防風　はっ水",
            "⭐️美品　モンベル　ライトシェルパーカ Men's　赤　XL　登山　防風ナイロン",
            "⭐️美品　モンベル　EXライト ウインドジャケット Men's　XL　緑　防風",
            "mont-bell モンベル 1103247 O.D. アノラックパーカーXL",
            "【未使用】montbell O.D.アノラック オレンジ XL",
        ]
        for title in cases:
            assert should_skip_color_size(title, "") is False, (
                f"montbell 誤判定: title={title!r}"
            )


# --------------------------------------------------------------------------
# エッジケース
# --------------------------------------------------------------------------
class TestEdgeCases:
    def test_empty_inputs(self):
        assert should_skip_color_size(title="", description="") is False
        assert should_skip_color_size(title=None, description=None) is False  # type: ignore[arg-type]

    def test_keyword_in_title_or_description(self):
        # title だけにあっても skip
        assert should_skip_color_size(title="PSA10 商品", description="") is True
        # description だけにあっても skip
        assert should_skip_color_size(title="商品", description="PSA10") is True

    def test_case_insensitive_psa(self):
        # 大文字小文字無視
        assert should_skip_color_size(title="psa10 鑑定品", description="") is True
        assert should_skip_color_size(title="Psa 10 graded", description="") is True

    def test_keywords_list_not_empty(self):
        # whitelist 構造保護: SKIP_COLOR_SIZE_KEYWORDS が空配列にならないこと
        assert len(SKIP_COLOR_SIZE_KEYWORDS) > 5
        # 主要キーワードが入ってる
        assert "psa10" in [kw.lower() for kw in SKIP_COLOR_SIZE_KEYWORDS]
        assert "ワンピースカード" in SKIP_COLOR_SIZE_KEYWORDS
        assert "ポケカ" in SKIP_COLOR_SIZE_KEYWORDS
