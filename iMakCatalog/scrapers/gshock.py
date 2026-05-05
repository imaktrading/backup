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
import re
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
        db_path = Path(r"C:/dev/iMak_data/catalog/products.sqlite")
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
        db_path = Path(r"C:/dev/iMak_data/catalog/products.sqlite")
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
# g-central 経由パイプライン (2026-05-05 追加)
# ============================================================================
# 設計背景:
#   CASIO 公式 (casio.com) は Akamai で Chrome tab crash を起こす状態 (5/5 確認).
#   既存 update_all_series は CASIO 公式に最初に当たるため使い物にならない.
#   → g-central のシリーズ一覧 page (/g-shock-{slug}/) で新作含む全 model 発見、
#      個別 spec も g-central + casiofanmag で取得する requests-only パイプ.
#   driver / Selenium 不要、Akamai 関係なし.

GCENTRAL_SERIES_URL_TEMPLATE = "https://www.g-central.com/g-shock-{slug}/"

# CASIO_SERIES_PAGES の series_name → g-central slug
# (g-central で記事 page が存在する series のみ. 他は random URL pattern かも)
GCENTRAL_SERIES_SLUG = {
    "DW-6900":  "dw-6900",
    "DW-5600":  "dw-5600",
    "DW-5900":  "dw-5900",
    "DW-6600":  "dw-6600",
    "DW-5700":  "dw-5700",
    "DW-9052":  "dw-9052",
    "DW-5000":  "dw-5000",
    "GA-2100":  "ga-2100",
    "GA-110":   "ga-110",
    "GA-100":   "ga-100",
    "GA-700":   "ga-700",
    "GA-900":   "ga-900",
    "GA-B2100": "ga-b2100",
    "GMW-B5000": "gmw-b5000",
    "GW-B5600": "gw-b5600",
    "GST-B100":  "gst-b100",
    "GST-B200":  "gst-b200",
    "MTG-B2000": "mtg-b2000",
    "MTG-B3000": "mtg-b3000",
    "GBA-900":   "gba-900",
    "GBD-200":   "gbd-200",
}


def discover_models_via_gcentral(series_name: str) -> list:
    """g-central のシリーズ記事 page から全 model_number を抽出.

    URL 例: https://www.g-central.com/g-shock-ga-2100/
    実測値: 179 model 取得可能 (2026-05-05).

    Args:
        series_name: 'GA-2100' / 'DW-6900' 等の series name.

    Returns:
        sorted unique list of model strings (例: 'GA-2100-1A1JF').
    """
    import requests  # type: ignore

    slug = GCENTRAL_SERIES_SLUG.get(series_name)
    if not slug:
        # slug 未登録なら series_name を lowercase で試す
        slug = series_name.lower()
    url = GCENTRAL_SERIES_URL_TEMPLATE.format(slug=slug)
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if r.status_code != 200:
            return []
    except Exception:
        return []
    # series_name prefix の model 番号を抽出
    # 例: GA-2100 → "GA-2100" + 続き ([A-Z0-9-]+)
    pattern = re.compile(rf"({re.escape(series_name)}[A-Z0-9-]+)", re.IGNORECASE)
    # G-SHOCK 正規 model 番号: ハイフン 2 個まで、末尾は (数字+英字) + (オプション JF/JR)
    # 例 OK:  GA-2100-1A1JF / GA-2100SU-9A / GA-2100TH-1A
    # 例 NG:  GA-2100TH-1A-308X370 (画像 size) / GA-2100-SPORTY (記事タグ)
    valid_re = re.compile(
        r"^[A-Z]{2,4}-\d{3,4}[A-Z]{0,4}-\d[A-Z][\dA-Z]{0,3}(?:JF|JR)?$"
    )
    found = set()
    for m in pattern.finditer(r.text):
        v = m.group(1).upper()
        if not valid_re.match(v):
            continue
        found.add(v)
    return sorted(found)


