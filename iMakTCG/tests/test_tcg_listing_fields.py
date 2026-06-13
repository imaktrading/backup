"""tcg_listing_fields (新生成コア) の回帰テスト (2026-06-13・並行ビルド)。

catalog specs → eBay Item Specifics の決定論マッピングが、旧生成の2バグを潰すことを固定:
  - #1 rarity 推測: rarity_ebay 無 → C:Rarity 空欄 (推測 'Common' を入れない)
  - #4 Subject 汚染: C:Card Name/Character は catalog 値のみ (PSA Subject を混ぜない)
純関数 map_specs_to_fields を DB/network 非依存でテスト。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tcg_listing_fields import map_specs_to_fields


# #1 SVOM-020 相当: rarity_ebay 無 → 空欄 (推測しない)
def test_rarity_blank_when_catalog_missing():
    specs = {"_name_en": "Marnie's Morpeko", "character_name": "Marnie's Morpeko",
             "game_ebay": "Pokémon TCG", "card_type_ebay": "Pokémon",
             "card_number_text": "020/019", "_language": "ja"}
    f = map_specs_to_fields(specs, year="2025")
    assert f["C:Rarity"] == ""               # 推測 'Common' を入れない
    assert f["C:Card Name"] == "Marnie's Morpeko"
    assert f["C:Language"] == "Japanese"
    assert f["C:Year Manufactured"] == "2025"


# #4 S8b-118 相当: catalog 値のみ・Subject 由来 'Vmax Climax' を混ぜない
def test_no_subject_pollution_in_name_and_character():
    specs = {"_name_en": "Zamazenta V", "character_name": "Zamazenta V",
             "set_name_ebay": "VMAX Climax", "rarity_ebay": "Double Rare",
             "game_ebay": "Pokémon TCG", "card_type_ebay": "Pokémon",
             "card_number_text": "118/184", "_language": "ja"}
    f = map_specs_to_fields(specs)
    assert f["C:Card Name"] == "Zamazenta V"     # 'Vmax Climax' 混入なし
    assert f["C:Character"] == "Zamazenta V"
    assert f["C:Set"] == "VMAX Climax"           # catalog 修正後の正値
    assert f["C:Rarity"] == "Double Rare"


# features list → 連結
def test_features_list_joined():
    specs = {"_name_en": "Scrafty", "character_name": "Scrafty",
             "rarity_ebay": "Art Rare", "features": ["Art Card"]}
    f = map_specs_to_fields(specs)
    assert f["C:Features"] == "Art Card"


# name_en ≠ character_name (romaji 修正漏れ) → そのまま出して可視化 (papering over しない)
def test_name_en_character_name_divergence_surfaced():
    specs = {"_name_en": "Irida", "character_name": "Kai", "_language": "ja"}
    f = map_specs_to_fields(specs)
    assert f["C:Card Name"] == "Irida"    # name_en 優先
    assert f["C:Character"] == "Kai"      # character_name = 不整合をそのまま露出


# 全列が必ず存在 (空欄でも)
def test_all_columns_present():
    f = map_specs_to_fields({"_name_en": "Pikachu"})
    for col in ("C:Game", "C:Set", "C:Card Name", "C:Character", "C:Rarity",
                "C:Features", "C:Language", "C:Year Manufactured"):
        assert col in f
