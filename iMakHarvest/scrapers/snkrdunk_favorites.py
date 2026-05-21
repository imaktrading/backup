"""snkrdunk_favorites - SNKRDUNK お気に入り商品 URL 抽出.

iMakTCG (or 他カテゴリ) の新規仕入候補として、ユーザーが SNKRDUNK で「お気に入り」
登録した商品 URL を集約して HIGH/LOW スプシ A 列に append する scraper。

設計原則:
  - 既存 snkrdunk_official.create_driver (= chrome_profile_snkrdunk) 流用
  - login 必須 (= 初回 `python -m scrapers.snkrdunk_favorites --login` で手動 login)
  - お気に入り page = login 後の `/users/me/favorites` (実機検証で URL pattern 確定)
  - 詳細取得 (= title / price / image) は既存 fetch_apparel_used_instance + aggregate API 流用
  - dedupe key = `snkrdunk:<m>/<i>` (sheet_writer.dedupe_key 拡張済)

返却形式 (per item):
    {
        "url": "https://snkrdunk.com/apparels/158327/used/45549454",
        "model_id": 158327,
        "instance_id": 45549454,
        "title": "ペローナ L-P [OP06-021] ...",
        "price_jpy": 8900,
        "image_urls": [...],
        "condition": "PSA10",
        "description": "",  # SNKRDUNK 個別出品に説明欄なし
    }
"""
from __future__ import annotations

import os
import re
import time
from typing import Callable, Optional

from selenium.webdriver.common.by import By

from scrapers import snkrdunk_official
from scrapers.snkrdunk_official import (
    APPAREL_USED_URL_RE,
    CHROME_PROFILE_DIR,
    SELENIUM_HYDRATION_WAIT_SEC,
    SNKRDUNK_BASE,
    create_driver,
    extract_tcg_card_id,
    fetch_apparel_aggregate,
    fetch_apparel_used_instance,
    find_psa10_urls_for_card,
)


# ============================================================================
# Constants
# ============================================================================
FAVORITES_URL_CANDIDATES = [
    # 2026-05-21 実機検証で確定 (= user 提供): /accounts/favorites
    "https://snkrdunk.com/accounts/favorites",
    # フォールバック候補 (= 未検証、将来 URL pattern 変更時の予備)
    "https://snkrdunk.com/users/me/favorites",
    "https://snkrdunk.com/mypage/favorites",
]

# login session cookie name (= 実機検証で確認、auth_session が存在すれば login 済)
SNKRDUNK_AUTH_COOKIE_NAME = "auth_session"
HOME_URL = SNKRDUNK_BASE + "/"

DEFAULT_MAX_ITEMS = 200
DEFAULT_LOAD_MORE_SCROLLS = 8

# 補仕入 価格幅緩和率 (= 元価格 × N 倍まで採用、5/22 HQ 確定で × 1.2 標準)
# 環境変数 SNKRDUNK_AUX_PRICE_TOLERANCE で override 可能 (= 再起動不要、起動毎に読込)
# 例: SNKRDUNK_AUX_PRICE_TOLERANCE=1.3 → ×1.3 まで
SNKRDUNK_AUX_PRICE_TOLERANCE_MULTIPLIER = 1.2


def _get_price_tolerance_multiplier() -> float:
    """環境変数 SNKRDUNK_AUX_PRICE_TOLERANCE が設定されていれば override、なければ default 1.2."""
    raw = os.environ.get("SNKRDUNK_AUX_PRICE_TOLERANCE", "").strip()
    if raw:
        try:
            v = float(raw)
            if v > 0:
                return v
        except ValueError:
            pass
    return SNKRDUNK_AUX_PRICE_TOLERANCE_MULTIPLIER


def _compute_max_price(base_price: Optional[int]) -> Optional[int]:
    """元価格 × 価格幅緩和率 = 補仕入候補の価格上限 (= max_price filter 用).

    元価格が int でない or 0 以下 → None (= 価格 filter なし扱い)
    元価格 × multiplier を int に floor (= 端数切り捨て、上限を厳密に)
    """
    if not isinstance(base_price, int) or base_price <= 0:
        return None
    multiplier = _get_price_tolerance_multiplier()
    return int(base_price * multiplier)


