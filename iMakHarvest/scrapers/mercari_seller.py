"""mercari_seller - メルカリセラー (= /user/profile/<id>) 出品一覧 URL 抽出.

iMak Trading Japan 信頼セラー (= 過去取引 安心) の出品中商品を まとめて中間スプシに
append する scraper。いいね 経由 (= mercari_likes) ではなく seller profile page から
取得する用途。

設計原則:
  - 既存 mercari_likes の login workflow / driver / detail 取得 logic を可能な限り流用
  - 一般 メルカリ C2C のみ (= Phase 1)、 Shops は Phase 3 別実装
  - title から card_id (= OP/ST/EB/P 系) 抽出 → 同 card_id group 化 → 主 (= 最安) + 補
    (= 残り、 価格昇順) で AC-AG 列投入 (= snkrdunk_favorites 補仕入連携と同思想、案 D)
  - SOLD 除外 default ON (= mercari_likes と同パターン、 in_stock=None は安全側)
  - ハード CAP 必須 (= 1000 件級セラー で bot 検出回避、 ユーザー上限と min 採用)
  - dedup は呼出側 (= mercari_seller_sheet) で per seller タブ単位、 本 module は scrape のみ

Phase 1 制約:
  - 一般メルカリ C2C のみ (= /user/profile/<id> 形式)
  - Shops (= /shops/* domain) は別 DOM のため非対応 (= Phase 3 別実装)
  - title only ベース card_id 抽出 (= Vision API 補強は Phase 2 別依頼)
"""
from __future__ import annotations

import re
import time
from typing import Callable, Optional

from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from scrapers import mercari_likes
from scrapers.mercari_likes import (
    DEFAULT_AFTER_CLICK_SLEEP,
    DEFAULT_INITIAL_WAIT_SEC,
    create_driver,
    parse_item_id,
)
from scrapers.snkrdunk_official import extract_tcg_card_id
from scrapers.vision_card_id import (
    judge_card_id_from_image_url,
    reconcile_title_and_vision,
)


# ============================================================================
# Constants
# ============================================================================
# /user/profile/<id> URL pattern (= 一般メルカリ C2C、 Shops は別 domain で別実装)
SELLER_PROFILE_URL_RE = re.compile(r"jp\.mercari\.com/user/profile/(\d+)")

# ハード CAP (= bot 検出回避のための絶対上限、 1 セッションで取得可能な最大件数)
# 既存 mercari_likes は DEFAULT_MAX_ITEMS=500、 seller は profile page で大量出品セラー
# (= 1000 件級) があるため CAP を厳しめに設定 = 1 セッション 150 件で打切
# それ以上欲しいユーザーは時間空けて複数セッションで取得 (= bot 検出 / IP block 回避)
HARD_CAP_PER_SESSION = 150

# default ユーザー上限 (= GUI entry の default 値、 ユーザーが上書き可能)
DEFAULT_USER_LIMIT = 25

# scroll 関連
# 5/26 user GUI 実行で「6 件で打切 + total_seen=6 (= 実際は 30+ 件)」 が発生 →
# lazy load が初期 hydration 直後だと不安定、 scroll 間隔 / no_progress 閾値 / 初期待機
# 全て延長して堅牢化。
DEFAULT_LOAD_MORE_SCROLLS = 40  # 「もっと見る」 button click + fallback scroll の総 iteration 数
DEFAULT_SCROLL_INTERVAL_SEC = 2.5  # 1.5s → 2.5s (lazy load 完了待ち)
DEFAULT_INITIAL_PROFILE_WAIT_SEC = 18  # 初期 hydration、 12s → 18s (= profile page は重め)
DEFAULT_NO_PROGRESS_THRESHOLD = 6  # 連続で listing 数増えなくても scroll 継続する回数

# 5/26 user 指摘 + 実機調査:
# メルカリ profile page には「もっとみる」 button (= `button.showMoreButton__*`) があり、
# 1 click で ~30-50 件 lazy load される (= フリマアシスト拡張機能で 5 click ≒ 全件 確認済)。
# 単純 scroll より bot 検出回避効果が高く + 効率的なので、 button click を主軸にする。
SHOW_MORE_BUTTON_CSS = "button[class*='showMoreButton']"
SHOW_MORE_BUTTON_TEXT_KEYWORDS = ("もっとみる", "もっと見る")  # text fallback 検索用
DEFAULT_AFTER_CLICK_WAIT_SEC = 2.0  # button click 後の lazy load 完了待ち

