"""snkrdunk_op_catalog - スニダン ワンピース PSA10 カタログ全件抽出 (Phase 2).

既存 snkrdunk_official.py は「iMakTCG 出品済カードの補仕入 URL lookup」(card単位)。
本モジュールは逆に **スニダンのワンピ PSA10 を catalog 横断で全件列挙・抽出** する。

判明 API (2026-06-12 調査、 [[snkrdunk_op_psa10_extraction]]):
  - model 詳細: GET /v1/apparels/{id} → name / productNumber(=OP02-059 等)
  - 出品一覧 : GET /v1/apparels/{id}/used?page=N&perPage=30 → apparelUsedItems
      (★ perPage 必須。 各 item: displayShortConditionTitle / price / status(0=出品中))
  - 列挙     : 検索結果ページ (CSR) を Selenium で DOM scrape → /apparels/<model_id> リンク
      → productNumber が OP/ST/EB/P のものだけ残す (= One Piece 限定、 fail-closed)

PSA10 + price<cap + status==0 のみ採用 (= 既存 is_psa10_on_sale 流用)。
"""
from __future__ import annotations

import re
import time
from typing import Optional

import requests

from scrapers import snkrdunk_official as SO

# One Piece TCG の productNumber pattern (= OP/ST/EB 本弾 + P プロモ)。
# Pokemon は "pkmn-tcg-*" なので確実に弾ける (= fail-closed One Piece 判定)。
ONE_PIECE_PN_RE = re.compile(r"^(?:OP|ST|EB|PRB)\d{2}-\d{3}$|^P-\d{3}$", re.IGNORECASE)

DEFAULT_PRICE_CAP = 100000  # 10万円
USED_PER_PAGE = 30
USED_MAX_PAGES = 20  # 1 model あたり最大 600 出品まで (= 安全上限)
RATE_SEC = 0.4


def create_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(SO.DEFAULT_HEADERS)
    return s


def _get_with_retry(session: requests.Session, url: str, params: dict | None = None,
                    retries: int = 3) -> Optional[requests.Response]:
    """GET with retry (= DNS/接続の一過性失敗で model を静かに脱落させない fail-closed)."""
    for attempt in range(retries):
        try:
            r = session.get(url, params=params, timeout=SO.TIMEOUT_SEC)
            return r
        except Exception:
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    return None


def is_one_piece_pn(product_number: Optional[str]) -> bool:
    """productNumber が One Piece (OP/ST/EB/PRB/P) かを判定 (= 他TCG除外)."""
    return bool(product_number) and bool(ONE_PIECE_PN_RE.match(product_number.strip()))


def fetch_model_detail(session: requests.Session, model_id: int | str) -> Optional[dict]:
    """GET /v1/apparels/{id} → {id, name, productNumber, ...}。 失敗時 None."""
    url = SO.APPAREL_API_TEMPLATE.format(model_id=model_id)
    r = _get_with_retry(session, url)
    if r is None or r.status_code != 200:
        return None
    try:
        return r.json()
    except Exception:
        return None


def fetch_used_items(session: requests.Session, model_id: int | str) -> list[dict]:
    """GET /v1/apparels/{id}/used を全頁取得 → apparelUsedItems list (= 全 condition 含む)."""
    items: list[dict] = []
    base = f"{SO.SNKRDUNK_BASE}/v1/apparels/{model_id}/used"
    for page in range(1, USED_MAX_PAGES + 1):
        r = _get_with_retry(session, base, params={"page": page, "perPage": USED_PER_PAGE})
        if r is None or r.status_code != 200:
            break
        try:
            chunk = r.json().get("apparelUsedItems", [])
        except Exception:
            break
        if not chunk:
            break
        items.extend(chunk)
        if len(chunk) < USED_PER_PAGE:
            break
        time.sleep(RATE_SEC)
    return items


def extract_psa10_under(
    session: requests.Session, model_id: int | str, price_cap: int | None = None,
) -> list[dict]:
    """1 model の PSA10 + 出品中 の出品を price 昇順で返す.

    price_cap=None (既定) なら価格上限なし (= 販売中の PSA10 を全部。 価格はスプシ後処理)。
    price_cap に数値を渡すと price<cap のみ。

    Returns: [{"instance_id": int, "price": int, "url": str}, ...]
    """
    out: list[dict] = []
    for it in fetch_used_items(session, model_id):
        if not SO.is_psa10_on_sale(it):  # status==0 AND displayShortConditionTitle=="PSA10"
            continue
        price = it.get("price")
        if not isinstance(price, int):
            continue
        if price_cap is not None and price >= price_cap:
            continue
        inst = it.get("id")
        out.append({
            "instance_id": inst,
            "price": price,
            "url": SO.build_apparel_used_url(int(model_id), int(inst)),
        })
    out.sort(key=lambda x: x["price"])
    return out


# ============================================================================
# Selenium: One Piece model_id 列挙 (= 検索結果 DOM scrape)
# ============================================================================

_APPAREL_LINK_RE = re.compile(r"/apparels/(\d+)")


def _scrape_model_ids_on_page(driver) -> list[str]:
    """現在表示中の検索結果ページから /apparels/<model_id> を全抽出 (scroll 込み)."""
    for _ in range(4):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1.5)
    hrefs = driver.execute_script(
        "return Array.from(document.querySelectorAll('a[href*=\"/apparels/\"]'))"
        ".map(a => a.getAttribute('href'))"
    ) or []
    ids: list[str] = []
    seen: set[str] = set()
    for h in hrefs:
        m = _APPAREL_LINK_RE.search(h or "")
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            ids.append(m.group(1))
    return ids


def enumerate_candidate_model_ids(
    driver, keyword: str = "ワンピース　PSA10", brand_ids: str = "onepiece",
    sale_only: bool = True, max_pages: int = 40,
) -> list[str]:
    """SNKRDUNK 検索を頁送りして model_id を収集 (= One Piece 販売中 PSA10 を網羅).

    ★ 正しいパラメータ (2026-06-14 user 提供 URL):
      `/search?keywords=<kw>&brandIds=onepiece&isSaleOnly=true&page=N`
      (= keyword/brandId 単数は無視される罠。 複数形 keywords/brandIds + isSaleOnly が効く)
    brandIds=onepiece で One Piece 限定、 isSaleOnly=true で販売中のみ。
    返り値は念のため呼び出し側で productNumber が One Piece か再判定する (fail-closed)。
    """
    from urllib.parse import quote  # noqa: PLC0415

    collected: list[str] = []
    seen: set[str] = set()
    empty_streak = 0
    for page in range(1, max_pages + 1):
        url = (f"{SO.SNKRDUNK_BASE}/search?keywords={quote(keyword)}"
               f"&brandIds={brand_ids}"
               f"&isSaleOnly={'true' if sale_only else 'false'}&page={page}")
        try:
            driver.get(url)
            time.sleep(6)
            ids = _scrape_model_ids_on_page(driver)
        except Exception as e:
            # driver/chrome 死亡 (= 接続拒否等)。 全体を落とさず収集済で打ち切る (fail-safe)。
            print(f"  [enum] page{page} 失敗 → 収集済 {len(collected)} 件で打切: "
                  f"{type(e).__name__}", flush=True)
            break
        new = [i for i in ids if i not in seen]
        for i in new:
            seen.add(i)
            collected.append(i)
        print(f"  [enum] page{page}: +{len(new)} (累計 {len(collected)})", flush=True)
        if not new:
            empty_streak += 1
            if empty_streak >= 2:
                break
        else:
            empty_streak = 0
    return collected
