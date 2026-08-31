# -*- coding: utf-8 -*-
"""監査くんが「値はあるが catalog と違う」を見る (2026-08-25 提案5 / 2026-08-26 実装).

8/25 の入稿は 7セルの誤値 (C:Attack/Power に HP / C:Cost に Leader の LIFE /
C:Attribute に Vision の色) を通したのに、監査くんの結果は
「除外0 / カタログ依頼0 / プログラム依頼0」だった。契約照合が
 ①出さない項目に値 ②出す項目が空 ③表に無い項目 の3つしか見ていなかったため。

突合に要る canonical sidecar (`<CSV名>.canonical.json`) は毎回出ている。

依頼書: hq/requests/2026-08-25_act_code_proposals_tcg.md 提案5
回答書: hq/requests/2026-08-26_act_code_proposals_tcg_response.md (7)
"""
import json
import os
import sys

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from aspect_contract import catalog_mismatch_findings, is_catalog_owned  # noqa: E402

_CONTRACT = {
    "Attack/Power":        {"emit": True,  "source": "specs.attack_power_ebay", "owner": "catalog"},
    "Cost":                {"emit": True,  "source": "specs.cost", "owner": "catalog"},
    "Attribute/MTG:Color": {"emit": True,  "source": "specs.color_ebay", "owner": "catalog"},
    "Features":            {"emit": True,  "source": "specs.features_ebay", "owner": "catalog"},
    "Card Name":           {"emit": True,  "source": "column.name_en", "owner": "catalog"},
    "Grade":               {"emit": True,  "source": "psa_cert", "owner": "catalog"},
    "Finish":              {"emit": False, "source": None, "owner": "catalog"},
}
_H = ["C:Attack/Power", "C:Cost", "C:Attribute/MTG:Color", "C:Features",
      "C:Card Name", "C:Grade", "C:Finish"]


def _msgs(row, expected):
    return [m for _, m in catalog_mismatch_findings(_H, row, _CONTRACT, expected)]


def test_the_three_cells_from_20260825_are_caught():
    """catalog が空なのに値が入っている 3セル (= 8/25 に通した形)。"""
    row = ["130", "4", "Pokémon", "", "Rayquaza", "10", ""]
    exp = {"C:Attack/Power": "", "C:Cost": "", "C:Attribute/MTG:Color": "",
           "C:Features": "", "C:Card Name": "Rayquaza"}
    got = _msgs(row, exp)
    assert len(got) == 3, got
    assert all(m.startswith("カタログが持たない値") for m in got)
    assert any("Attack/Power" in m for m in got)
    assert any("Cost" in m for m in got)
    assert any("Attribute/MTG:Color" in m for m in got)


def test_different_value_is_reported():
    row = ["5000", "", "", "", "", "10", ""]
    got = _msgs(row, {"C:Attack/Power": "3000"})
    assert len(got) == 1 and got[0].startswith("カタログの値と違います"), got


def test_catalog_value_not_copied_is_reported():
    row = ["", "", "", "", "", "10", ""]
    got = _msgs(row, {"C:Attack/Power": "3000"})
    assert len(got) == 1 and got[0].startswith("カタログの値を写せていません"), got


def test_matching_rows_are_silent():
    row = ["3000", "4", "Red", "Promo|Alternative Art", "Luffy", "10", ""]
    exp = {"C:Attack/Power": "3000", "C:Cost": "4", "C:Attribute/MTG:Color": "Red",
           "C:Features": "Promo|Alternative Art", "C:Card Name": "Luffy"}
    assert _msgs(row, exp) == []


def test_multi_value_order_does_not_matter():
    """Features は複数値。並び順の違いを不一致にしない。"""
    row = ["", "", "", "Alternative Art|Promo", "", "10", ""]
    assert _msgs(row, {"C:Features": ["Promo", "Alternative Art"]}) == []


def test_columns_catalog_does_not_own_are_not_compared():
    """Grade (psa_cert) / Finish (emit=false) は対象外。

    Card Name (column.name_en) は 2026-09-01 から対象 (誤ると SNAD 直結の項目が
    無検査だったため。出典: hq/requests/2026-09-01_act_code_proposals_tcg_response.md 提案3)。
    """
    assert is_catalog_owned("C:Card Name", _CONTRACT)
    assert not is_catalog_owned("C:Grade", _CONTRACT)
    assert not is_catalog_owned("C:Finish", _CONTRACT)
    row = ["", "", "", "", "ちがう名前", "9", "Holo"]
    assert _msgs(row, {"C:Grade": "10", "C:Finish": ""}) == []


def test_unknown_column_is_not_judged():
    """catalog を引けなかった列は判定しない (引けない=不一致 に倒さない)。"""
    row = ["130", "", "", "", "", "10", ""]
    assert _msgs(row, {"C:Cost": ""}) == []
    assert catalog_mismatch_findings(_H, row, _CONTRACT, {}) == []
    assert catalog_mismatch_findings(_H, row, None, {"C:Attack/Power": ""}) == []


def test_mismatch_goes_to_program_not_catalog():
    """写し方 (②) の誤りなので、カタログに投げない。"""
    import csv_auditor as ca
    for m in ("カタログが持たない値が入っています: Cost='4' — カタログは空欄",
              "カタログの値と違います: Attack/Power='1' — カタログ='2'",
              "カタログの値を写せていません: Cost が空欄 — カタログ='4'"):
        assert ca.classify_finding("ERROR", m) == ca.REPORT_PROGRAM, m


# --- sidecar の読み込み (I/O 側) ---

def test_sidecar_is_read_and_missing_one_is_harmless(tmp_path):
    import csv_auditor as ca
    csv_path = tmp_path / "tcg_upload_x.csv"
    csv_path.write_text("dummy", encoding="utf-8")
    assert ca.load_canonical_sidecar(str(csv_path)) == {}      # 無くても落ちない
    (tmp_path / "tcg_upload_x.canonical.json").write_text(
        json.dumps({"by_cert": {"123": "pokemon_tcg:SM9a-067"}}), encoding="utf-8")
    assert ca.load_canonical_sidecar(str(csv_path)) == {"123": "pokemon_tcg:SM9a-067"}


def test_old_sidecar_without_category_is_not_compared():
    """category 前置きの無い旧 sidecar は照合しない (別ゲームの同 id を引く危険)。"""
    import csv_auditor as ca
    assert ca.catalog_expected_fields("SM9a-067") == {}
    assert ca.catalog_expected_fields("") == {}
