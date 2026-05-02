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
  python iMakCatalog/scrapers/gshock.py --update-subset DW-6900 --max-models 5  # 小バッチ
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
#
# 2026-05-03 (Step 1 原因究明後 / A 改修):
# Akamai は explicit 403 と silent 404 disguise (404 風 "見つかりませんでした" ページ)
# を混合して serve する. 5/1 16:04 smoke では 100% silent 404 disguise だった.
# → 404 disguise 文字列を block signal に追加. real 404 (削除済 model) も
#    block 扱いになるが、同じく skip 動作で問題なし (false positive 影響軽微).
_BLOCK_SIGNALS = (
    # explicit Akamai
    "permission to access",       # Akamai 403 メッセージ
    "errors.edgesuite.net",       # Akamai 403 ページ URL
    "Reference #",                # Akamai リファレンス ID 行
    "Access Denied",              # 汎用
    "Cloudflare",                 # Cloudflare チャレンジ
    # silent 404 disguise (CASIO + Akamai が組合せで使う 5/1 PM ~ 確認済の挙動)
    "見つかりませんでした",       # CASIO 404 page "お探しのページは見つかりませんでした"
    "ご不便をおかけして",         # 同 404 ページの定型文
)

# Cooldown / pacing 秒数 (block 検出時の待機時間).
# 2026-05-03 (Step 1 後 / B 改修): リクエスト密度を ~1/15 に下げて Akamai 学習閾値を回避.
#   旧: PACING 2/3s → 新: 30/60s
#   1 model 1 ~ 2 分かかるが、yield 0% よりマシな小バッチ運用前提
_COOLDOWN_AFTER_BLOCK = 75
_PACING_BETWEEN_SERIES = 60
_PACING_BETWEEN_MODELS = 30


# ============================================================================
# 公開 API
# ============================================================================
def update_all_series(driver=None, series_filter: Optional[set] = None,
                       max_models_per_session: Optional[int] = None) -> int:
    """全シリーズ差分更新 (月次バッチ想定). 2-pass + anti-bot resilience.

    Pass 1: 全 series のモデル一覧を tight burst で取得 (戦略価値の確保最優先)
    Pass 2: 各 model の詳細スクレイプ + upsert

    各段階で block 検出 → cooldown + driver 再起動で recovery.

    Args:
        driver: 既存 Selenium driver を渡せば使い回す. None なら本関数内で起動・終了.
        series_filter: 指定シリーズのみ対象 (例: {"DW-6900", "DW-5600"}).
                       None なら CASIO_SERIES_PAGES 全件.
        max_models_per_session: Pass 2 の model attempt 上限.
            None なら無制限. 指定すると attempt 数 (success/skip 問わず) がこの値に達した
            時点で正常終了. Akamai の rate limit を超えないための「小バッチ」運用に必須.
            production 経験則: ~10 models/session が block 発火閾値の下限.

    Returns:
        upsert 成功件数.
    """
    from casio_finder import CASIO_SERIES_PAGES  # type: ignore

    own_driver = driver is None
    if own_driver:
        # 初期 driver 起動も _restart_driver 経由で URLError 等の chromedriver CDN 取得失敗を
        # 3 回 retry する (2026-05-03 修正: Phase 3-D で _restart_driver にだけ retry を入れたが、
        # update_all_series 冒頭の初期起動で発火する URLError には未対応だった露呈).
        # _restart_driver(None) は old_driver=None でも quit() を try/except で吸収する設計.
        driver = _restart_driver(None)
        if driver is None:
            raise RuntimeError("初期 driver 起動が 3 回試行後も失敗 (DNS / chromedriver CDN 取得不可)")

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
            attempts = 0
            cap_reached = False
            n_total = sum(len(m) for m in series_models.values())
            cap_msg = f", session cap={max_models_per_session}" if max_models_per_session else ""
            print(f"\n=== Pass 2/2: model 詳細スクレイプ ({n_total} models{cap_msg}) ===")
            for series_name, models in series_models.items():
                if not models:
                    continue
                if driver is None:
                    print(f"\n[{series_name}] ⛔ driver halt 検出、残 series skip")
                    halted = True
                    break
                if cap_reached:
                    break
                print(f"\n[{series_name}] {len(models)} models")
                for model in models:
                    if driver is None:
                        # _safe_upsert_model が None を返したら以降の model も skip
                        halted = True
                        break
                    if max_models_per_session and attempts >= max_models_per_session:
                        # Akamai 学習回避: session cap 到達で正常終了
                        cap_reached = True
                        break
                    attempts += 1
                    success, driver = _safe_upsert_model(driver, model, series_name)
                    if success:
                        total += 1
                    time.sleep(_PACING_BETWEEN_MODELS)

            # 終了状態の決定:
            #   halt → driver 再起動失敗 (URLError 等)、partial
            #   cap_reached → session cap 正常打切、success
            #   それ以外 → 全件処理完了、success
            if halted:
                final_status = "partial"
                done_marker = "完了 (一部 halt)"
            elif cap_reached:
                final_status = "success"
                done_marker = f"session cap {max_models_per_session} 到達で正常打切"
            else:
                final_status = "success"
                done_marker = "完了"
            _scrape_log_finish(scrape_id, status=final_status, products_added=total)
            print(f"\n=== {done_marker}: {total} models upserted "
                  f"(attempts={attempts}/{n_total}) ===")
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


