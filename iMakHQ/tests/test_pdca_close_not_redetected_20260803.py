# -*- coding: utf-8 -*-
"""pdca_store.close_not_redetected — 「今回の走行で再検出されなかったら閉じる」(2026-08-03)。

auditor 由来の finding は時間でしか閉じられなかった。`prune_resolved_gaps` の resolver は
catalog の product_id で照合するが、auditor 行の item_id は **メルカリ item id**
(`m81161788422`) なので必ず False = 永久に pending (実測 queue_id 546 / seen 3 / 07-31 更新)。
監査くんは毎回「その走行で検出した全件」を持っているので、そこに居ない pending は
**今回のCSVでは再現しなかった** = 解決済。時間の閾値は要らない。

★最重要の回帰点: **今回の検出が0件 / 監査行0件の走行では1件も閉じない**。
  空の走行を「全部解決した」と解釈すると未解決の指摘を全消しする
  ([[failclosed_must_skip_not_destructive]])。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import pdca_store as pdca

TS = "2026-08-03"


def _seed():
    con = pdca.connect(":memory:")
    # 今回も再検出される finding
    pdca.upsert_improvement(con, "tcg", "m111", "C:Set", "", source="auditor", layer="A",
                            finding_type="catalog_gap", ts="2026-07-29")
    # 今回は再検出されない finding (= CSV側が直った)
    pdca.upsert_improvement(con, "tcg", "m222", "C:Set", "", source="auditor", layer="A",
                            finding_type="catalog_gap", ts="2026-07-29")
    # 別カテゴリ (触ってはいけない)
    pdca.upsert_improvement(con, "gshock", "m333", "C:Set", "", source="auditor", layer="A",
                            finding_type="catalog_gap", ts="2026-07-29")
    # 別source (auditor 以外は対象外)
    pdca.upsert_improvement(con, "tcg", "GA-710", "catalog_add", "", source="missing_models",
                            layer="A", finding_type="catalog_gap", ts="2026-07-29")
    return con


def _status(con, item_id):
    r = con.execute("SELECT status FROM improvement_queue WHERE item_id=?", (item_id,)).fetchone()
    return r["status"] if r else None


def test_not_redetected_is_closed_and_redetected_is_kept():
    con = _seed()
    seen = {pdca.dedup_key("tcg", "m111", "C:Set", "")}
    got = pdca.close_not_redetected(con, "tcg", seen, ["m111", "m222"], ts=TS, audited_rows=8)
    assert got["closed"] == 1
    assert _status(con, "m111") == "pending", "今回も出た finding を閉じている"
    assert _status(con, "m222") == "done", "再検出されなかった finding が閉じていない"


def test_other_category_and_source_are_untouched():
    con = _seed()
    pdca.close_not_redetected(con, "tcg", {pdca.dedup_key("tcg", "m111", "C:Set", "")},
                              ["m111", "m222", "m333", "GA-710"], ts=TS, audited_rows=8)
    assert _status(con, "m333") == "pending", "別カテゴリを閉じている"
    assert _status(con, "GA-710") == "pending", "別source(missing_models)を閉じている"


def test_finding_outside_this_runs_population_is_kept():
    """★今回そのSKUを監査していない finding は閉じない。

    監査は毎回「その日のCSV1本」しか見ない。母集団を絞らないと **未解決の backlog を全消し**
    する (実測: tcg/auditor pending 13件のうち12件が過去CSV由来。絞らずに走らせたら13件全部
    done になった)。「今日そのSKUを監査した。そして指摘が出なかった」が唯一の証拠。
    """
    con = _seed()
    # 今回のCSVには m111 しか入っていない → m222 は判定対象外
    got = pdca.close_not_redetected(con, "tcg", {pdca.dedup_key("tcg", "m111", "C:Set", "")},
                                    ["m111"], ts=TS, audited_rows=8)
    assert got["closed"] == 0, "監査していないSKUを閉じている(未解決の全消し)"
    assert _status(con, "m222") == "pending"


def test_zero_findings_closes_nothing():
    """今回1件も検出しなかった場合でも、監査した SKU の分だけは閉じてよい。"""
    con = _seed()
    got = pdca.close_not_redetected(con, "tcg", set(), ["m111", "m222"], ts=TS,
                                    audited_rows=8)
    assert got["closed"] == 2, "監査済みSKUで指摘0件なら閉じてよい"


def test_empty_population_closes_nothing():
    """監査対象SKUを特定できない走行では1件も閉じない (fail-closed)。"""
    con = _seed()
    got = pdca.close_not_redetected(con, "tcg", set(), [], ts=TS, audited_rows=8)
    assert got["closed"] == 0 and "fail-closed" in got["skipped_reason"]
    assert _status(con, "m222") == "pending"


def test_zero_audited_rows_closes_nothing():
    """CSVが空/0行の走行では閉じない。全消し事故の回帰点。"""
    con = _seed()
    got = pdca.close_not_redetected(con, "tcg", {pdca.dedup_key("tcg", "m111", "C:Set", "")},
                                    ["m111", "m222"], ts=TS, audited_rows=0)
    assert got["closed"] == 0 and "fail-closed" in got["skipped_reason"]
    assert _status(con, "m222") == "pending"


def test_closed_finding_revives_on_redetection():
    """閉じたあと再発したら pending に戻る (既存の revival をそのまま使う = 見逃さない)。"""
    con = _seed()
    pdca.close_not_redetected(con, "tcg", {pdca.dedup_key("tcg", "m111", "C:Set", "")},
                              ["m111", "m222", "m333", "GA-710"], ts=TS, audited_rows=8)
    assert _status(con, "m222") == "done"
    pdca.upsert_improvement(con, "tcg", "m222", "C:Set", "", source="auditor", layer="A",
                            finding_type="catalog_gap", ts="2026-08-04")
    assert _status(con, "m222") == "pending", "再発しても閉じたままになっている"


def test_close_reason_is_recorded_in_evidence():
    """なぜ閉じたかが残らないと監査ログとして読めない。"""
    con = _seed()
    pdca.close_not_redetected(con, "tcg", {pdca.dedup_key("tcg", "m111", "C:Set", "")},
                              ["m111", "m222", "m333", "GA-710"], ts=TS, audited_rows=8)
    ev = con.execute("SELECT evidence FROM improvement_queue WHERE item_id='m222'").fetchone()[0]
    assert "再検出なし" in ev and TS in ev


def test_finding_types_filter_is_honoured():
    con = _seed()
    got = pdca.close_not_redetected(con, "tcg", {pdca.dedup_key("tcg", "m111", "C:Set", "")},
                                    ["m111", "m222"], ts=TS, audited_rows=8,
                                    finding_types=("program_fix",))
    assert got["closed"] == 0, "対象外の finding_type を閉じている"
    assert _status(con, "m222") == "pending"