# ============================================================================
# URL parsing
# ============================================================================
def parse_apparel_used_url(url: str) -> Optional[tuple[int, int]]:
    """`https://snkrdunk.com/apparels/<m>/used/<i>` → (model_id, instance_id) or None."""
    if not url:
        return None
    m = APPAREL_USED_URL_RE.search(url)
    if not m:
        return None
    try:
        return int(m.group(1)), int(m.group(2))
    except ValueError:
        return None


def normalize_apparel_used_url(url: str) -> Optional[str]:
    """お気に入り link を正準化された /apparels/<m>/used/<i> URL に変換 (query/fragment 除去)."""
    parsed = parse_apparel_used_url(url)
    if not parsed:
        return None
    m, i = parsed
    return f"https://snkrdunk.com/apparels/{m}/used/{i}"


# ============================================================================
# Login check / login workflow
# ============================================================================
def is_logged_in(driver) -> bool:
    """login 状態判定: snkrdunk.com domain で auth_session cookie が存在するかで判定.

    SNKRDUNK は SPA で menu が JS 後から render されるため DOM 文字判定は不安定。
    実機検証 (2026-05-21) で確認: login 済みなら `auth_session` cookie が
    snkrdunk.com domain で発行される (= 未 login 時は存在しない)。
    cookie が profile に書き込まれていることを保証するため、まず home page を hit して
    cookie store を warm-up してから判定する。
    """
    try:
        driver.get(HOME_URL)
    except Exception:
        return False
    time.sleep(3.0)  # cookie warm-up、SPA hydration は不要 (cookie 判定なので)
    try:
        cookies = driver.get_cookies()
    except Exception:
        return False
    for c in cookies:
        if c.get("name") == SNKRDUNK_AUTH_COOKIE_NAME:
            domain = (c.get("domain") or "").lower()
            if "snkrdunk" in domain:
                return True
    return False


def login_interactive(profile_dir: Optional[str] = None) -> None:
    """初回ログイン用 (interactive mode, stdin 必須). user が Enter を押して完了.

    使い方:
        python -m scrapers.snkrdunk_favorites --login
    ログイン後 chrome_profile_snkrdunk に cookie が保存され、以降 collect_*() は自動。
    """
    driver = create_driver(headless=False, profile_dir=profile_dir)
    try:
        driver.get(HOME_URL)
        print("Chrome が開きました。SNKRDUNK にログインしてください。")
        print("(右上の「ログイン」 から、メール+パスワード or LINE/Google/Apple 等で)")
        print("お気に入り商品が 1 件以上ある状態にしてから、")
        print("このターミナルで Enter を押してください。")
        input(">>> Enter to finish login: ")
        # login 状態確認
        ok = is_logged_in(driver)
        print(f"login 状態判定: {'OK (ログイン済)' if ok else 'NG (未ログイン)'}")
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def login_async(
    profile_dir: Optional[str] = None,
    timeout_sec: int = 600,
    poll_interval_sec: int = 15,
) -> bool:
    """stdin 不要な login mode (= background 実行可、login 検出で auto-quit).

    chrome を非 headless で起動 → user が手動 login (任意のタイミング、最大 timeout_sec) →
    poll_interval_sec ごとに is_logged_in 判定 → 検出時点で driver.quit して True 返却。
    タイムアウトすれば False。

    使い方:
        python -m scrapers.snkrdunk_favorites --login-async [--timeout 600] [--poll 15]
    """
    driver = create_driver(headless=False, profile_dir=profile_dir)
    deadline = time.time() + timeout_sec
    try:
        driver.get(HOME_URL)
        print(f"Chrome を開きました。最大 {timeout_sec}s 以内に SNKRDUNK にログインしてください。")
        print(f"  - 右上「ログイン」 → メール / LINE / Google / Apple 等")
        print(f"  - お気に入り 1 件以上が望ましい (POC で URL 取得確認のため)")
        print(f"  - {poll_interval_sec}s ごとに login 状態を poll、検出時点で自動 quit")
        print()
        while time.time() < deadline:
            time.sleep(poll_interval_sec)
            try:
                ok = is_logged_in(driver)
            except Exception as e:
                # driver crashed / page navigated badly → 続行
                print(f"  [poll] login check error: {type(e).__name__}: {e}")
                continue
            elapsed = int(timeout_sec - (deadline - time.time()))
            if ok:
                print(f"  [poll {elapsed}s] login 検出 → 完了")
                return True
            print(f"  [poll {elapsed}s] まだ未 login (= login + お気に入り追加を続けてください)")
        print(f"!!! timeout {timeout_sec}s 経過、未 login 状態で終了")
        return False
    finally:
        try:
            driver.quit()
        except Exception:
            pass


