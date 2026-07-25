"""snkrdunk_scraper - スニダン (SNKRDUNK) PSA10 中古 商品在庫 scraper.

5/17 commit (Phase 1): iMakTCG 補仕入元拡充の一環、PSA10 TCG 在庫監視。
HTTP-only (Selenium 不要)、JSON-LD parse で完結。

対象 URL 形式:
  https://snkrdunk.com/apparels/{model_id}/used/{instance_id}
  (= PSA10 鑑定済 1 個体 出品 page)

判定 logic (★2026-07-25 改訂: snkrdunk CSR 化対応 + fail-closed 厳格化):
  - HTTP 404 → 削除/売却確定 (status=DELETED, in_stock=False) ← 信頼できる sold 信号
  - RSC ペイロード `"isSoldOut":true`  → SOLD_OUT (in_stock=False)
  - RSC ペイロード `"isSoldOut":false` → IN_STOCK (in_stock=True)
  - (legacy) JSON-LD availability InStock / HTML app div class sold → IN_STOCK / SOLD_OUT
  - どの信号でも確定できない → **status=UNKNOWN, in_stock=None (判定不能)**
    ★ 旧実装は in_stock=False に潰していたため、CSR 化で jsonld Product 消滅 → 全件「判定不能」が
      「売切確定(is_sold=True)」に化け、偽取下げ/偽消込を量産した (2026-07-25 発覚)。None のまま返し
      monitor 側で is_sold=None (uncertain→skip) に倒す = fail-closed (Precision 100%)。
  - 注意: CSR 化で isSoldOut は初期 HTML に安定して来ない → requests では取りこぼしが多く UNKNOWN 多発。
    確実な自動判定復旧には Selenium 描画 or 公式 API 特定が必要 (別タスク)。当面は uncertain を
    「要手動chk」で顕在化させ、偽取下げは出さない安全側に倒す。

仕入元特性:
  - 1 URL = 1 個体 (variation なし、size/color 無関係)
  - 売れた瞬間に 404 → AC-AG 中の他 URL で listing 維持 (= 既存 ichibankuji pattern)
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from typing import Optional

import requests

# ── snkrdunk sold 検知の API 復旧 (2026-07-25) ──────────────────────────────
# snkrdunk 商品ページが CSR 化しページ scrape sold 検知が壊れた (偽sold量産→偽取下げ/偽消込) 対策。
# HQ の CSR非依存 helper `is_listing_live(url)` を流用 (used-listings API の listing_id 突合で
# True=live / False=sold / None=API失敗or非対象=uncertain)。commit iMakHQ 42a5064、self-contained
# (requests のみ依存)。監視くんは絶対パスで遅延 import、利用不能時は既存 requests パスに安全フォールバック。
_HQ_TOOLS_PATH = r"C:\dev\iMak\iMakHQ\tools"
_LIVE_CACHE: dict = {}   # url → True/False/None (cycle 内重複 API 抑制、run_cycle 単位でプロセスは使い捨て)


def _hq_is_listing_live(url: str):
    """HQ `is_listing_live` を遅延 import で呼ぶ。利用不能/例外なら None (= 既存 fail-closed へ)。"""
    if url in _LIVE_CACHE:
        return _LIVE_CACHE[url]
    result = None
    try:
        if _HQ_TOOLS_PATH not in sys.path:
            sys.path.insert(0, _HQ_TOOLS_PATH)
        from snkrdunk_psa_resource import is_listing_live  # noqa: PLC0415
        result = is_listing_live(url)
    except Exception:
        result = None
    _LIVE_CACHE[url] = result
    return result


_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/136.0.0.0 Safari/537.36"),
    "Accept-Language": "ja-JP,ja;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
_TIMEOUT_SEC = 15

_PRODUCT_URL_RE = re.compile(r"snkrdunk\.com/apparels/(\d+)/used/(\d+)")


def parse_product_id(url: str) -> Optional[str]:
    """URL から (model_id, instance_id) 抽出 → "model:instance" 形式 product_id 返却.

    例: https://snkrdunk.com/apparels/159278/used/45538280 → "159278:45538280"
    """
    if not url:
        return None
    m = _PRODUCT_URL_RE.search(url)
    if not m:
        return None
    return f"{m.group(1)}:{m.group(2)}"


def _extract_jsonld_product(html: str) -> Optional[dict]:
    """HTML 内の application/ld+json から @type=Product を抽出."""
    for m in re.finditer(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.+?)</script>',
        html, re.S | re.I,
    ):
        try:
            data = json.loads(m.group(1))
        except Exception:
            continue
        # 単一 dict or list の可能性
        candidates = data if isinstance(data, list) else [data]
        for c in candidates:
            if isinstance(c, dict) and c.get("@type") == "Product":
                return c
            # @graph 内 product
            if isinstance(c, dict) and "@graph" in c:
                for g in c.get("@graph", []):
                    if isinstance(g, dict) and g.get("@type") == "Product":
                        return g
    return None


def _extract_is_sold_out(html: str, url: str):
    """RSC ペイロード内の当該 instanceId に紐づく isSoldOut を抽出.

    ★ 2026-07-25: snkrdunk が CSR 化し jsonld から Product が消滅・旧 sold 信号(app div class)も消滅。
      在庫状態は Next.js RSC ペイロードの `{"id":<iid>,...,"isSoldOut":true|false}` にのみ残る。
      同一 object 内 (id と isSoldOut の間に別 object 境界 {} を挟まない) の一致のみ採用 =
      隣接 object の誤取得を防ぐ。見つからなければ None (= 判定不能、fail-closed で uncertain)。

    Returns: True (売切) / False (在庫あり) / None (判定不能)。
    """
    pid = parse_product_id(url) or ""
    iid = pid.split(":")[-1] if ":" in pid else pid
    if not iid or not iid.isdigit():
        return None
    # {"id":IID ... "isSoldOut":X}  (同一 object = 間に {} 境界なし)
    m = re.search(r'"id":' + iid + r'\b[^{}]*?"isSoldOut":(true|false)', html)
    if not m:
        m = re.search(r'"isSoldOut":(true|false)[^{}]*?"id":' + iid + r'\b', html)
    if m:
        return m.group(1) == "true"
    return None


def _fetch_via_requests(url: str) -> dict:
    """requests で fetch、status + 在庫情報 dict を返却."""
    # ★ 2026-07-25 fail-closed 修正: in_stock 既定を None (判定不能) に。
    #   旧実装は既定 False → 判定不能(jsonld_missing 等)が「売切確定(is_sold=True)」に化け、
    #   偽取下げ・偽消込を量産した (snkrdunk CSR 化で jsonld Product 消滅が発端)。
    #   True/False は POSITIVE な信号でのみ設定し、確証なきは None のまま返す。
    out = {"http_status": None, "in_stock": None, "name": "", "price_jpy": None,
           "_reason": "unknown"}
    try:
        r = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT_SEC, allow_redirects=True)
    except Exception as e:
        out["_reason"] = f"http_error:{type(e).__name__}"
        return out

    out["http_status"] = r.status_code
    if r.status_code == 404:
        # 404 = 出品削除 = 売却/取下げ確定 (信頼できる sold 信号)
        out["in_stock"] = False
        out["_reason"] = "http_404"
        return out
    if r.status_code != 200:
        out["_reason"] = f"http_{r.status_code}"   # in_stock=None (判定不能)
        return out

    # ① RSC ペイロードの isSoldOut (CSR 化後の唯一の在庫信号、在れば positive)
    iso = _extract_is_sold_out(r.text, url)
    if iso is True:
        out["in_stock"] = False
        out["_reason"] = "rsc_sold_out"
        return out
    if iso is False:
        out["in_stock"] = True
        out["_reason"] = "rsc_in_stock"
        return out

    # ② legacy: jsonld Product の availability / HTML app div class sold (現行 snkrdunk では通常不在)
    product = _extract_jsonld_product(r.text)
    if product:
        out["name"] = product.get("name", "")
        offers = product.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        out["price_jpy"] = offers.get("price") if offers else None
        availability = (offers.get("availability") or "") if isinstance(offers, dict) else ""
        html_sold = bool(re.search(
            r'<div\s+id=["\']app["\'][^>]*class=["\'][^"\']*\bsold\b[^"\']*["\']',
            r.text, re.I,
        ))
        if html_sold:
            out["in_stock"] = False
            out["_reason"] = "html_class_sold"
            return out
        if "InStock" in availability:
            out["in_stock"] = True
            out["_reason"] = "instock"
            return out
        # availability が明示的に sold 系 (OutOfStock/SoldOut) → positive sold
        if availability and ("OutOfStock" in availability or "SoldOut" in availability):
            out["in_stock"] = False
            out["_reason"] = f"availability:{availability.split('/')[-1]}"
            return out

    # ③ どの信号でも確定できない → 判定不能 (in_stock=None のまま = fail-closed で uncertain→skip)
    out["_reason"] = "undetermined_csr"
    return out


def fetch_product_inventory(
    url: str,
    use_selenium_fallback: bool = False,   # 互換: 未使用 (snkrdunk は HTTP-only)
    max_retries: int = 3,
) -> Optional[dict]:
    """スニダン 商品 URL → uniqlo/fril scraper と契約互換の dict.

    Returns: {
        "name": str, "product_id": "<model>:<instance>", "color": "",
        "status": "IN_STOCK"/"SOLD_OUT"/"DELETED"/"UNKNOWN",
        "fetched_at": iso8601,
        "skus": [{"size": "", "in_stock": bool, "quantity": 0 or 1, "price_jpy": int or None}]
    } or None on fetch failure.
    """
    pid = parse_product_id(url) or ""

    # ★ 2026-07-25 API 復旧: HQ の is_listing_live を PRIMARY 判定に (CSR非依存・positive信号)。
    #   True=live→IN_STOCK / False=sold→SOLD_OUT (= 消込を snkrdunk でも正しく発火) / None→既存 requests
    #   パス (404/isSoldOut/uncertain) にフォールバック。helper 利用不能でも既存挙動で安全。
    live = _hq_is_listing_live(url)
    if live is True or live is False:
        return {
            "name": "", "product_id": pid, "color": "",
            "status": "IN_STOCK" if live else "SOLD_OUT",
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "skus": [{"size": "", "in_stock": live,
                      "quantity": 1 if live else 0, "price_jpy": None}],
        }
    # live is None → 従来の requests 経路へフォールバック (404 は依然 reliable sold 信号)

    # 接続例外リトライ (2026-06-11): cycle 中は snkrdunk を大量に叩くため (多数行 × 各最大6候補)、
    # rate-limit/接続瞬断で requests.get が例外→http_status=None→None を返し、 monitor 側で
    # 「uncertain: N/M candidates errored」 の誤アラートになる (= fril と同型、 在庫ある補欠候補が
    # transient で落ちると「在庫あるのに uncertain」 になり履行不能の見落とし誤認を招く)。
    # http_status=None (= 接続例外) のときのみ間隔 (2/4/6s) を空けて再取得する。 404/sold/in_stock
    # の確定結果 (http_status が立つ) は即採用 (= retry しない)。
    raw = _fetch_via_requests(url)
    for attempt in range(max_retries):
        if raw["http_status"] is not None:
            break
        time.sleep(2 * (attempt + 1))  # 2,4,6s: rate-limit 回避間隔
        raw = _fetch_via_requests(url)
    if raw["http_status"] is None:
        return None  # 通信失敗 (retry 全滅)

    reason = raw.get("_reason", "")
    # ★ 2026-07-25 fail-closed: in_stock は None(判定不能)/True/False の 3 値。
    #   None を bool() で False に潰すと「判定不能→売切確定」の偽 sold になる (今回の bug 根本) →
    #   None のまま skus に載せ、 monitor 側で is_sold=None (uncertain→skip) に倒す。
    raw_in_stock = raw.get("in_stock")   # None / True / False

    if reason == "http_404":
        status = "DELETED"
        raw_in_stock = False             # 削除=売却確定
    elif raw_in_stock is True:
        status = "IN_STOCK"
    elif raw_in_stock is False:
        # POSITIVE な sold 信号 (rsc_sold_out / html_class_sold) のみここに来る
        status = "SOLD_OUT"
    else:
        # 判定不能 (undetermined_csr / jsonld_missing / http_5xx 等) → UNKNOWN、in_stock=None 維持
        status = "UNKNOWN"
        raw_in_stock = None

    try:
        price = int(raw.get("price_jpy")) if raw.get("price_jpy") is not None else None
    except (TypeError, ValueError):
        price = None

    return {
        "name": raw.get("name", ""),
        "product_id": pid,
        "color": "",
        "status": status,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "skus": [
            {
                "size": "",
                "in_stock": raw_in_stock,   # None=判定不能 (monitor が is_sold=None=uncertain に倒す)
                "quantity": 1 if raw_in_stock else 0,
                "price_jpy": price,
            }
        ],
    }


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    test_url = sys.argv[1] if len(sys.argv) > 1 else \
        "https://snkrdunk.com/apparels/159278/used/45538280"
    print(f"--- snkrdunk scrape: {test_url} ---")
    info = fetch_product_inventory(test_url)
    if info is None:
        print("  [!] 通信失敗 (None)")
        sys.exit(1)
    print(f"  Name:     {info['name'][:60]}")
    print(f"  Pid:      {info['product_id']}")
    print(f"  Status:   {info['status']}")
    print(f"  InStock:  {info['skus'][0]['in_stock']}")
    print(f"  Price:    ¥{info['skus'][0]['price_jpy']}")
