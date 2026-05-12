"""Regression: 2026-05-12 seller_hub_writeback.py (再出品 ItemID 反映ツール).

【背景】
5/12 ユーザー判断「数十件規模の再出品で手動 ItemID 貼付は不可」→ 自動化必須。
Active Listings Report (eBay DL) → SKU 照合 → スプシ B列書込 + diff CSV (OLD/NEW pair).
"""
from __future__ import annotations
import csv
import importlib.util
import json
import os
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_HQ = _REPO_ROOT / "iMakHQ"
_EBAY_API = _REPO_ROOT / "iMakeBayAPI"


def _load_writeback():
    path = _HQ / "seller_hub_writeback.py"
    spec = importlib.util.spec_from_file_location("_test_writeback", str(path))
    m = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(m)
    except Exception:
        pass
    return m


def test_writeback_module_exists():
    """seller_hub_writeback.py 存在 + 必要関数定義."""
    src = (_HQ / "seller_hub_writeback.py").read_text(encoding="utf-8")
    assert "def process_writeback" in src
    assert "def read_active_report" in src
    assert "def read_mapping_csv" in src
    assert "def read_old_state_csv" in src
    assert "def read_recent_add_csvs" in src
    assert "def generate_diff_csv" in src
    assert "def sku_from_url" in src
    assert "def main" in src


def test_sku_from_url_extracts_last_12_chars():
    """sku_from_url が listing_common.extract_sku_from_url と同規約."""
    m = _load_writeback()
    assert m.sku_from_url("https://mercari.com/jp/items/m12345678901") == "m12345678901"
    # クエリ除去
    assert m.sku_from_url("https://mercari.com/jp/items/m99999999999?ref=src") == "m99999999999"
    # trailing slash 除去
    assert m.sku_from_url("https://mercari.com/jp/items/m11111111111/") == "m11111111111"
    # 空 URL
    assert m.sku_from_url("") == ""


def test_active_report_reader_filters_empty_sku():
    """Active Listings Report 読込時に Custom Label 空欄行を skip."""
    m = _load_writeback()
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "test_active.csv")
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["Item number", "Title", "Custom label (SKU)", "Available quantity"])
            w.writerow(["111111111111", "Old listing", "", "1"])         # SKU 空 → skip
            w.writerow(["222222222222", "New listing", "m12345678901", "1"])  # SKU あり
            w.writerow(["333333333333", "Old zaiko", "zaiko", "1"])      # SKU "zaiko" → 含める
        result = m.read_active_report(path)
        assert "m12345678901" in result
        assert "zaiko" in result
        # 空欄は skip
        assert "" not in result
        assert len(result) == 2


def test_dry_run_default():
    """--execute フラグなしで dry-run."""
    src = (_HQ / "seller_hub_writeback.py").read_text(encoding="utf-8")
    assert '"--execute"' in src
    assert "execute=args.execute" in src


def test_no_open_flag():
    """--no-open で auto-open skip."""
    src = (_HQ / "seller_hub_writeback.py").read_text(encoding="utf-8")
    assert '"--no-open"' in src
    assert "args.no_open" in src


def test_diff_csv_has_old_new_marker():
    """diff CSV は OLD/NEW marker 列を持つ."""
    src = (_HQ / "seller_hub_writeback.py").read_text(encoding="utf-8")
    assert '"marker"' in src
    assert '"OLD"' in src
    assert '"NEW"' in src


def test_diff_csv_output_to_desktop():
    """diff CSV はデスクトップに出力 (relist_diff_*.csv)."""
    src = (_HQ / "seller_hub_writeback.py").read_text(encoding="utf-8")
    assert "DESKTOP_DIR" in src
    assert "relist_diff_" in src


def test_writeback_archives_active_report():
    """Active Report は active_reports/ にアーカイブコピー."""
    src = (_HQ / "seller_hub_writeback.py").read_text(encoding="utf-8")
    assert "ACTIVE_REPORTS_DIR" in src
    assert "active_reports" in src
    assert "shutil.copy2" in src


def test_writeback_guards_already_filled_b():
    """B列既に値ありの行は二重書込防止 (skip + WARN)."""
    src = (_HQ / "seller_hub_writeback.py").read_text(encoding="utf-8")
    assert "already_filled" in src
    assert "B_already_has_different_id" in src


def test_relist_old_state_function_exists():
    """seller_hub_relist.py に OLD state scrape 関数追加."""
    src = (_HQ / "seller_hub_relist.py").read_text(encoding="utf-8")
    assert "def save_old_state_csv" in src
    assert "ebay_listing_scraper" in src or "scrape_listings_batch" in src
    # --skip-scrape フラグ
    assert "--skip-scrape" in src


def test_ebay_listing_scraper_module_exists():
    """iMakeBayAPI/ebay_listing_scraper.py 存在 + 必要関数."""
    p = _EBAY_API / "ebay_listing_scraper.py"
    assert p.exists()
    src = p.read_text(encoding="utf-8")
    assert "def scrape_listing_detail" in src
    assert "def scrape_listings_batch" in src
    assert "def scrape_session" in src
    # eBay listing DOM parser
    assert "_extract_title" in src
    assert "_extract_price" in src
    assert "_extract_item_specifics" in src


def test_control_panel_has_writeback_button():
    """control_panel.py に「再出品結果反映」ボタン + custom_buttons handler."""
    src = (_HQ / "control_panel.py").read_text(encoding="utf-8")
    assert "再出品結果反映" in src
    assert "writeback_file_dialog" in src
    assert "_launch_writeback_dialog" in src
    # file dialog 起動
    assert "filedialog.askopenfilename" in src
    # dry-run / execute 確認 dialog
    assert "messagebox.askyesno" in src
