# -*- coding: utf-8 -*-
"""公式にレアリティが無いカードは「空欄のまま出す」(2026-08-15 HQ 判断)。

★経緯: Catalog から「公式にレアリティが無いカードをどうするか。今は空欄=出品しないので
  スターターセットの GX は永久に出せない。7/21 の One Piece リーダーと同じく何か入れるか」。

  HQ 判断: **入れない**。
  - 7/21 の Leader は カードに 'L' が **印字されている**ので写しただけ (無い物を作っていない)。
    同じ回答の末尾で「DON / Resource / ENERGY MARKER は rarity 空が正」と明記している。
  - 無いレアリティを埋めるのは、出品の正確性の大前提 (推測で埋めない) に反する。
  - 出せない原因は catalog ではなく **HQ 側の監査が C:Rarity を必須にしている**こと。
    = 1丁目1番地の②。こちらで直す (catalog に修正依頼は出さない)。
"""
from __future__ import annotations

import importlib.util
import os
import sys

_TCG = r"C:\dev\iMak\iMakTCG"


def _load():
    spec = importlib.util.spec_from_file_location(
        "_hq_check_csv_rarity", os.path.join(_TCG, "check_csv.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    if _TCG not in sys.path:
        sys.path.insert(0, _TCG)
    spec.loader.exec_module(mod)
    return mod


C = _load()


def test_starter_set_cards_do_not_require_rarity():
    """スターターセット/デッキは印刷レアリティが無い → 空欄でも出品を止めない。"""
    for pid in ("SD-001", "SLD-014", "SLL-021", "SVEL-003", "SVEM-020"):
        req = C.required_specifics_for_card(pid)
        assert "C:Rarity" not in req, f"{pid} で C:Rarity を必須にしている (出品できない)"
        # 他の必須は緩めない (まとめて免除しない)
        assert "C:Set" in req and "C:Card Name" in req


def test_normal_sets_still_require_rarity():
    """通常セットは必須のまま。丸ごと免除にすると本当の欠損を見逃す。"""
    for pid in ("SV9a-091", "OP03-122", "FB01-071"):
        assert "C:Rarity" in C.required_specifics_for_card(pid), pid


def test_no_invented_rarity_value_is_introduced():
    """『無いなら何か入れる』方向に倒していないこと (値の捏造をコードに入れない)。"""
    src = open(os.path.join(_TCG, "check_csv.py"), encoding="utf-8", errors="replace").read()
    for bad in ('"Common"', "'Common'", '"Not specified"', '"Does not apply"'):
        assert f"C:Rarity\"] = {bad}" not in src and f"rarity = {bad}" not in src


def test_rule_reads_catalog_not_a_prefix_list(tmp_path):
    """★2026-08-16: prefix ハードコードをやめ、カタログの `specs.rarity` で判定する。

    Catalog 回答: 「1枚も rarity を持たないセットが 215個 / 5,294件。prefix を手で足す限り
    足し忘れた分が黙って出品されない」。実際、発端の SMI-007 は 8/15 に 5 prefix を足した
    後も出せないままだった。
    """
    import json
    import sqlite3
    db = tmp_path / "products.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE products (product_id TEXT, specs TEXT)")
    con.executemany("INSERT INTO products VALUES (?,?)", [
        ("SMI-007", json.dumps({"rarity": ""})),        # 公式に表記なし
        ("SV9a-091", json.dumps({"rarity": "UR"})),     # 公式に有り
    ])
    con.commit(); con.close()
    C._RARITY_ABSENT_CACHE = None
    try:
        assert C.rarity_absent_official("SMI-007", db_path=str(db)) is True
        assert C.rarity_absent_official("SV9a-091", db_path=str(db)) is False
    finally:
        C._RARITY_ABSENT_CACHE = None


def test_unreadable_catalog_does_not_exempt(tmp_path):
    """カタログを読めない時は免除しない (判定不能を『無い』に倒さない)。"""
    C._RARITY_ABSENT_CACHE = None
    try:
        assert C.rarity_absent_official("SMI-007", db_path=str(tmp_path / "nope.sqlite")) is False
    finally:
        C._RARITY_ABSENT_CACHE = None


def test_same_id_in_two_categories_is_not_exempted(tmp_path):
    """同じ product_id が別カテゴリにも在り、片方に rarity が有るなら免除しない。"""
    import json
    import sqlite3
    db = tmp_path / "p.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE products (product_id TEXT, specs TEXT)")
    con.executemany("INSERT INTO products VALUES (?,?)", [
        ("P-001", json.dumps({"rarity": ""})),
        ("P-001", json.dumps({"rarity": "SR"})),
    ])
    con.commit(); con.close()
    C._RARITY_ABSENT_CACHE = None
    try:
        assert C.rarity_absent_official("P-001", db_path=str(db)) is False
    finally:
        C._RARITY_ABSENT_CACHE = None
