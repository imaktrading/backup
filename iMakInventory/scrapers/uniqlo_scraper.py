"""uniqlo_scraper - UNIQLO 商品ページの在庫・価格スクレイパー (独立モジュール).

設計原則 (修正連鎖を生まないため):
  - 既存モジュール (iMakeBayAPI / iMakHQ / 他プロジェクト) を一切 import しない
  - requests + 標準ライブラリのみで完結 (Selenium 不要、無料 API 経由)
  - 失敗時は例外送出 or None 返却、呼出側でハンドリング

API 経路 (Selenium 不要の理由):
  UNIQLO の商用 L2S API が公開エンドポイント (認証不要) で在庫・価格を JSON 返却:
    https://www.uniqlo.com/jp/api/commerce/v5/ja/products/{pid}/price-groups/{pg}/l2s?withPrices=true&withStocks=true

  - pid: 商品 ID (例: E483933-000) — 商品 URL から抽出
  - pg : price-group (常に 00)
  - 在庫: l2s[].l2Id をキーに stocks{} dict を引いて statusCode/quantity を取得
  - 価格: 同様に prices{} dict を引いて base/promo の value (¥) を取得

  ※ 静的 HTML は homepage redirect (bot 検出) で取れないが、API は通る。

使用例:
    from uniqlo_scraper import fetch_product_inventory
    info = fetch_product_inventory("https://www.uniqlo.com/jp/ja/products/E483933-000/00?colorDisplayCode=09&sizeDisplayCode=004")
    # → {
    #     "name": "マンガキュレーション UT/ベルセルク/リラックス",
    #     "product_id": "E483933-000",
    #     "color": "BLACK",
    #     "color_display_code": "09",
    #     "skus": [
    #         {"size": "XS", "size_display_code": "002", "l2Id": "08969942",
    #          "in_stock": True, "quantity": 11, "price_jpy": 990, ...},
    #         ...
    #     ],
    # }
"""
from __future__ import annotations

import re
import urllib.parse
from typing import Optional

import requests


UNIQLO_API_TEMPLATE = (
    "https://www.uniqlo.com/jp/api/commerce/v5/ja/products/"
    "{product_id}/price-groups/{price_group}/l2s?withPrices=true&withStocks=true"
)
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.8",
}
TIMEOUT_SEC = 15


# ============================================================================
# URL パーサ
# ============================================================================
def parse_uniqlo_url(url: str) -> dict:
    """UNIQLO 商品 URL から product_id / price_group / colorDisplayCode / sizeDisplayCode を抽出.

    対応 URL 例:
      https://www.uniqlo.com/jp/ja/products/E483933-000/00?colorDisplayCode=09&sizeDisplayCode=004
      https://www.uniqlo.com/jp/ja/products/E483933-000/00
      https://www.uniqlo.com/jp/ja/products/483933              (簡易表記、E + 0-padding 補完)
    """
    if not url:
        raise ValueError("URL が空です")

    parsed = urllib.parse.urlparse(url)
    path_parts = [p for p in parsed.path.split("/") if p]

    # パスから product_id を抽出 ("E483933-000" 形式優先)
    product_id = None
    price_group = "00"
    for i, p in enumerate(path_parts):
        m = re.match(r"^(E\d{6,7}-\d{3})$", p)
        if m:
            product_id = m.group(1)
            # 次のセグメントが price_group (00 等) の可能性
            if i + 1 < len(path_parts) and re.match(r"^\d{2}$", path_parts[i + 1]):
                price_group = path_parts[i + 1]
            break

    # フォールバック: 数字のみの id (E + 0-padding 補完)
    if product_id is None:
        for p in path_parts:
            m = re.match(r"^(\d{6,7})$", p)
            if m:
                product_id = f"E{m.group(1)}-000"
                break

    if product_id is None:
        raise ValueError(f"product_id を URL から抽出できません: {url}")

    qs = urllib.parse.parse_qs(parsed.query)
    return {
        "product_id": product_id,
        "price_group": price_group,
        "color_display_code": (qs.get("colorDisplayCode") or [None])[0],
        "size_display_code": (qs.get("sizeDisplayCode") or [None])[0],
    }


