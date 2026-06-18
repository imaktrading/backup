"""Regression: 2026-06-17 — PSA再仕入れ 入力の同一eBay出品 重複除去。

funnel/CSV 由来で同じ listing が複数行になる(実機: 81行中10重複。itemID 358481165472 /
358441104504 等が×2)。同じ現物を2回探索/2回目視しないよう入口で1本化する。
"""
import importlib.util
from pathlib import Path

_P = Path(__file__).resolve().parent.parent / "iMakHQ" / "tools" / "psa_resource_gate.py"
_spec = importlib.util.spec_from_file_location("psa_resource_gate_t", _P)
import sys
sys.path.insert(0, str(_P.parent))
g = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(g)


def _id(r):
    import re
    m = re.search(r"/itm/(\d+)", r.get("ebay_url", ""))
    return m.group(1) if m else ""


def test_dedupe_removes_duplicate_itemids_preserving_order():
    rows = [
        {"ebay_url": "https://www.ebay.com/itm/358481165472", "title": "Gundam GD02-069"},
        {"ebay_url": "https://www.ebay.com/itm/358481165472", "title": "Gundam GD02-069"},
        {"ebay_url": "https://www.ebay.com/itm/358441104504", "title": "B"},
        {"ebay_url": "https://www.ebay.com/itm/999", "title": "C"},
        {"ebay_url": "https://www.ebay.com/itm/358441104504", "title": "B"},
    ]
    out = g.dedupe_rows(rows, _id)
    assert [_id(r) for r in out] == ["358481165472", "358441104504", "999"]


def test_load_restock_prefers_funnel_over_stale_desktop_csv():
    # 2026-06-18: 毎回 funnel から最新生成(実需フィルタ込み)→ 古い 03_CSV があっても無視
    # (= 手動削除不要)。funnel無の時だけ既存CSVにfallback。
    src = (Path(__file__).resolve().parent.parent / "iMakHQ" / "tools" / "psa_resource_gate.py").read_text(encoding="utf-8")
    body = src[src.index("def _load_restock_psa10"):]
    body = body[:body.index("\ndef ", 1)]
    assert "src = mp.build_input_from_funnel()" in body            # funnelから生成
    assert body.index("build_input_from_funnel()") < body.index("glob.glob")  # funnel優先 → CSVはfallback


def test_gate_excludes_restock_taisyougai():
    # catalog非対応(Weiss Schwarz等)を「RESTOCK対象外」で除外=毎回候補なし→依頼の無限ループを止める
    src = (Path(__file__).resolve().parent.parent / "iMakHQ" / "tools" / "psa_resource_gate.py").read_text(encoding="utf-8")
    body = src[src.index("def _load_restock_psa10"):]
    body = body[:body.index("\ndef ", 1)]
    assert 'read_tab("RESTOCK対象外")' in body
    assert "対象外除外" in body
    # 除外は重複除去の後(両方適用)
    assert body.index("dedupe_rows") < body.index("RESTOCK対象外")


def test_dedupe_falls_back_to_url_title_when_no_itemid():
    rows = [
        {"ebay_url": "", "title": "X"},
        {"ebay_url": "", "title": "X"},   # 同一 → 除去
        {"ebay_url": "", "title": "Y"},
    ]
    out = g.dedupe_rows(rows, lambda r: "")
    assert [r["title"] for r in out] == ["X", "Y"]
