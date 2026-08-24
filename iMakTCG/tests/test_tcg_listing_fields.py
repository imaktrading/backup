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
    # 2026-08-22 契約: Features は catalog の features_ebay だけを写す (生 features は使わない)。
    # 2026-08-25: 複数値の区切りは **縦棒**。読点だと eBay が1値の自由文として持ち、
    #             正規値の絞り込みに当たらない (実測 itemID 820035999901)。
    specs = {"_name_en": "Scrafty", "character_name": "Scrafty",
             "rarity_ebay": "Art Rare", "features_ebay": ["Full Art", "Promo"]}
    f = map_specs_to_fields(specs)
    assert f["C:Features"] == "Full Art|Promo"


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
                "C:Features", "C:Language", "C:Year Manufactured", "C:Card Size"):
        assert col in f


# (C) Card Size: catalog card_size_ebay をコピー (旧 "Japanese" ハードコード是正)
def test_card_size_from_catalog():
    specs = {"_name_en": "Pikachu", "character_name": "Pikachu",
             "card_size_ebay": "Standard", "_language": "ja"}
    f = map_specs_to_fields(specs, "2025")
    assert f["C:Card Size"] == "Standard"


# (C) Card Size: catalog に無くても確証ある既定 'Standard' (旧の "Japanese" を出さない)
def test_card_size_default_standard_when_missing():
    specs = {"_name_en": "Pikachu", "character_name": "Pikachu", "_language": "ja"}
    f = map_specs_to_fields(specs, "2025")
    assert f["C:Card Size"] == "Standard"     # 推測でなく市場標準・catalog全件Standard
    assert f["C:Card Size"] != "Japanese"     # 旧コアのハードコード誤りを是正


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


def test_title_no_cross_field_word_dup_super():
    # Set"Super Electric Breaker" + Rarity"Super Rare" → "Super" 重複させない (Rarity を足さない)
    specs = {"_name_en": "Pikachu Ex", "character_name": "Pikachu ex",
             "set_name_ebay": "Super Electric Breaker", "rarity_ebay": "Super Rare",
             "game_ebay": "Pokémon TCG", "card_number_text": "122/106", "_language": "ja"}
    t = build_title_from_fields(map_specs_to_fields(specs, "2024"))
    assert t.lower().split().count("super") == 1, f"'super' 重複: {t}"
    assert "Super Electric Breaker" in t            # Set(同定)は死守


def test_title_core_legit_word_repeat_kept():
    # core 同士の正当な重複 (Set"Mega Brave" + Character"Mega Venusaur") は保持 (落とさない)
    specs = {"_name_en": "Mega Venusaur ex", "character_name": "Mega Venusaur ex",
             "set_name_ebay": "Scarlet & Violet—Mega Brave", "rarity_ebay": "",
             "game_ebay": "Pokémon TCG", "card_number_text": "087/063", "_language": "ja"}
    t = build_title_from_fields(map_specs_to_fields(specs, "2025"))
    assert "Mega Brave" in t and "Mega Venusaur" in t   # 両方の Mega を死守


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


# --- verify→build: forced_card_id で指定カードから決定論生成 ---
def test_forced_card_id_builds_from_given_id():
    from tcg_listing_fields import build_listing_fields
    # 人が確定した product_id を直接採用 (cert→card_id 自動解決をスキップ)。実 catalog 参照。
    f, err = build_listing_fields("0000000", forced_card_id="S6K-037")
    assert err is None
    assert f["_card_id"] == "S6K-037"
    assert f["C:Card Size"] == "Standard"
    assert f["C:Set"]                      # set_name_ebay が入る
    # 存在しない card_id は err
    f2, err2 = build_listing_fields("0000000", forced_card_id="NOPE-999")
    assert err2 and f2 == {}


# --- eBay 正規化フィールド (catalog *_ebay 由来・最大活用 2026-06-15) ---
def test_cost_from_raw_clean_integer():
    # cost はどのゲームも clean 整数 → raw 直結 (即活用)
    f = map_specs_to_fields({"_name_en": "Yamato", "character_name": "Yamato", "cost": "4"})
    assert f["C:Cost"] == "4"


