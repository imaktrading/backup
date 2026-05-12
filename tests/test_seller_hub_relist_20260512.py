"""Regression: 2026-05-12 seller_hub_relist.py (View=0 死蔵 listing 取下げ再出品ツール).

【背景】
5/12 ユーザー判断「在庫あり + View=0 listing は取下げ + 再出品 (案 B)、Revise くん
出番なし、HQ で直接実装」。
スプシ B 列空欄化 + mapping CSV + status CSV + End CSV を生成する統合ツール。
"""
from __future__ import annotations
import csv
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_HQ = _REPO_ROOT / "iMakHQ"


def _load_module():
    path = _HQ / "seller_hub_relist.py"
    spec = importlib.util.spec_from_file_location("_test_relist", str(path))
    m = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(m)
    except Exception:
        pass
    return m


def test_module_exists_with_required_functions():
    """seller_hub_relist.py に必要な関数が定義されている."""
    src = (_HQ / "seller_hub_relist.py").read_text(encoding="utf-8")
    assert "def find_and_update_row" in src
    assert "def save_mapping_csv" in src
    assert "def save_status_csv" in src
    assert "def generate_end_csv" in src
    assert "def main" in src


def test_end_csv_format():
    """End CSV は FileExchange Action=EndItem 形式."""
    src = (_HQ / "seller_hub_relist.py").read_text(encoding="utf-8")
    # eBay 標準 Action 列
    assert "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)" in src
    assert "EndItem" in src
    assert "OtherListingError" in src


def test_dry_run_default():
    """dry-run mode が default ON."""
    src = (_HQ / "seller_hub_relist.py").read_text(encoding="utf-8")
    assert '"--execute"' in src  # --execute フラグで本実行
    assert "dry_run = not args.execute" in src


def test_two_sheets_supported():
    """2 スプシ (Porter/TCG/UNIQLO UT 系 + G-Shock/Tomica/Reel 系) を両方検索."""
    src = (_HQ / "seller_hub_relist.py").read_text(encoding="utf-8")
    assert "19kj8NqWHIGP" in src  # スプシ 1
    assert "1jF9vggbfUC" in src   # スプシ 2


def test_no_ai_column_removed():
    """AI 列退避ロジックは廃止 (5/12: グリッド外で実装失敗、mapping CSV で代替)."""
    src = (_HQ / "seller_hub_relist.py").read_text(encoding="utf-8")
    # COL_AI が定義されていない (or コメントアウトされてる)
    assert "COL_AI      = 35" not in src
    # mapping CSV が代替
    assert "save_mapping_csv" in src
    assert "relist_mapping_" in src


def test_status_csv_includes_listing_info():
    """status CSV に旧 listing 詳細列が含まれる (成果確認用)."""
    src = (_HQ / "seller_hub_relist.py").read_text(encoding="utf-8")
    for f in ["old_item_id", "title", "price_jpy", "url", "next_action"]:
        assert f'"{f}"' in src


def test_category_flag_support():
    """--category フラグで auto_extract_targets が動く."""
    src = (_HQ / "seller_hub_relist.py").read_text(encoding="utf-8")
    assert '"--category"' in src
    assert "def auto_extract_targets" in src
    # CLI category → categorize_by_keyword マッピング
    for key in ["tshirt", "porter", "gshock", "tcg", "reel", "ichibankuji", "tomica"]:
        assert f'"{key}"' in src


def test_control_panel_category_structure():
    """control_panel.py の SCRIPTS が category + type 階層化されている."""
    src = (_HQ / "control_panel.py").read_text(encoding="utf-8")
    # category / type フィールド存在
    assert '"category":' in src
    assert '"type":' in src
    assert '"new"' in src
    assert '"relist"' in src
    assert '"utility"' in src
    # 主要カテゴリ
    for cat in ["Tシャツ", "Montbell", "Porter", "G-SHOCK", "PSA TCG", "リール", "一番くじ", "Tomica"]:
        assert f'"{cat}"' in src


def test_control_panel_labelframe_layout():
    """control_panel.py の描画ロジックが Labelframe + 新規/再出品 2 ボタン構成."""
    src = (_HQ / "control_panel.py").read_text(encoding="utf-8")
    assert "ttk.LabelFrame" in src
    assert 'text="新規"' in src
    assert 'text="再出品"' in src
    # verified カテゴリの先頭並べ替え
    assert "_cat_verified" in src or "verified" in src
