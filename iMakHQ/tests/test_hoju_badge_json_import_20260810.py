# -*- coding: utf-8 -*-
"""補URL 残件バッジが「取得できず」になっていた回帰テスト (2026-08-10)。

真因: `control_panel.py` の module レベルに `import json` が無く、`import json as _json`
だけだった。関数内で `json.loads(...)` を書いていたため **NameError** が出て、
広い `except Exception` に飲まれ「(残件 取得できず)」と表示され続けていた。
`count_workload()` 自体は単体でも pythonw 経由でも 7秒で正常に返っていたので、
「集計が失敗している」と誤診しやすい形だった。

ここで固定すること:
  - module 名前空間に `json` が居ること (関数内のローカル import に依存しない)
  - モジュール全体を compile して未定義名の混入を検出できる形にしておくこと
"""
import ast
import importlib.util
import os
import sys

PANEL = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "control_panel.py"))


def _module_level_imports(src):
    """module スコープで import された名前 (as 名を優先) の集合。"""
    tree = ast.parse(src)
    names = set()
    for node in tree.body:                       # ★body 直下 = module スコープのみ
        if isinstance(node, ast.Import):
            for a in node.names:
                names.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                names.add(a.asname or a.name)
    return names


def test_json_is_imported_at_module_level():
    src = open(PANEL, encoding="utf-8").read()
    assert "json" in _module_level_imports(src), (
        "control_panel に module レベルの `import json` が無い。"
        "`json.loads` が NameError になり、補URL 残件バッジが『取得できず』になる"
    )


def test_panel_compiles():
    """構文エラーで起動しない状態を commit しない。"""
    src = open(PANEL, encoding="utf-8").read()
    compile(src, PANEL, "exec")


def test_hoju_badge_uses_names_available_at_module_level():
    """残件バッジ関数が使う module 名が、module スコープで解決できること。

    関数内ローカル import に頼っている名前を、別の関数がうっかり使うと同じ事故が起きる。
    ここでは実際に使っている 3つ (json / os / subprocess) を固定する。
    """
    src = open(PANEL, encoding="utf-8").read()
    mods = _module_level_imports(src)
    for name in ("json", "os", "subprocess", "sys", "time"):
        assert name in mods, f"{name} が module レベルに無い"