# ============================================================================
# API 呼出
# ============================================================================
def _call_l2s_api(product_id: str, price_group: str = "00") -> dict:
    """UNIQLO L2S API を呼出して result dict を返す."""
    url = UNIQLO_API_TEMPLATE.format(product_id=product_id, price_group=price_group)
    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=TIMEOUT_SEC)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("status") != "ok":
        raise RuntimeError(f"UNIQLO API status != ok: {payload.get('status')}")
    return payload.get("result", {})


def _call_details_api(product_id: str, price_group: str = "00") -> dict:
    """UNIQLO details API (商品名・カラー・サイズ正規名取得) を呼出."""
    url = (
        "https://www.uniqlo.com/jp/api/commerce/v5/ja/products/"
        f"{product_id}/price-groups/{price_group}/details?withPrices=true&withStocks=true"
    )
    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=TIMEOUT_SEC)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("status") != "ok":
        raise RuntimeError(f"UNIQLO details API status != ok: {payload.get('status')}")
    return payload.get("result", {})


# ============================================================================
# 公開 API
# ============================================================================
def fetch_product_inventory(
    url: str,
    target_color_code: Optional[str] = None,
) -> Optional[dict]:
    """UNIQLO 商品 URL から在庫・価格情報を取得.

    Args:
        url: UNIQLO 商品 URL (colorDisplayCode をクエリに含むのが望ましい)
        target_color_code: URL に colorDisplayCode が無い時、このカラーコードでフィルタ.
                           None なら URL から推定 → なければ全カラー (現実装は1色目)

    Returns:
        {
            "name":               商品名 (例: "マンガキュレーション UT/..."),
            "product_id":         商品 ID,
            "price_group":        価格グループ (通常 "00"),
            "color":              カラー名 (例: "BLACK"),
            "color_display_code": "09" 等,
            "fetched_at":         取得時刻 (ISO 8601),
            "skus": [
                {
                    "size":              "S" / "M" / "L" 等の表示名,
                    "size_display_code": "002" 等の内部コード,
                    "l2Id":              "08969942" (UNIQLO 内部 SKU ID),
                    "communication_code":"483933-09-002-000" (人間可読 SKU),
                    "in_stock":          True/False,
                    "stock_status":      "IN_STOCK" / "STOCK_OUT",
                    "stock_label":       "在庫あり" / "在庫なし",
                    "quantity":          11 (在庫数、概数),
                    "price_jpy":         990 (税込円),
                    "promo_price_jpy":   990 (セール価格、なければ price_jpy と同値),
                    "sales_active":      True (販売停止中なら False),
                },
                ...
            ],
        }

    例外: URL 不正 / API 失敗 → ValueError or RuntimeError 送出.
    """
    from datetime import datetime

    info = parse_uniqlo_url(url)
    product_id = info["product_id"]
    price_group = info["price_group"]
    target_code = target_color_code or info.get("color_display_code")

    l2s_result = _call_l2s_api(product_id, price_group)
    details_result = _call_details_api(product_id, price_group)

    l2s_list = l2s_result.get("l2s", [])
    stocks = l2s_result.get("stocks", {})
    prices = l2s_result.get("prices", {})

    # カラー名解決
    colors = details_result.get("colors", [])
    color_map = {c["displayCode"]: c["name"] for c in colors if "displayCode" in c}

    # ターゲットカラーが指定されてれば該当 l2s のみ抽出
    if target_code:
        l2s_filtered = [x for x in l2s_list if x.get("color", {}).get("displayCode") == target_code]
        if not l2s_filtered:
            # 指定カラーがヒットしない → 全色返す (URL 推定の誤りに備えて)
            l2s_filtered = l2s_list
    else:
        l2s_filtered = l2s_list

    # 検出されたカラー
    if l2s_filtered:
        first_color_code = l2s_filtered[0].get("color", {}).get("displayCode", "")
    else:
        first_color_code = ""

    skus = []
    for item in l2s_filtered:
        l2id = item.get("l2Id")
        size_dc = item.get("size", {}).get("displayCode", "")
        stock_info = stocks.get(l2id, {})
        price_info = prices.get(l2id, {})

        # UNIQLO statusCode 分類:
        #   IN_STOCK   (qty=11) → 在庫豊富 ◎
        #   LOW_STOCK  (qty=2-5) → 残少だが ◎
        #   STOCK_OUT  (qty=0)   → ✕
        # 防御: sales=False (販売停止中) は在庫あっても買えないので強制 ✕
        # 防御: 未知 statusCode は ✕ + 警告 (見落とし防止)
        status_code = stock_info.get("statusCode", "")
        sales_active = item.get("sales", True)
        if status_code in ("IN_STOCK", "LOW_STOCK"):
            in_stock = True
        elif status_code == "STOCK_OUT":
            in_stock = False
        else:
            # 未知 statusCode → 警告ログ出して安全側 (✕)
            print(f"    ⚠️ uniqlo_scraper: 未知 statusCode={status_code!r} "
                  f"l2Id={l2id} → ✕扱い (要コード対応)")
            in_stock = False
        # 販売停止中は在庫があっても ✕
        if not sales_active:
            print(f"    ⚠️ uniqlo_scraper: sales=False l2Id={l2id} → ✕扱い (販売停止中)")
            in_stock = False
        # quantity が「在庫数」だが UNIQLO は概算 (0/2/5/11 等の段階値)
        qty = int(stock_info.get("quantity", 0) or 0)

        base_price = (price_info.get("base") or {}).get("value")
        promo_price = (price_info.get("promo") or {}).get("value", base_price)

        skus.append({
            "size": _resolve_size_name(size_dc, details_result.get("sizes", [])),
            "size_display_code": size_dc,
            "l2Id": l2id,
            "communication_code": item.get("communicationCode", ""),
            "in_stock": in_stock,
            "stock_status": stock_info.get("statusCode", ""),
            "stock_label": stock_info.get("statusLocalized", ""),
            "quantity": qty,
            "price_jpy": int(base_price) if base_price is not None else None,
            "promo_price_jpy": int(promo_price) if promo_price is not None else None,
            "sales_active": item.get("sales", True),
        })

    return {
        "name": details_result.get("name", ""),
        "product_id": product_id,
        "price_group": price_group,
        "color": color_map.get(first_color_code, ""),
        "color_display_code": first_color_code,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "skus": skus,
    }


def _resolve_size_name(size_display_code: str, sizes_list: list) -> str:
    """displayCode から 表示名 (XS/S/M/L/XL等) を引く."""
    for s in sizes_list:
        if s.get("displayCode") == size_display_code:
            return s.get("name", size_display_code)
    return size_display_code


# ============================================================================
# CLI (動作確認用)
# ============================================================================
if __name__ == "__main__":
    import json
    import sys
    test_url = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "https://www.uniqlo.com/jp/ja/products/E483933-000/00?colorDisplayCode=09&sizeDisplayCode=004"
    )
    print(f"--- URL: {test_url}")
    info = fetch_product_inventory(test_url)
    print(json.dumps(info, ensure_ascii=False, indent=2))
    print()
    print(f"=== 在庫サマリー ({info['name']} / {info['color']}) ===")
    for sku in info["skus"]:
        mark = "◎" if sku["in_stock"] else "✕"
        print(f"  {mark} {sku['size']:>4} ({sku['size_display_code']}) "
              f"{sku['stock_label']:>6} qty={sku['quantity']:>2} ¥{sku['price_jpy']}")
