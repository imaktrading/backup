#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RESTOCK Revise は新規出品用の重複くん(dedupe excluder)を走らせない (2026-06-22)。

発覚バグ: ♻RESTOCK Revise CSV生成 で確定12件中3件(OP02-036/S8b-187/ST29-016)が
dedupe excluder に「真の重複」として物理除外された。RESTOCK は Action=Revise(itemID指定で
既存出品の qty 0→1)で新規出品を作らず重複し得ないが、新規出品用の重複くんが RESTOCK 対象の
**自分の既存出品 KEY**(商品管理シート AI列)と自己マッチして誤除外。特に qty=0 の OP02-036 は
再出品されず機会損失。
対策: restock_revise エントリは _runs_new_listing_dedupe()=False で新規用 dedupe を skip。
title-fix / Add→Revise 変換は従来どおり走らせる(skip_postprocess 丸ごとskipとは別)。
"""
import importlib.util
import os

_CP = os.path.join(os.path.dirname(__file__), "..", "control_panel.py")
_spec = importlib.util.spec_from_file_location("control_panel", _CP)
cp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cp)


def _entry(cmd_tail):
    return [s for s in cp.SCRIPTS
            if isinstance(s.get("cmd"), list) and any(str(c).endswith(cmd_tail) for c in s["cmd"])]


def test_restock_entry_has_restock_revise_flag():
    """♻RESTOCK ボタンは restock_revise=True を持つ (= dedupe skip の判定軸)。"""
    e = _entry("psa_restock_build.py")
    assert len(e) == 1, "psa_restock_build エントリが1つであること"
    assert e[0].get("restock_revise") is True


def test_restock_skips_new_listing_dedupe():
    """RESTOCK Revise は新規用 dedupe を走らせない (自己重複誤除外の根治)。"""
    e = _entry("psa_restock_build.py")[0]
    assert cp._runs_new_listing_dedupe(e) is False


def test_new_listing_runs_dedupe():
    """新規出品本体(psa_to_csv 等)は従来どおり dedupe を走らせる (回帰防止)。"""
    for tail in ("psa_to_csv.py",):
        e = _entry(tail)
        assert e, f"{tail} エントリが存在すること"
        assert cp._runs_new_listing_dedupe(e[0]) is True, f"{tail} は新規=dedupe走らせる"


def test_skip_postprocess_also_skips_dedupe():
    """skip_postprocess(監査/relist)は引き続き dedupe を走らせない (回帰防止)。"""
    assert cp._runs_new_listing_dedupe({"skip_postprocess": True}) is False
    assert cp._runs_new_listing_dedupe({"restock_revise": True}) is False
    assert cp._runs_new_listing_dedupe({}) is True