def test_attack_power_only_from_ebay_not_raw():
    # power は DragonBall が不正値を持つ → raw は使わず catalog attack_power_ebay のみ
    f = map_specs_to_fields({"_name_en": "X", "character_name": "X",
                             "power": "15000 / (裏)20000", "attack_power_ebay": "15000"})
    assert f["C:Attack/Power"] == "15000"        # 正規化済を採用
    f2 = map_specs_to_fields({"_name_en": "X", "character_name": "X", "power": "15000 / (裏)20000"})
    assert f2["C:Attack/Power"] == ""            # raw の不正値は入れない (catalog 正規化待ち)


def test_color_only_from_ebay_not_raw_japanese():
    # color は日本語 (緑/赤) → raw は使わず color_ebay のみ
    f = map_specs_to_fields({"_name_en": "X", "character_name": "X", "color": "緑/黄"})
    assert f["C:Attribute/MTG:Color"] == ""      # 日本語 raw は入れない
    f2 = map_specs_to_fields({"_name_en": "X", "character_name": "X", "color_ebay": "Green"})
    assert f2["C:Attribute/MTG:Color"] == "Green"


def test_hp_stage_forward_compatible_from_ebay():
    # HP/Stage は catalog *_ebay が来れば流れる (forward-compatible)
    f = map_specs_to_fields({"_name_en": "X", "character_name": "X",
                             "hp_ebay": "320", "stage_ebay": "Basic"})
    assert f["C:HP"] == "320"
    assert f["C:Stage"] == "Basic"
    # 未充填なら空欄 (回帰なし)
    f2 = map_specs_to_fields({"_name_en": "X", "character_name": "X"})
    assert f2["C:HP"] == "" and f2["C:Stage"] == ""


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


# (5a) description Specs の Language は C:Language をそのまま転記 (空→行省略・無条件Japanese禁止)
def test_specs_pairs_language_not_forced_japanese():
    from tcg_listing_fields import specs_pairs_from_fields, build_tcg_specs_html
    # 英語/言語不明 (C:Language 空) → description に "Japanese" を出さない
    pairs = specs_pairs_from_fields({"C:Card Name": "Pikachu", "C:Language": ""})
    assert ("Language", "") in pairs
    html = build_tcg_specs_html(pairs)
    assert "Japanese" not in html           # 無条件 Japanese 埋め禁止 (誤表示防止)
    # 日本語カードは C:Language='Japanese' が転記される
    pairs2 = specs_pairs_from_fields({"C:Card Name": "Pikachu", "C:Language": "Japanese"})
    assert ("Language", "Japanese") in pairs2


def test_map_specs_features_normalized_in_field():
    """★2026-08-22 契約: 出品側で生 features を正規化しない (語彙の判断は catalog の持ち物)。

    生 features しか無い行は **空欄**で出す。旧の変換表で埋め戻すと catalog の穴が見えなくなり、
    レアリティ語が Features に載る事故が起きた (2026-08-22 に 4件)。
    """
    specs = {"_name_en": "Scrafty", "character_name": "Scrafty",
             "set_name_ebay": "Scarlet & Violet—White Flare", "rarity_ebay": "Art Rare",
             "features": ["Art Card"], "_language": "ja"}
    f = map_specs_to_fields(specs, "2025")
    assert f["C:Features"] == ""              # 生値は使わない → 空欄
    specs["features"] = ["Alt Art"]
    f2 = map_specs_to_fields(specs, "2025")
    assert f2["C:Features"] == ""             # 出品側で 'Alternative Art' に化けさせない
    specs["features_ebay"] = "Alternative Art"   # catalog が決めた値なら str 単値でもそのまま写す
    f3 = map_specs_to_fields(specs, "2025")
    assert f3["C:Features"] == "Alternative Art"
