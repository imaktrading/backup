#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""control_panel SCRIPTS の skip_postprocess 不変条件 (2026-06-10)。

発覚バグ: 監査ユーティリティ(csv_auditor)が listing 後処理チェーン(excluder/dedupe/write-keys)を
再実行 → 直前 cycle で write-keys が書いた canonical KEY を dedupe が「既存」と誤認し、未出品
(itemID空)の自カードを **自己重複として CSV から削除** (3件→1件に誤減)。
対策: 監査=読取専用は skip_postprocess=True で後処理を再実行させない (psa_to_csv で既に1回処理済)。
"""
import importlib.util
import os

_CP = os.path.join(os.path.dirname(__file__), "..", "control_panel.py")
_spec = importlib.util.spec_from_file_location("control_panel", _CP)
cp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cp)


def _entry(cmd_tail):
    """cmd の末尾スクリプト名で SCRIPTS エントリを引く。"""
    return [s for s in cp.SCRIPTS
            if isinstance(s.get("cmd"), list) and any(str(c).endswith(cmd_tail) for c in s["cmd"])]


def test_csv_auditor_skips_postprocess():
    """csv_auditor(監査)は後処理チェーンを再実行しない (= 自己重複誤除外の根治)。"""
    e = _entry("csv_auditor.py")
    assert len(e) == 1, "csv_auditor エントリが1つであること"
    assert e[0].get("skip_postprocess") is True


def test_relist_add_keeps_skip_postprocess():
    """取下再出品②(同型番の意図的再出品)も従来どおり後処理スキップを維持 (回帰防止)。"""
    e = _entry("relist_add_from_pending.py")
    assert len(e) == 1
    assert e[0].get("skip_postprocess") is True


def test_listing_generators_run_postprocess():
    """listing 生成本体(psa_to_csv 等)は後処理チェーンを走らせる (skip_postprocess を持たない)。"""
    for tail in ("psa_to_csv.py", "ichibankuji_to_csv.py"):
        e = _entry(tail)
        assert e, f"{tail} エントリが存在すること"
        assert not e[0].get("skip_postprocess"), f"{tail} は後処理を走らせる(skip無し)"
