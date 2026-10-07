"""ポケカのミラーの版の行 (<通常版>_mb / _pb / _rk) を使う (2026-10-07 catalog 回答・ユーザー「正しく作成できるなら、やって」)。

- 刷りの確認: ラベルの版 (MASTER BALL / POKE BALL / ROCKET REVERSE HOLO) と行の specs.variant_psa_text を突き合わせる
- タイトル: 版の行なら PSA の表記を必ず入れる
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "iMakTCG"))
import psa_variant_gate as G  # noqa: E402
import tcg_listing_fields as T  # noqa: E402


def test_mirror_text():
    assert G.mirror_text("RAYQUAZA POKÉ BALL REVERSE HOLO") == "POKE BALL REVERSE HOLO"
    assert G.mirror_text("PERSIAN MASTER BALL REVERSE HOLO") == "MASTER BALL REVERSE HOLO"
    assert G.mirror_text("PIKACHU REVERSE HOLO") == ""                 # 版名なしはまだ見ない
    assert G.mirror_text("") == ""


def test_conflict_by_variant_text():
    base = {"product_id": "M2a-127", "specs": "{}"}
    pb = {"product_id": "M2a-127_pb", "specs": '{"variant_psa_text": "POKE BALL REVERSE HOLO"}'}
    b = "POKEMON JAPANESE M2A-MEGA DREAM EX"
    assert G.conflict("pokemon_tcg", b, "RAYQUAZA POKE BALL REVERSE HOLO", base)
    assert not G.conflict("pokemon_tcg", b, "RAYQUAZA POKE BALL REVERSE HOLO", pb)
    assert G.conflict("pokemon_tcg", b, "RAYQUAZA", pb)
    assert not G.conflict("pokemon_tcg", b, "RAYQUAZA", base)


def test_title_keeps_mirror_name():
    f = {"C:Game": "Pokémon TCG", "C:Language": "Japanese", "C:Set": "Mega Dream ex", "C:Card Number": "127/193",
         "C:Character": "Rayquaza", "C:Rarity": "Rare", "C:Year Manufactured": "2025",
         "_mirror": "Poke Ball Reverse Holo"}
    t = T.build_title_from_fields(f)
    assert "Poke Ball Reverse Holo" in t and len(t) <= 80
