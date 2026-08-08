"""graniph_scraper - graniph 商品ページの在庫・価格スクレイパー (独立モジュール).

設計原則:
  - 既存モジュール (iMakeBayAPI / iMakInventory / 他プロジェクト) を一切 import しない
  - requests + 標準ライブラリのみで完結 (Selenium 不要、HTML 内 embedded JSON を parse)
  - 失敗時は例外送出、呼出側で fail-closed ハンドリング

データ取得元 (JSON-LD だけを見ない):
  - JSON-LD `ProductGroup.name` / `.color`  → 商品名・色
  - HTML 内 `const stocks = {...}`           → SKU 単位の実在庫数 (real_quantity)
  - HTML 内 `const priceData = {...}`        → SKU 単位の 定価 / sale_flg / sale_price
  - `<label class="in-stock|few|soldout">`   → UI 表示 stock_label (在庫あり/残り3点/在庫なし)

注意 (2026-08-08 窓口 [IMPLEMENT-GO] 起票時に明示):
  - HTML 全体の文字列 grep は禁止。全サイズ売切でもページ末尾の JS テンプレ
    (`stock_status: hasStock ? '在庫あり' : ...`) が "在庫あり" を1回ヒットさせる
  - `LimitedAvailability` (label class `few`) は「残りN点」= 在庫あり。quantity > 0 で判定
  - sku_code は 14桁の正規値 (商品12桁 + サイズ2桁)。合成禁止 (canonical KEY 遵守)
  - 他色は sitemap 経由でのみ取れる。連番推測は 404
  - 前段に AWS CloudFront がいる。pacing 0.5〜1s 推奨
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _http_util import get_with_retry  # noqa: E402


DEFAULT_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0.0.0 Safari/537.36"),
    "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.8",
}
TIMEOUT_SEC = 15

# CloudFront が前段にいる (2026-08-08 窓口実測: Via: cloudfront)。pacing 必須。
# env override 可 (unit test は 0 秒で高速化)
PACING_SEC_DEFAULT = 0.8


def _pacing_sec() -> float:
    v = os.environ.get("GRANIPH_PACING_SEC")
    try:
        return float(v) if v is not None else PACING_SEC_DEFAULT
    except ValueError:
        return PACING_SEC_DEFAULT


# ============================================================================
# 仕入送料 (2026-08-08 窓口 [IMPLEMENT-GO] 追加)
# ============================================================================
# 公式 https://www.graniph.com/guide/guide-delivery より (2026-08-08 実取得):
#   「送料について 全国一律440円（税込）です。
#    ※1回の配送で商品代金とギフトバッグ料金の合計金額が5,000円（税込）以上の場合、
#      送料無料となります。」
# graniph は実店舗が近くにない → 必ず通販で仕入れる → 送料が毎回仕入コストに乗る。
#
# 相互参照: 出品側 `iMakMercari/graniph_csv_builder.py` にも同じ +440 規則が入る。
# 片方だけ直る事故を防ぐため、両方を同じ定数・同じ関数で管理すること。
PROCUREMENT_SHIPPING_JPY = 440       # 全国一律 (税込)
FREE_SHIPPING_THRESHOLD_JPY = 5000   # 商品代金がこれ以上なら送料無料


def _procurement_shipping(item_price_jpy: int) -> int:
    """graniph 通販の仕入送料を返す (無料閾値判定は 商品代金=送料を足す前 で行う).

    ★閾値の判定は必ず「送料を足す前の商品代金」で行う。足した後で判定すると
    ¥4,999 の商品が ¥5,439 で無料判定に化ける。
    ★セール中はセール価格が商品代金 (定価ではない)。
    """
    return 0 if item_price_jpy >= FREE_SHIPPING_THRESHOLD_JPY else PROCUREMENT_SHIPPING_JPY


# ============================================================================
# URL パーサ
# ============================================================================
_ITEM_URL_RE = re.compile(r"/item-detail/(\d{12})(?:[/?#]|$)")


def parse_graniph_url(url: str) -> dict:
    """graniph 商品 URL から product_id (12桁) 抽出.

    対応 URL 例:
      https://www.graniph.com/item-detail/012000906300
      https://www.graniph.com/item-detail/012000906300/  (末尾スラッシュ)
      https://www.graniph.com/item-detail/012000906300?utm_...
    """
    if not url:
        raise ValueError("URL が空です")
    m = _ITEM_URL_RE.search(url)
    if not m:
        raise ValueError(f"graniph product_id を URL から抽出できません: {url}")
    return {"product_id": m.group(1)}


# ============================================================================
# HTML パース (fetch と分離。ユニットテスト用に純関数化)
# ============================================================================
_STOCKS_RE     = re.compile(r"const\s+stocks\s*=\s*(\{.*?\});", re.DOTALL)
_PRICE_DATA_RE = re.compile(r"const\s+priceData\s*=\s*(\{.*?\});", re.DOTALL)
_LDJSON_RE     = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
# label class="in-stock|few|soldout ..." for="<size_code>" [data-text="残りN点"]
#   <span translate="no">SS</span>
_LABEL_RE = re.compile(
    r'<label\s+class="([^"]+)"\s+for="(\d{2})"'
    r'(?:\s+data-text="([^"]*)")?'
    r'[^>]*>\s*<span\s+translate="no">([^<]+)</span>',
    re.DOTALL,
)


def _extract_product_group_ld(html: str) -> dict:
    """JSON-LD の <script> ブロック群から ProductGroup 要素を1件返す (無ければ {})."""
    for block in _LDJSON_RE.findall(html):
        text = block.strip()
        if "ProductGroup" not in text:
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        candidates = data if isinstance(data, list) else [data]
        for e in candidates:
            if isinstance(e, dict) and e.get("@type") == "ProductGroup":
                return e
    return {}


def _stock_label_from_class(cls: str, data_text: str, quantity: int) -> str:
    """label class + data-text + quantity から表示ラベル文字列を組み立てる.

    graniph UI:
      in-stock → '在庫あり'
      few      → '残りN点' (data-text にそのまま入っている)
      soldout  → '在庫なし'
    """
    cls_n = (cls or "").strip().split()[0] if cls else ""
    if cls_n == "few":
        return (data_text or f"残り{quantity}点").strip()
    if cls_n == "soldout":
        return "在庫なし"
    if cls_n == "in-stock":
        return "在庫あり"
    return cls_n or ""


def _is_sales_active(sku_info: dict, now_ms: Optional[int] = None) -> bool:
    """sku_info.status == PUBLISHED かつ 現在時刻が sales_start..sales_end 内なら True."""
    if not sku_info:
        return False
    if sku_info.get("status") != "PUBLISHED":
        return False
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    start = sku_info.get("sales_start_timestamp")
    end = sku_info.get("sales_end_timestamp")
    if isinstance(start, (int, float)) and now_ms < start:
        return False
    if isinstance(end, (int, float)) and now_ms >= end:
        return False
    return True


def parse_graniph_html(html: str, url: str, now_ms: Optional[int] = None) -> dict:
    """graniph 商品ページ HTML から SKU 一覧を抽出.

    純関数 (I/O 無し、テストしやすい). 例外は ValueError で送出。

    Returns: {
        "name":               商品名 (ProductGroup.name),
        "product_id":         URL 12桁,
        "product_group_id":   JSON-LD productGroupID (9桁、参考),
        "color":              JSON-LD color (例 "ブラウン"),
        "color_code":         sku_info.color_code (例 "300"),
        "fetched_at":         取得時刻 ISO,
        "skus": [
            {
                "size":              "SS" / "S" / "M" / "L" / "XL",
                "size_display_code": "01" / "02" / "03" / "04" / "10",
                "sku_code":          "01200090630001" (14桁 canonical KEY),
                "l2Id":              (uniqlo 互換のためエイリアス、値は sku_code と同じ),
                "communication_code":(uniqlo 互換のためエイリアス、値は sku_code と同じ),
                "in_stock":          quantity > 0,
                "stock_status":      "STOCKED" 等 (inventory_status 生値),
                "stock_label":       "在庫あり" / "残り3点" / "在庫なし",
                "quantity":          real_quantity (実数),
                "price_jpy":         priceData.price (定価),
                "promo_price_jpy":   sale_flg なら sale_price、無ければ price,
                "list_price_jpy":    priceData.price (= price_jpy と同値。sheet U 列用),
                "sales_active":      True / False,
                "color":             JSON-LD color (uniqlo と揃えるため sku 単位でも保持),
                "color_code":        sku_info.color_code,
            },
            ...
        ],
    }
    """
    info = parse_graniph_url(url)
    product_id = info["product_id"]

    sm = _STOCKS_RE.search(html)
    if not sm:
        raise ValueError(f"const stocks が見つかりません (URL={url})")
    try:
        stocks = json.loads(sm.group(1))
    except json.JSONDecodeError as e:
        raise ValueError(f"const stocks の JSON parse 失敗: {e}") from e

    pm = _PRICE_DATA_RE.search(html)
    if not pm:
        raise ValueError(f"const priceData が見つかりません (URL={url})")
    try:
        prices = json.loads(pm.group(1))
    except json.JSONDecodeError as e:
        raise ValueError(f"const priceData の JSON parse 失敗: {e}") from e

    ld = _extract_product_group_ld(html)
    name = ld.get("name", "")
    color_ld = ld.get("color", "")
    product_group_id = ld.get("productGroupID", "")

    # size_code → label class / data-text (在庫表示 UI) を索引化
    label_by_size = {}
    for cls, size_code, data_text, _size_display in _LABEL_RE.findall(html):
        label_by_size[size_code] = {"class": cls, "data_text": data_text or ""}

    # 決定的順序で SKU 列挙 (テスト・目視突合しやすさ優先)
    skus_out = []
    for sku_code in sorted(stocks.keys()):
        stock_entry = stocks[sku_code]
        sku_info = stock_entry.get("sku_info", {}) or {}
        # sku_code の末尾 2桁 = size_code (spec)
        size_code = sku_info.get("size_code") or sku_code[-2:]
        size_label = sku_info.get("size_label") or ""
        color_code = sku_info.get("color_code") or ""
        color_label = sku_info.get("color_label") or color_ld

        quantity = int(stock_entry.get("real_quantity") or stock_entry.get("quantity") or 0)
        inv_status = stock_entry.get("inventory_status") or ""
        in_stock = quantity > 0

        label_meta = label_by_size.get(size_code, {})
        stock_label = _stock_label_from_class(
            label_meta.get("class", ""),
            label_meta.get("data_text", ""),
            quantity,
        )

        price_entry = prices.get(sku_code, {}) or {}
        base_price = price_entry.get("price")
        sale_flg = bool(price_entry.get("sale_flg"))
        sale_price = price_entry.get("sale_price")
        # "" (empty string) が入ることがあるため None 化
        base_price_int = int(base_price) if isinstance(base_price, (int, float)) and base_price != "" else None
        if sale_flg and isinstance(sale_price, (int, float)) and sale_price != "":
            promo_int = int(sale_price)
        else:
            promo_int = base_price_int

        # 仕入送料 (2026-08-08 窓口): 「実際に払う額」= J 列 = 商品代金 + 送料
        # 閾値判定は「送料を足す前の商品代金」で。セール中はセール価格が商品代金。
        # base/promo それぞれ独立に閾値を評価 (base だけ高くて無料、みたいなケースを潰さない)
        base_price_with_ship = (base_price_int + _procurement_shipping(base_price_int)
                                if base_price_int is not None else None)
        promo_with_ship = (promo_int + _procurement_shipping(promo_int)
                           if promo_int is not None else None)

        skus_out.append({
            "size":              size_label,
            "size_display_code": size_code,
            "sku_code":          sku_code,
            "l2Id":              sku_code,               # uniqlo 互換エイリアス
            "communication_code": sku_code,              # uniqlo 互換エイリアス
            "in_stock":          in_stock,
            "stock_status":      inv_status,
            "stock_label":       stock_label,
            "quantity":          quantity,
            "price_jpy":         base_price_with_ship,   # J 列 (+送料)
            "promo_price_jpy":   promo_with_ship,        # J 列 (+送料、セール優先)
            "list_price_jpy":    base_price_int,          # U 列 (定価、送料を乗せない)
            "sales_active":      _is_sales_active(sku_info, now_ms=now_ms),
            "color":             color_label,
            "color_code":        color_code,
        })

    # 決定的順序: sku_code 昇順 = size_code 昇順 (01,02,03,04,10) と等価
    return {
        "name":              name,
        "product_id":        product_id,
        "product_group_id":  product_group_id,
        "color":             color_ld,
        "color_code":        (skus_out[0]["color_code"] if skus_out else ""),
        "fetched_at":        datetime.now().isoformat(timespec="seconds"),
        "skus":              skus_out,
    }


# ============================================================================
# 公開 API
# ============================================================================
def fetch_product_inventory(url: str, target_color_code: Optional[str] = None) -> dict:
    """graniph 商品 URL から在庫・価格情報を取得 (uniqlo_scraper と同 shape).

    Args:
        url: graniph 商品 URL (`https://www.graniph.com/item-detail/{12桁}`)
        target_color_code: 現状未使用 (1 URL = 1色 のため。sitemap 経由で別色を扱う想定)

    Returns: parse_graniph_html の出力。取得失敗時は ValueError / RuntimeError 送出.
    """
    del target_color_code  # 将来拡張用 placeholder (現状 1 URL 1色で不要)
    time.sleep(_pacing_sec())  # CloudFront 前段 pacing
    resp = get_with_retry(url, headers=DEFAULT_HEADERS, timeout=TIMEOUT_SEC)
    resp.raise_for_status()
    # レスポンス encoding を UTF-8 に明示 (Content-Type header が不安定なため)
    if resp.encoding is None or resp.encoding.lower() not in ("utf-8", "utf8"):
        resp.encoding = "utf-8"
    return parse_graniph_html(resp.text, url)


# ============================================================================
# CLI (動作確認用)
# ============================================================================
if __name__ == "__main__":
    # Windows cp932 コンソールでの ¥/◎/✕ 等 print 時 UnicodeEncodeError 回避
    for _stream_name in ("stdout", "stderr"):
        _s = getattr(sys, _stream_name, None)
        if _s is not None and hasattr(_s, "reconfigure"):
            try:
                _s.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    test_url = (
        sys.argv[1] if len(sys.argv) > 1
        else "https://www.graniph.com/item-detail/012000906300"
    )
    print(f"--- URL: {test_url}")
    result = fetch_product_inventory(test_url)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print()
    print(f"=== 在庫サマリー ({result['name']} / {result['color']}) ===")
    for sku in result["skus"]:
        mark = "◎" if sku["in_stock"] else "✕"
        # 表示上の「定価」= list_price_jpy (送料抜き). price_jpy は J 列用で送料込.
        list_p = sku["list_price_jpy"]
        pay = sku["promo_price_jpy"]
        price_str = f"¥{pay}" if pay == list_p else f"¥{pay} (定価 ¥{list_p})"
        print(f"  {mark} {sku['size']:>3} ({sku['size_display_code']}) "
              f"{sku['stock_label']:>7} qty={sku['quantity']:>2} {price_str}")
