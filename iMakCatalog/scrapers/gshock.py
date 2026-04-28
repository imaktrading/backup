"""G-SHOCK catalog scraper - 既存 iMakG-shock 資産の薄ラッパー.

設計原則 (Phase 3 / 2026-04-29):
  - スクレイピングロジックは iMakG-shock/gshock_to_csv.py の `scrape_casio` を再利用
  - シリーズ全件取得は iMakG-shock/casio_finder/casio_finder.py の `scrape_casio_series` を再利用
  - 限定/コラボ/NEW 判定は同 `check_new_flag` を再利用
  - **新規スクレイピング実装ゼロ** (オーケストレーションのみ)
  - 月次バッチで products テーブルに upsert

依存:
  - iMakG-shock/gshock_to_csv.py (scrape_casio, MODEL_OVERRIDES, SERIES_WEIGHT 等)
  - iMakG-shock/casio_finder/casio_finder.py (scrape_casio_series, check_new_flag, CASIO_SERIES_PAGES)
  - undetected_chromedriver (Selenium、heavy)

実行:
  python iMakCatalog/scrapers/gshock.py --update                   # 全シリーズ差分更新
  python iMakCatalog/scrapers/gshock.py --series GA-2100           # 単独シリーズのみ
  python iMakCatalog/scrapers/gshock.py --model GA-2100-1A1JF      # 単独モデルのみ (テスト用)
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# ============================================================================
# sys.path 設定 (iMakG-shock 既存資産の import 経路を確立)
# ============================================================================
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_GSHOCK_DIR = _REPO_ROOT / "iMakG-shock"
_CASIO_FINDER_DIR = _GSHOCK_DIR / "casio_finder"
_EBAY_API_DIR = _REPO_ROOT / "iMakeBayAPI"  # listing_common 依存
_CATALOG_ROOT = Path(__file__).resolve().parent.parent  # iMakCatalog/

for p in (_GSHOCK_DIR, _CASIO_FINDER_DIR, _EBAY_API_DIR, _CATALOG_ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# 遅延 import に統一して、CLI 以外の import 時に Selenium ドライバ起動コストを払わない


CATEGORY = "gshock"
SOURCE = "casio_official"
PRODUCT_URL_TEMPLATE = "https://www.casio.com/jp/watches/gshock/product.{model}/"


# ============================================================================
# 公開 API
# ============================================================================
def update_all_series(driver=None) -> int:
    """全シリーズ差分更新 (月次バッチ想定).

    Args:
        driver: 既存 Selenium driver を渡せば使い回す. None なら本関数内で起動・終了.

    Returns:
        upsert 成功件数.
    """
    from casio_finder import scrape_casio_series, CASIO_SERIES_PAGES  # type: ignore

    own_driver = driver is None
    if own_driver:
        driver = _start_driver()
    try:
        total = 0
        scrape_id = _scrape_log_start()
        try:
            for series_name, series_url in CASIO_SERIES_PAGES:
                print(f"\n=== {series_name}: シリーズ取得中 ===")
                models = scrape_casio_series(driver, series_name, series_url)
                for model in models:
                    if _upsert_one_model(driver, model, series_name):
                        total += 1
            _scrape_log_finish(scrape_id, status="success", products_added=total)
            print(f"\n=== 完了: {total} models upserted ===")
        except Exception as e:
            _scrape_log_finish(scrape_id, status="failed",
                               error_message=f"{type(e).__name__}: {e}")
            raise
        return total
    finally:
        if own_driver:
            driver.quit()


def update_single_series(series_name: str, series_url: str, driver=None) -> int:
    """単一シリーズだけ更新 (CLI / デバッグ用)."""
    from casio_finder import scrape_casio_series  # type: ignore

    own_driver = driver is None
    if own_driver:
        driver = _start_driver()
    try:
        models = scrape_casio_series(driver, series_name, series_url)
        n = 0
        for model in models:
            if _upsert_one_model(driver, model, series_name):
                n += 1
        return n
    finally:
        if own_driver:
            driver.quit()


def update_single_model(model: str, series_name: str = "", driver=None) -> bool:
    """単独モデル upsert (CLI / テスト用)."""
    own_driver = driver is None
    if own_driver:
        driver = _start_driver()
    try:
        return _upsert_one_model(driver, model, series_name)
    finally:
        if own_driver:
            driver.quit()


# ============================================================================
# 内部処理 — scrape + upsert
# ============================================================================
def _upsert_one_model(driver, model: str, series_name: str = "") -> bool:
    """1 モデル分: scrape_casio + check_new_flag + api.upsert."""
    from gshock_to_csv import scrape_casio  # type: ignore
    from casio_finder import check_new_flag  # type: ignore
    import api  # type: ignore

    product_url = PRODUCT_URL_TEMPLATE.format(model=model)
    print(f"  {model}...", end="", flush=True)

    data = scrape_casio(driver, product_url)
    if not data:
        print(" [scrape failed]")
        return False

    is_new, is_limited, price_jpy = check_new_flag(driver, model)

    specs = _build_specs(data, series_name, is_new, is_limited, price_jpy)
    model_official = data.get("model_official") or model

    api.upsert(
        category=CATEGORY,
        product_id=model_official,
        name=f"Casio G-SHOCK {model_official}",
        specs=specs,
        images=[],   # CASIO 公式画像 URL は scrape_casio 戻り値に未含、Phase 2 で
        source=SOURCE,
        source_url=product_url,
    )
    print(f" [{specs.get('case_size','?')} / "
          f"{'NEW' if is_new else '-'} / "
          f"{'限定' if is_limited else '-'}]")
    return True


def _build_specs(data: dict, series_name: str,
                 is_new: bool, is_limited: bool, price_jpy: str) -> dict:
    """scrape_casio + check_new_flag の戻り値を catalog specs JSON に整形.

    Phase 1 必須フィールド + Phase 2 拡張枠 (null 予約) を含む.
    """
    return {
        # === Phase 1 必須 (scrape_casio で取得) ===
        "case_size":         data.get("case_size", ""),
        "case_thickness":    data.get("case_thickness", ""),
        "case_material":     data.get("case_material", ""),
        "case_shape":        data.get("case_shape", ""),
        "band_material":     data.get("band_material", ""),
        "band_width":        data.get("band_width", ""),
        "band_length":       data.get("band_length", ""),
        "band_color":        data.get("band_color", ""),
        "band_strap":        data.get("band_strap_override", "Two-Piece Strap"),
        "dial_color":        data.get("dial_color", ""),
        "bezel_color":       data.get("bezel_color", ""),
        "bezel_material":    "Stainless Steel" if data.get("is_metal") else "Resin",
        "crystal":           data.get("crystal", ""),
        "movement":          data.get("movement", ""),
        "water_resistance":  data.get("water_resistance", ""),
        "weight":            data.get("weight", ""),
        "year":              data.get("year", ""),
        "display":           data.get("display", ""),
        "features":          data.get("features", ""),
        "is_metal":          bool(data.get("is_metal", False)),
        "series":            series_name,

        # === メタデータ (check_new_flag 由来) ===
        "is_new":            bool(is_new),
        "is_limited":        bool(is_limited),
        "is_collab":         False,    # Phase 2 で別判定 (限定の中にコラボ含むため細分化)
        "is_anniversary":    False,    # 同上
        "price_jpy_msrp":    price_jpy or "",

        # === Phase 2 拡張枠 (現状 null、別モジュールが後段で UPDATE) ===
        "ebay_search_volume":     None,
        "ebay_median_price_usd":  None,
        "ebay_sell_through_rate": None,
        "ebay_active_listings":   None,
        "mercari_supply_count":   None,
        "mercari_median_jpy":     None,
        "profit_margin_pct":      None,
        "is_active_msrp":         None,
        "msrp_last_checked":      None,
    }


# ============================================================================
# Selenium driver
# ============================================================================
def _start_driver():
    """undetected_chromedriver を起動 (CASIO 公式は JS 描画必須)."""
    import undetected_chromedriver as uc  # type: ignore
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    return uc.Chrome(options=options, version_main=146)


# ============================================================================
# scrape_log (差分更新の判断材料)
# ============================================================================
def _scrape_log_start() -> Optional[int]:
    """scrape_log に開始 row を挿入. 失敗時は None 返却 (DB なしで動かす場合)."""
    try:
        import sqlite3
        db_path = _CATALOG_ROOT / "db" / "products.sqlite"
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO scrape_log (category, started_at, status) VALUES (?, ?, 'running')",
            (CATEGORY, datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
        log_id = cur.lastrowid
        conn.close()
        return log_id
    except Exception as e:
        print(f"⚠️ scrape_log 開始失敗 (続行): {type(e).__name__}: {e}")
        return None


def _scrape_log_finish(log_id: Optional[int], status: str,
                       products_added: int = 0,
                       error_message: Optional[str] = None) -> None:
    if log_id is None:
        return
    try:
        import sqlite3
        db_path = _CATALOG_ROOT / "db" / "products.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "UPDATE scrape_log SET finished_at = ?, status = ?, "
            "products_added = ?, error_message = ? WHERE id = ?",
            (datetime.now().isoformat(timespec="seconds"), status,
             products_added, error_message, log_id),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"⚠️ scrape_log 終了失敗 (続行): {type(e).__name__}: {e}")


# ============================================================================
# CLI
# ============================================================================
def _cli():
    args = sys.argv[1:]
    if not args:
        print("Usage:")
        print("  python iMakCatalog/scrapers/gshock.py --update")
        print("  python iMakCatalog/scrapers/gshock.py --series GA-2100")
        print("  python iMakCatalog/scrapers/gshock.py --model GA-2100-1A1JF")
        sys.exit(1)

    if args[0] == "--update":
        update_all_series()
    elif args[0] == "--series" and len(args) >= 2:
        from casio_finder import CASIO_SERIES_PAGES  # type: ignore
        target = args[1]
        for name, url in CASIO_SERIES_PAGES:
            if name == target:
                update_single_series(name, url)
                return
        print(f"⚠️ シリーズ {target!r} が見つかりません. 候補: "
              f"{[n for n, _ in CASIO_SERIES_PAGES]}")
        sys.exit(1)
    elif args[0] == "--model" and len(args) >= 2:
        update_single_model(args[1])
    else:
        print(f"⚠️ 不明な引数: {args}")
        sys.exit(1)


if __name__ == "__main__":
    _cli()