# manual click 待機 mode (= user 手動「もっと見る (5)」 click 完了待ち)
DEFAULT_MANUAL_WAIT_POLL_SEC = 3.0  # polling 間隔
DEFAULT_MANUAL_WAIT_STABLE_SEC = 15.0  # 連続 N 秒 listing 増えなければ完了とみなす
DEFAULT_MANUAL_WAIT_MAX_SEC = 600  # 最大待機時間 (= 10 分)


# ============================================================================
# URL parse
# ============================================================================
def parse_seller_id(url: str) -> Optional[str]:
    """`https://jp.mercari.com/user/profile/<id>` から seller_id (= str of digits) 抽出.

    Shops (= /shops/*) や別形式は対象外で None。
    """
    if not url:
        return None
    m = SELLER_PROFILE_URL_RE.search(url)
    if m:
        return m.group(1)
    return None


def build_seller_profile_url(seller_id: str) -> str:
    """seller_id (= str) → 正規化された profile URL."""
    return f"https://jp.mercari.com/user/profile/{seller_id}"


# ============================================================================
# 件数 CAP
# ============================================================================
def resolve_effective_cap(user_limit: Optional[int]) -> int:
    """ユーザー上限 + ハード CAP の min を採用 (= 依頼書 sec 5).

    user_limit:
      - None / 0 以下 → 「無制限希望」 扱い、 ハード CAP 採用
      - 正の int → min(user_limit, HARD_CAP_PER_SESSION)
    """
    if user_limit is None or not isinstance(user_limit, int) or user_limit <= 0:
        return HARD_CAP_PER_SESSION
    return min(user_limit, HARD_CAP_PER_SESSION)


# ============================================================================
# Listing 抽出
# ============================================================================
def _collect_listing_urls_from_page(driver) -> list[str]:
    """現在 driver が開いている page から `/item/m\\d+` 全 link 抽出 (= dedupe + 順序保持)."""
    anchors = driver.find_elements(By.TAG_NAME, "a")
    seen: set[str] = set()
    urls: list[str] = []
    for a in anchors:
        try:
            href = a.get_attribute("href") or ""
        except Exception:
            continue
        item_id = parse_item_id(href)
        if not item_id:
            continue
        canon = f"https://jp.mercari.com/item/{item_id}"
        if canon in seen:
            continue
        seen.add(canon)
        urls.append(canon)
    return urls


def _click_load_more_if_exists(driver, wait_sec: int = 5) -> bool:
    """profile page の listing 用「もっと見る(N)」 button があれば click、 成功なら True.

    5/26 Gemini 相談で確定:
    - フリマアシスト button click は selenium native click だと不安定 (= UserActivation
      `event.isTrusted` チェックで弾かれる可能性)
    - **ActionChains.move_to_element().click()** で 物理マウス操作模倣
      → ブラウザ側で「ユーザー操作」 として認識されやすい
    - **WebDriverWait** で button が clickable になるまで明示待ち (= 拡張機能 DOM
      注入の timing 不安定対策)

    button 区別 (= 5/26 実機調査):
    | button | 提供元 | text | 親 |
    |--------|--------|------|-----|
    | 自己紹介展開 | メルカリ ネイティブ | 「もっとみる」 | `merShowMore` |
    | **listing 拡張** | **フリマアシスト** | **「もっと見る(N)」** | `merCheckboxLabel` |
    | フォロワー等 | メルカリ ネイティブ | 「もっと見る」 | `merButton secondary__*` |

    selector: XPath `contains(text(), 'もっと見る(')` (= 「(」 付きで listing 拡張のみ)
    """
    xpath = "//button[contains(text(), 'もっと見る(')]"
    try:
        btn = WebDriverWait(driver, wait_sec).until(
            EC.element_to_be_clickable((By.XPATH, xpath))
        )
    except Exception:
        return False
    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
        time.sleep(0.5)  # scroll animation 完了待ち
        # ActionChains で物理マウス操作 模倣 (= UserActivation 対策、 Gemini 5/26 推奨)
        ActionChains(driver).move_to_element(btn).click().perform()
        return True
    except Exception:
        return False


def _dismiss_alert_if_present(driver) -> Optional[str]:
    """page に alert dialog があれば accept で dismiss、 dismiss した text を返す.

    フリマアシスト が listing 全件 lazy load 完了時に「読込完了」 alert を出す挙動を
    検出して、 dismiss + 完了 signal として扱う。
    """
    try:
        alert = driver.switch_to.alert
        text = alert.text
        try:
            alert.accept()
        except Exception:
            pass
        return text
    except Exception:
        return None


