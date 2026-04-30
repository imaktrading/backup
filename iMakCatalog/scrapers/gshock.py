"""G-SHOCK catalog scraper - 既存 iMakG-shock 資産の薄ラッパー.

設計原則 (Phase 3 / 2026-04-29):
  - スクレイピングロジックは iMakG-shock/gshock_to_csv.py の `scrape_casio` を再利用
  - シリーズ全件取得は iMakG-shock/casio_finder/casio_finder.py の `scrape_casio_series` を再利用
  - 限定/コラボ/NEW 判定は同 `check_new_flag` を再利用
  - **新規スクレイピング実装ゼロ** (オーケストレーションのみ)
  - 月次バッチで products テーブルに upsert

Anti-bot resilience (Phase 3-D / 2026-04-29 追加):
  CASIO 公式は Akamai EdgeSuite WAF で保護されており、
  約 30-70 リクエストで 403 ブロックを発動する.
  対応:
    A. Series 先取り (Pass 1) — 全 6 series モデル一覧を tight burst で取得し、
       戦略価値を最優先で確保 (block 発火しても model list は確保済)
    B. Block 検出 + retry — body に "permission to access" / "edgesuite" 等を検出したら
       cooldown 75 秒 + driver 再起動で session 切替を試みる
    C. Pacing — series 間 / model 間に短い sleep を挿入し block 発火頻度を低減

依存:
  - iMakG-shock/gshock_to_csv.py (scrape_casio, MODEL_OVERRIDES, SERIES_WEIGHT 等)
  - iMakG-shock/casio_finder/casio_finder.py (scrape_casio_series, check_new_flag, CASIO_SERIES_PAGES)
  - undetected_chromedriver (Selenium、heavy)

実行:
  python iMakCatalog/scrapers/gshock.py --update                          # 全シリーズ
  python iMakCatalog/scrapers/gshock.py --update-subset DW-6900,DW-5600   # 指定シリーズのみ
  python iMakCatalog/scrapers/gshock.py --series GA-2100                  # 単独シリーズ (legacy)
  python iMakCatalog/scrapers/gshock.py --model GA-2100-1A1JF             # 単独モデル (テスト用)
"""
from __future__ import annotations

import os
import sys
import time
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

# Anti-bot block 検出シグナル (Akamai EdgeSuite / Cloudflare 等).
# body 文字列内にこれらが含まれていたら block 判定.
_BLOCK_SIGNALS = (
    "permission to access",       # Akamai 403 メッセージ
    "errors.edgesuite.net",       # Akamai 403 ページ URL
    "Reference #",                # Akamai リファレンス ID 行
    "Access Denied",              # 汎用
    "Cloudflare",                 # Cloudflare チャレンジ
)

# Cooldown / pacing 秒数 (block 検出時の待機時間).
_COOLDOWN_AFTER_BLOCK = 75
_PACING_BETWEEN_SERIES = 3
_PACING_BETWEEN_MODELS = 2


