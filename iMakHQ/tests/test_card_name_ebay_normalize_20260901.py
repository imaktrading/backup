# -*- coding: utf-8 -*-
"""C:Card Name をカタログ照合の対象にする (2026-09-01)。

何が起きていたか: `is_catalog_owned` は `source.startswith("specs.")` だけを見ており、
Card Name (`source: column.name_en`) は監査くんの catalog 突合から外れていた。
Card Name は誤ると SNAD に直結する唯一の項目なのに、そこだけ無検査だった。

単純に `column.*` を対象へ足すだけだと、`apply_ebay_filter_to_row` が正当に
eBay 正規値へ書き換えた分 (例 catalog='Greninja ex' → csv='Greninja Ex') が毎回
誤検出になる (pokemon の name_en 語尾小文字は実測 883件)。そのため
eBay 実取得マスタ (`ebay_183454_facet_master_20260821.json`) の正規値と一致する
書き換えだけを正当と認める。

出典: hq/requests/2026-09-01_act_code_proposals_tcg_response.md 提案3
"""
import os
import sys

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from aspect_contract import catalog_mismatch_findings, is_catalog_owned  # noqa: E402

_CONTRACT = {"Card Name": {"emit": True, "source": "column.name_en", "owner": "catalog"}}
_H = ["C:Card Name"]
_MASTER = {"Card Name": {"all": ["Greninja Ex", "Toxtricity Ex", "Frogadier"]}}


def _msgs(csv_value, catalog_value, ebay_master=_MASTER):
    return [m for _, m in catalog_mismatch_findings(
        _H, [csv_value], _CONTRACT, {"C:Card Name": catalog_value}, ebay_master=ebay_master)]


def test_card_name_is_now_catalog_owned():
    assert is_catalog_owned("C:Card Name", _CONTRACT)


def test_ebay_normalized_rewrite_is_accepted():
    """catalog='Greninja ex' -> csv='Greninja Ex' (eBay マスタの正規綴り) は通す。"""
    assert _msgs("Greninja Ex", "Greninja ex") == []
    assert _msgs("Toxtricity Ex", "Toxtricity ex") == []


def test_different_card_is_still_stopped():
    """catalog='Greninja ex' -> csv='Frogadier' (別カード) は止める。"""
    got = _msgs("Frogadier", "Greninja ex")
    assert len(got) == 1 and got[0].startswith("カタログの値と違います"), got


def test_case_diff_not_in_master_is_still_stopped():
    """casefold は一致するが eBay マスタに存在しない綴りは正当化しない (fail-closed)。"""
    got = _msgs("Greninja EX", "Greninja ex", ebay_master={"Card Name": {"all": ["Greninja Ex"]}})
    assert len(got) == 1 and got[0].startswith("カタログの値と違います"), got


def test_without_ebay_master_falls_back_to_strict_compare():
    """マスタが渡されない/読めない時は、これまでどおり大文字小文字も一致必須 (fail-closed)。"""
    got = _msgs("Greninja Ex", "Greninja ex", ebay_master=None)
    assert len(got) == 1 and got[0].startswith("カタログの値と違います"), got