# ============================================================================
# お気に入り URL 収集
# ============================================================================
def _scroll_to_load_more(driver, scrolls: int, sleep_after: float = 1.5) -> None:
    """お気に入り page を scroll して lazy load を発火."""
    for _ in range(max(0, scrolls)):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(sleep_after)


def _collect_apparel_used_links_from_page(driver) -> list[str]:
    """現在 driver が開いている page から /apparels/<m>/used/<i> link を全部抽出 (順序保持 + dedupe)."""
    anchors = driver.find_elements(By.TAG_NAME, "a")
    seen: set[str] = set()
    urls: list[str] = []
    for a in anchors:
        try:
            href = a.get_attribute("href") or ""
        except Exception:
            continue
        canon = normalize_apparel_used_url(href)
        if not canon:
            continue
        if canon in seen:
            continue
        seen.add(canon)
        urls.append(canon)
    return urls


def collect_favorite_urls(
    driver=None,
    headless: bool = False,
    max_items: int = DEFAULT_MAX_ITEMS,
    load_more_scrolls: int = DEFAULT_LOAD_MORE_SCROLLS,
    favorites_url: Optional[str] = None,
) -> list[str]:
    """SNKRDUNK お気に入り page から /apparels/<m>/used/<i> URL list を取得.

    Args:
        driver: 既存の Selenium driver (None なら新規 create)
        headless: 新規 driver 起動時の headless 設定
        max_items: 最大件数 (=超過分は drop)
        load_more_scrolls: お気に入り page で scroll する回数 (= lazy load)
        favorites_url: 強制指定の favorites page URL (default = FAVORITES_URL_CANDIDATES を順次試行)

    Returns: ['https://snkrdunk.com/apparels/.../used/...', ...] (= dedupe + 順序保持)
    """
    owns_driver = driver is None
    if owns_driver:
        driver = create_driver(headless=headless)
    try:
        if not is_logged_in(driver):
            raise RuntimeError(
                "SNKRDUNK が未ログイン状態です。先に手動 login してください:\n"
                "  python -m scrapers.snkrdunk_favorites --login"
            )

        # URL 候補を順次試して /apparels/ link が取れるものを採用
        candidates = [favorites_url] if favorites_url else FAVORITES_URL_CANDIDATES
        tried: list[tuple[str, int]] = []
        urls: list[str] = []
        for url in candidates:
            driver.get(url)
            time.sleep(SELENIUM_HYDRATION_WAIT_SEC)
            _scroll_to_load_more(driver, scrolls=load_more_scrolls)
            urls = _collect_apparel_used_links_from_page(driver)
            tried.append((url, len(urls)))
            if urls:
                break
        if not urls:
            raise RuntimeError(
                "お気に入り商品が 1 件も取れませんでした。試行 URL:\n  "
                + "\n  ".join(f"{u} ({n} 件)" for u, n in tried)
                + "\n(login 状態 / お気に入り 0 件 / URL pattern 変更 を確認してください)"
            )
        return urls[:max_items]
    finally:
        if owns_driver:
            try:
                driver.quit()
            except Exception:
                pass


# ============================================================================
# 詳細取得
# ============================================================================
def _extract_image_urls(agg: Optional[dict], instance: Optional[dict]) -> list[str]:
    """instance / aggregate から画像 URL list を抽出 (= 1 枚以上、order 保持).

    優先順:
      1. instance.imageUrls (= 出品者の実物写真 list、6 枚程度)
      2. instance.primaryPhoto.imageUrl (= 単体 fallback)
      3. aggregate.primaryMedia.imageUrl (= カード本体公式画像、instance なし時)
    """
    image_urls: list[str] = []
    if instance:
        inst_imgs = instance.get("imageUrls")
        if isinstance(inst_imgs, list):
            image_urls = [u for u in inst_imgs if isinstance(u, str) and u]
        if not image_urls:
            pp = instance.get("primaryPhoto")
            if isinstance(pp, dict):
                img = pp.get("imageUrl")
                if isinstance(img, str) and img:
                    image_urls.append(img)
    if not image_urls and agg:
        pm = agg.get("primaryMedia")
        if isinstance(pm, dict):
            img = pm.get("imageUrl")
            if isinstance(img, str) and img:
                image_urls.append(img)
    return image_urls


