# -*- coding: utf-8 -*-
"""商品説明テンプレは「読めなければ止める」(2026-08-13)。

★実害 (2026-08-12 19:43 の走行):
  テンプレを読めなかった時に **1行の代用文**(72字)を黙って返す作りだったため、
  その走行の6件すべてが説明72字のまま CSV に載り、監査も素通りして「入稿OK」になった。
  ユーザーが目視で発見。過去78本のうちダミー化はこの1本だけ = 一過性だが、
  **次に起きても誰も分からない** (fail-OPEN) のが問題。

固定する挙動:
  1. パスは**スクリプト基準の絶対パス** (実行フォルダに左右されない)
  2. 読めない → 例外で止める (代用文を返さない)
  3. 短すぎる (テンプレ壊れ) → 例外で止める
  4. 代用文の文字列はコードから消えている
"""
from __future__ import annotations

import importlib.util
import os
import sys

import pytest

_TCG = r"C:\dev\iMak\iMakTCG"
_TARGETS = ("psa_to_csv.py", "psa_restock_csv.py")


def _load(name):
    if _TCG not in sys.path:
        sys.path.insert(0, _TCG)
    spec = importlib.util.spec_from_file_location(f"t_{name}", os.path.join(_TCG, name))
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    return mod


@pytest.mark.parametrize("name", _TARGETS)
def test_no_silent_fallback_text_in_source(name):
    src = open(os.path.join(_TCG, name), encoding="utf-8").read()
    assert "PSA graded card shipped from Japan. Grade and cert" not in src, \
        "テンプレ読取失敗時の代用文が残っている (黙って1行の説明で出品されうる)"


@pytest.mark.parametrize("name", _TARGETS)
def test_reads_template_regardless_of_cwd(name, monkeypatch, tmp_path):
    mod = _load(name)
    monkeypatch.chdir(tmp_path)          # 別フォルダから呼ぶ
    body = mod.load_description()
    assert len(body) > 2000, "テンプレを読めていない (相対パス依存が残っている)"


@pytest.mark.parametrize("name", _TARGETS)
def test_missing_template_raises(name, monkeypatch):
    mod = _load(name)
    monkeypatch.setattr(mod, "DESCRIPTION_FILE", "no_such_template_20260813.txt")
    with pytest.raises(RuntimeError) as e:
        mod.load_description()
    assert "読めません" in str(e.value)


@pytest.mark.parametrize("name", _TARGETS)
def test_truncated_template_raises(name, monkeypatch, tmp_path):
    mod = _load(name)
    p = tmp_path / "short.txt"
    p.write_text("<html>短すぎる</html>", encoding="utf-8")
    monkeypatch.setattr(mod, "DESCRIPTION_FILE", str(p))
    with pytest.raises(RuntimeError) as e:
        mod.load_description()
    assert "短すぎます" in str(e.value)