def _scrape_via_external_sources(model: str) -> dict:
    """g-central + casiofanmag + 既存 pure 関数による model spec 組立.

    2026-05-03 設計変更:
      CASIO 公式は Akamai で block されるため、Pass 2 では公式直叩きを完全回避する.
      既存 iMakG-shock/gshock_to_csv.py の関数群を import 再利用 (修正連鎖回避).

    取得経路:
      1. scrape_gcentral(model_base) — weight / year / case_size / case_thickness
                                        / band_material / dial_color
      2. scrape_casiofanmag(model_base) — weight / year (gcentral miss 時 fallback)
      3. 型番由来 pure 関数 — band_color / band_strap / band_material (GMW系)
                              / case_shape / is_metal / Solar/movement
      4. デフォルト値 — water_resistance / case_material / crystal / display 等

    失われる情報 (許容):
      - is_new / is_limited (check_new_flag が CASIO 必要、default False)
      - 細部 spec の例外モデル (G-SHOCK 全体の <5%、出品時手動調整で対処)

    Returns:
        scrape_casio 互換 dict (build_specs / build_row が同じ shape を期待).
        全フィールド miss なら空 dict 返却.
    """
    import re as _re
    from gshock_to_csv import (  # type: ignore
        scrape_gcentral, scrape_casiofanmag,
        get_band_color, get_band_strap, get_band_material_by_model,
        get_case_shape, get_default_weight, is_tough_solar,
    )

    model_base = _re.sub(r"(?:JF|JR)$", "", model)
    data: dict = {
        "model": model,
        "model_official": model,
        "model_base": model_base,
    }

    # 1. g-central (主)
    gc = scrape_gcentral(model_base)
    for k in ("weight", "year", "case_size", "case_thickness",
              "band_material", "dial_color"):
        if gc.get(k):
            data[k] = gc[k]

    # 2. casiofanmag (fallback)
    cfm = scrape_casiofanmag(model_base)
    if not data.get("year") and cfm.get("year"):
        data["year"] = cfm["year"]
    if not data.get("weight") and cfm.get("weight"):
        data["weight"] = cfm["weight"]

    # 3. 型番由来 pure 関数推論
    data["band_color"] = get_band_color(model)
    data["case_shape"] = get_case_shape(model_base)
    auto_band_strap = get_band_strap(model)
    if auto_band_strap != "Two-Piece Strap":
        data["band_strap_override"] = auto_band_strap
    auto_band_material = get_band_material_by_model(model)
    if auto_band_material:
        data["band_material"] = auto_band_material
    key = model_base.upper().replace("-", "")
    data["is_metal"] = key.startswith("GM") or key.startswith("GMW")
    if not data.get("weight"):
        data["weight"] = get_default_weight(model_base)

    # 4. defaults (CASIO 公式取れた時の典型値)
    data.setdefault("water_resistance", "200 m (20 ATM)")
    data.setdefault("band_material", "Resin")
    data.setdefault("case_material", "Resin")
    data.setdefault("crystal", "Mineral Glass")
    data.setdefault("case_size", "")
    data.setdefault("case_thickness", "")
    data.setdefault("band_length", "")
    data.setdefault("year", "")
    data.setdefault("dial_color", "")
    data.setdefault("bezel_color", "")
    data.setdefault("movement", "Quartz")
    data.setdefault("display", "Digital")  # G-SHOCK は Digital 主流
    data.setdefault("features", "Shock-Resistant")
    data.setdefault("band_width", "")

    # 5. Solar 検出 (型番 prefix から)
    if is_tough_solar(model_base):
        if "Solar Powered" not in data["features"]:
            data["features"] = "Solar Powered, " + data["features"]
        data["movement"] = "Solar Quartz"

    # 6. post-processing 検閲 (g-central / casiofanmag 由来の既知バグ補正).
    # production gshock_to_csv 影響を避けるため scrape_*** 本体は触らず本関数で sanitize.
    return _sanitize_external_data(data)


