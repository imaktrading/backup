"""レアリティ/キャラが構造的に存在しない種別を必須チェックから外す (2026-07-29).

出所: `hq/requests/2026-07-29_audit_exclusions_final_and_rarity_in_title.md` (Advisor 経由)。
Catalog が **1件ずつ実機判定**して「取れなかった」ではなく **「存在しない」**と確定したもの:
  - dragonball_scg ENERGY MARKER 257件 (同base に rarity 持ち兄弟 0件)
  - gundam_tcg RESOURCE 140 / EX RESOURCE 13 / EX BASE 13
これらは C:Character(登場キャラ概念)も持たない。

★粒度は card_type / 番号 prefix 単位。**カテゴリ丸ごとの除外は禁止**(本当の欠損を見逃すため)。
"""
import os
import sys

sys.path.insert(0, os.path.normpath(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "iMakTCG")))

from check_csv import REQUIRED_SPECIFICS, required_specifics_for_card as req  # noqa: E402


def test_normal_card_requires_everything():
    assert req("OP09-020", "Event") == REQUIRED_SPECIFICS
    assert req("073/066", "Pokémon") == REQUIRED_SPECIFICS


def test_don_card_keeps_existing_behavior():
    """2026-07-02 に入れた DON!! の除外を壊さない。"""
    out = req("DON-PRB02-018", "Don")
    assert "C:Rarity" not in out


def test_gundam_resource_drops_rarity_and_character():
    for ct in ("Resource", "EX Resource", "EX Base"):
        out = req("RP-024", ct)
        assert "C:Rarity" not in out, ct
        assert "C:Character" not in out, ct


def test_dbscg_energy_marker_drops_rarity_and_character():
    out = req("E-60", "Energy Marker")
    assert "C:Rarity" not in out
    assert "C:Character" not in out


def test_number_prefix_alone_is_enough():
    """card_type が空でも RP- 番号なら Resource と判る(生成側が type を落とすことがある)。"""
    assert "C:Rarity" not in req("RP-027", "")


def test_case_insensitive():
    assert "C:Rarity" not in req("", "ENERGY MARKER")
    assert "C:Rarity" not in req("rp-001", "")


def test_other_specs_survive():
    """除外するのは非該当の2つだけ。Game/Set/Card Name まで落とさない。"""
    out = req("RP-024", "Resource")
    for s in ("C:Game", "C:Set", "C:Card Name"):
        assert s in out


def test_whole_category_is_not_excluded():
    """同じ Gundam でも通常カードは必須のまま(カテゴリ丸ごと除外の禁止)。"""
    assert req("ST02-010", "Unit") == REQUIRED_SPECIFICS
