# -*- coding: utf-8 -*-
"""監査くんがカタログの決定表を基準に照合する (2026-08-22 役割確定)。

役割: カタログ=値を決める / 出品くん=写す / 監査くん=表どおりか照合する。
監査くんは **判定しない**。表に書いてあることだけを言う。

守るもの:
  - emit=false の項目に値が入っていたら止める (ERROR → 除外+program報告)
  - emit=true が空なら数えるだけ (INFO・自動起票しない)
  - 表に無い項目は判定しない (INFO・カタログに投げる)
  - 表が読めない時は何も言わない (カタログ側の不調で出品を止めない)
"""
import importlib.util
import os
import sys

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import aspect_contract as AC  # noqa: E402

HEADERS = ["*Title", "C:Rarity", "C:Finish", "C:Attack/Power", "C:Nonexistent"]
CONTRACT = {
    "Rarity": {"ebay_aspect": "Rarity", "emit": True, "owner": "catalog",
               "source": "specs.rarity_ebay"},
    "Finish": {"ebay_aspect": "Finish", "emit": False, "owner": "catalog",
               "reason": "現物を見ないと決まらない"},
    "Attack/Power": {"ebay_aspect": "Attack/Power", "emit": True, "owner": "catalog",
                     "source": "specs.attack_power_ebay"},
}


def _msgs(row, contract=CONTRACT):
    return AC.contract_findings(HEADERS, row, contract)


def test_emit_false_with_value_is_error():
    out = _msgs(["t", "Super Rare", "Foil", "5000", ""])
    errs = [m for sev, m in out if sev == "ERROR"]
    assert len(errs) == 1 and "Finish" in errs[0] and "現物を見ないと決まらない" in errs[0]


def test_emit_false_blank_is_silent():
    out = _msgs(["t", "Super Rare", "", "5000", ""])
    assert not [m for sev, m in out if sev == "ERROR"]


def test_emit_true_blank_is_info_only():
    out = _msgs(["t", "", "", "5000", ""])
    infos = [m for sev, m in out if sev == "INFO"]
    assert any(m.startswith("空欄です (契約では出す項目): Rarity") for m in infos)
    assert not [m for sev, m in out if sev == "ERROR"]


def test_column_not_in_table_is_not_judged():
    out = _msgs(["t", "Super Rare", "", "5000", "なにか"])
    infos = [m for sev, m in out if sev == "INFO"]
    assert any(m.startswith("契約表に無い項目") and "Nonexistent" in m for m in infos)


def test_no_contract_means_no_findings():
    assert AC.contract_findings(HEADERS, ["t", "", "Foil", "", ""], None) == []


def test_load_contract_returns_none_when_missing(tmp_path):
    assert AC.load_contract(tmp_path / "no_such_file.yaml") is None


def test_shared_table_is_readable_and_has_both_kinds():
    """カタログが共有領域に置く実物 (置かれていない環境では skip)。"""
    c = AC.load_contract()
    if c is None:
        import pytest
        pytest.skip("共有領域に決定表がまだ置かれていない")
    assert len(c) >= 30
    assert any(r.get("emit") for r in c.values())
    assert any(not r.get("emit") for r in c.values())


def _auditor():
    spec = importlib.util.spec_from_file_location(
        "csv_auditor_contract_t", os.path.join(_TOOLS, "csv_auditor.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_auditor_classifies_contract_findings():
    A = _auditor()
    assert A.classify_finding("ERROR", "契約で出さないと決めた項目に値が入っています: Finish='Foil'") \
        == A.REPORT_PROGRAM
    assert A.classify_finding("INFO", "空欄です (契約では出す項目): Rarity — 担当=catalog") \
        == A.INFO_ONLY
    assert A.classify_finding("INFO", "契約表に無い項目です (判定しません・カタログに投げる): X") \
        == A.INFO_ONLY


def test_auditor_calls_contract_findings():
    src = open(os.path.join(_TOOLS, "csv_auditor.py"), encoding="utf-8").read()
    assert "contract_findings(" in src and "load_contract(ebay_category=" in src, \
        "audit() から呼ばれていないと、表は審判にならない"


# =============================================================================
# 2026-09-01 追記: 表は TCG (183454) 専用。他カテゴリに当てない (fail-closed)
#   経緯: category で絞らず全カテゴリに当てていたため、G-shock/一番くじの CSV が
#   TCG 専用の表 (Customized/Vintage 等) で全行 ERROR になった。
#   回答書: hq/requests/2026-08-28_act_code_proposals_gshock_response_question_response.md
# =============================================================================

_TCG_CATEGORY = "183454"
_ICHIBANKUJI_CATEGORY = "261055"


def test_load_contract_scopes_to_declared_ebay_category(tmp_path):
    p = tmp_path / "contract.yaml"
    p.write_text(
        'ebay_category: "183454"\n'
        'aspects:\n'
        '  - ebay_aspect: "Vintage"\n'
        '    emit: false\n',
        encoding="utf-8")
    assert AC.load_contract(p, ebay_category=_TCG_CATEGORY) is not None
    # わざと TCG 以外 (一番くじ) に当てる → 表は当たらない (None)
    assert AC.load_contract(p, ebay_category=_ICHIBANKUJI_CATEGORY) is None


def test_load_contract_with_no_category_arg_ignores_scope(tmp_path):
    """ebay_category を渡さない旧来呼び出しは従来どおり絞らない (後方互換)。"""
    p = tmp_path / "contract.yaml"
    p.write_text('ebay_category: "183454"\naspects:\n  - ebay_aspect: "Vintage"\n    emit: false\n',
                 encoding="utf-8")
    assert AC.load_contract(p) is not None


def test_shared_table_does_not_apply_outside_tcg():
    """実物の共有表 (置かれていない環境では skip) が TCG 以外に当たらないことを見る。"""
    c_tcg = AC.load_contract(ebay_category=_TCG_CATEGORY)
    if c_tcg is None:
        import pytest
        pytest.skip("共有領域に決定表がまだ置かれていない")
    assert AC.load_contract(ebay_category=_ICHIBANKUJI_CATEGORY) is None, (
        "TCG 専用の表が一番くじ (261055) にも当たっている")
