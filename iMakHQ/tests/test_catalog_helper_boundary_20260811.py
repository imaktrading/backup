# -*- coding: utf-8 -*-
"""契約 v1.2 §HQ-3: HQ から catalog の set 整合 helper は **iMakCatalog 経由**でのみ呼ぶ
(2026-08-11 co-sign, `2026-08-10_ssot_contract_cosign_snapshot_on_listing_response.md`
+ `2026-08-10_catalog_tcg_ssot_interface_contract_all_categories_response.md`)。

固定する境界:
  1. check_csv は iMakHQ/tools/catalog_set_audit を直接 import しない
     (catalog helper `iMakCatalog/set_reference.py` を経由する)
  2. catalog helper が公開 API を全て提供している
     (set_total_reference / row_set_issue / eb_era / ERA_YEARS / card_total /
      pokemon_set_master)
  3. HQ 側の catalog_set_audit は catalog helper に delegate している
     (re-export で backward compatibility を保つが SSOT は catalog)
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys

_HQ_TOOLS = r"C:\dev\iMak\iMakHQ\tools"
_TCG = r"C:\dev\iMak\iMakTCG"
_CATALOG = r"C:\dev\iMak\iMakCatalog"
for _p in (_HQ_TOOLS, _TCG, _CATALOG):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _load_check_csv_source():
    with open(os.path.join(_TCG, "check_csv.py"), "r", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# 1. check_csv は catalog helper 経由でしか呼ばない
# ---------------------------------------------------------------------------
def test_check_csv_imports_from_catalog_helper_not_hq_tools():
    """check_csv は `set_reference` (catalog helper) を import する。

    旧 path (`from catalog_set_audit import ...`) は削除済であること。
    """
    src = _load_check_csv_source()
    assert "from set_reference import" in src, (
        "check_csv が catalog helper (iMakCatalog/set_reference.py) を import していない"
    )
    # 旧 path を残していないこと (再発防止 = ここが SSOT)
    assert "from catalog_set_audit import" not in src, (
        "check_csv がまだ HQ 側 catalog_set_audit を直接 import している。"
        "catalog helper 経由に切替えること (契約 v1.2 §HQ-3)"
    )


def test_check_csv_sys_path_points_to_iMakCatalog():
    """helper import 時に sys.path に iMakCatalog を足していること。"""
    src = _load_check_csv_source()
    assert re.search(r'"\.\.",\s*"iMakCatalog"', src), (
        "check_csv が iMakCatalog を sys.path に足していない"
    )


# ---------------------------------------------------------------------------
# 2. catalog helper 公開 API
# ---------------------------------------------------------------------------
def test_catalog_helper_exports_all_public_api():
    """iMakCatalog/set_reference.py が公開 API を全て提供している。"""
    import set_reference as sr
    for name in ("set_total_reference", "row_set_issue", "eb_era",
                 "ERA_YEARS", "card_total", "pokemon_set_master"):
        assert hasattr(sr, name), f"catalog helper に {name} が無い"


def test_catalog_helper_card_total_extraction():
    import set_reference as sr
    assert sr.card_total("097/080") == "080"
    assert sr.card_total("") == ""
    assert sr.card_total(None) == ""


def test_catalog_helper_eb_era_prefix_detection():
    import set_reference as sr
    assert sr.eb_era("Sun & Moon—Ultra Prism") == "Sun & Moon"
    assert sr.eb_era("Scarlet & Violet—Destined Rivals") == "Scarlet & Violet"
    assert sr.eb_era("Nihil Zero") == "bare/other"
    assert sr.eb_era("") == "bare/other"


def test_catalog_helper_row_set_issue_pure():
    """row_set_issue が純関数として動く (DB 依存無し、ref dict だけで判定)。"""
    import set_reference as sr
    ref = {"Sun & Moon—Ultra Prism": "156", "Nihil Zero": "080"}
    # 誤マップ検出
    assert sr.row_set_issue("Sun & Moon—Ultra Prism", "097/080", ref) is not None
    # 正
    assert sr.row_set_issue("Nihil Zero", "097/080", ref) is None
    # 参照に無い set / 番号不明 → 判定不能 None
    assert sr.row_set_issue("Unknown Set", "001/100", ref) is None
    assert sr.row_set_issue("Nihil Zero", "", ref) is None


def test_catalog_helper_row_set_issue_respects_multi_total_whitelist():
    """verified-legit な多 total (Sun & Moon = SM1p/051 vs SM1S/060) は誤ブロックしない。"""
    import set_reference as sr
    assert "Sun & Moon" in sr._KNOWN_MULTI_TOTAL_OK
    ref = {"Sun & Moon": "060"}
    # 少数派 /051 を /060 基準で弾かない (whitelist)
    assert sr.row_set_issue("Sun & Moon", "045/051", ref) is None
    # whitelist 外の本物の誤マップは検出 (回帰防止)
    ref2 = {"Sun & Moon—Ultra Prism": "156"}
    assert sr.row_set_issue("Sun & Moon—Ultra Prism", "097/080", ref2) is not None


# ---------------------------------------------------------------------------
# 3. HQ 側 catalog_set_audit は catalog helper に delegate している
# ---------------------------------------------------------------------------
def _load_hq_audit():
    spec = importlib.util.spec_from_file_location(
        "catalog_set_audit_delegating", os.path.join(_HQ_TOOLS, "catalog_set_audit.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_hq_catalog_set_audit_reexports_from_catalog_helper():
    """HQ 側 audit が catalog helper と同じ関数オブジェクトを exposed する (SSOT 共有)。"""
    import set_reference as sr
    hq = _load_hq_audit()
    # object identity で SSOT を担保 (もし別実装を復活させたら別 object になり test fail)
    assert hq.set_total_reference is sr.set_total_reference
    assert hq.row_set_issue is sr.row_set_issue
    assert hq.eb_era is sr.eb_era
    assert hq.card_total is sr.card_total
    assert hq.ERA_YEARS is sr.ERA_YEARS
