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


def test_promo_reject_but_rescued_is_not_a_drop():
    # reject後にpromo fallbackでbuild成功した品は drop に数えない(二重計上回避・2026-07-10)。
    log = ("⚠️ iMakCatalog ID hit P-013 (ゴードン) だが PSA Subject 'SANJI' と名前不一致 → reject\n"
           "🎯 iMakCatalog hit (promo fallback): OP01-013_p1 サンジ (Subject='SANJI' brand='X' と一致, 11件中 score=280)\n"
           "✨ Title: PSA 10 One Piece ... #OP01-013 Sanji")
    drops = dc.classify_drops(log, set_exists=lambda p: True)
    assert not any(d["class"] == "promo衝突" for d in drops), \
        "救済済(build成功)のpromoが drop に二重計上されている"


def test_promo_reject_without_rescue_still_flagged():
    # 救済ログが無い純粋な reject は従来どおり promo衝突として問題提起する(回帰: 見落とさない)。
    log = "⚠️ iMakCatalog ID hit P-013 (ゴードン) だが PSA Subject 'SANJI' と名前不一致 → reject"
    drops = dc.classify_drops(log, set_exists=lambda p: True)
    assert any(d["class"] == "promo衝突" and d["item"] == "P-013" for d in drops)


def test_reconcile_accurate_after_rescue_exclusion():
    # 処理2 = 成功1(fallback build) + 落ち1(該当なし) → 照合OK。救済分をdropに数えないので合う。
    log = ("2件を処理します\n成功: 1件 / 失敗: 0件\n"
           "⚠️ ID hit P-013 (ゴードン) だが PSA Subject 'SANJI' と名前不一致 → reject\n"
           "🎯 iMakCatalog hit (promo fallback): OP01-013_p1 サンジ (Subject='SANJI' と一致)\n"
           "スキップ(目視未確定): #163045378")
    drops = dc.classify_drops(log, set_exists=lambda p: True)
    assert "照合OK" in dc.reconcile_counts(log, drops)


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


# ============================================================================
# 構造的 drop 検出 (2026-08-01) — 「分類ルールの足し忘れ」で件数不一致が毎回出るのを止める
# ============================================================================
_LOG_STRUCTURAL = (
    "4件を処理します。（仕入値あり: 4件）\n"
    "取得中(確認用): #111111111... ✓\n"
    "取得中(確認用): #222222222... ✓\n"
    "取得中(確認用): #333333333... ✓\n"
    "取得中(確認用): #444444444... 失敗\n"
    "スキップ(目視未確定): #333333333\n"
    "    ❌ セルフチェック失敗 (#222222222):\n"
    "       ❌ タイトルに'ST02'があるが PSA brand に存在しない: 'GUNDAM JAPANESE PB01-...'\n"
    "    ⚠️ Skipping #222222222: selfcheck failed in build_row\n"
    "成功: 1件 / 失敗: 1件\n"
    "完了！出力: C:/x/tcg_upload_1.csv\n"
)
_CSV_STRUCTURAL = '"CustomLabel"\n"PSA10-111111111"\n'


def _structural_drops():
    return dc.classify_drops(_LOG_STRUCTURAL, set_exists=lambda p: True,
                             csv_text=_CSV_STRUCTURAL)


def test_universe_minus_csv_defines_the_drop_set():
    # 落ちは「処理cert − CSVcert」の差分で決まる。分類ルールの有無に依存しない。
    assert dc.processed_certs(_LOG_STRUCTURAL) == [
        "111111111", "222222222", "333333333", "444444444"]
    assert dc.built_certs(_CSV_STRUCTURAL) == {"111111111"}
    certs = {d["cert"] for d in dc.structural_drops(_LOG_STRUCTURAL, _CSV_STRUCTURAL)}
    assert certs == {"222222222", "333333333", "444444444"}


