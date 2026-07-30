# -*- coding: utf-8 -*-
"""Pokemon hi-class / Classic / スタートデッキ100 系の C:Rarity 除外 回帰テスト (2026-07-31).

Advisor 依頼 `2026-07-29_audit_exclusions_final_and_rarity_in_title.md` §1:
  「set 名の部分一致は却下、set code prefix で判定」
  「rarity が公式に存在しない → 空欄が正 → 監査必須から外す」

対象 set code prefix (実 output 済 11 件):
  S8b  VMAXクライマックス     (S8b-101, S8b-126)
  M2a  MEGAドリームex        (M2a-012, M2a-079)  ← 2026-07-29 実害
  SM8b GXウルトラシャイニー   (SM8b-001, SM8b-089, SM8b-105)
  SV4a シャイニートレジャーex (SV4a-055)
  S6K                       (S6K-037)
  XY   プロモ系              (XY-139, XY-140)
  HSZm BW期プロモ           (HSZm-014)

+ Classic / スタートデッキ100 系 (番号 prefix):
  MC-  / SI-  / CP4- / CP5-
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_pokemon_hi_class_set_prefixes_drop_rarity():
    """S8b/M2a/SM8b/SV4a/S6K/XY/HSZm は C:Rarity 必須から外れる。"""
    from check_csv import required_specifics_for_card
    for cardno in ["S8b-101", "S8b-126", "M2a-012", "M2a-079",
                   "SM8b-001", "SM8b-089", "SM8b-105",
                   "SV4a-055", "S6K-037", "XY-139", "XY-140", "HSZm-014"]:
        req = required_specifics_for_card(cardno, "")
        assert "C:Rarity" not in req, \
            f"{cardno}: C:Rarity 必須のまま (hi-class prefix 除外が効いていない)"


def test_pokemon_start_deck_100_and_classic_prefixes_drop_rarity():
    """MC-* / SI-* (スタートデッキ100) / CP4-*/CP5- (Classic) も除外。"""
    from check_csv import required_specifics_for_card
    for cardno in ["MC-001", "SI-002", "CP4-003", "CP5-042"]:
        req = required_specifics_for_card(cardno, "")
        assert "C:Rarity" not in req, \
            f"{cardno}: C:Rarity 必須のまま (start-deck/Classic prefix 除外が効いていない)"


def test_pokemon_normal_expansion_still_requires_rarity():
    """通常拡張パック (SV10/SV4 通常/S8a 等 hi-class 系でない) は C:Rarity 必須のまま。

    ★ Advisor 明示指示: 「カテゴリ丸ごとの除外は本当の欠損を見逃すので禁止」
    """
    from check_csv import required_specifics_for_card
    for cardno in ["SV10-001", "SV4-025", "S8a-005", "SV-P-100"]:
        req = required_specifics_for_card(cardno, "")
        assert "C:Rarity" in req, \
            f"{cardno}: C:Rarity 過剰除外 (通常拡張は必須のまま維持)"


def test_don_and_resource_prefixes_still_drop_rarity():
    """既存挙動 (DON!!/Gundam RESOURCE) の回帰。"""
    from check_csv import required_specifics_for_card
    assert "C:Rarity" not in required_specifics_for_card("DON-PRB01-027", "")
    assert "C:Rarity" not in required_specifics_for_card("RP-022", "")


def test_energy_marker_and_resource_types_still_drop_rarity_and_character():
    """既存挙動 (dragonball_scg ENERGY MARKER / gundam_tcg RESOURCE) の回帰。"""
    from check_csv import required_specifics_for_card
    req = required_specifics_for_card("SOMETHING-001", "energy marker")
    assert "C:Rarity" not in req and "C:Character" not in req
    req = required_specifics_for_card("SOMETHING-001", "resource")
    assert "C:Rarity" not in req and "C:Character" not in req


def test_case_insensitive_matching():
    """card_number は小文字/大文字混在でも判定。"""
    from check_csv import required_specifics_for_card
    for cardno in ["s8b-101", "M2A-012", "sm8b-001", "XY-139", "hszm-014"]:
        assert "C:Rarity" not in required_specifics_for_card(cardno, "")


def test_pokemon_prefix_list_defined_at_module_scope():
    """定数として module-level に定義されていることを固定 (Advisor 指示: prefix 単位)。"""
    import check_csv
    assert hasattr(check_csv, "NO_RARITY_POKEMON_SET_PREFIXES"), \
        "NO_RARITY_POKEMON_SET_PREFIXES が module-scope に無い"
    prefixes = check_csv.NO_RARITY_POKEMON_SET_PREFIXES
    for expected in ("s8b-", "m2a-", "sm8b-", "sv4a-", "s6k-", "xy-", "hszm-"):
        assert expected in prefixes, f"expected prefix missing: {expected}"


def test_pokemon_number_prefix_list_contains_classic():
    """CP4-/CP5-/MC-/SI- が NO_RARITY_NUMBER_PREFIXES に含まれる (2026-07-30 追加)。"""
    import check_csv
    for expected in ("mc-", "si-", "cp4-", "cp5-"):
        assert expected in check_csv.NO_RARITY_NUMBER_PREFIXES, \
            f"expected number prefix missing: {expected}"
