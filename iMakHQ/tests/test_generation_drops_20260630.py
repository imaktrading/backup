# -*- coding: utf-8 -*-
"""control_panel.summarize_generation_drops: 生成段階で CSVにならなかった分の抽出 (2026-06-30)。

全カテゴリ共通(generator固有文言に依存しない)。監査くんはCSV化された行しか見ないので、
生成段階の fail-closed 除外(名前不一致reject/catalog未登録/目視未確定/既出品除外等)が
盲点になるのを防ぐ。ユーザー指摘「CSVにならなかった分はなんなの」「TCGだけのは無し」。
"""
import os
import sys
import importlib.util

_CP = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "control_panel.py"))
_spec = importlib.util.spec_from_file_location("control_panel", _CP)
cp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cp)


def test_extracts_tcg_drops():
    log = """=== 新規 ===
  ⏭️ 既出品(同KEYが出品済)の2枚目を除外: 20件
  ⚠️ iMakCatalog ID hit P-013 だが PSA Subject 'SANJI' と名前不一致 → reject
  ⚠️ iMakCatalog (Pokemon) 未登録: SM9a-067 → Skip
スキップ(目視未確定): #139291730
成功: 5件 / 失敗: 2件
"""
    s = cp.summarize_generation_drops(log)
    assert "CSVにならなかった" in s
    assert "20件" in s
    assert "reject" in s
    assert "未登録" in s
    assert "目視未確定" in s


def test_generic_other_category():
    # G-shock/Mercari 等 別文言でも共通 marker で拾う
    log = "在庫切れでスキップ: GA-2100\n仕入元在庫✕で見送り 3件\n成功: 8件 / 失敗: 1件"
    s = cp.summarize_generation_drops(log)
    assert s and ("スキップ" in s or "見送り" in s or "失敗" in s)


def test_empty_when_no_drops():
    assert cp.summarize_generation_drops("成功: 5件 / 失敗: 0件\n完了") == ""   # 失敗0件=ドロップ無し=空
    assert cp.summarize_generation_drops("") == ""
    assert cp.summarize_generation_drops("普通の進捗ログ\n完了") == ""
    # 補正/目視確定 は誤検出しない(ノイズ除外)
    assert cp.summarize_generation_drops("🤖 card_number 不一致補正: Vision=054 → PSA=054") == ""
    assert cp.summarize_generation_drops("✅ 目視確定: 8 件を build へ (未確定は除外)") == ""
