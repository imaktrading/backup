# -*- coding: utf-8 -*-
"""カタログ権威の列を契約表から決める (2026-08-25 提案4 / 2026-08-26 実装)。

守るもの:
  1. 契約表で `source: specs.*` の項目に当たる列は **全部** カタログ権威
     (= 新コアが空なら CSV も空。旧コアの値を残さない)
  2. 表が読めない時は 8/22 に直した 4列だけの退避値に戻る (fail-safe)
  3. 実際に出た誤値 (8/23〜8/26 の入稿) が override 後に消えること

経緯: 事故のたびに `_ALWAYS_OVERWRITE` へ 1列ずつ足していたので、**まだ足していない列**で
同じ事故が出続けた。8/23〜8/26 の入稿 4本で C:Cost 21 / C:Attack/Power 18 / C:Attribute 2 =
41セルが catalog に無い値だった。
依頼書: hq/requests/2026-08-25_act_code_proposals_tcg.md 提案4 /
        回答書: hq/requests/2026-08-26_act_code_proposals_tcg_response.md
"""
import os
import sys

import pytest

_TCG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "iMakTCG")
if _TCG not in sys.path:
    sys.path.insert(0, _TCG)

import tcg_new_gen_override as O  # noqa: E402

# 実際の表と同じ形の最小 fixture (表そのものには依存しない = 純関数テスト)
_CONTRACT = {
    "Attack/Power":        {"emit": True,  "source": "specs.attack_power_ebay"},
    "Cost":                {"emit": True,  "source": "specs.cost"},
    "Attribute/MTG:Color": {"emit": True,  "source": "specs.color_ebay"},
    "HP":                  {"emit": True,  "source": "specs.hp_ebay"},
    "Card Name":           {"emit": True,  "source": "column.name_en"},   # specs. でない
    "Year Manufactured":   {"emit": True,  "source": "psa_cert"},         # specs. でない
    "Finish":              {"emit": False, "source": None},               # 出さない
}
_COLS = ["C:Attack/Power", "C:Cost", "C:Attribute/MTG:Color", "C:HP",
         "C:Card Name", "C:Year Manufactured", "C:Finish"]


def test_specs_sourced_columns_are_authoritative():
    got = O.contract_authoritative_cols(contract=_CONTRACT, cols=_COLS)
    assert got == {"C:Attack/Power", "C:Cost", "C:Attribute/MTG:Color", "C:HP"}, got


def test_non_specs_and_emit_false_are_not_authoritative():
    got = O.contract_authoritative_cols(contract=_CONTRACT, cols=_COLS)
    for col in ("C:Card Name", "C:Year Manufactured", "C:Finish"):
        assert col not in got, f"{col} は catalog の specs 由来ではない (空欄化してはいけない)"


def test_falls_back_when_contract_unreadable():
    # 表が読めない (= None) / 1列も当たらない → 8/22 に直した 4列は権威のまま
    assert O.contract_authoritative_cols(contract={}, cols=_COLS) == \
        O._ALWAYS_OVERWRITE_FALLBACK
    assert O.contract_authoritative_cols(contract=_CONTRACT, cols=["C:Card Name"]) == \
        O._ALWAYS_OVERWRITE_FALLBACK


def test_live_contract_covers_the_columns_that_leaked():
    """実際の表でも、8/25〜8/26 に誤値が出た 3列が権威になっていること。"""
    cols = O.contract_authoritative_cols()
    for col in ("C:Attack/Power", "C:Cost", "C:Attribute/MTG:Color"):
        assert col in cols, f"{col} が権威列に入っていない (41セルの再発源)"


# --- 行に適用したときの振る舞い (提案1・2・3 の 3セルがそのまま消えること) ---

_HEADERS = ["*Title", "C:Game", "C:Grade", "C:Attack/Power", "C:Cost",
            "C:Attribute/MTG:Color", "C:HP", "C:Card Name"]


def _row(power, cost, attr, hp):
    return ["old title", "Pokémon TCG", "10", power, cost, attr, hp, "Rayquaza"]


def test_blank_catalog_values_clear_the_old_cores_leftovers(monkeypatch):
    """catalog が空の列に旧コアの値 (HP の写し / Leader の LIFE / Vision の色) を残さない。"""
    fields = {"C:Attack/Power": "", "C:Cost": "", "C:Attribute/MTG:Color": "",
              "C:HP": "250", "C:Card Name": "Rayquaza", "_card_id": "pokemon_tcg:SM11-112"}
    monkeypatch.setattr(O, "_AUTH_COLS_CACHE",
                        {"C:Attack/Power", "C:Cost", "C:Attribute/MTG:Color", "C:HP"})
    monkeypatch.setitem(sys.modules, "tcg_listing_fields", _FakeFields(fields))
    out = O.apply_new_gen_override(_row("250", "4", "Pokémon", "250"), _HEADERS,
                                   "141208100", override_title=False)
    assert out[_HEADERS.index("C:Attack/Power")] == ""   # 8/25 提案1 (HP の写し)
    assert out[_HEADERS.index("C:Cost")] == ""           # 8/25 提案2 (Leader の LIFE)
    assert out[_HEADERS.index("C:Attribute/MTG:Color")] == ""  # 8/25 提案3 (Vision の色)
    assert out[_HEADERS.index("C:HP")] == "250"          # catalog が持つ値はそのまま
    assert out[_HEADERS.index("C:Card Name")] == "Rayquaza"    # 権威外の列は触らない


def test_non_authoritative_column_keeps_old_value(monkeypatch):
    """権威列でない列は従来どおり value-only (情報欠落の回帰を作らない)。"""
    fields = {"C:Card Name": "", "C:Attack/Power": "", "_card_id": "x:y"}
    monkeypatch.setattr(O, "_AUTH_COLS_CACHE", {"C:Attack/Power"})
    monkeypatch.setitem(sys.modules, "tcg_listing_fields", _FakeFields(fields))
    out = O.apply_new_gen_override(_row("250", "4", "Pokémon", "250"), _HEADERS,
                                   "1", override_title=False)
    assert out[_HEADERS.index("C:Card Name")] == "Rayquaza"


class _FakeFields:
    """`from tcg_listing_fields import ...` を差し替えるための最小 stub。"""

    def __init__(self, fields):
        self._fields = fields

    def build_listing_fields(self, cert, game, forced_card_id=""):
        return dict(self._fields), None

    def build_title_from_fields(self, fields, grade="10"):
        return ""

    def build_tcg_specs_html(self, pairs):
        return ""

    def replace_tcg_specs(self, desc, html):
        return desc

    def specs_pairs_from_fields(self, fields):
        return []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
