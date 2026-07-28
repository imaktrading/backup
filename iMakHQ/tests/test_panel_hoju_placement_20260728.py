"""補URL の2ボタンが「新規出品」パネルに出ること (2026-07-28 ユーザー指示).

出品 → 入稿 → itemID書込 → 補URL確保 は一連の流れなので、既存メンテ側に離すと導線が切れる。
定常運用の 件数感(status) / 夜間検索 はメンテ側のまま。
"""
import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HQ)


def _scripts():
    """GUI を起動せず SCRIPTS 定義だけ取り出す。"""
    src = open(os.path.join(HQ, "control_panel.py"), encoding="utf-8").read()
    ns = {"__file__": os.path.join(HQ, "control_panel.py")}
    exec(compile(src[:src.index("class ")], "cp", "exec"), ns)
    return ns["SCRIPTS"]


def _ugroup(cmd):
    """control_panel._ugroup と同じ判定(そちらを変えたらここも落ちる)。"""
    c = " ".join(cmd)
    if "csv_auditor" in c:
        return "audit"
    if any(s in c for s in ("listing_funnel", "demand_winners", "funnel_diff")):
        return "analyze"
    if any(s in c for s in ("mercari_psa_resource", "restock_worklist", "cull_end")):
        return "oos"
    if any(s in c for s in ("casio_finder", "montbell_outlet_scraper", "mercari_scout.py")):
        return "discover"
    if "psa_hoju_fill.py" in c and ("--limit=15" in c or "confirm" in c):
        return "hoju"
    return "report"


def _group_of(label):
    for sc in _scripts():
        if sc.get("label") == label:
            return _ugroup(sc.get("cmd", []))
    raise AssertionError(f"ボタンが無い: {label}")


def test_post_listing_buttons_are_in_new_panel():
    assert _group_of("🆕 出品直後の補URL候補検索(当日分)") == "hoju"
    assert _group_of("🩹 補URL補強(昼確認/slice3)") == "hoju"


def test_routine_buttons_stay_in_maintenance():
    assert _group_of("📊 補URL件数感(status)") == "report"
    assert _group_of("🔎 補URL夜間検索(slice2)") == "report"


def test_new_panel_renders_the_hoju_group():
    """グループを作っても描画側に配線しなければボタンは消える。"""
    src = open(os.path.join(HQ, "control_panel.py"), encoding="utf-8").read()
    assert 'ug["hoju"]' in src
    assert '"hoju": []' in src
    assert "出品後 補URL確保" in src