# フリマアシスト 完了 signal の alert text
FURIMA_ASSIST_COMPLETE_ALERT_TEXT = "読込完了"


def _load_until_enough(
    driver,
    target_count: int,
    max_iterations: int = DEFAULT_LOAD_MORE_SCROLLS,
    interval: float = DEFAULT_AFTER_CLICK_WAIT_SEC,
    no_progress_threshold: int = DEFAULT_NO_PROGRESS_THRESHOLD,
) -> int:
    """profile page で target_count 件以上 listing が取れるまで「もっとみる」 button click
    + scroll fallback を続ける.

    動作:
      1. button click を試行、 成功なら click 後 interval 秒待機 (= lazy load 完了)
      2. button なければ scroll (= window.scrollTo end)
      3. listing 数が target に達するか、 no_progress_threshold 連続で増えなければ stop

    button click 主軸の理由 (= 5/26 実機調査 + フリマアシスト拡張機能観察):
      - 1 click ≒ 30-50 件 lazy load (= scroll より効率的)
      - bot 検出回避 (= 通常 user 操作)
      - 5 click ≒ 100-300 件全件 (= 普通の seller 完結)
      - 1000 件 seller でも 20-30 click で 1 セッション全件

    Returns: 取得件数 (= 最後の iteration 後の listing 件数)
    """
    last_count = 0
    no_progress = 0
    for i in range(max_iterations):
        # フリマアシスト「読込完了」 alert あれば dismiss + 全件 完了 signal で 即 return
        alert_text = _dismiss_alert_if_present(driver)
        if alert_text and FURIMA_ASSIST_COMPLETE_ALERT_TEXT in alert_text:
            return len(_collect_listing_urls_from_page(driver))

        current = len(_collect_listing_urls_from_page(driver))
        if current >= target_count:
            return current
        if current == last_count:
            no_progress += 1
            if no_progress >= no_progress_threshold:
                break
        else:
            no_progress = 0
        last_count = current
        # button click を優先試行、 失敗時のみ scroll
        clicked = _click_load_more_if_exists(driver)
        if clicked:
            # フリマアシスト は 1 click で内部連続 fetch (= 30 → 60 → 90 → 120 → 150)、
            # listing 数が増え続ける間 wait 継続。 増加停止 or 完了 alert で次の iteration へ。
            inner_last = current
            inner_no_progress = 0
            for j in range(30):  # 最大 30 * interval = 75s wait
                time.sleep(interval)
                # alert check
                alert_text = _dismiss_alert_if_present(driver)
                if alert_text and FURIMA_ASSIST_COMPLETE_ALERT_TEXT in alert_text:
                    return len(_collect_listing_urls_from_page(driver))
                new_count = len(_collect_listing_urls_from_page(driver))
                if new_count >= target_count:
                    return new_count
                if new_count > inner_last:
                    inner_last = new_count
                    inner_no_progress = 0
                else:
                    inner_no_progress += 1
                    if inner_no_progress >= 3:
                        # 3 iteration (= ~7.5s) 増えなくなった → fetch 完了
                        break
        else:
            try:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            except Exception:
                pass
            time.sleep(interval)
    # 最終 alert dismiss + listing 数
    _dismiss_alert_if_present(driver)
    return len(_collect_listing_urls_from_page(driver))


# 後方互換: 既存呼出 (= _scroll_until_enough) は _load_until_enough の alias
_scroll_until_enough = _load_until_enough


