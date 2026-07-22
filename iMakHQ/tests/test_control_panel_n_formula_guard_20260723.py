# -*- coding: utf-8 -*-
"""control_panel の N列関数ガード(両スプシ)の回帰テスト (2026-07-23)。

背景: 仕入値SSOT の N列は N1 の ARRAYFORMULA。LOW は gshock_to_csv 内ガードで守られるが、
HIGH の主要消費者 psa_to_csv は no-touch 運用のため、control_panel の listing run 前
チェックが HIGH の唯一のガード。壊れていたら run を中止する(誤価格出品 fail-OPEN 防止)。
"""
import os
import re
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

_CP = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "control_panel.py"))
with open(_CP, encoding="utf-8") as f:
    _SRC = f.read()


def test_guard_function_exists_and_checks_both_sheets():
    """_check_n_formula_guard が定義され、CONSOLIDATED_SHEETS (high+low) を走査する。"""
    assert "_check_n_formula_guard" in _SRC
    body = _SRC.split("def _check_n_formula_guard")[1].split("def run_script")[0]
    assert "CONSOLIDATED_SHEETS" in body, "両スプシを走査していない"
    assert "ARRAYFORMULA" in body
    assert 'value_render_option="FORMULA"' in body, "式の存在確認は FORMULA render 必須"


def test_run_script_gates_new_type_on_guard():
    """★本命: type=='new' の run が guard False で中止される配線。"""
    m = re.search(
        r'script\.get\("type"\) == "new" and not self\._check_n_formula_guard\(\)',
        _SRC)
    assert m, "run_script に new-type の N関数ガード配線が無い"
    after = _SRC[m.end():m.end() + 200]
    assert "return" in after, "破損検知時に run を中止していない"


def test_guard_fails_open_only_on_check_error():
    """チェック自体の失敗(ネットワーク等)は警告のみで続行 (True)、破損確証時のみ False。"""
    body = _SRC.split("def _check_n_formula_guard")[1].split("def run_script")[0]
    assert "return False" in body      # 破損 → 中止
    assert body.rstrip().endswith("return True")  # except 側 → 続行
