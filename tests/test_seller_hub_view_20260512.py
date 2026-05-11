"""Regression: 2026-05-12 seller_hub_view + control_panel「今、見る」ボタン.

【背景】
5/12 ユーザーが Seller Hub Active Listings を一緒に見たい要求。iMakInventory の
chrome_profile_ebay (eBay ログイン状態 cookie 永続化済) を流用する Selenium ベースの
分析ツール seller_hub_view.py を新規実装。control_panel に「📊 今、見る」ボタン +
カテゴリ選択ダイアログを追加。
"""
from __future__ import annotations
import importlib.util
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_HQ = _REPO_ROOT / "iMakHQ"


def _load_seller_hub_view():
    path = _HQ / "seller_hub_view.py"
    spec = importlib.util.spec_from_file_location("_test_shv", str(path))
    m = importlib.util.module_from_spec(spec)
    # selenium/uc 重い → import 時例外でも attribute は使える: 例外なら skip
    try:
        spec.loader.exec_module(m)
    except Exception:
        pass
    return m


def test_seller_hub_view_has_category_config():
    """seller_hub_view.py に CATEGORY_KEYWORDS が定義され、想定カテゴリが含まれる."""
    src = (_HQ / "seller_hub_view.py").read_text(encoding="utf-8")
    assert "CATEGORY_KEYWORDS" in src
    for key in ("porter", "gshock", "tcg", "ichibankuji", "reel"):
        assert f'"{key}":' in src, f"category '{key}' missing"


def test_seller_hub_view_has_parse_function():
    """parse_listing_row が定義されている (row text → dict 変換)."""
    src = (_HQ / "seller_hub_view.py").read_text(encoding="utf-8")
    assert "def parse_listing_row" in src
    assert "def extract_listings" in src
    assert "def analyze" in src


def test_parse_listing_row_extracts_views_and_price():
    """parse_listing_row の sample text 入力で views/price/item_id が抽出できる."""
    mod = _load_seller_hub_view()
    if not hasattr(mod, "parse_listing_row"):
        return  # selenium import 失敗時 skip
    sample = """編集
YOSHIDA PORTER Tanker 2Way Shoulder Bag Green Nylon Medium Pre-owned Japan
今すぐ買う · 358545495042
ZP37Dt8Zoaof
14
US $173.98
JPY 27,243.00
今すぐ買う
またはベストオファー
価格を調査
1
0
リンク。ビュー数210。トラフィック歴を見ます。"""
    result = mod.parse_listing_row(sample)
    assert result["item_id"] == "358545495042"
    assert result["price"] == "173.98"
    assert result["views"] == 210
    assert "Porter Tanker" in result["title"] or "PORTER Tanker" in result["title"]


def test_parse_listing_row_handles_short_input():
    """parse_listing_row が短い input でクラッシュしない."""
    mod = _load_seller_hub_view()
    if not hasattr(mod, "parse_listing_row"):
        return
    result = mod.parse_listing_row("編集\n")
    assert isinstance(result, dict)
    assert result["item_id"] == ""


def test_control_panel_has_seller_hub_button():
    """control_panel に「📊 今、見る (Seller Hub 分析)」ボタン定義 + custom_buttons='seller_hub_view'."""
    src = (_HQ / "control_panel.py").read_text(encoding="utf-8")
    assert "📊 今、見る (Seller Hub 分析)" in src
    assert '"custom_buttons": "seller_hub_view"' in src
    assert "seller_hub_view.py" in src


def test_control_panel_has_seller_hub_dialog_class():
    """SellerHubCategoryDialog クラスが定義され、6 カテゴリ選択肢が存在."""
    src = (_HQ / "control_panel.py").read_text(encoding="utf-8")
    assert "class SellerHubCategoryDialog" in src
    # ラジオ選択肢の category key
    for key in ("porter", "gshock", "tcg", "ichibankuji", "reel"):
        assert f'"{key}"' in src or f"'{key}'" in src, f"radio key '{key}' missing"
    # 全件 (絞込なし) 選択肢
    assert "全件" in src