def _build_item_dict(model_id: int, instance_id: int) -> Optional[dict]:
    """API 2 つで title / price / image / condition / in_stock を取得して item dict にまとめる.

    aggregate 取得失敗 (= 404 等) なら None。
    in_stock の値:
      - True:  instance.status == 0 (= 出品中)
      - False: instance.status != 0 (= 売切等、status が int で 0 以外)
      - None:  instance 取得失敗 or status field 欠落 (= 不明、メルカリと同様 安全側で含める)
    """
    agg = fetch_apparel_aggregate(model_id)
    if not agg:
        return None
    instance = fetch_apparel_used_instance(model_id, instance_id)
    # instance API 失敗時は title だけでも取れているので best effort で返す
    title = (agg.get("name") or agg.get("localizedName") or "").strip()
    price = None
    condition = ""
    in_stock: Optional[bool] = None
    if instance:
        price = instance.get("price")
        condition = (instance.get("displayShortConditionTitle") or "").strip()
        status = instance.get("status")
        if isinstance(status, int):
            in_stock = (status == 0)
    image_urls = _extract_image_urls(agg, instance)

    return {
        "url": f"https://snkrdunk.com/apparels/{model_id}/used/{instance_id}",
        "model_id": model_id,
        "instance_id": instance_id,
        "title": title,
        "price_jpy": price,
        "image_urls": image_urls,
        "condition": condition,
        "description": "",  # SNKRDUNK 個別出品に説明欄なし
        "in_stock": in_stock,
    }


def collect_favorites_with_details(
    driver=None,
    headless: bool = False,
    max_items: int = DEFAULT_MAX_ITEMS,
    load_more_scrolls: int = DEFAULT_LOAD_MORE_SCROLLS,
    favorites_url: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    enable_auxiliary: bool = False,
    aux_max_per_item: int = 5,
    exclude_sold: bool = True,
) -> list[dict]:
    """お気に入り URL + 詳細 (title/price/image/condition) を取得.

    Args:
        enable_auxiliary: True で「補仕入連携」 ON
            - 各お気に入り item の title から card_id 抽出 (= OP/ST/EB/P 系)
            - SNKRDUNK 内で同 card_id の PSA10 出品検索
            - 価格 ≤ 元 price のみ採用 (= 同価格 or 安い)
            - 元 instance_id は除外 (= 自分自身は補に出さない)
            - 結果は item dict の "auxiliary_urls" key に list[str] で格納
              (= sheet_writer 経由で AC-AG 列に投入される運用)
        aux_max_per_item: 補仕入 1 item あたりの最大件数 (= AC-AG 5 列なので default 5)
        exclude_sold: True で SOLD 商品 (= in_stock=False) を除外
            (メルカリと同パターン、in_stock=None は安全側で含める)

    progress_callback(cur, total, msg): GUI 進捗用 (省略可).
    """
    # 補仕入連携時は Selenium driver 必須 (= find_psa10_urls_for_card が要)、
    # driver なし起動なら create_driver する
    owns_driver = driver is None
    if owns_driver:
        driver = create_driver(headless=headless)

    try:
        urls = collect_favorite_urls(
            driver=driver,
            headless=headless,
            max_items=max_items,
            load_more_scrolls=load_more_scrolls,
            favorites_url=favorites_url,
        )
        items: list[dict] = []
        total = len(urls)
        for i, url in enumerate(urls, start=1):
            parsed = parse_apparel_used_url(url)
            if not parsed:
                continue
            model_id, instance_id = parsed
            if progress_callback:
                progress_callback(i, total, url)
            d = _build_item_dict(model_id, instance_id)
            if not d:
                continue
            # SOLD 除外 (= メルカリと同パターン、in_stock=None は安全側で含める)
            if exclude_sold and d.get("in_stock") is False:
                continue
            if enable_auxiliary:
                d["auxiliary_urls"] = _collect_auxiliary_for_item(
                    d, driver, max_results=aux_max_per_item,
                )
            items.append(d)
        return items
    finally:
        if owns_driver:
            try:
                driver.quit()
            except Exception:
                pass


