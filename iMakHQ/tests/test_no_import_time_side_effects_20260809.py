# -*- coding: utf-8 -*-
"""`test_*.py` が import された瞬間に副作用を起こさないこと (2026-08-09).

実害:
    `iMakTCG/data/test_selenium.py` / `test_psa.py` は「使い捨ての確認スクリプト」だったが、
    ファイル名が `test_` で始まるため **pytest が収集して import** する。
    両方とも処理が全部 module 直下にあり、import = 実行だった:

      test_selenium.py … `driver.get("https://www.psacard.com/ja-JP/cert/139075607/psa")`
                         で **Chrome が勝手に開き**、末尾の `input()` で固まる
      test_psa.py      … PSA API を叩き、`input()` で固まる

    2026-08-09 に **7回** Chrome が立ち上がった。走らせた本人にも心当たりが無く、
    毎回「何かが勝手に動いている」と疑うことになった。
    (2026-08-08 に消した `test_carddb.py` も同型。あの時は名前が `test_` だったことに
     気づかず、「調査のたびに実行される」とだけ書いて再発を止められなかった)

ここで止めること:
  1. `test_*.py` の **module 直下** に browser 起動 / ネットワーク / `input()` を書かない
  2. `input()` は pytest 実行を**ハングさせる**ので、関数の中でも禁止
"""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

ROOT = Path(r"C:\dev\iMak")

# module 直下 (関数/クラスの外) に在ってはいけない呼び出し
FORBIDDEN_TOPLEVEL = (
    "input",              # pytest がハングする
    "webdriver.Chrome", "uc.Chrome", "Chrome",
    "driver.get",
    "requests.get", "requests.post",
)


def _tracked_test_files():
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "*test_*.py"],
                         capture_output=True, text=True, encoding="utf-8").stdout
    return [ROOT / p for p in out.splitlines() if p.strip()]


def _call_name(node: ast.Call) -> str:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        base = f.value.id if isinstance(f.value, ast.Name) else ""
        return f"{base}.{f.attr}" if base else f.attr
    return ""


def test_no_side_effects_at_module_level():
    bad = []
    for p in _tracked_test_files():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"), str(p))
        except SyntaxError:
            continue
        for node in tree.body:                      # ★module 直下だけを見る
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    name = _call_name(sub)
                    if name in FORBIDDEN_TOPLEVEL:
                        bad.append(f"{p.relative_to(ROOT)}: module 直下で {name}()")
    assert not bad, (
        "test_*.py が import されただけで副作用を起こす (pytest が収集して実行する):\n  "
        + "\n  ".join(bad))


def test_no_input_anywhere_in_tests():
    """`input()` は関数の中でも禁止。pytest がハングして原因究明が難しい。"""
    bad = []
    for p in _tracked_test_files():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"), str(p))
        except SyntaxError:
            continue
        for sub in ast.walk(tree):
            if isinstance(sub, ast.Call) and _call_name(sub) == "input":
                bad.append(f"{p.relative_to(ROOT)}:{sub.lineno}")
    assert not bad, "test_*.py に input() がある (pytest がハングする):\n  " + "\n  ".join(bad)


def test_throwaway_scripts_are_not_named_like_tests():
    """使い捨てスクリプトを `test_` で始めない。名前だけで pytest に拾われる。

    置き場所も含めて禁止する: `*/data/test_*.py` は「データ置き場に紛れた実行スクリプト」で、
    テストとして書かれていないのに収集される最悪の組合せ。
    """
    bad = [str(p.relative_to(ROOT)) for p in _tracked_test_files()
           if p.parent.name == "data"]
    assert not bad, "data/ 配下に test_*.py がある (pytest が拾って実行する):\n  " + "\n  ".join(bad)
