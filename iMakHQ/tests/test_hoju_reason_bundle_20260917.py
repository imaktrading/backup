# -*- coding: utf-8 -*-
"""補URL③ / 再仕入れ① の「外す理由」に「まとめ売り・複数枚」(2026-09-17 ユーザー指示)。

押した仕入元は「買えない URL」台帳へ = どの候補画面にも二度と出ない (売り切れと同じ扱い)。
"""
import json
import os
import sys

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)


def _src(name):
    return open(os.path.join(_TOOLS, name), encoding="utf-8").read()


def test_button_and_payload_are_wired():
    s = _src("psa_resource_confirm.py")
    assert "data-r='bundle'" in s and "まとめ売り・複数枚" in s
    assert "rsn==='bundle'" in s and "bundle:bundles" in s


def test_server_parses_bundle():
    s = _src("psa_resource_confirm.py")
    assert '"bundle": bundle' in s and 'data.get("bundle")' in s


def test_both_consumers_record_to_not_buyable_ledger():
    for f in ("psa_hoju_fill.py", "psa_resource_gate.py"):
        s = _src(f)
        i = s.index('res.get("bundle")')
        assert "remember_not_buyable(" in s[i:i + 600], f


def test_skip_row_reason_is_not_mixed_into_miokuri():
    s = _src("psa_hoju_fill.py")
    assert '"まとめ売り" if idx in bundles' in s
