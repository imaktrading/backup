# -*- coding: utf-8 -*-
"""drop_classifier: CSVにならなかった分を 原因+対策案 に自動分類する問題提起テスト (2026-06-30)。

ユーザー方針: Act(修正)は人が判断・指示。問題提起(原因→対策案)の自動化が目的。
catalog照会(set_exists)で 収録漏れ(セット在)/ scope外(セット無)を分ける。
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tools")))
import drop_classifier as dc


def test_catalog_miss_in_scope_vs_scope_out():
    log = ("⚠️ iMakCatalog (Pokemon) 未登録: SM9a-067 → Skip\n"
           "⚠️ iMakCatalog (Pokemon) 未登録: ZZ99-001 → Skip")
    # SM9a はセット在り(収録漏れ)、ZZ99 はセット無し(scope外)
    se = lambda p: p == "SM9a"
    drops = dc.classify_drops(log, set_exists=se)
    by = {d["item"]: d for d in drops}
    assert by["SM9a-067"]["class"] == "収録漏れ"
    assert "拡充依頼" in by["SM9a-067"]["act"]
    assert by["ZZ99-001"]["class"] == "scope外"
    assert "再試行停止" in by["ZZ99-001"]["act"] or "scope-out" in by["ZZ99-001"]["act"]


def test_promo_collision():
    log = "⚠️ iMakCatalog ID hit P-013 (ゴードン) だが PSA Subject 'SANJI' と名前不一致 → reject"
    drops = dc.classify_drops(log, set_exists=lambda p: True)
    d = drops[0]
    assert d["class"] == "promo衝突" and "SANJI" in d["act"] and d["item"] == "P-013"


def test_unconfirmed_viewer():
    log = "スキップ(目視未確定): #139291730"
    drops = dc.classify_drops(log, set_exists=lambda p: True)
    assert drops and "catalog欠" in drops[0]["class"] and "139291730" in drops[0]["item"]


def test_normal_exclusion_is_no_action():
    log = "⏭️ 既出品(同KEYが出品済)の2枚目を除外: 20件"
    drops = dc.classify_drops(log, set_exists=lambda p: True)
    assert drops[0]["class"] == "正常" and "不要" in drops[0]["act"]


def test_don_card_skip_is_classified_not_silent():
    # 番号なし DON!! は set+treatment(rarity)で識別可能 → silent drop させず問題提起に出す (2026-07-10)。
    # 回帰: この skip 行が分類0件だと "-1 silent drop" に埋もれ、有価カードを見過ごす。
    log = ("    ⏭️ Skip: reason=no_card_number_don DON!!カード番号欠落=変種特定不能 "
           "(cert 154458065, subject='DON!! CARD')")
    drops = dc.classify_drops(log, set_exists=lambda p: True)
    assert drops, "DON!! skip が分類されず silent drop になっている(見過ごし再発)"
    d = drops[0]
    assert d["class"] == "DON!!識別可(要catalog)"
    assert "154458065" in d["item"]
    assert d["class"] != "正常"          # actionable として reconcile に計上される
    assert "catalog" in d["act"]


def test_don_skip_makes_reconcile_account_for_it():
    # DON!! を分類すれば actionable に載り、処理件数照合で silent drop が減る方向に働く。
    log = ("2件を処理します\n成功: 1件 / 失敗: 1件\n"
           "    ⏭️ Skip: reason=no_card_number_don DON!!... (cert 999999, subject='DON!! CARD')")
    drops = dc.classify_drops(log, set_exists=lambda p: True)
    # 処理2 = 成功1 + 落ち1(DON!!) → 照合OK(DON!! が silent でなく計上される)
    assert "照合OK" in dc.reconcile_counts(log, drops)


def test_reconcile_counts():
    # 処理10 = 成功8 + 落ち2(actionable) → OK
    log_ok = "10件を処理します\n成功: 8件 / 失敗: 0件"
    drops = [{"class": "収録漏れ"}, {"class": "promo衝突"}, {"class": "正常"}]  # actionable=2
    assert "照合OK" in dc.reconcile_counts(log_ok, drops)
    # 処理10 ≠ 成功5+落ち2=7 → 不一致警告(silent drop余地)
    log_ng = "10件を処理します\n成功: 5件 / 失敗: 0件"
    r = dc.reconcile_counts(log_ng, drops)
    assert "不一致" in r and "silent drop" in r
    # 処理件数不明 → 空
    assert dc.reconcile_counts("成功: 5件", drops) == ""


def test_render_and_empty():
    assert dc.render_problem_report([]) == ""
    rep = dc.render_problem_report([{"item": "X", "class": "収録漏れ", "cause": "c", "act": "a"}])
    assert "問題提起" in rep and "対策案" in rep
