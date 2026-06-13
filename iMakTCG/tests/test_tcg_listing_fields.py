"""tcg_listing_fields (新生成コア) の回帰テスト (2026-06-13・並行ビルド)。

catalog specs → eBay Item Specifics の決定論マッピングが、旧生成の2バグを潰すことを固定:
  - #1 rarity 推測: rarity_ebay 無 → C:Rarity 空欄 (推測 'Common' を入れない)
  - #4 Subject 汚染: C:Card Name/Character は catalog 値のみ (PSA Subject を混ぜない)
純関数 map_specs_to_fields を DB/network 非依存でテスト。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tcg_listing_fields import map_specs_to_fields, build_title_from_fields


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
    # 2026-06-14: features は eBay facet 正規化される。facet 値の list は ", " 連結。
    specs = {"_name_en": "Scrafty", "character_name": "Scrafty",
             "rarity_ebay": "Art Rare", "features": ["Full Art", "Promo"]}
    f = map_specs_to_fields(specs)
    assert f["C:Features"] == "Full Art, Promo"


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


# --- タイトル生成 (catalog 由来・LLM/Subject 無し) ---
def test_title_correct_set_no_pollution_japanese():
    """#4 相当: 正しい set名・Subject汚染なし・Japanese明記・≤80字。"""
    specs = {"_name_en": "Zamazenta V", "character_name": "Zamazenta V",
             "set_name_ebay": "VMAX Climax", "rarity_ebay": "Double Rare",
             "game_ebay": "Pokémon TCG", "card_type_ebay": "Pokémon",
             "card_number_text": "118/184", "_language": "ja"}
    f = map_specs_to_fields(specs, year="2021")
    t = build_title_from_fields(f)
    assert len(t) <= 80
    assert t.startswith("PSA 10 Pokemon")
    assert "Japanese" in t
    assert "VMAX Climax" in t
    assert "Brilliant Stars" not in t          # 旧の誤set名が出ない
    assert "#118/184" in t
    assert "Zamazenta V" in t
    assert "Vmax Climax #118" not in t         # Subject汚染パターンが出ない


def test_title_no_duplicate_words():
    specs = {"_name_en": "Scrafty", "character_name": "Scrafty",
             "set_name_ebay": "Scarlet & Violet—White Flare", "rarity_ebay": "Art Rare",
             "game_ebay": "Pokémon TCG", "card_number_text": "137/086", "_language": "ja"}
    t = build_title_from_fields(map_specs_to_fields(specs, "2025"))
    words = [w.lower() for w in t.split() if len(w) >= 4]
    assert len(words) == len(set(words)), f"重複語: {t}"
    assert len(t) <= 80


def test_title_blank_set_skipped():
    """C:Set 空 (SVOM) でも空文字が紛れ込まない。"""
    specs = {"_name_en": "Marnie's Morpeko", "character_name": "Marnie's Morpeko",
             "game_ebay": "Pokémon TCG", "card_number_text": "020/019", "_language": "ja"}
    t = build_title_from_fields(map_specs_to_fields(specs, "2025"))
    assert "  " not in t                       # 二重スペース無し
    assert t == "PSA 10 Pokemon Japanese #020/019 Marnie's Morpeko 2025"


# --- Features 正規化 (2026-06-14): catalog生値 → eBay TCG facet 値 / 不明はdrop ---
def test_features_normalize_maps_known_values():
    from tcg_listing_fields import normalize_tcg_features
    assert normalize_tcg_features(["Alt Art"]) == ["Alternative Art"]
    assert normalize_tcg_features(["Promo"]) == ["Promo"]
    assert normalize_tcg_features(["Full Art"]) == ["Full Art"]       # facet一致
    assert normalize_tcg_features("Limited Edition") == ["Limited Edition"]


def test_features_normalize_drops_rarity_and_unknown():
    from tcg_listing_fields import normalize_tcg_features
    # rarity語/type語/非facet生値は drop (推測で 'Full Art' 化しない)
    assert normalize_tcg_features(["Ultra Rare"]) == []
    assert normalize_tcg_features(["Secret"]) == []
    assert normalize_tcg_features(["Leader Card"]) == []
    assert normalize_tcg_features(["Art Card"]) == []


def test_features_normalize_mixed_and_dedup():
    from tcg_listing_fields import normalize_tcg_features
    assert normalize_tcg_features(["Ultra Rare", "Alt Art", "Alt Art"]) == ["Alternative Art"]


def test_map_specs_features_normalized_in_field():
    specs = {"_name_en": "Scrafty", "character_name": "Scrafty",
             "set_name_ebay": "Scarlet & Violet—White Flare", "rarity_ebay": "Art Rare",
             "features": ["Art Card"], "_language": "ja"}
    f = map_specs_to_fields(specs, "2025")
    assert f["C:Features"] == ""              # 'Art Card' は drop → 空欄 (旧の非facet値を出さない)
    specs["features"] = ["Alt Art"]
    f2 = map_specs_to_fields(specs, "2025")
    assert f2["C:Features"] == "Alternative Art"
