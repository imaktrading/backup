# -*- coding: utf-8 -*-
"""出品くんが裏で呼ぶ PowerShell / taskkill で黒い窓を出さない (2026-09-15)。

ユーザー「powershellが定期的に立ち上がるのはなに？」→「掃除してくれるのはいいんだけど、黒窓が邪魔」。
出品くん (pythonw・窓なし) が10分おきに kill_orphan_drivers で置き去りブラウザを掃除し、
そのたびに PowerShell の窓が一瞬出ていた。PSA 補URL の検索後の片付けも同じ呼び方だった。
"""
import ast
import os

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
CONSOLE_APPS = ("powershell", "taskkill", "cmd", "_GIT_KILL")


def _calls_without_flag(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Attribute) and f.attr in ("run", "Popen", "call", "check_output")
                and isinstance(f.value, ast.Name) and f.value.id == "subprocess"):
            continue
        if not node.args or not isinstance(node.args[0], ast.List) or not node.args[0].elts:
            continue
        first = node.args[0].elts[0]
        name = first.value if isinstance(first, ast.Constant) else getattr(first, "id", "")
        if not any(str(name).lower().startswith(a.lower()) for a in CONSOLE_APPS):
            continue
        if not any(k.arg == "creationflags" for k in node.keywords):
            bad.append((node.lineno, name))
    return bad


def test_orphan_cleaner_hides_windows():
    assert _calls_without_flag(os.path.join(TOOLS, "kill_orphan_drivers.py")) == []


def test_psa_hoju_cleanup_hides_windows():
    assert _calls_without_flag(os.path.join(TOOLS, "psa_hoju_fill.py")) == []