def _collect_auxiliary_for_item(item: dict, driver, max_results: int = 5) -> list[str]:
    """1 お気に入り item に対して同 card_id の PSA10 補仕入 URL list を取得.

    元のお気に入り の model_id を force_model_id として渡す = 検索 step skip して
    same packaging の他出品のみ取得 (= packaging ブレ回避)。

    Returns: 価格 ≤ 元 price の PSA10 URL list (= 元 instance 除外)、card_id 抽出失敗時は []。
    """
    title = (item.get("title") or "").strip()
    card_id = extract_tcg_card_id(title)
    if not card_id:
        return []
    self_iid = item.get("instance_id")
    self_price = item.get("price_jpy")
    self_model = item.get("model_id")
    exclude_ids: set[int] = {int(self_iid)} if isinstance(self_iid, int) else set()
    # 5/22 確定: 元価格 × 1.2 (= SNKRDUNK_AUX_PRICE_TOLERANCE_MULTIPLIER) を上限
    max_price = _compute_max_price(self_price if isinstance(self_price, int) else None)
    force_model = int(self_model) if isinstance(self_model, int) else None
    info = find_psa10_urls_for_card(
        card_id,
        driver,
        max_results=max_results,
        max_price=max_price,
        exclude_instance_ids=exclude_ids,
        force_model_id=force_model,
    )
    return list(info.get("psa10_urls") or [])


# ============================================================================
# CLI (動作確認用)
# ============================================================================
if __name__ == "__main__":
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser()
    ap.add_argument("--login", action="store_true", help="ログイン用 Chrome を起動 (interactive、Enter で完了)")
    ap.add_argument("--login-async", action="store_true",
                    help="ログイン用 Chrome を起動 (stdin 不要、login 検出で auto-quit)")
    ap.add_argument("--timeout", type=int, default=600,
                    help="--login-async タイムアウト秒 (default: 600)")
    ap.add_argument("--poll", type=int, default=15,
                    help="--login-async poll 間隔秒 (default: 15)")
    ap.add_argument("--headless", action="store_true", help="headless で実行 (login 後のみ推奨)")
    ap.add_argument("--max-items", type=int, default=DEFAULT_MAX_ITEMS)
    ap.add_argument("--load-more", type=int, default=DEFAULT_LOAD_MORE_SCROLLS)
    ap.add_argument("--urls-only", action="store_true", help="URL list のみ出力 (= 詳細取得スキップ)")
    ap.add_argument("--favorites-url", default=None, help="お気に入り page URL を強制指定 (= POC 用)")
    ap.add_argument("--with-aux", action="store_true",
                    help="補仕入連携 ON (= 各お気に入り item に同 card_id PSA10 URL list を auxiliary_urls に追加)")
    ap.add_argument("--aux-max", type=int, default=5, help="補仕入 1 item あたり最大件数 (default 5)")
    ap.add_argument("--no-exclude-sold", dest="exclude_sold", action="store_false", default=True,
                    help="SOLD 商品も含める (default は SOLD 除外、メルカリと同仕様)")
    args = ap.parse_args()

    if args.login:
        login_interactive()
        sys.exit(0)

    if args.login_async:
        ok = login_async(timeout_sec=args.timeout, poll_interval_sec=args.poll)
        sys.exit(0 if ok else 1)

    if args.urls_only:
        urls = collect_favorite_urls(
            headless=args.headless,
            max_items=args.max_items,
            load_more_scrolls=args.load_more,
            favorites_url=args.favorites_url,
        )
        print(json.dumps(urls, ensure_ascii=False, indent=2))
        sys.exit(0)

    items = collect_favorites_with_details(
        headless=args.headless,
        max_items=args.max_items,
        load_more_scrolls=args.load_more,
        favorites_url=args.favorites_url,
        progress_callback=lambda i, t, u: print(f"  [{i}/{t}] {u}"),
        enable_auxiliary=args.with_aux,
        aux_max_per_item=args.aux_max,
        exclude_sold=args.exclude_sold,
    )
    json.dump(items, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