# ============================================================================
# 公開 API
# ============================================================================
def update_all_series(driver=None, series_filter: Optional[set] = None) -> int:
    """全シリーズ差分更新 (月次バッチ想定). 2-pass + anti-bot resilience.

    Pass 1: 全 series のモデル一覧を tight burst で取得 (戦略価値の確保最優先)
    Pass 2: 各 model の詳細スクレイプ + upsert

    各段階で block 検出 → cooldown + driver 再起動で recovery.

    Args:
        driver: 既存 Selenium driver を渡せば使い回す. None なら本関数内で起動・終了.
        series_filter: 指定シリーズのみ対象 (例: {"DW-6900", "DW-5600"}).
                       None なら CASIO_SERIES_PAGES 全件.

    Returns:
        upsert 成功件数.
    """
    from casio_finder import CASIO_SERIES_PAGES  # type: ignore

    own_driver = driver is None
    if own_driver:
        driver = _start_driver()

    if series_filter:
        pages = [(n, u) for n, u in CASIO_SERIES_PAGES if n in series_filter]
    else:
        pages = list(CASIO_SERIES_PAGES)

    try:
        scrape_id = _scrape_log_start()
        try:
            # === Pass 1: 全 series モデル一覧取得 (tight burst) ===
            print(f"\n=== Pass 1/2: series モデル一覧取得 ({len(pages)} series) ===")
            series_models: dict[str, list[str]] = {}
            halted = False
            for series_name, series_url in pages:
                if driver is None:
                    print(f"\n[{series_name}] ⛔ driver halt 検出、Pass 1 中断")
                    halted = True
                    break
                print(f"\n[{series_name}] series page get...")
                models, driver = _safe_fetch_series_models(driver, series_name, series_url)
                series_models[series_name] = models
                print(f"  → {len(models)} 件取得")
                time.sleep(_PACING_BETWEEN_SERIES)

            # === Pass 2: 各 model の詳細スクレイプ + upsert ===
            total = 0
            n_total = sum(len(m) for m in series_models.values())
            print(f"\n=== Pass 2/2: model 詳細スクレイプ ({n_total} models) ===")
            for series_name, models in series_models.items():
                if not models:
                    continue
                if driver is None:
                    print(f"\n[{series_name}] ⛔ driver halt 検出、残 series skip")
                    halted = True
                    break
                print(f"\n[{series_name}] {len(models)} models")
                for model in models:
                    if driver is None:
                        # _safe_upsert_model が None を返したら以降の model も skip
                        halted = True
                        break
                    success, driver = _safe_upsert_model(driver, model, series_name)
                    if success:
                        total += 1
                    time.sleep(_PACING_BETWEEN_MODELS)

            # halt があれば status=partial で記録 (success とも failed とも違う中間状態).
            # scrape_log の status カラムは TEXT なので任意値 OK.
            final_status = "partial" if halted else "success"
            _scrape_log_finish(scrape_id, status=final_status, products_added=total)
            done_marker = "完了 (一部 halt)" if halted else "完了"
            print(f"\n=== {done_marker}: {total} models upserted ===")
        except Exception as e:
            _scrape_log_finish(scrape_id, status="failed",
                               error_message=f"{type(e).__name__}: {e}")
            raise
        return total
    finally:
        if own_driver:
            try:
                driver.quit()
            except Exception:
                pass


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
# Anti-bot resilience helpers (Phase 3-D)
# ============================================================================
def _is_blocked(driver) -> bool:
    """Akamai / Cloudflare 等の anti-bot ブロック検出.

    block ページ特徴:
      - "You don't have permission to access ..."
      - "errors.edgesuite.net" (Akamai 403)
      - "Reference #..." (Akamai ref ID)

    body 取得失敗時 (driver 例外等) は False 返却 (block ではないと判断).
    """
    from selenium.webdriver.common.by import By  # type: ignore
    try:
        body = driver.find_element(By.TAG_NAME, "body").text or ""
    except Exception:
        return False
    return any(sig in body for sig in _BLOCK_SIGNALS)


def _restart_driver(old_driver):
    """driver を破棄 → 5 秒待機 → 新規起動 (Akamai セッション切替を期待).

    block 検出後の最終手段. cooldown だけでは block が解除されない場合に session を切る.

    DNS / chromedriver CDN 取得失敗 (URLError 等) は最大 3 回リトライ.
    全失敗時は None を返す (caller が halt 判断).
    本処理を try/except で囲わなかった結果が 2026-04-29 β night1 クラッシュ事故.
    """
    print(f"  🔄 driver 再起動 (Akamai セッション切替)...", flush=True)
    try:
        old_driver.quit()
    except Exception:
        pass
    time.sleep(5)

    last_err = None
    for attempt in range(1, 4):
        try:
            return _start_driver()
        except Exception as e:
            last_err = e
            print(f"     driver 起動失敗 (attempt {attempt}/3): "
                  f"{type(e).__name__}: {e}", flush=True)
            if attempt < 3:
                time.sleep(30)
    print(f"  ⛔ driver 再起動を 3 回試行後も失敗、process halt します. "
          f"last error: {type(last_err).__name__}: {last_err}", flush=True)
    return None