def _sanitize_year(raw: str) -> str:
    """year string を sanity check. 2010-2030 以外は空に.

    g-central の Series Launch Year regex が series 番号 (GA-2100 の '2100'
    等) を誤拾いするケースがある. 現実的な発売年代 2010-2030 に制限.
    """
    if not raw:
        return ""
    m = re.search(r"\d{4}", str(raw))
    if not m:
        return ""
    n = int(m.group(0))
    return str(n) if 2010 <= n <= 2030 else ""


def _build_specs_via_gcentral(data: dict, series_name: str,
                               casiofanmag_data: Optional[dict] = None) -> dict:
    """scrape_gcentral / scrape_casiofanmag の戻り値を catalog specs に整形.

    g-central が提供する範囲 (year / weight / case_size / case_thickness /
    band_material / dial_color) のみ. 公式情報 (price_jpy_msrp / is_new /
    is_limited / 公式画像) は構造的に空のまま.

    sanity filter:
      - year は 2010-2030 範囲外なら空に (series 番号誤拾い対策)
      - weight は シリーズ代表値で全件同一になるが、null よりは ましなので採用
    """
    cfm = casiofanmag_data or {}
    raw_year = data.get("year", "") or cfm.get("year", "")
    return {
        # === g-central / casiofanmag 由来 ===
        "case_size":         data.get("case_size", ""),
        "case_thickness":    data.get("case_thickness", ""),
        "case_material":     "Resin",  # g-central 多くは bezel material 別表記、Resin default
        "case_shape":        "",
        "band_material":     data.get("band_material", "Resin"),
        "band_width":        "",
        "band_length":       "",
        "band_color":        "",
        "band_strap":        "Two-Piece Strap",
        "dial_color":        data.get("dial_color", ""),
        "bezel_color":       "",
        "bezel_material":    "Resin",
        "crystal":           "",
        "movement":          "Quartz",
        "water_resistance":  "",
        "weight":            data.get("weight", "") or cfm.get("weight", ""),
        "year":              _sanitize_year(raw_year),
        "display":           "",
        "features":          "",
        "is_metal":          False,
        "series":            series_name,
        # === メタデータ (g-central では取れない) ===
        "is_new":            False,
        "is_limited":        False,
        "is_collab":         False,
        "is_anniversary":    False,
        "price_jpy_msrp":    "",
        # === Phase 2 拡張枠 (現状 null) ===
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


def update_via_gcentral_only(only_new: bool = True,
                              series_filter: Optional[list] = None) -> dict:
    """g-central + casiofanmag のみで catalog 更新 (CASIO 公式完全 skip).

    Args:
        only_new: True なら catalog 既存品は skip (新作発見モード).
                  False なら全 model を再 fetch (rebuild モード).
        series_filter: 特定 series のみ対象 (例: ['GA-2100', 'DW-6900']).
                       None なら GCENTRAL_SERIES_SLUG 全部.

    Returns:
        {"discovered": dict, "upserted": int, "skipped": int}
    """
    import api  # type: ignore
    import requests  # type: ignore
    sys.path.insert(0, str(_GSHOCK_DIR))
    from gshock_to_csv import scrape_gcentral, scrape_casiofanmag  # type: ignore

    target_series = series_filter or list(GCENTRAL_SERIES_SLUG.keys())
    discovered_per_series: dict = {}
    upserted = 0
    skipped = 0

    for s in target_series:
        models = discover_models_via_gcentral(s)
        discovered_per_series[s] = models
        print(f"\n=== {s}: discovered {len(models)} models ===")
        for model in models:
            existing = api.lookup(CATEGORY, model)
            if existing and only_new:
                skipped += 1
                continue
            print(f"  {model}...", end="", flush=True)
            gc_data = scrape_gcentral(model)
            cfm_data = scrape_casiofanmag(model) if not gc_data.get("year") else {}
            specs = _build_specs_via_gcentral(gc_data, s, cfm_data)
            try:
                api.upsert(
                    category=CATEGORY,
                    product_id=model,
                    name=f"Casio G-SHOCK {model}",
                    specs=specs,
                    images=[],
                    source="g-central+casiofanmag",
                    source_url=f"https://www.g-central.com/specs/{model.lower()}/",
                )
                upserted += 1
                wt = specs.get("weight", "?")
                yr = specs.get("year", "?")
                print(f" [w={wt} y={yr}]")
            except Exception as e:
                print(f" ⚠️ upsert failed: {type(e).__name__}: {e}")

    print(f"\n=== 完了: upserted={upserted} skipped={skipped} ===")
    return {
        "discovered": discovered_per_series,
        "upserted": upserted,
        "skipped": skipped,
    }


# ============================================================================
# gshock.casio.com 限定/新製品 page から flag 取得 (2026-05-05 追加)
# ============================================================================
# 設計背景:
#   www.casio.com/jp/watches/gshock/ は Akamai で tab crash (個別 product page)
#   gshock.casio.com は Selenium で Akamai 突破可能、HTML 内に
#   data-sku / data-producttype / NEW tag / 公式画像 URL が埋まっている.
#   - /jp/products/limited/   → 限定品 sku list (is_limited=True 判定)
#   - /jp/products/recommend/ → 新製品 sku list (is_new=True 判定)
#   - /jp/products/all-linup/ → 全 active sku + 公式画像

CASIO_GSHOCK_LIMITED_URL = "https://gshock.casio.com/jp/products/limited/"
CASIO_GSHOCK_NEW_URL = "https://gshock.casio.com/jp/products/recommend/"


def _fetch_casio_skus_with_images(url: str, scroll_iter: int = 15) -> dict:
    """gshock.casio.com の category page から sku + 画像 URL を抽出.

    Returns:
        {sku: {"image_url": "..."} or {}}
    """
    import undetected_chromedriver as uc  # type: ignore
    opts = uc.ChromeOptions()
    opts.add_argument("--lang=ja-JP")
    opts.add_argument("--window-size=1400,900")
    driver = uc.Chrome(options=opts, version_main=147)
    try:
        driver.get(url)
        import time as _t
        _t.sleep(8)
        for _ in range(scroll_iter):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            _t.sleep(1.5)
        html = driver.page_source

        # 各 panel の HTML を分割して sku + 画像を関連付け
        # 注意: 各 panel に data-sku が 2 回出現する (親 cmp-product_panel +
        # 子 cmp-product_panel__icon-fav). 1 番目 (親 panel 開始) だけ採用.
        results: dict = {}
        all_positions = [(m.start(), m.group(1)) for m in re.finditer(r'data-sku="([^"]+)"', html)]
        # sku 別 1 番目のみ
        seen: set = set()
        positions: list = []
        for pos, sku in all_positions:
            if sku not in seen:
                seen.add(sku)
                positions.append((pos, sku))
        for i, (pos, sku) in enumerate(positions):
            end = positions[i + 1][0] if i + 1 < len(positions) else len(html)
            chunk = html[pos:end]
            # img src は '/content/dam/casio/.../image.png.transform/product-panel/image.png'
            # のように .png が連結する形式. greedy で末尾 '"' までマッチさせる.
            img_match = re.search(
                r'<img[^>]+src="(/content/dam/casio/[^"]+)"',
                chunk,
            )
            image_url = ""
            if img_match:
                image_url = img_match.group(1)
                if image_url.startswith("/"):
                    image_url = "https://gshock.casio.com" + image_url
            results[sku] = {"image_url": image_url}
        return results
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def update_casio_official_flags() -> dict:
    """gshock.casio.com の限定/新製品 page から flag + 公式画像を catalog に反映.

    既存 catalog record を update (is_limited/is_new/公式画像 URL).
    存在しない sku は新規 record 作成.

    Returns:
        {"limited_skus": int, "new_skus": int,
         "updated": int, "newly_inserted": int}
    """
    import api  # type: ignore
    import json as _json

    print(f"=== fetch limited page ===")
    limited = _fetch_casio_skus_with_images(CASIO_GSHOCK_LIMITED_URL)
    print(f"  → {len(limited)} skus")
    print(f"=== fetch new (recommend) page ===")
    new_p = _fetch_casio_skus_with_images(CASIO_GSHOCK_NEW_URL)
    print(f"  → {len(new_p)} skus")

    all_skus = set(limited.keys()) | set(new_p.keys())
    print(f"\n=== unique skus to process: {len(all_skus)} ===")

    updated = 0
    newly_inserted = 0
    for sku in sorted(all_skus):
        is_limited = sku in limited
        is_new = sku in new_p
        # 公式画像 URL は両 page から取れた方を採用 (recommend 優先)
        image_url = (new_p.get(sku, {}).get("image_url") or
                     limited.get(sku, {}).get("image_url") or "")
        existing = api.lookup(CATEGORY, sku)
        if existing:
            # 既存 specs を update (is_limited / is_new / 公式画像)
            specs = existing.get("specs") or {}
            specs["is_limited"] = bool(is_limited)
            specs["is_new"] = bool(is_new)
            existing_imgs = existing.get("images") or []
            if image_url and image_url not in existing_imgs:
                existing_imgs = [image_url] + existing_imgs
            api.upsert(
                category=CATEGORY,
                product_id=sku,
                name=existing.get("name") or f"Casio G-SHOCK {sku}",
                specs=specs,
                images=existing_imgs,
                source=existing.get("source") or "casio_official_categorized",
                source_url=existing.get("source_url"),
            )
            updated += 1
        else:
            # 新規 record (フラグだけ持つ最低限)
            specs = _build_specs_via_gcentral({}, "")
            specs["is_limited"] = bool(is_limited)
            specs["is_new"] = bool(is_new)
            api.upsert(
                category=CATEGORY,
                product_id=sku,
                name=f"Casio G-SHOCK {sku}",
                specs=specs,
                images=[image_url] if image_url else [],
                source="casio_official_categorized",
                source_url=CASIO_GSHOCK_LIMITED_URL if is_limited else CASIO_GSHOCK_NEW_URL,
            )
            newly_inserted += 1

    print(f"\n=== 完了 ===")
    print(f"  限定 sku: {len(limited)}")
    print(f"  新製品 sku: {len(new_p)}")
    print(f"  既存 catalog 更新: {updated}")
    print(f"  新規 catalog 追加: {newly_inserted}")
    return {
        "limited_skus": len(limited),
        "new_skus": len(new_p),
        "updated": updated,
        "newly_inserted": newly_inserted,
    }


# ============================================================================
# CLI
# ============================================================================
def _cli():
    args = sys.argv[1:]
    if not args:
        print("Usage:")
        print("  python iMakCatalog/scrapers/gshock.py --update                 # CASIO 公式経由 (現在 Akamai でブロック)")
        print("  python iMakCatalog/scrapers/gshock.py --series GA-2100         # 旧経路 (公式)")
        print("  python iMakCatalog/scrapers/gshock.py --model GA-2100-1A1JF    # 旧経路 (公式)")
        print("  python iMakCatalog/scrapers/gshock.py --gcentral-discover GA-2100  # g-central で 1 series 一覧確認")
        print("  python iMakCatalog/scrapers/gshock.py --gcentral-update            # g-central のみで catalog 新作追加 (推奨)")
        print("  python iMakCatalog/scrapers/gshock.py --gcentral-update GA-2100    # g-central で 1 series のみ更新")
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
    elif args[0] == "--gcentral-discover" and len(args) >= 2:
        ids = discover_models_via_gcentral(args[1])
        print(f"\n=== {args[1]}: {len(ids)} models discovered ===")
        for m in ids:
            print(f"  {m}")
    elif args[0] == "--gcentral-update":
        if len(args) >= 2:
            update_via_gcentral_only(only_new=True, series_filter=[args[1]])
        else:
            update_via_gcentral_only(only_new=True)
    elif args[0] == "--casio-flags":
        update_casio_official_flags()
    else:
        print(f"⚠️ 不明な引数: {args}")
        sys.exit(1)


if __name__ == "__main__":
    _cli()