def test_selfcheck_failure_is_named_not_a_bare_count_gap():
    # 2026-08-01 の実ケース: selfcheck 落ちに分類ルールが無く「⚠️件数不一致」だけが出ていた。
    d = {x["cert"]: x for x in _structural_drops() if x.get("cert")}
    assert d["222222222"]["class"] == "セルフチェック不合格"
    assert "ST02" in d["222222222"]["cause"], "弾いた理由の明細が出ていない"
    assert "①" in d["222222222"]["act"] and "②" in d["222222222"]["act"], \
        "1丁目1番地の判定に接続されていない"
    assert d["444444444"]["class"] == "PSA取得失敗"
    assert d["333333333"]["class"] == "該当なし(catalog欠)"


def test_unknown_drop_is_surfaced_with_cert_not_silent():
    # 未知の落ち方でも **集合から外れない**。cert 付きで「未分類」として必ず表に出る。
    log = ("2件を処理します\n取得中: #777777777... ✓\n取得中: #888888888... ✓\n"
           "🌀 これは将来の新しい落ち方 (#888888888)\n完了！出力: C:/x/a.csv\n")
    drops = dc.classify_drops(log, set_exists=lambda p: True,
                              csv_text='"PSA10-777777777"\n')
    unknown = [d for d in drops if d["class"] == "未分類(要調査)"]
    assert len(unknown) == 1 and unknown[0]["cert"] == "888888888"
    assert "888888888" in unknown[0]["act"], "調べる手がかり(cert)が対策案に無い"


def test_reconcile_always_balances_when_csv_given():
    # 新種の落ち方が増えても件数は定義上合う → ⚠️不一致は分類漏れでは鳴らない。
    r = dc.reconcile_counts(_LOG_STRUCTURAL, _structural_drops(), csv_text=_CSV_STRUCTURAL)
    assert "照合OK" in r and "処理4" in r and "CSV1" in r and "落ち3" in r


def test_reconcile_reports_unknown_count():
    log = ("2件を処理します\n取得中: #777777777... ✓\n取得中: #888888888... ✓\n"
           "完了！出力: C:/x/a.csv\n")
    csv = '"PSA10-777777777"\n'
    drops = dc.classify_drops(log, set_exists=lambda p: True, csv_text=csv)
    r = dc.reconcile_counts(log, drops, csv_text=csv)
    assert "照合OK" in r and "理由未特定 1件" in r


def test_reconcile_still_flags_truncated_log():
    # 分類漏れでは鳴らないが、ログ自体が欠けている(宣言数 ≠ 取得中行数)は実害なので鳴らす。
    log = ("10件を処理します\n取得中: #777777777... ✓\n完了！出力: C:/x/a.csv\n")
    csv = '"PSA10-777777777"\n'
    r = dc.reconcile_counts(log, dc.classify_drops(log, set_exists=lambda p: True, csv_text=csv),
                            csv_text=csv)
    assert "ログ欠落" in r


def test_structural_mode_does_not_double_count_existing_rules():
    # ③目視未確定 は旧ルールでも cert 付きで拾える。構造側と二重に並べない。
    drops = _structural_drops()
    certs = [d.get("cert") for d in drops if d.get("cert")]
    assert len(certs) == len(set(certs)), f"cert が二重計上されている: {certs}"


def test_legacy_path_unchanged_without_csv():
    # csv_text 未指定(旧呼出/他カテゴリ)では従来のパターン方式のまま = 後方互換。
    drops = dc.classify_drops(_LOG_STRUCTURAL, set_exists=lambda p: True)
    assert not any(d["class"] == "未分類(要調査)" for d in drops)
    assert "不一致" in dc.reconcile_counts(_LOG_STRUCTURAL, drops)


def test_render_and_empty():
    assert dc.render_problem_report([]) == ""
    rep = dc.render_problem_report([{"item": "X", "class": "収録漏れ", "cause": "c", "act": "a"}])
    assert "問題提起" in rep and "対策案" in rep
