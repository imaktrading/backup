"""Workman 公式 site (workman.jp) から商品 spec を catalog 化.

設計 (2026-05-16 HQ 本実装 GO 後):
  - SKU discovery: Selenium で カテゴリ page を JS render + scroll、商品 URL 収集
  - 個別 page parser: requests + BeautifulSoup (Cloudflare なし、static HTML)
  - JSON-LD Product schema + 本文 spec text 解析
  - catalog category='workman'、product_id='workman:<品番>' 形式

優先カテゴリ (海外需要強い line):
  c5104 ファンウエア・ペルチェ  (Peltier Vest)
  c5107 レイン・ヤッケ          (Aegis 防水)
  c5200 メンズ/アウター         (XShelter / 防水)
  c5202 メンズ/ボトムス         (WM STRETCH / コットンキャンバス)
  c5201 メンズ/トップス         (XShelter Tシャツ)

実行:
  python iMakCatalog/scrapers/workman.py --discover c5107  # SKU 一覧取得
  python iMakCatalog/scrapers/workman.py --fetch <product_url>  # 個別 fetch
  python iMakCatalog/scrapers/workman.py --priority             # 優先カテゴリ一括投入
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Optional

_CATALOG_ROOT = Path(__file__).resolve().parent.parent
if str(_CATALOG_ROOT) not in sys.path:
    sys.path.insert(0, str(_CATALOG_ROOT))

import api  # type: ignore  # noqa: E402

CATEGORY = "workman"
SOURCE = "workman_official"

# 優先カテゴリ (HQ 確定スコープ)
PRIORITY_CATEGORIES = {
    "c5104": "ファンウエア・ペルチェ",
    "c5107": "レイン・ヤッケ (Aegis)",
    "c5200": "メンズ/アウター",
    "c5201": "メンズ/トップス",
    "c5202": "メンズ/ボトムス",
}

PRODUCT_URL_TEMPLATE = "https://workman.jp/shop/g/{full_id}/"
CATEGORY_URL_TEMPLATE = "https://workman.jp/shop/c/{cat}/"


# ============================================================================
# Helpers (品番抽出)
# ============================================================================
def _hinban_from_full_id(full_id: str) -> Optional[str]:
    """full_id 'g2300035345090' → 品番 '35345'.

    形式: 'g' + 4桁prefix + 6桁品番(zero-padded) + 3桁suffix = 計 14 chars.
    例: g2300018604015 → prefix=2300, hinban=018604, suffix=015 → 品番 18604
    """
    if not full_id:
        return None
    m = re.match(r"^g\d{4}(\d{6})\d{3}$", full_id)
    if not m:
        return None
    return m.group(1).lstrip("0") or None


def _hinban_from_image_url(image_url: str) -> Optional[str]:
    """workman.jp/img/goods/S/35345_t1.jpg → '35345'."""
    if not image_url:
        return None
    m = re.search(r"/goods/[A-Z]/(\d{3,6})_", image_url)
    return m.group(1) if m else None


# ============================================================================
# SKU Discovery (Selenium 必須 — カテゴリ page は SPA pattern)
# ============================================================================
def discover_skus_in_category(category_code: str, driver=None) -> list[dict]:
    """カテゴリ page を Selenium で開いて全商品 URL + 品番を抽出.

    Returns:
        [{"full_id": "g2300...", "hinban": "18604", "url": "https://..."}, ...]
    """
    own_driver = driver is None
    if own_driver:
        driver = _start_driver()
    try:
        url = CATEGORY_URL_TEMPLATE.format(cat=category_code)
        driver.get(url)
        time.sleep(4)
        # 商品 grid 全表示まで scroll
        for _ in range(6):
            driver.execute_script("window.scrollBy(0, 2000)")
            time.sleep(1.2)
        src = driver.page_source
        full_ids = sorted(set(re.findall(r'/shop/g/(g[A-Za-z0-9]+)/?', src)))
        items = []
        for fid in full_ids:
            items.append({
                "full_id": fid,
                "hinban": _hinban_from_full_id(fid),
                "url": PRODUCT_URL_TEMPLATE.format(full_id=fid),
                "category_code": category_code,
            })
        return items
    finally:
        if own_driver:
            try:
                driver.quit()
            except Exception:
                pass


def _start_driver():
    import undetected_chromedriver as uc
    opts = uc.ChromeOptions()
    opts.add_argument("--lang=ja-JP")
    opts.add_argument("--window-size=1400,900")
    return uc.Chrome(options=opts, version_main=147)


# ============================================================================
# 個別 page parser (Cloudflare なし、requests OK)
# ============================================================================
def fetch_product_page(url: str) -> Optional[dict]:
    """workman 個別商品 page の HTML から spec dict 構築.

    Returns:
        None if 廃番 / 取扱なし.
        dict with keys: hinban, name_jp, price_jpy, color_jp, brand, image_url,
                         material, size_options, description, features, gender
    """
    import requests, html as _html_mod

    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    except Exception as e:
        return {"_error": f"{type(e).__name__}: {e}"}
    if r.status_code != 200:
        return {"_error": f"HTTP {r.status_code}"}

    text = r.text
    text_decoded = _html_mod.unescape(text)
    plain = re.sub(r"<script[\s\S]*?</script>", " ", text_decoded)
    plain = re.sub(r"<style[\s\S]*?</style>", " ", plain)
    plain = re.sub(r"<[^>]+>", " ", plain)
    plain = re.sub(r"\s+", " ", plain).strip()

    # 廃番判定
    if "販売終了" in plain or "ただ今お取扱いできない" in plain:
        return None
    if "ご指定の商品ページはただ今お取扱いをしておりません" in plain:
        return None

    out: dict = {}

    # 1) JSON-LD Product schema 抽出
    ld_blocks = re.findall(r'<script[^>]*application/ld\+json[^>]*>([\s\S]+?)</script>', text_decoded)
    for blk in ld_blocks:
        try:
            data = json.loads(blk)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("@type") != "Product":
            continue
        if "name" in data:
            out["name_jp"] = data["name"]
        if "color" in data:
            out["color_jp"] = data["color"]
        if "image" in data:
            img = data["image"]
            if isinstance(img, str):
                out["image_url"] = img
            elif isinstance(img, list) and img:
                out["image_url"] = img[0]
        if "brand" in data:
            brand = data["brand"]
            if isinstance(brand, dict):
                out["brand"] = brand.get("name", "Workman")
            elif isinstance(brand, str):
                out["brand"] = brand
            else:
                out["brand"] = "Workman"
        if "sku" in data:
            out["sku"] = data["sku"]
        break

    # 2) title からも品番取得 (JSON-LD で sku 取れない場合)
    title_m = re.search(r"<title>([^<]+)</title>", text_decoded)
    if title_m:
        ttl = title_m.group(1).strip()
        # 「18604 レディースシン... | ワークマン公式オンラインストア」 → 18604
        hinban_m = re.match(r"^(\d{4,6})\s+(.+?)\s*\|", ttl)
        if hinban_m:
            out["hinban"] = hinban_m.group(1)
            if "name_jp" not in out:
                out["name_jp"] = hinban_m.group(2).strip()

    # 3) image_url から品番抽出 (title に品番が無い page 用 fallback)
    if "hinban" not in out and out.get("image_url"):
        h = _hinban_from_image_url(out["image_url"])
        if h:
            out["hinban"] = h

    # 3) 価格 (本文 / og:price)
    for pat in [r'"price"\s*:\s*"?([0-9.]+)', r'data-price="([0-9]+)"',
                r'(?:商品番号\s+\d+[\s\S]{0,200}?)([0-9,]+)\s*円']:
        m = re.search(pat, text_decoded)
        if m:
            try:
                out["price_jpy"] = int(m.group(1).replace(",", "").split(".")[0])
                break
            except ValueError:
                continue

    # 4) 商品本文の Description (Workman は商品説明に機能性キーワード列挙)
    desc_text = ""
    desc_match = re.search(r"商品説明[\s\S]{0,2000}?(?=他のデザイン|ご注意|サイズ表|使用上のご注意|お取扱いの注意)", plain)
    if desc_match:
        desc_text = desc_match.group(0).strip()
        out["description"] = desc_text[:1000]

    # 5) features (機能性 keyword 抽出) — description section 内のみ走査
    # 全 page text に対して走査すると関連商品 / アクセサリの機能まで誤検出.
    feature_keywords = {
        "防水": "Waterproof",
        "撥水": "Water-Repellent",
        "透湿": "Breathable",
        "吸汗速乾": "Quick-Dry",
        "接触冷感": "Cooling",
        "ストレッチ": "Stretch",
        "UVカット": "UV Protection",
        "抗菌": "Antibacterial",
        "消臭": "Deodorizing",
        "防風": "Windproof",
        "保温": "Thermal",
        "難燃": "Flame-Resistant",
        "蓄熱": "Heat-Retention",
        "ペルチェ": "Peltier Cooling",
        "暑熱軽減": "Heat-Reduction",
        "リフレクター": "Reflective",
    }
    features = []
    scan_target = desc_text if desc_text else ""
    for jp, en in feature_keywords.items():
        if jp in scan_target and en not in features:
            features.append(en)
    if features:
        out["features"] = features

    # 6) 素材 (本文の「素材」section、次 section 開始まで)
    material_m = re.search(r"素材[：:\s]+([^●｜|]{2,200}?)(?=\s*※|\s*お取扱|\s*サイズ|\s*対応|\s*【|$)", plain)
    if material_m:
        out["material_jp"] = material_m.group(1).strip()[:120]

    # 7) gender (カテゴリ or 商品名から推定)
    name_jp = out.get("name_jp", "")
    if "レディース" in name_jp or "WOMEN" in name_jp.upper():
        out["gender"] = "Women"
    elif "キッズ" in name_jp:
        out["gender"] = "Kids"
    else:
        out["gender"] = "Men"

    out["source_url"] = url
    out["fetched_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return out


# ============================================================================
# Upsert
# ============================================================================
def upsert_product(item: dict, data: dict, category_code: str = "") -> bool:
    """fetch_product_page の戻り値を catalog に投入.

    Args:
        item: {"hinban", "full_id", "url"}
        data: fetch_product_page の戻り
        category_code: c5104 等

    Returns:
        True on success.
    """
    if not data or data.get("_error"):
        return False
    hinban = data.get("hinban") or item.get("hinban")
    if not hinban:
        return False
    product_id = f"workman:{hinban}"
    name_jp = data.get("name_jp", "")
    if not name_jp:
        return False
    specs = {
        "hinban":            hinban,
        "color_jp":          data.get("color_jp", ""),
        "brand":             data.get("brand", "Workman"),
        "price_jpy":         data.get("price_jpy"),
        "material_jp":       data.get("material_jp", ""),
        "features":          data.get("features", []),
        "description":       data.get("description", ""),
        "gender":            data.get("gender", "Unisex"),
        "category_code":     category_code or item.get("category_code", ""),
        "category_name":     PRIORITY_CATEGORIES.get(item.get("category_code", ""), ""),
        "image_url":         data.get("image_url", ""),
        "full_id":           item.get("full_id", ""),
        # eBay 拡張枠
        "ebay_active_listings":   None,
        "ebay_median_price_usd":  None,
        "is_active_msrp":         True,  # 取得時点では active
        "msrp_last_checked":      data.get("fetched_at"),
    }
    api.upsert(
        category=CATEGORY,
        product_id=product_id,
        name=name_jp,
        name_jp=name_jp,
        set_name=PRIORITY_CATEGORIES.get(item.get("category_code", ""), ""),
        specs=specs,
        images=[data.get("image_url")] if data.get("image_url") else [],
        source=SOURCE,
        source_url=data.get("source_url"),
    )
    return True


def update_priority_categories(limit_per_cat: Optional[int] = None) -> dict:
    """優先カテゴリを一括 fetch + upsert."""
    driver = _start_driver()
    stats = {"discovered": 0, "fetched": 0, "upserted": 0,
             "skipped": 0, "errors": 0}
    try:
        for cat, label in PRIORITY_CATEGORIES.items():
            print(f"\n=== {cat}: {label} ===")
            items = discover_skus_in_category(cat, driver)
            print(f"  discovered: {len(items)} items")
            stats["discovered"] += len(items)
            if limit_per_cat:
                items = items[:limit_per_cat]
            for i, item in enumerate(items, 1):
                data = fetch_product_page(item["url"])
                if data is None:
                    stats["skipped"] += 1
                    continue
                if data.get("_error"):
                    print(f"  [{i}] {item['hinban']}: ERR {data['_error']}")
                    stats["errors"] += 1
                    continue
                stats["fetched"] += 1
                if upsert_product(item, data, cat):
                    stats["upserted"] += 1
                    name = (data.get("name_jp") or "")[:50]
                    if i <= 5 or i % 20 == 0:
                        print(f"  [{i}] {item['hinban']}: ✓ {name}")
                else:
                    stats["errors"] += 1
                time.sleep(0.3)  # rate limit safety
    finally:
        try:
            driver.quit()
        except Exception:
            pass
    print(f"\n=== 完了 ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    return stats


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    p = argparse.ArgumentParser()
    p.add_argument("--discover", help="カテゴリ code を渡して SKU 一覧取得")
    p.add_argument("--fetch", help="商品 URL 個別 fetch")
    p.add_argument("--priority", action="store_true", help="優先カテゴリ一括投入")
    p.add_argument("--limit", type=int, default=None, help="--priority に件数上限")
    args = p.parse_args()

    if args.discover:
        items = discover_skus_in_category(args.discover)
        print(f"discovered: {len(items)}")
        for it in items[:20]:
            print(f"  {it['hinban']}: {it['url']}")
    elif args.fetch:
        d = fetch_product_page(args.fetch)
        print(json.dumps(d, ensure_ascii=False, indent=2))
    elif args.priority:
        update_priority_categories(limit_per_cat=args.limit)
    else:
        p.print_help()
