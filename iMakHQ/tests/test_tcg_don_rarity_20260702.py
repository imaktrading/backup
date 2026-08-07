#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TCG check_csv: DON!!カードを C:Rarity 必須から外す card-aware 判定 (2026-07-02)。

DON!!カード(One Piece, card number 'DON-' prefix)は構造的に rarity を持たない。
従来 REQUIRED_SPECIFICS に C:Rarity があり、DON カードが毎監査で「必須 C:Rarity 空」を
誤検出→再発計上していた。won't-fix で隠すのでなく監査ルールを card-aware 化して解消
(Gemini 推奨: 恒久ロジックで識別できる例外はルール化が正)。その回帰固定。
"""
import importlib.util
import os

_TCG = os.path.join(os.path.dirname(__file__), "..", "..", "iMakTCG", "check_csv.py")


def _load():
    spec = importlib.util.spec_from_file_location("tcg_check_csv", _TCG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_don_card_not_require_rarity():
    mod = _load()
    req = mod.required_specifics_for_card("DON-PRB01-027")
    assert "C:Rarity" not in req
    # 他の必須は維持
    assert set(req) >= {"C:Game", "C:Set", "C:Card Name", "C:Character"}


def test_don_case_insensitive():
    mod = _load()
    assert "C:Rarity" not in mod.required_specifics_for_card("don-prb01-027")


def test_normal_card_keeps_rarity():
    mod = _load()
    for num in ("OP01-025", "089/080", "126/S-P", ""):
        assert "C:Rarity" in mod.required_specifics_for_card(num), num
    # 通常カードは既定の完全リストと一致
    assert mod.required_specifics_for_card("OP01-025") == mod.REQUIRED_SPECIFICS