def _sanitize_external_data(data: dict) -> dict:
    """g-central / casiofanmag 由来 data の検閲 post-processing.

    既知バグ修正:
      - year に型番由来の数字混入 (例: model='DW-6900' → casiofanmag が year='6900' 抽出).
        scrape_casiofanmag の `(\\d{4})[^\\d].*?release|release.*?(\\d{4})` regex が
        型番中の連続 4 数字に hit する事象.
      - year が妥当範囲外 (1990-2030 の外) の値.

    修正方針 (修正連鎖回避 / 5fee51a 準拠):
      本番 gshock_to_csv で稼働中の scrape_gcentral / scrape_casiofanmag は触らず、
      catalog 取込み層に検閲ロジックを集中させる.
      → 本番出品処理に影響なし、catalog 側だけ品質向上.
    """
    import re as _re

    year = data.get("year", "")
    if year:
        # 型番由来の数字に一致 → 誤抽出として空にする
        model_base = data.get("model_base", "")
        model_digits = "".join(_re.findall(r"\d+", model_base))
        if model_digits and year in model_digits:
            data["year"] = ""
        else:
            # 妥当範囲外 (1990-2030 の外) → 空にする
            try:
                yi = int(year)
                if not (1990 <= yi <= 2030):
                    data["year"] = ""
            except ValueError:
                data["year"] = ""

    return data


def _safe_upsert_model(driver, model: str, series_name: str = "",
                        max_attempts: int = 2) -> tuple:
    """1 model upsert (g-central + casiofanmag 経由、CASIO 直叩き完全回避).

    2026-05-03 仕様変更:
      旧 path (scrape_casio + check_new_flag) は Akamai で block されるため
      _scrape_via_external_sources に切替. driver は Pass 1 で使ったものが
      引数として渡されるが、本関数では使わない (signature 互換のため受け取るのみ).

    Returns:
        (success_bool, current_driver)  driver は変更されずそのまま返す
    """
    import api  # type: ignore

    print(f"  {model}...", end="", flush=True)

    data = _scrape_via_external_sources(model)

    # 成功判定: g-central か casiofanmag のいずれかから 1 つ以上の field を取得できれば OK.
    # case_size / weight / year のいずれかが空でなければ実データありとみなす.
    has_real_data = bool(data.get("case_size") or data.get("weight") or data.get("year"))
    if not has_real_data:
        print(f" empty (g-central/casiofanmag 両方 miss)")
        return False, driver

    # is_new / is_limited は CASIO が必要なので default False で投入 (Phase 2 で別ソース)
    is_new = False
    is_limited = False
    price_jpy = ""

    specs = _build_specs(data, series_name, is_new, is_limited, price_jpy)
    model_official = data.get("model_official") or model

    api.upsert(
        category=CATEGORY,
        product_id=model_official,
        name=f"Casio G-SHOCK {model_official}",
        specs=specs,
        images=[],
        source="g-central+casiofanmag",  # 明示的に CASIO 経由でないことを示す
        source_url=f"https://www.g-central.com/specs/g-shock-{data['model_base']}/",
    )
    print(f" [case={data.get('case_size','?')} / year={data.get('year','?')} / "
          f"weight={data.get('weight','?')}]")
    return True, driver


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
        print("  python iMakCatalog/scrapers/gshock.py --update-subset DW-6900 --max-models 5")
        print("  python iMakCatalog/scrapers/gshock.py --series GA-2100")
        print("  python iMakCatalog/scrapers/gshock.py --model GA-2100-1A1JF")
        sys.exit(1)

    # --max-models N を args から抽出 (順序問わず受け付け).
    # 「小バッチ」運用で Akamai rate limit 学習を避けるためのキャップ.
    max_models = None
    if "--max-models" in args:
        idx = args.index("--max-models")
        if idx + 1 >= len(args):
            print("⚠️ --max-models の値が指定されていません")
            sys.exit(1)
        try:
            max_models = int(args[idx + 1])
        except ValueError:
            print(f"⚠️ --max-models の値が整数でない: {args[idx + 1]!r}")
            sys.exit(1)
        if max_models <= 0:
            print(f"⚠️ --max-models は正の整数でなければなりません: {max_models}")
            sys.exit(1)
        # 抽出した分を args から除去
        args = [a for i, a in enumerate(args) if i not in (idx, idx + 1)]

    if args[0] == "--update":
        update_all_series(max_models_per_session=max_models)
    elif args[0] == "--update-subset" and len(args) >= 2:
        names = {s.strip() for s in args[1].split(",") if s.strip()}
        if not names:
            print("⚠️ subset 名が空")
            sys.exit(1)
        update_all_series(series_filter=names, max_models_per_session=max_models)
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
