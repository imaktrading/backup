"""Regression: 2026-05-11 casio_finder_from_catalog.py (catalog × active diff).

【背景】
旧 casio_finder.py は CASIO 公式サイトを直スクレイプ → bot 検出/429 で実用性低。
iMakCatalog (公式 DB 集約済、5/5 export で 581 件) を起点に active diff する
新スクリプト。
"""
from __future__ import annotations
import csv
import importlib.util
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_FINDER = _REPO_ROOT / "iMakG-shock" / "casio_finder"


def _load_module():
    path = _FINDER / "casio_finder_from_catalog.py"
    if str(_FINDER) not in sys.path:
        sys.path.insert(0, str(_FINDER))
    spec = importlib.util.spec_from_file_location("_test_finder_catalog", str(path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _write_csv(path, fieldnames, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def test_load_catalog_models_reads_product_id():
    mod = _load_module()
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "gshock.csv"
        _write_csv(path,
            ["product_id", "name_en", "price_jpy_msrp"],
            [
                {"product_id": "AWG-M100FP-1A1JR", "name_en": "Casio AWG", "price_jpy_msrp": "31900"},
                {"product_id": "DW-6900NB-1JF", "name_en": "Casio DW", "price_jpy_msrp": "12100"},
                {"product_id": "", "name_en": "Empty PID", "price_jpy_msrp": ""},  # skip
            ])
        rows = mod.load_catalog_models(str(path))
        assert len(rows) == 2
        assert rows[0]["product_id"] == "AWG-M100FP-1A1JR"


def test_load_active_models_extracts_with_and_without_suffix():
    """active CSV から型番抽出時、JF/JR 末尾あり版/なし版両方で active set に登録."""
    mod = _load_module()
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "active.csv"
        _write_csv(path,
            ["Title"],
            [
                {"Title": "Casio G-SHOCK DW-6900NB-1JF Black Watch"},
                {"Title": "G-SHOCK GA-2100-1A1 Carbon Core"},
            ])
        active = mod.load_active_models(str(path))
        # JF 付き / なし両方
        assert "DW-6900NB-1JF" in active
        assert "DW-6900NB-1" in active
        # 元値のみ
        assert "GA-2100-1A1" in active


def test_find_unlisted_filters_out_listed_models():
    """catalog の product_id が active に含まれていれば diff 結果から除外."""
    mod = _load_module()
    catalog = [
        {"product_id": "AWG-M100FP-1A1JR", "name_en": "A"},
        {"product_id": "DW-6900NB-1JF", "name_en": "B"},  # active で hit
        {"product_id": "GA-2100-1A1JR", "name_en": "C"},  # active で hit (JF/JR なし版)
    ]
    active = {"DW-6900NB-1JF", "DW-6900NB-1", "GA-2100-1A1"}
    unlisted = mod.find_unlisted(catalog, active)
    pids = [r["product_id"] for r in unlisted]
    assert pids == ["AWG-M100FP-1A1JR"]


def test_find_unlisted_with_empty_active_returns_all():
    """active 空 = 全部未出品."""
    mod = _load_module()
    catalog = [{"product_id": "AWG-M100FP-1A1JR"}, {"product_id": "DW-6900-1V"}]
    assert len(mod.find_unlisted(catalog, set())) == 2


def test_find_latest_catalog_picks_lexicographic_max():
    """gshock_*.csv の最新 (ファイル名 lexicographic max = 日時 YYYYMMDD_HHMMSS) を選ぶ."""
    mod = _load_module()
    with tempfile.TemporaryDirectory() as td:
        Path(td, "gshock_20260101_000000.csv").write_text("x", encoding="utf-8")
        Path(td, "gshock_20260505_174531.csv").write_text("x", encoding="utf-8")
        Path(td, "gshock_20260301_120000.csv").write_text("x", encoding="utf-8")
        latest = mod.find_latest_catalog(td)
        assert latest is not None
        assert latest.endswith("gshock_20260505_174531.csv")


def test_control_panel_has_catalog_button():
    """control_panel に「G-SHOCK 未出品モデル (catalog)」ボタン定義が含まれる."""
    src = (_REPO_ROOT / "iMakHQ" / "control_panel.py").read_text(encoding="utf-8")
    assert "casio_finder_from_catalog.py" in src
    assert "G-SHOCK 未出品モデル (catalog)" in src
