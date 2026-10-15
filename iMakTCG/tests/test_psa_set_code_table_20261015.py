# -*- coding: utf-8 -*-
"""2026-10-15 残務 №330: PSA のセット名 → セット記号を、今の引き方が引けなかった時だけカタログの表で補う。"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

YAML = """
pokemon_tcg:
  - {psa_brand: "POKEMON JAPANESE SWORD & SHIELD SHINY STAR V", set_codes: [S4a], status: ok}
  - {psa_brand: "POKEMON JAPANESE SUN & MOON EEVEE GX STARTER SET", set_codes: [], status: not_in_catalog}
  - {psa_brand: "POKEMON JAPANESE MULTI", set_codes: [A, B], status: multi}
"""


def _mod():
    m = types.SimpleNamespace()
    m.extract_set_code_from_brand_pokemon = lambda b: "SV2a" if "151" in b else None
    m.lookup_pokemon = lambda brand, num: (m.extract_set_code_from_brand_pokemon(brand), num)
    return m


def test_fills_only_when_existing_lookup_returns_none(tmp_path):
    import psa_set_code_table as P
    p = tmp_path / "t.yaml"
    p.write_text(YAML, encoding="utf-8")
    m = _mod()
    assert P.install(m, str(p)) == 1
    assert m.extract_set_code_from_brand_pokemon("POKEMON JAPANESE SV2a 151") == "SV2a"          # 今引ける物は変わらない
    assert m.extract_set_code_from_brand_pokemon("pokemon japanese sword & shield  shiny star v") == "S4a"  # 引けなかった物を補う
    assert m.lookup_pokemon("POKEMON JAPANESE SWORD & SHIELD SHINY STAR V", "323") == ("S4a", "323")  # lookup の中からも効く
    assert m.extract_set_code_from_brand_pokemon("POKEMON JAPANESE SUN & MOON EEVEE GX STARTER SET") is None  # not_in_catalog は使わない
    assert m.extract_set_code_from_brand_pokemon("POKEMON JAPANESE MULTI") is None                 # multi は使わない
    assert P.install(m, str(p)) == 0                                                              # 2回付けない


def test_unreadable_table_changes_nothing(tmp_path):
    import psa_set_code_table as P
    m = _mod()
    f = m.extract_set_code_from_brand_pokemon
    assert P.install(m, str(tmp_path / "none.yaml")) == 0
    assert m.extract_set_code_from_brand_pokemon is f


def test_real_table_has_the_known_example():
    import psa_set_code_table as P
    t = P.load_table()
    if t:
        assert t["pokemon_tcg"]["POKEMON JAPANESE SWORD & SHIELD SHINY STAR V"] == "S4a"
