# -*- coding: utf-8 -*-
"""契約 v1.2 §4 CI: 「183454 master に無い値が CSV に出ていない」(2026-08-11)。

回答書:
  - 2026-08-10_catalog_tcg_ssot_interface_contract_all_categories_response.md §HQ-4

固定する挙動:
  1. Pokemon (category=183454) の C:Set 値は catalog `pokemon_set_master()` に存在する
     もののみ許容する
  2. master 外の C:Set が来たら check_csv.validate_row が ERROR を出す
     (生成側で自由文字列 / 表記揺れ / 廃止 set 名が混入していないかを毎行 gate)
  3. master 読取失敗 (helper 例外) は fail-open で判定を降ろす (誤ブロック回避)
  4. 非 Pokemon (category != 183454) は本 CI の対象外 (誤検出防止)
"""
from __future__ import annotations

import os
import sys

_TCG = r"C:\dev\iMak\iMakTCG"
_CATALOG = r"C:\dev\iMak\iMakCatalog"
for _p in (_TCG, _CATALOG):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# validate_row が使う HEADER_MAP をテスト用に埋めるための最小 CSV headers。
_HEADERS = [
    "*Title", "*Category", "ConditionID", "*StartPrice", "ShippingProfileName",
    "CDA:Certification Number - (ID: 27503)", "C:Card Number", "C:Card Type",
    "C:Game", "C:Set", "C:Card Name", "C:Character", "C:Rarity",
    "C:Year Manufactured",
]


def _make_row(*, c_set, category="183454", cert="199999999"):
    row = [""] * len(_HEADERS)

    def put(k, v):
        row[_HEADERS.index(k)] = v
    put("*Title", "PSA 10 Some Pokemon Card 001 " + "x" * 30)
    put("*Category", category)
    put("ConditionID", "2750")
    put("*StartPrice", "100.0")
    put("ShippingProfileName", "60-100")
    put("CDA:Certification Number - (ID: 27503)", cert)
    put("C:Card Number", "001/184")
    put("C:Card Type", "Pokémon")
    put("C:Game", "Pokemon")
    put("C:Set", c_set)
    put("C:Card Name", "Test")
    put("C:Character", "Test")
    put("C:Rarity", "Rare")
    put("C:Year Manufactured", "2023")
    return row


def _seed(monkeypatch, master_set):
    """catalog helper の pokemon_set_master を差し替える (テストで DB を触らない)。"""
    import check_csv as C
    monkeypatch.setattr(C, "_POKEMON_SET_MASTER", set(master_set), raising=False)
    # HEADER_MAP を validate_row が参照するので、テスト用に埋めておく
    C.HEADER_MAP = {h: i for i, h in enumerate(_HEADERS)}


# ---------------------------------------------------------------------------
# 1. master 内 → OK
# ---------------------------------------------------------------------------
def test_pokemon_set_in_master_is_ok(monkeypatch):
    from check_csv import validate_row
    _seed(monkeypatch, {"Scarlet & Violet—Destined Rivals", "Ultra Prism"})
    row = _make_row(c_set="Scarlet & Violet—Destined Rivals")
    issues = validate_row(row, 1)
    # 「master に無い」ERROR が **出ていない** こと
    master_errs = [t for lv, t in issues if "master に存在しない" in t]
    assert master_errs == [], f"master にあるのに ERROR: {master_errs}"


# ---------------------------------------------------------------------------
# 2. master 外 → ERROR
# ---------------------------------------------------------------------------
def test_pokemon_set_not_in_master_flagged(monkeypatch):
    from check_csv import validate_row
    _seed(monkeypatch, {"Scarlet & Violet—Destined Rivals"})
    row = _make_row(c_set="Bogus Set That Never Existed")
    issues = validate_row(row, 1)
    master_errs = [t for lv, t in issues if "master に存在しない" in t]
    assert len(master_errs) == 1, f"master 外なのに ERROR が出ていない: {issues}"
    assert "Bogus Set That Never Existed" in master_errs[0]


# ---------------------------------------------------------------------------
# 3. master 読取失敗 → fail-open (誤ブロック回避)
# ---------------------------------------------------------------------------
def test_master_read_failure_fails_open(monkeypatch):
    from check_csv import validate_row
    # master を空集合に (= 読取失敗の代替表現) → 判定を降ろす
    _seed(monkeypatch, set())
    row = _make_row(c_set="Anything Goes When Master Empty")
    issues = validate_row(row, 1)
    master_errs = [t for lv, t in issues if "master に存在しない" in t]
    assert master_errs == [], "master が空 (= 読取失敗) の時は誤ブロックしない (fail-open)"


# ---------------------------------------------------------------------------
# 4. 非 Pokemon は対象外
# ---------------------------------------------------------------------------
def test_non_pokemon_category_not_gated_by_pokemon_master(monkeypatch):
    from check_csv import validate_row
    _seed(monkeypatch, {"Scarlet & Violet—Destined Rivals"})
    # One Piece TCG category (183454 以外) は Pokemon master 突合の対象外
    row = _make_row(c_set="Wings of the Captain", category="183454X")
    row[_HEADERS.index("*Category")] = "38292"   # 適当な非 183454
    # 非 183454 は本 CI の対象外なので「master に存在しない」ERROR は出ない
    issues = validate_row(row, 1)
    master_errs = [t for lv, t in issues if "master に存在しない" in t]
    assert master_errs == [], (
        "非 Pokemon カテゴリで Pokemon master 突合が発火している (誤検出)"
    )


# ---------------------------------------------------------------------------
# 5. helper の pokemon_set_master 呼出契約
# ---------------------------------------------------------------------------
def test_check_csv_uses_catalog_helper_for_master():
    """check_csv が iMakCatalog/set_reference.pokemon_set_master を経由している。"""
    with open(os.path.join(_TCG, "check_csv.py"), "r", encoding="utf-8") as f:
        src = f.read()
    assert "from set_reference import pokemon_set_master" in src, (
        "check_csv が catalog helper の pokemon_set_master を import していない"
    )
