"""Regression: 2026-06-08 PDCA 台帳 (audit_ledger) — 蓄積/前回比/再発検知.

監査を「検出して終わり」にせず PDCA で回すための土台 ([[pdca_spiral_up_expectation]])。
固定する不変条件:
  - 初回は previous=None・trend空。2回目以降に前回比 trend が出る。
  - 再発(recurring)=前回も今回も有る finding / 解消(resolved)=前回有→今回無 / new=今回新規。
  - trend_arrow は KPI 方向 (down良/up良) に従って 改善/悪化 を返す。
  - dry-run (write=False) は台帳に追記しない。
"""
import importlib.util
import os
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent.parent / "iMakHQ" / "tools"


def _load():
    spec = importlib.util.spec_from_file_location("audit_ledger", str(_TOOLS / "audit_ledger.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _point(mod, tmp_path):
    mod.LEDGER_DIR = str(tmp_path)
    mod.LEDGER_PATH = str(tmp_path / "ledger.jsonl")


def test_first_run_has_no_trend(tmp_path):
    L = _load(); _point(L, tmp_path)
    res = L.record_run("tcg", {"rows": 10, "short_titles": 4, "avg_title_len": 68.0},
                       ["sku1|SEO弱", "sku2|形式逸脱"], stamp="2026-06-08 10:00:00")
    assert res["previous"] is None
    assert res["trend"] == {}
    assert set(res["new"]) == {"sku1|SEO弱", "sku2|形式逸脱"}
    assert res["recurring"] == [] and res["resolved"] == []


def test_second_run_trend_and_recurrence(tmp_path):
    L = _load(); _point(L, tmp_path)
    L.record_run("tcg", {"rows": 10, "short_titles": 4, "avg_title_len": 68.0},
                 ["sku1|SEO弱", "sku2|形式逸脱"], stamp="2026-06-08 10:00:00")
    res = L.record_run("tcg", {"rows": 10, "short_titles": 1, "avg_title_len": 74.0},
                       ["sku1|SEO弱", "sku3|日本語"], stamp="2026-06-08 11:00:00")
    assert res["previous"] is not None
    assert res["trend"]["short_titles"] == -3      # 4→1 改善方向
    assert res["trend"]["avg_title_len"] == 6.0     # 68→74
    assert res["recurring"] == ["sku1|SEO弱"]       # 残存(まだ直ってない)
    assert res["resolved"] == ["sku2|形式逸脱"]      # 解消
    assert res["new"] == ["sku3|日本語"]             # 新規


def test_category_isolation(tmp_path):
    L = _load(); _point(L, tmp_path)
    L.record_run("tcg", {"rows": 5}, ["a|SEO弱"], stamp="t1")
    res = L.record_run("gshock", {"rows": 3}, ["b|形式逸脱"], stamp="t2")
    assert res["previous"] is None   # gshock 初回 (tcg と混ざらない)


def test_dry_run_does_not_persist(tmp_path):
    L = _load(); _point(L, tmp_path)
    L.record_run("tcg", {"rows": 5}, ["a|SEO弱"], stamp="t1", write=False)
    assert not os.path.exists(L.LEDGER_PATH)       # 追記されない
    assert L.last_run("tcg") is None


def test_trend_arrow_direction(tmp_path):
    L = _load()
    assert "改善" in L.trend_arrow("short_titles", -2)      # 減=良
    assert "悪化" in L.trend_arrow("short_titles", 2)       # 増=悪
    assert "改善" in L.trend_arrow("avg_title_len", 3)      # 増=良
    assert "悪化" in L.trend_arrow("avg_title_len", -3)     # 減=悪
    assert L.trend_arrow("short_titles", 0) == "→"
