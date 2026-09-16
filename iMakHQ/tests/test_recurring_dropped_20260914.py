# -*- coding: utf-8 -*-
"""digest の recurring_missing が台帳(missing_models.csv/pdca)しか見ないため、
カテゴリが確定する前に落ちる cert (PSA 404 等・提案3型) を取りこぼす件 (2026-09-14 提案4)。

実害: cert936643273 が14走行連続で「build skip」「出品見送り」に載り続けていたが、
台帳には一度も乗らないため digest の recurring_missing は毎日 0 のままだった
(9/11 提案3 / 9/12 提案4 / 9/13 で3日連続同じ穴を報告)。

依頼書: hq/requests/2026-09-13_act_code_proposals_tcg.md 提案4
回答書: hq/requests/2026-09-13_act_code_proposals_tcg_response.md
"""
import os
import sys

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import csv_auditor as ca  # noqa: E402

# 実ログの表記そのまま (run_logs/____20260829_190826.log 等・iMakTCG/psa_to_csv.py 出力)
_LOG_936643273 = (
    "取得中(確認用): #936643273...\n"
    "  ⚠️ cert 936643273: cache miss/category不明/対象外 → 目視対象外 (build skip)\n"
    "     ・目視に出せなかった (PSAデータ/カテゴリ不明): 1件 [#936643273]\n"
    "スキップ(目視未確定): #936643273\n"
    "🔎 目視未確定で出品見送り: 2 件 ['936643273', '152977069']\n"
)
_LOG_CLEAN = "🔎 目視未確定で出品見送り: 0 件 []\n"


def test_extract_dropped_certs_from_build_skip_line():
    certs = ca._extract_dropped_certs_from_log(_LOG_936643273)
    assert certs == {"936643273", "152977069"}


def test_extract_dropped_certs_empty_when_no_drops():
    assert ca._extract_dropped_certs_from_log(_LOG_CLEAN) == set()


def test_recurring_dropped_certs_needs_min_days():
    """1〜2日だけの drop は再発扱いにしない (min_days=3 既定)。"""
    by_date = {"20260910": _LOG_936643273, "20260911": _LOG_936643273}
    assert ca.recurring_dropped_certs(by_date) == []


def test_recurring_dropped_certs_flags_after_three_days():
    """実害相当: 14走行 (>=3日) 連続で同じ cert が落ち続けたら再発として返す。"""
    by_date = {f"2026090{d}": _LOG_936643273 for d in range(1, 8)}   # 7日分
    out = ca.recurring_dropped_certs(by_date)
    got = {r["cert"]: r["days"] for r in out}
    assert got["936643273"] == 7
    assert got["152977069"] == 7
    # days 降順
    assert out == sorted(out, key=lambda r: r["days"], reverse=True)


def test_build_ng_digest_carries_recurring_dropped():
    d = ca._build_ng_digest("tcg", [], [], [], recurring_dropped=[{"cert": "936643273", "days": 14}])
    assert d["recurring_dropped"] == [{"cert": "936643273", "days": 14}]
    assert d["counts"]["recurring_dropped"] == 1


def test_build_ng_digest_recurring_dropped_defaults_empty_when_omitted():
    """既存呼出 (recurring_dropped 省略) は壊さない。"""
    d = ca._build_ng_digest("tcg", [("sku1", "msg1")], ["error: 2件"], [])
    assert d["recurring_dropped"] == []
    assert d["counts"]["recurring_dropped"] == 0


# ---- 2026-09-16: 窓 / 理由 / 前段の除外行 / 再仕入れの itemID 行 / プロジェクト絞り ----
# 依頼書: hq/requests/2026-09-14_act_code_proposals_tcg.md 提案① (GO) /
#         2026-09-14_act_code_proposals_mercari.md 提案2 (GO) / 2026-09-15_act_code_proposals_tcg.md 提案③

_LOG_STAGE = (
    "  ⏭️ 枠を選ぶ前に除外 [OUT-OF-SCOPE=参入しないゲーム]: 2件 → ['140273536', '146117881']\n"
    "  ⏭️ 枠を選ぶ前に除外 [COST-CAP=仕入値が上限を超えている(目視しても最後に落ちる)]: 1件 → ['123143536']\n"
    "  🚫 PSA に写真が無い個体を除外: 1件 → ['15123139']\n"
    "  ⏭ ('358609093013', 'cert#未解決(商品管理シートI列に無い)→生成不可')\n"
    "  ⏭ ('358604221711', '仕入値が上限を超えている ¥132,500 (上限 ¥70,000)→生成不可')\n"
    "  ⏭ ('358887214446', '仕入元が生きている (D列が空) = 売れた分の補充 / 監視くんの担当→生成不可')\n"
)


def _by_key(out):
    return {(r.get("cert") or r.get("item_id")): r for r in out}


def test_stage_and_item_lines_are_counted_with_reason():
    got = _by_key(ca.recurring_dropped_certs({f"2026091{d}": _LOG_STAGE for d in range(3)}))
    assert got["140273536"]["reason"] == "OUT-OF-SCOPE"
    assert got["123143536"]["reason"] == "COST-CAP"
    assert got["15123139"]["reason"] == "写真なし"
    assert got["358609093013"]["reason"] == "cert#未解決" and "item_id" in got["358609093013"]
    assert got["358604221711"]["reason"] == "COST-CAP"
    assert "358887214446" not in got, "他の担当に回す正常な振り分けは詰まりではない"


def test_days_outside_window_are_not_counted():
    by_date = {"20260801": _LOG_936643273, "20260802": _LOG_936643273, "20260803": _LOG_936643273}
    assert ca.recurring_dropped_certs(by_date, since="20260902") == []


def test_psa_not_found_cert_gets_its_own_reason():
    by_date = {f"2026091{d}": _LOG_936643273 for d in range(3)}
    got = _by_key(ca.recurring_dropped_certs(by_date, not_found={"936643273"}))
    assert got["936643273"]["reason"] == "PSA照会失敗"
    assert got["152977069"]["reason"] != "PSA照会失敗"


def test_non_tcg_project_gets_no_psa_drops(tmp_path):
    (tmp_path / "x_20990101_000000.log").write_text(_LOG_936643273, encoding="utf-8")
    assert ca._scan_run_logs_dropped(str(tmp_path), min_days=1, project="mercari") == []
