# -*- coding: utf-8 -*-
"""183454 の master 突合は「全 TCG」で見る (2026-08-12 入稿0件事故)。

事故:
  契約 v1.2 §4 CI (8/11 実装) が **Pokemon 専用**の master を
  eBay カテゴリ 183454 の**全行**に当てていた。183454 は
  ポケモン/ワンピ/ドラゴンボール/ガンダム/遊戯王 の共通カテゴリなので、
  catalog に実在する 'Awakened Pulse' (dragonball) / '500 Years in the Future'
  (one_piece) 等が軒並み「master に存在しない」で ERROR → 物理除外。
  8/12 の入稿は残り6件が全部ワンピ/ドラゴンボールで **入稿0件** になった。

1丁目1番地の判定: ①カタログは正しい / ②引き方(検査側)が誤り → ②を修正。

固定する挙動:
  1. catalog helper `tcg_set_master()` は 183454 に出す全 TCG category を含む
  2. 事故当日に弾かれた実データのセット名が master に含まれる
  3. ワンピ/ドラゴンボールの行 (183454) が「master に存在しない」で弾かれない
  4. どの category にも無い自由文字列は従来どおり ERROR (検出力を落としていない)
"""
from __future__ import annotations

import importlib.util
import os
import sys

_TCG = r"C:\dev\iMak\iMakTCG"
_CATALOG = r"C:\dev\iMak\iMakCatalog"
for _p in (_TCG, _CATALOG):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ★TCG の check_csv は **固有名でロード**する (bare `import check_csv` をしない)。
#   4カテゴリが同名 check_csv.py を持つため、bare import すると sys.modules['check_csv']
#   が先着1つに固定され、後続テストが別カテゴリの check_csv を掴む
#   (このファイルは名前順で最初に走るので、bare import すると全体を汚染する)。
#   csv_auditor.load_check_csv_module と同じ方式。
_TCG_CHECK_CSV = None


def _tcg_check_csv():
    global _TCG_CHECK_CSV
    if _TCG_CHECK_CSV is None:
        spec = importlib.util.spec_from_file_location(
            "tcg_check_csv_183454_test", os.path.join(_TCG, "check_csv.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _TCG_CHECK_CSV = mod
    return _TCG_CHECK_CSV

# 8/12 の入稿で実際に弾かれた C:Set (全て catalog に実在)
_BLOCKED_ON_20260812 = [
    "Awakened Pulse",                     # dragonball_scg
    "500 Years in the Future",            # one_piece_tcg
    "ONE PIECE Heroines Edition",         # one_piece_tcg
    "Adventure on Kami's Island",         # one_piece_tcg
    "Promo Cards",                        # one_piece_tcg / dragonball_scg / gundam_tcg
    "Premium Booster One Piece The Best",  # one_piece_tcg
    "The Azure Sea's Seven Heroes",       # one_piece_tcg
]

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
    put("*Title", "PSA 10 One Piece Japanese Some Card OP01-001 " + "x" * 20)
    put("*Category", category)
    put("ConditionID", "2750")
    put("*StartPrice", "100.0")
    put("ShippingProfileName", "60-100")
    put("CDA:Certification Number - (ID: 27503)", cert)
    put("C:Card Number", "OP01-001")
    put("C:Game", "One Piece")
    put("C:Set", c_set)
    put("C:Card Name", "Test")
    put("C:Character", "Test")
    put("C:Rarity", "Rare")
    put("C:Year Manufactured", "2023")
    return row


def _seed(monkeypatch, master_set):
    C = _tcg_check_csv()
    monkeypatch.setattr(C, "_TCG_SET_MASTER", set(master_set), raising=False)
    C.HEADER_MAP = {h: i for i, h in enumerate(_HEADERS)}
    return C


# ---------------------------------------------------------------------------
# 1. master は Pokemon 限定ではない
# ---------------------------------------------------------------------------
def test_tcg_master_covers_all_183454_categories():
    from set_reference import TCG_183454_CATEGORIES
    for cat in ("pokemon_tcg", "one_piece_tcg", "dragonball_scg",
                "gundam_tcg", "yugioh_tcg"):
        assert cat in TCG_183454_CATEGORIES, f"{cat} が 183454 の master 対象から漏れている"


# ---------------------------------------------------------------------------
# 2. 事故当日に弾かれたセット名が実 DB の master に入っている
# ---------------------------------------------------------------------------
def test_sets_blocked_on_20260812_are_in_master():
    from set_reference import tcg_set_master
    master = tcg_set_master()
    if not master:
        import pytest
        pytest.skip("catalog DB を読めない環境 (master 空 = fail-open)")
    missing = [s for s in _BLOCKED_ON_20260812 if s not in master]
    assert missing == [], f"catalog に実在するのに master から漏れている: {missing}"


# ---------------------------------------------------------------------------
# 3. ワンピ/ドラゴンボール行が誤って弾かれない (事故の再現防止)
# ---------------------------------------------------------------------------
def test_one_piece_rows_not_flagged_by_pokemon_only_master(monkeypatch):
    # master には「全 TCG 分」= tcg_set_master の想定内容を入れて検査する
    C = _seed(monkeypatch, set(_BLOCKED_ON_20260812) | {"Ultra Prism"})
    for s in _BLOCKED_ON_20260812:
        issues = C.validate_row(_make_row(c_set=s), 1)
        errs = [t for lv, t in issues if "master に存在しない" in t]
        assert errs == [], f"catalog 実在の Set '{s}' が弾かれた: {errs}"


# ---------------------------------------------------------------------------
# 4. 検出力は落としていない (どの category にも無い値は ERROR)
# ---------------------------------------------------------------------------
def test_free_text_set_still_flagged(monkeypatch):
    C = _seed(monkeypatch, set(_BLOCKED_ON_20260812))
    issues = C.validate_row(_make_row(c_set="Totally Made Up Set 9999"), 1)
    errs = [t for lv, t in issues if "master に存在しない" in t]
    assert len(errs) == 1, f"master 外の自由文字列を検出できていない: {issues}"