def _wait_for_manual_load(
    driver,
    poll_interval: float = DEFAULT_MANUAL_WAIT_POLL_SEC,
    stable_sec: float = DEFAULT_MANUAL_WAIT_STABLE_SEC,
    max_wait_sec: int = DEFAULT_MANUAL_WAIT_MAX_SEC,
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> int:
    """user の手動 「もっと見る (N)」 click 完了を待つ.

    listing 数を polling し、 連続 `stable_sec` 秒 増加しなければ
    user click 完了とみなして scrape 開始。
    最大 `max_wait_sec` 秒で打切 (= timeout)。

    progress_callback(count, msg): GUI 進捗表示用 (optional)。

    Returns: 最終 listing 数
    """
    elapsed = 0.0
    last_count = len(_collect_listing_urls_from_page(driver))
    last_change_time = elapsed
    if progress_callback:
        progress_callback(last_count, f"初期 {last_count} 件、 user click 待機開始")

    while elapsed < max_wait_sec:
        time.sleep(poll_interval)
        elapsed += poll_interval
        # alert dismiss (= フリマアシスト 「読込完了」 alert があれば accept)
        _dismiss_alert_if_present(driver)
        current = len(_collect_listing_urls_from_page(driver))
        if current > last_count:
            last_count = current
            last_change_time = elapsed
            if progress_callback:
                progress_callback(current, f"{current} 件 (user click 検出)")
        else:
            # 増えてない時間
            stable_elapsed = elapsed - last_change_time
            if stable_elapsed >= stable_sec:
                if progress_callback:
                    progress_callback(current, f"{current} 件で {stable_sec:.0f}s 安定、 完了とみなす")
                return current
    if progress_callback:
        progress_callback(last_count, f"{max_wait_sec}s timeout、 {last_count} 件で打切")
    return last_count


def collect_seller_listing_urls(
    seller_id: str,
    driver=None,
    headless: bool = False,
    user_limit: Optional[int] = DEFAULT_USER_LIMIT,
    max_scrolls: int = DEFAULT_LOAD_MORE_SCROLLS,
    initial_wait_sec: int = DEFAULT_INITIAL_PROFILE_WAIT_SEC,
    wait_for_manual_load: bool = False,
    manual_wait_stable_sec: float = DEFAULT_MANUAL_WAIT_STABLE_SEC,
    manual_wait_max_sec: int = DEFAULT_MANUAL_WAIT_MAX_SEC,
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> dict:
    """seller profile page から listing URL 一覧取得.

    Returns:
        {
            "seller_id": str,
            "urls": list[str],  # = 取得 listing URL (= /item/m\\d+ 正規化済)
            "effective_cap": int,  # = min(user_limit, HARD_CAP_PER_SESSION)
            "cap_hit": bool,  # = ハード CAP に到達したか
            "total_seen": int,  # = scroll で見えた listing 全件数 (= CAP 切り捨て前)
        }
    """
    own_driver = driver is None
    if own_driver:
        driver = create_driver(headless=headless)
    try:
        effective_cap = resolve_effective_cap(user_limit)
        profile_url = build_seller_profile_url(seller_id)
        driver.get(profile_url)
        # 5/26 fix (= HQ 推奨 A 案): GUI subprocess 経由で chrome が background 化すると
        # メルカリ profile page の lazy load トリガーが発火しない問題対策。
        # window.focus() + maximize_window() で chrome を強制 active 化、
        # render 計算 + scroll event を foreground 条件に近づける。
        try:
            driver.maximize_window()
        except Exception:
            pass
        try:
            driver.execute_script("window.focus();")
        except Exception:
            pass
        # 初期 hydration 待機 (= profile page は重め、 5/26 fix で 12s → 18s 延長)
        time.sleep(max(initial_wait_sec, DEFAULT_INITIAL_PROFILE_WAIT_SEC))
        if wait_for_manual_load:
            # user 手動「もっと見る (5)」 click 完了待ち mode
            # (= 自動 click の不安定問題回避、 user が手動で全件展開してから scrape)
            total_seen = _wait_for_manual_load(
                driver,
                stable_sec=manual_wait_stable_sec,
                max_wait_sec=manual_wait_max_sec,
                progress_callback=progress_callback,
            )
        else:
            # CAP + 1 件取れるまで「もっとみる」 button click + scroll fallback
            # (= CAP 到達判定のため 1 件余分に取得を試みる)
            total_seen = _load_until_enough(
                driver,
                target_count=effective_cap + 1,
                max_iterations=max_scrolls,
            )
        all_urls = _collect_listing_urls_from_page(driver)
        cap_hit = total_seen > effective_cap
        return {
            "seller_id": seller_id,
            "urls": all_urls[:effective_cap],
            "effective_cap": effective_cap,
            "cap_hit": cap_hit,
            "total_seen": total_seen,
        }
    finally:
        if own_driver:
            try:
                driver.quit()
            except Exception:
                pass


# ============================================================================
# 詳細取得 + SOLD 除外
# ============================================================================
def collect_seller_with_details(
    seller_id: str,
    driver=None,
    headless: bool = False,
    user_limit: Optional[int] = DEFAULT_USER_LIMIT,
    max_scrolls: int = DEFAULT_LOAD_MORE_SCROLLS,
    initial_wait_sec: int = DEFAULT_INITIAL_PROFILE_WAIT_SEC,
    exclude_sold: bool = True,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    wait_for_manual_load: bool = False,
    manual_wait_stable_sec: float = DEFAULT_MANUAL_WAIT_STABLE_SEC,
    manual_wait_max_sec: int = DEFAULT_MANUAL_WAIT_MAX_SEC,
    manual_progress_callback: Optional[Callable[[int, str], None]] = None,
) -> dict:
    """seller listing 全件 + 詳細 (title/price/image/condition/in_stock) を取得.

    Returns:
        {
            "seller_id": str,
            "items": list[dict],  # = 詳細付き item dict list (mercari_likes と同 schema)
            "effective_cap": int,
            "cap_hit": bool,
            "total_seen": int,
            "skipped_sold": int,  # = SOLD 除外で skip した件数
            "skipped_detail_failed": int,  # = 詳細取得 fail で skip した件数 (現状: 含める方針)
        }
    """
    from scrapers import mercari_item_detail  # noqa: PLC0415

    own_driver = driver is None
    if own_driver:
        driver = create_driver(headless=headless)
    try:
        url_result = collect_seller_listing_urls(
            seller_id=seller_id,
            driver=driver,
            headless=headless,
            user_limit=user_limit,
            max_scrolls=max_scrolls,
            initial_wait_sec=initial_wait_sec,
            wait_for_manual_load=wait_for_manual_load,
            manual_wait_stable_sec=manual_wait_stable_sec,
            manual_wait_max_sec=manual_wait_max_sec,
            progress_callback=manual_progress_callback,
        )
        urls = url_result["urls"]
        items: list[dict] = []
        skipped_sold = 0
        skipped_detail_failed = 0
        total = len(urls)
        for i, url in enumerate(urls, start=1):
            if progress_callback:
                try:
                    progress_callback(i, total, url)
                except Exception:
                    pass
            detail = mercari_item_detail.fetch_detail(driver, url)
            if detail is None:
                # 取得失敗 → mercari_likes と同パターンで空欄で含める (推測で埋めない)
                merged = {
                    "url": url,
                    "item_id": parse_item_id(url),
                    "title": "",
                    "price_jpy": None,
                    "condition": "",
                    "description": "",
                    "image_urls": [],
                    "in_stock": None,
                    "status": "UNKNOWN",
                }
                skipped_detail_failed += 1
            else:
                merged = {"url": url, "item_id": parse_item_id(url), **detail}

            # SOLD 除外 (= in_stock=False のみ skip、 None=不明 は安全側で含める)
            if exclude_sold and merged.get("in_stock") is False:
                skipped_sold += 1
                continue
            items.append(merged)
        return {
            "seller_id": seller_id,
            "items": items,
            "effective_cap": url_result["effective_cap"],
            "cap_hit": url_result["cap_hit"],
            "total_seen": url_result["total_seen"],
            "skipped_sold": skipped_sold,
            "skipped_detail_failed": skipped_detail_failed,
        }
    finally:
        if own_driver:
            try:
                driver.quit()
            except Exception:
                pass


# ============================================================================
# card_id group 化 (= 案 D、 同 card_id 主 + 補)
# ============================================================================
def pick_card_image_url(image_urls: list[str]) -> Optional[str]:
    """画像 URL list から「カード本体画像」 と思われるものを選択.

    メルカリ商品 page から取得した image_urls は **プロフィール画像が先頭に入る** ケース
    があるため、 単純に [0] を採用すると Vision が誤判定する (= 「これはユーザーアバター
    です」 NONE 返却)。 以下の優先順で 商品本体画像 を選ぶ:

      1. URL に `/item/detail/` を含むもの (= 確実に商品画像)
      2. URL に `/item/` を含むもの (= 商品系画像、 thumb 等)
      3. `/thumb/members/` 以外の何か (= プロフィール画像でない、 best effort)
      4. それ以外 (= 全部プロフィール画像) → None

    Returns: 候補 URL (= str) または None
    """
    if not image_urls:
        return None
    valid = [u for u in image_urls if isinstance(u, str) and u]
    if not valid:
        return None
    # 第一優先: /item/detail/
    for url in valid:
        if "/item/detail/" in url:
            return url
    # 第二優先: /item/
    for url in valid:
        if "/item/" in url:
            return url
    # 第三優先: /thumb/members/ 以外 (= プロフィール画像でない)
    for url in valid:
        if "/thumb/members/" not in url:
            return url
    # 全部プロフィール画像 → None (= Vision 呼出さない)
    return None


def _resolve_card_id_for_item(
    item: dict,
    use_vision: bool = False,
    vision_stats: Optional[dict] = None,
) -> Optional[str]:
    """1 item に対し card_id を確定 (= title 抽出 + Vision 合議).

    Args:
        use_vision: True で Vision API による画像認識を併用 (= title が取れなくても
            画像から取得を試みる、 title 取れた場合も Vision で 二重確認 + 不一致時 Vision 優先)
        vision_stats: 統計用 dict (任意):
            - "vision_calls": Vision API 呼出数
            - "vision_hits": Vision で card_id 取れた数
            - "title_vs_vision_disagree": title と Vision で 一致しなかった数

    Returns: card_id (= "OP01-001" 等 大文字) or None
    """
    title = (item.get("title") or "").strip()
    title_card_id = extract_tcg_card_id(title) if title else None
    if not use_vision:
        return title_card_id

    # Vision 補強 (= カード本体画像を Claude Haiku Vision で識別、
    # プロフィール画像 / 不適切画像 は pick_card_image_url で除外)
    image_urls = item.get("image_urls") or []
    image_url = pick_card_image_url(image_urls) or ""
    vision_card_id = ""
    if image_url:
        if vision_stats is not None:
            vision_stats["vision_calls"] = vision_stats.get("vision_calls", 0) + 1
        vision_card_id = judge_card_id_from_image_url(image_url)
        if vision_card_id and vision_stats is not None:
            vision_stats["vision_hits"] = vision_stats.get("vision_hits", 0) + 1
    if vision_stats is not None and title_card_id and vision_card_id and title_card_id.upper() != vision_card_id.upper():
        vision_stats["title_vs_vision_disagree"] = vision_stats.get("title_vs_vision_disagree", 0) + 1

    resolved = reconcile_title_and_vision(title_card_id or "", vision_card_id)
    return resolved or None


def group_items_by_card_id(
    items: list[dict],
    use_vision: bool = False,
    vision_stats: Optional[dict] = None,
) -> list[dict]:
    """items を card_id (= title 抽出 + 任意で Vision 合議) でグループ化、 各 group を 1 row に変換.

    Args:
        use_vision: True で Vision API による画像 card_id 認識を併用 (Phase 2)
        vision_stats: Vision 統計を入れる dict (= "vision_calls"/"vision_hits"/
            "title_vs_vision_disagree" keys)

    各 row dict:
      - card_id 取れた group: 主 (= 最安) + auxiliary_urls (= 残り 価格昇順、 最大 5 件)
      - card_id 取れなかった item: 単独 row (= auxiliary_urls なし)

    入力 items は collect_seller_with_details の "items" 想定 (= mercari_likes 同 schema)。

    Returns: list[dict] (= sheet_writer に渡せる形、 auxiliary_urls 含む)
    """
    # 1) card_id でグループ化、 card_id 取れない item は None キーに集める
    groups: dict[Optional[str], list[dict]] = {}
    for item in items:
        card_id = _resolve_card_id_for_item(item, use_vision=use_vision, vision_stats=vision_stats)
        groups.setdefault(card_id, []).append(item)

    # 2) 各 group を 1 row に変換
    result: list[dict] = []
    for card_id, group_items in groups.items():
        if card_id is None:
            # card_id 取れなかった item は単独 row (= group 化しない)
            for item in group_items:
                result.append(dict(item))
            continue
        # card_id 取れた group: 価格昇順でソート、 主 = 最安、 補 = 残り
        # price_jpy=None (= 詳細取得失敗) は最後に回す (= sort 安定化)
        def _price_key(it):
            p = it.get("price_jpy")
            return (0, p) if isinstance(p, int) else (1, 0)
        sorted_group = sorted(group_items, key=_price_key)
        main = sorted_group[0]
        aux_items = sorted_group[1:5]  # 最大 4 件 (= AD-AG の 4 列分、 AC は主が入る想定)
        # ただし sheet_writer._build_row は AC-AG (= 5 列) に auxiliary を入れる仕様
        # 主が A 列、 auxiliary が AC-AG に入る = main 自体は aux に含めない、 aux は最大 5 件まで OK
        aux_items = sorted_group[1:6]  # = 最大 5 件 (= AC-AG 5 列)
        main_row = dict(main)
        main_row["auxiliary_urls"] = [it["url"] for it in aux_items if it.get("url")]
        result.append(main_row)
    return result
