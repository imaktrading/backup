#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSV監査くん (csv_auditor.py) 純関数の回帰テスト。

固定する不変条件 (ユーザー合意・出品の正確性):
  - 「修正」3分岐の分類が崩れない (送料=機械修正 / データ誤り=除外+カタログ依頼 /
     生成バグ=除外+プログラム依頼 / SEO=報告のみ)。値の捏造は決して MECH_FIX にしない。
  - 誤出品直結 (title>80/PSA10/禁止語/日本語/カテゴリ/cert/価格非数値/set誤マップ) は必ず除外。
  - 行集約は重い処置 (除外) を優先。
check_csv の validate_row 文言に依存するので、文言変更が起きたらここが落ちる (回帰検知)。
"""
import importlib.util
import os

_TOOLS = os.path.join(os.path.dirname(__file__), "..", "tools")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_TOOLS, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


A = _load("csv_auditor")


def test_classify_mech_fix_shipping():
    assert A.classify_finding("WARN", "送料ポリシー '40-60' が価格$55に対して不一致（期待: 60-100）") == A.MECH_FIX


def test_classify_data_error_set_mismap():
    msg = "Set世代↔Year 不整合: Set='X'(世代 SM:2017-2019) なのに Year=2026 → set_name_ebay 誤マップ疑い"
    assert A.classify_finding("ERROR", msg) == A.EXCLUDE_CATALOG


def test_classify_required_spec_empty():
    assert A.classify_finding("WARN", "必須Item Specific 'C:Rarity' が空") == A.SPEC_EMPTY


def test_classify_failclosed():
    assert A.classify_finding("ERROR", "PSA鑑定番号が不正: abc") == A.EXCLUDE_FAILCLOSED
    assert A.classify_finding("ERROR", "価格が数値でない: ") == A.EXCLUDE_FAILCLOSED


def test_classify_program_bugs():
    assert A.classify_finding("ERROR", "タイトル92字 > 上限80字") == A.REPORT_PROGRAM
    assert A.classify_finding("ERROR", "タイトルが 'PSA 10' で始まっていない") == A.REPORT_PROGRAM
    assert A.classify_finding("ERROR", "禁止ワード 'mint' がタイトルに含まれている") == A.REPORT_PROGRAM
    assert A.classify_finding("ERROR", "カテゴリが 183454 でない: 999") == A.REPORT_PROGRAM
    assert A.classify_finding("ERROR", "ConditionID が 2750 でない: 1000") == A.REPORT_PROGRAM
    assert A.classify_finding("ERROR", "タイトルに日本語文字が混入: 'リソース'") == A.REPORT_PROGRAM


def test_classify_seo_and_info():
    assert A.classify_finding("WARN", "タイトル60字 < 推奨70字（キーワード不足の可能性）") == A.SEO_NOTE
    assert A.classify_finding("WARN", "タイトル内で 'pikachu' が重複") == A.SEO_NOTE
    # 推奨spec空は SEO 改善メモ扱い (プラン table どおり、行は残す)
    assert A.classify_finding("INFO", "推奨Item Specifics が空: Card Type, Features") == A.SEO_NOTE
    # SEO語を含まない素の INFO は INFO_ONLY
    assert A.classify_finding("INFO", "参考情報") == A.INFO_ONLY


def test_seo_never_becomes_mech_fix():
    # 値の捏造禁止: SEO/データ系が機械修正に分類されない (送料以外は CSV を書き換えない)
    for sev, msg in [
        ("WARN", "必須Item Specific 'C:Set' が空"),
        ("WARN", "タイトル60字 < 推奨70字（キーワード不足の可能性）"),
        ("ERROR", "Set↔total 不整合"),
    ]:
        assert A.classify_finding(sev, msg) != A.MECH_FIX


def test_row_disposition_priority_and_exclude():
    # 除外は機械修正より優先 / 1つでも除外系があれば行除外
    disps = [A.MECH_FIX, A.SEO_NOTE, A.EXCLUDE_CATALOG]
    assert A.row_disposition(disps) == A.EXCLUDE_CATALOG
    assert A.should_exclude(disps) is True
    # 送料修正だけの行は除外されない (修正して残す)
    assert A.should_exclude([A.MECH_FIX, A.SEO_NOTE]) is False
    assert A.row_disposition([A.MECH_FIX, A.SEO_NOTE]) == A.MECH_FIX


def test_detect_category():
    headers = ["*Title", "*Category", "C:Game", "C:Card Name", "C:Rarity"]
    rows = [["x", "183454", "Pokémon TCG", "Pikachu", "SR"]]
    assert A.detect_category(headers, rows) == "tcg"
    # *Category 値優先
    h2 = ["*Title", "*Category", "C:Model", "C:Movement"]
    assert A.detect_category(h2, [["x", "31387", "GA-100", "Quartz"]]) == "gshock"
    # 判定不能 (Mercari系等) → None
    assert A.detect_category(["*Title", "C:Department"], [["x", "Men"]]) is None
