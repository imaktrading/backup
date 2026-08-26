# -*- coding: utf-8 -*-
"""catalog 以外から Item Specifics の値を作らない (2026-08-26)。

契約 (_contract_aspects.yaml) は「値はカタログが決める・出品くんは写すだけ」。
出品くん側に **catalog 以外から値が入る口** が残っていて、catalog が空の列に
別の数字/色が出ていた。口そのものを塞ぐ。

  提案1: C:Attack/Power に **HP** が入る (8/25 の入稿 17行中 6行)
  提案3: C:Attribute/MTG:Color に **Vision が読んだ色** が入る

依頼書: hq/requests/2026-08-25_act_code_proposals_tcg.md 提案1・提案3
回答書: hq/requests/2026-08-26_act_code_proposals_tcg_response.md (2)(3)
"""
import ast
import io
import os
import sys

_TCG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "iMakTCG")
if _TCG not in sys.path:
    sys.path.insert(0, _TCG)


def _source(name="psa_to_csv.py"):
    return io.open(os.path.join(_TCG, name), encoding="utf-8").read()


def _assigned_from(src, target):
    """`target = <expr>` の右辺ソースを全部返す (コメントは拾わない = AST)。"""
    out = []
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and any(
                getattr(t, "id", "") == target for t in n.targets):
            out.append(ast.unparse(n.value))
    return out


def test_attack_power_is_never_filled_from_pokemon_hp():
    """HP は C:HP が持つ。C:Attack/Power の供給元にしてはいけない。"""
    for expr in _assigned_from(_source(), "official_power"):
        assert "hp" not in expr.lower(), (
            f"official_power = {expr} — HP を C:Attack/Power に写している "
            "(2026-08-25 の入稿で 6/17行が C:HP と同値になった)")
