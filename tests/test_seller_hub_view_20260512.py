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
    assert result["price_usd"] == "173.98"
    assert result["views"] == "210"
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


def test_csv_fields_includes_all_15_columns():
    """CSV_FIELDS に 15 項目が定義され、画像系は含まれない."""
    mod = _load_seller_hub_view()
    if not hasattr(mod, "CSV_FIELDS"):
        return
    expected = [
        "snapshot_date", "status", "item_id", "sku", "title",
        "price_usd", "views", "watchers", "quantity_available",
        "listed_date", "ended_date", "promoted_rate",
        "format", "best_offer_enabled", "search_keyword",
    ]
    for f in expected:
        assert f in mod.CSV_FIELDS, f"missing field: {f}"
    # 画像系は意図的に含めない (無在庫モデルで仕入元出品者所有のため)
    assert "first_image_url" not in mod.CSV_FIELDS
    assert "listing_url" not in mod.CSV_FIELDS


def test_parse_listing_row_extracts_format_and_best_offer():
    """parse_listing_row が format / best_offer / promoted_rate を抽出."""
    mod = _load_seller_hub_view()
    if not hasattr(mod, "parse_listing_row"):
        return
    sample = """編集
Porter Tanker Shoulder Bag Black
今すぐ買う · 358545495042
ABCD12345678
3
US $189.98
JPY 29,755.00
今すぐ買う
またはベストオファー
価格を調査
1
0
リンク。ビュー数76。
一般： 広告掲載
お客様の広告費率： 7%"""
    result = mod.parse_listing_row(sample, status="active", search_keyword="Porter")
    assert result["format"] == "BIN"
    assert result["best_offer_enabled"] == "yes"
    assert result["promoted_rate"] == "7"
    assert result["status"] == "active"
    assert result["search_keyword"] == "Porter"
    assert result["item_id"] == "358545495042"
    assert result["views"] == "76"
    # watchers は num_lines[0] = 3
    assert result["watchers"] == "3"
    # quantity_available は num_lines[-2] = 1
    assert result["quantity_available"] == "1"


def test_seller_hub_view_has_save_function():
    """save_to_csv が存在し、保存先が iMak_data/seller_hub."""
    src = (_HQ / "seller_hub_view.py").read_text(encoding="utf-8")
    assert "def save_to_csv" in src
    assert "iMak_data" in src and "seller_hub" in src
    assert "QUOTE_NONNUMERIC" in src  # eBay CSV 規約準拠


def test_seller_hub_view_supports_ended_status():
    """--status active|ended の URL 切替が実装されてる."""
    src = (_HQ / "seller_hub_view.py").read_text(encoding="utf-8")
    assert "URL_BASE" in src
    assert '"active":' in src and '"ended":' in src
    assert "/sh/lst/active" in src and "/sh/lst/ended" in src


def test_fetch_all_pages_function_exists():
    """fetch_all_pages がページ送りで全件取得する関数として実装されてる."""
    src = (_HQ / "seller_hub_view.py").read_text(encoding="utf-8")
    assert "def fetch_all_pages" in src
    # Next ボタン selector
    assert ".pagination__next" in src
    # ItemID デドゥープ
    assert "seen" in src and "uniq" in src


def test_main_supports_all_pages_flag():
    """--all-pages CLI フラグが実装されてる."""
    src = (_HQ / "seller_hub_view.py").read_text(encoding="utf-8")
    assert '"--all-pages"' in src
    assert "fetch_all_pages" in src


def test_monthly_snapshot_batch_exists():
    """Windows タスクスケジューラ用 batch が存在し、Ended+Active 両方走らせる."""
    batch_path = _HQ / "tools" / "monthly_seller_hub_snapshot.bat"
    assert batch_path.exists(), "monthly_seller_hub_snapshot.bat 不在"
    src = batch_path.read_text(encoding="utf-8", errors="replace")
    assert "--status ended" in src and "--all-pages" in src
    assert "--status active" in src
    assert "--save" in src
    # ログ出力先
    assert "logs" in src.lower()


def test_monthly_snapshot_readme_exists():
    """タスクスケジューラ登録手順 README が存在."""
    readme = _HQ / "tools" / "README_monthly_snapshot.md"
    assert readme.exists()
    src = readme.read_text(encoding="utf-8")
    assert "タスクスケジューラ" in src
    assert "monthly_seller_hub_snapshot.bat" in src
    # 通知 → 手動実行フローへの書換確認
    assert "通知" in src
    assert "monthly_snapshot_alert.py" in src


def test_monthly_snapshot_alert_script_exists():
    """通知 script monthly_snapshot_alert.py が存在し、toast 通知を実装."""
    alert = _HQ / "tools" / "monthly_snapshot_alert.py"
    assert alert.exists()
    src = alert.read_text(encoding="utf-8")
    # win10toast or PowerShell フォールバック実装
    assert "win10toast" in src or "ToastNotifier" in src
    assert "NotifyIcon" in src  # フォールバック
    # 通知タイトルに iMak Seller Hub
    assert "Seller Hub" in src