def _safe_fetch_series_models(driver, series_name: str, series_url: str,
                               max_attempts: int = 3) -> tuple:
    """series page → モデル一覧 (block 検出 + retry/再起動付き).

    挙動:
      attempt 1: 通常実行 → block 検出なら cooldown
      attempt 2: 再実行 → block 解除されてなければ driver 再起動
      attempt 3: 再実行 → ダメなら空リスト返却 + skip

    Returns:
        (models_list, current_driver) — driver は restart で入れ替わる可能性あり
    """
    from casio_finder import scrape_casio_series  # type: ignore

    for attempt in range(1, max_attempts + 1):
        if driver is None:
            # driver 復旧不能 → 残 attempt も実行不可、空リスト返却
            print(f"  ⛔ [{series_name}] driver なし、残 attempt skip.")
            return [], None
        models = scrape_casio_series(driver, series_name, series_url)
        blocked = _is_blocked(driver)
        if not blocked and len(models) > 0:
            return models, driver  # success
        # 失敗パス
        if blocked:
            print(f"  🚧 [{series_name}] anti-bot block (attempt {attempt}/{max_attempts})")
        else:
            print(f"  ⚠️ [{series_name}] 0 件取得 (block なし、JS 描画?) (attempt {attempt}/{max_attempts})")
        if attempt < max_attempts:
            if blocked:
                print(f"     cooldown {_COOLDOWN_AFTER_BLOCK} 秒...", flush=True)
                time.sleep(_COOLDOWN_AFTER_BLOCK)
            else:
                time.sleep(10)
            if attempt >= 2:
                # 2 回失敗で driver 再起動 (session 切替). None なら次 attempt で halt.
                driver = _restart_driver(driver)
    print(f"  ⚠️ [{series_name}] {max_attempts} 回試行後も失敗、skip.")
    return [], driver


def _safe_upsert_model(driver, model: str, series_name: str = "",
                        max_attempts: int = 2) -> tuple:
    """1 model upsert (block 検出 + retry/再起動付き).

    Returns:
        (success_bool, current_driver)
    """
    from gshock_to_csv import scrape_casio  # type: ignore
    from casio_finder import check_new_flag  # type: ignore
    import api  # type: ignore

    product_url = PRODUCT_URL_TEMPLATE.format(model=model)
    print(f"  {model}...", end="", flush=True)

    for attempt in range(1, max_attempts + 1):
        if driver is None:
            print(f" ⛔ driver なし、skip.")
            return False, None
        data = scrape_casio(driver, product_url)
        blocked = _is_blocked(driver)
        # 成功条件: data あり + block なし + case_size 取得済 (block ページは case_size 空)
        if data and not blocked and data.get("case_size"):
            is_new, is_limited, price_jpy = check_new_flag(driver, model)
            specs = _build_specs(data, series_name, is_new, is_limited, price_jpy)
            model_official = data.get("model_official") or model
            api.upsert(
                category=CATEGORY,
                product_id=model_official,
                name=f"Casio G-SHOCK {model_official}",
                specs=specs,
                images=[],
                source=SOURCE,
                source_url=product_url,
            )
            print(f" [{specs.get('case_size','?')} / "
                  f"{'NEW' if is_new else '-'} / "
                  f"{'限定' if is_limited else '-'}]")
            return True, driver
        # 失敗パス
        if blocked:
            print(f" 🚧 block (attempt {attempt}/{max_attempts})")
        else:
            print(f" empty (attempt {attempt}/{max_attempts})")
        if attempt < max_attempts:
            if blocked:
                time.sleep(_COOLDOWN_AFTER_BLOCK)
                # block 後は driver 再起動 (session 切替で解除狙い). None なら次 attempt で skip.
                driver = _restart_driver(driver)
            else:
                time.sleep(10)
    print(f"     skip {model} (recovery 失敗)")
    return False, driver


# ============================================================================
# 内部処理 — scrape + upsert (legacy, update_single_series/model 経由用)
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
        print("  python iMakCatalog/scrapers/gshock.py --update-subset DW-6900,DW-5600")
        print("  python iMakCatalog/scrapers/gshock.py --series GA-2100")
        print("  python iMakCatalog/scrapers/gshock.py --model GA-2100-1A1JF")
        sys.exit(1)

    if args[0] == "--update":
        update_all_series()
    elif args[0] == "--update-subset" and len(args) >= 2:
        names = {s.strip() for s in args[1].split(",") if s.strip()}
        if not names:
            print("⚠️ subset 名が空")
            sys.exit(1)
        update_all_series(series_filter=names)
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
