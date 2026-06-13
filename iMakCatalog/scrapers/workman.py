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
import os
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
AJAX_VARIATIONS_ENDPOINT = "https://workman.jp/shop/goods/ajaxgoodsstock.aspx"


# 日本語 color → eBay 16 色 enum (HQ v2: ebay_color 別 field 必須)
_JP_COLOR_TO_EBAY = {
    "ブラック":         "Black",
    "ホワイト":         "White",
    "オフホワイト":     "White",
    "アイボリー":       "White",
    "ネイビー":         "Blue",
    "ブルー":           "Blue",
    "ロイヤルブルー":   "Blue",
    "ライトブルー":     "Blue",
    "コン":             "Blue",     # 紺
    "グリーン":         "Green",
    "フォレストグリーン": "Green",
    "オリーブ":         "Green",
    "カーキ":           "Green",
    "イエロー":         "Yellow",
    "レッド":           "Red",
    "パステルレッド":   "Red",
    "オレンジ":         "Orange",
    "ピンク":           "Pink",
    "パープル":         "Purple",
    "ブラウン":         "Brown",
    "ベージュ":         "Beige",
    "グレー":           "Gray",
    "チャコール":       "Gray",
    "シルバー":         "Silver",
    "ゴールド":         "Gold",
    "アイスブラック":   "Black",
    "モノグラムブラック": "Black",
    "ディープネイビー": "Blue",
}


def _jp_color_to_ebay(jp: str) -> str:
    """日本語色名 → eBay 16 enum. 未知は空文字."""
    if not jp:
        return ""
    # 完全一致優先
    if jp in _JP_COLOR_TO_EBAY:
        return _JP_COLOR_TO_EBAY[jp]
    # 部分一致 (例: "ブラック×ホワイト" → "Black", "ブラック：スタンダード" → "Black")
    for k, v in _JP_COLOR_TO_EBAY.items():
        if k in jp:
            return v
    return ""


# 全角 → 半角 size 正規化
_SIZE_NORMALIZE = {
    "Ｓ": "S", "Ｍ": "M", "Ｌ": "L",
    "ＸＳ": "XS", "ＸＬ": "XL",
    "ＸＸＬ": "XXL",
    "ＬＬ": "LL",
    "３Ｌ": "3L", "４Ｌ": "4L", "５Ｌ": "5L",
    "フリー": "Free", "Free": "Free",
    "ワンサイズ": "One Size",
}


def _normalize_size(jp_size: str) -> str:
    """全角 size → 半角. 未知はそのまま."""
    if not jp_size:
        return ""
    s = jp_size.strip()
    if s in _SIZE_NORMALIZE:
        return _SIZE_NORMALIZE[s]
    # ASCII で既に正規化されてる場合 (S / M / L / LL / 3L)
    if re.match(r"^[A-Z0-9]+$", s):
        return s
    return s


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


def _parent_mpn_from_url(url: str) -> Optional[str]:
    """https://workman.jp/shop/g/g2300067335038/ → '2300067335038' (13 桁)."""
    m = re.search(r"/shop/g/g(\d{13})/", url)
    return m.group(1) if m else None


# ============================================================================
# AJAX endpoint (HQ Phase 2 設計 — variation 一括取得、Selenium 不要)
# ============================================================================
def fetch_variations_via_ajax(parent_mpn: str, timeout: int = 15) -> Optional[dict]:
    """POST /shop/goods/ajaxgoodsstock.aspx で variation 一括取得.

    Returns:
        None if AJAX 失敗 (= 廃番 / endpoint 消失 / network エラー).
        dict with keys: color_variants, size_variants, sku_matrix.

    Schema:
        {
          "color_variants": [
            {"variant_hinban": "67335_c3", "color_jp": "ブラック",
             "color_en": "Black", "ebay_color": "Black",
             "image_url": "https://workman.jp/img/goods/C/67335_c3.jpg"},
            ...
          ],
          "size_variants": ["S", "M", "L", "LL", "3L"],
          "sku_matrix": [
            {"variant_sku_mpn": "2300067335021", "color_jp": "ブラック",
             "size_normalized": "S", "in_stock": False,
             "last_no_stock_seen_at": "2026-05-16T21:30:00"},
            ...
          ],
          "fetched_at": "2026-05-16T21:30:00",
        }
    """
    import html as _html_mod, requests as _req

    try:
        r = _req.post(
            AJAX_VARIATIONS_ENDPOINT,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Requested-With": "XMLHttpRequest",
            },
            data={"goods": parent_mpn},
            timeout=timeout,
        )
    except Exception:
        return None
    if r.status_code != 200 or len(r.text) < 100:
        return None

    body = _html_mod.unescape(r.text)
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%S")

    return _parse_ajax_response(body, parent_mpn, now_iso)


def _parse_ajax_response(body: str, parent_mpn: str, fetched_at: str) -> dict:
    """AJAX response HTML 断片 → variation dict."""
    # representative_hinban は image filename から優先取得 (= 5-6 桁の品番).
    # parent_mpn = 13 桁 mpn なので slice しても余分 suffix が残るため image_url 派生に統一.
    hinban: Optional[str] = None

    # 1) color_variants 抽出: <dl class="...block-color--item..." title="ブラック"><img src="..."></dl>
    color_variants: list[dict] = []
    color_block_m = re.search(r'block-variation--item-list block-color--item-list[\s\S]+?</div>', body)
    color_section = color_block_m.group(0) if color_block_m else body
    # 各 <dl> から title / img src 抽出
    for dl_m in re.finditer(
        r'<dl\s+class="[^"]*block-color--item[^"]*"\s+title="([^"]+)"[\s\S]+?<img\s+src="([^"]+)"',
        color_section,
    ):
        color_jp = dl_m.group(1).strip()
        img_path = dl_m.group(2).strip()
        # variant_hinban: image filename suffix から抽出 (例: /img/goods/C/67335_c3.jpg → 67335_c3)
        vh_m = re.search(r"/(\d+_c\d+)\.jpg", img_path)
        variant_hinban = vh_m.group(1) if vh_m else f"unknown_c{len(color_variants)+1}"
        # representative hinban: image filename の 数字 prefix (= 5-6 桁品番)
        if hinban is None and vh_m:
            hinban = vh_m.group(1).split("_")[0]
        ebay_color = _jp_color_to_ebay(color_jp)
        # 完全な image URL (relative path の場合 workman.jp prefix)
        if img_path.startswith("/"):
            image_url = f"https://workman.jp{img_path}"
        else:
            image_url = img_path
        color_variants.append({
            "variant_hinban": variant_hinban,
            "color_jp": color_jp,
            "color_en": color_jp,       # 直訳は後で API 翻訳、現状は JP 同値
            "ebay_color": ebay_color,
            "image_url": image_url,
        })

    # 2) size_variants 抽出: <div class="block-pattern--size-text">Ｓ</div>
    size_set: list[str] = []
    seen_sizes: set[str] = set()
    for sz_m in re.finditer(r'<div\s+class="block-pattern--size-text">([^<]+)</div>', body):
        sz_jp = sz_m.group(1).strip()
        sz_norm = _normalize_size(sz_jp)
        if sz_norm and sz_norm not in seen_sizes:
            seen_sizes.add(sz_norm)
            size_set.append(sz_norm)

    # 3) sku_matrix 抽出: block-select-size-detail group ごと (= color 単位) に
    #    各 block-pattern (= 1 size) の sku param + 在庫を取得.
    #    group i (0-indexed) → color_variants[i] と対応 (= AJAX response 順序).
    #    2026-05-17 fix: 以前は全 sku を flat 抽出 + 完全マトリクス前提で
    #    div / mod 紐付けしていたが、color によって取扱 size 数が違う場合に
    #    同 (color, size) 重複が大量発生 (35840 = ErrorCode 21916585 で発覚).
    sku_matrix: list[dict] = []
    group_pat = re.compile(
        r'<div\s+class="block-select-size-detail\s+js-variation-size">'
        r'([\s\S]+?)'
        r'(?=<div\s+class="block-select-size-detail\s+js-variation-size">|$)',
    )
    seen_combos: set = set()  # (color_jp, size_normalized) の dedup
    for group_idx, group_m in enumerate(group_pat.finditer(body)):
        group_html = group_m.group(1)
        color_jp = ""
        if group_idx < len(color_variants):
            color_jp = color_variants[group_idx]["color_jp"]
        # 各 block-pattern (= 1 size) 抽出
        for bp_m in re.finditer(
            r'<div\s+class="block-select-size-detail--item\s+block-pattern([^"]*)"([\s\S]+?)'
            r'(?=<div\s+class="block-select-size-detail--item|$)',
            group_html,
        ):
            block_classes = bp_m.group(1)
            block_html = bp_m.group(2)
            in_stock = "no-stock" not in block_classes
            sz_m = re.search(r'block-pattern--size-text">([^<]+)<', block_html)
            size_jp = sz_m.group(1).strip() if sz_m else ""
            size_norm = _normalize_size(size_jp)
            sku_m = re.search(r"[?&]sku=(\d{13})", block_html)
            sku_mpn = sku_m.group(1) if sku_m else ""
            if not sku_mpn:
                continue
            combo = (color_jp, size_norm)
            if combo in seen_combos:
                # 同 (color, size) 重複は skip (= 旧 mpn 退避は extra_skus に)
                continue
            seen_combos.add(combo)
            sku_matrix.append({
                "variant_sku_mpn": sku_mpn,
                "color_jp": color_jp,
                "size_normalized": size_norm,
                "in_stock": in_stock,
                "last_no_stock_seen_at": fetched_at if not in_stock else "",
            })

    # hinban fallback: image filename から取れない場合 parent_mpn の中央部分
    if hinban is None and len(parent_mpn) == 13:
        # 13 桁 mpn の 中央 5 桁 (= 5/6 桁品番 + 末尾 size_idx 3 桁 を除く部分)
        # 例: 2300067335038 → 2300 + 067335 + 038 → 67335
        mid = parent_mpn[4:10]
        hinban = mid.lstrip("0") or None
    return {
        "parent_mpn": parent_mpn,
        "representative_hinban": hinban,
        "color_variants": color_variants,
        "size_variants": size_set,
        "sku_matrix": sku_matrix,
        "fetched_at": fetched_at,
    }


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
    # 2026-06-14: version_main を実機 Chrome 自動検出 (旧 147 固定。Chrome更新で mismatch→orphan回避)。
    try:
        import os as _os, sys as _sys
        _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
        from _chrome_version import installed_chrome_major as _icm
        _vm = _icm(147)
    except Exception:
        _vm = 147
    return uc.Chrome(options=opts, version_main=_vm)



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

    # 2) title から品番取得 (5-6 桁優先、image_url 由来 5 桁と整合させる)
    title_m = re.search(r"<title>([^<]+)</title>", text_decoded)
    title_name = ""
    if title_m:
        ttl = title_m.group(1).strip()
        # 「18604 レディースシン... | ワークマン公式オンラインストア」 → 18604
        hinban_m = re.match(r"^(\d{4,6})\s+(.+?)\s*\|", ttl)
        if hinban_m:
            title_name = hinban_m.group(2).strip()
            if "name_jp" not in out:
                out["name_jp"] = title_name

    # 3) image_url から 5 桁品番抽出 (= AJAX endpoint と整合する正規形)
    # 2026-05-16 bug fix: title からの 4 桁 hinban を採用していた 40 件で
    # 集約 entry (= image_url 5 桁 hinban) と紐付かない問題発生.
    if out.get("image_url"):
        h_img = _hinban_from_image_url(out["image_url"])
        if h_img:
            out["hinban"] = h_img
    # 4) image_url なし or 抽出失敗時に title hinban をフォールバック
    if "hinban" not in out and title_m:
        hb_m = re.match(r"^(\d{4,6})\s+", title_m.group(1).strip())
        if hb_m:
            out["hinban"] = hb_m.group(1)

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


# ============================================================================
# 集約 entry 生成 (HQ Phase 2 設計 — variation 集約)
# ============================================================================
def _aggregate_to_series_entry(parent_mpn: str, existing_data: Optional[dict] = None) -> Optional[dict]:
    """parent_mpn から AJAX で variation 取得 → 集約 entry dict 生成.

    Args:
        parent_mpn: 13 桁 mpn
        existing_data: 既存個別 entry の fetch_product_page 結果 (name_jp/price/features 等).
                       None なら parent URL から fresh fetch.

    Returns:
        集約 entry の specs dict (api.upsert に渡せる形). None if AJAX 失敗.
    """
    var = fetch_variations_via_ajax(parent_mpn)
    if not var or not var.get("color_variants"):
        return None
    hinban = var["representative_hinban"]

    # existing_data から name_jp / price / features 等を埋める
    if existing_data is None:
        # fresh fetch (URL pattern: g<parent_mpn>)
        url = PRODUCT_URL_TEMPLATE.format(full_id=f"g{parent_mpn}")
        existing_data = fetch_product_page(url) or {}

    name_jp = (existing_data.get("name_jp") or "").strip()
    if not name_jp:
        return None

    return {
        "product_id": f"workman:series:{hinban}",
        "name_jp": name_jp,
        "specs": {
            "is_series_aggregate": True,
            "parent_mpn": parent_mpn,
            "representative_hinban": hinban,
            "color_variants": var["color_variants"],
            "size_variants": var["size_variants"],
            "sku_matrix": var["sku_matrix"],
            "fetched_at": var["fetched_at"],
            # existing_data 由来
            "price_jpy":      existing_data.get("price_jpy"),
            "brand":          existing_data.get("brand", "Workman"),
            "material_jp":    existing_data.get("material_jp", ""),
            "features":       existing_data.get("features", []),
            "description":    existing_data.get("description", ""),
            "gender":         existing_data.get("gender", "Men"),
            "category_code":  existing_data.get("category_code", ""),
            "category_name":  PRIORITY_CATEGORIES.get(existing_data.get("category_code", ""), ""),
            "image_url":      var["color_variants"][0]["image_url"],
            # eBay 拡張枠
            "is_active_msrp": True,
            "msrp_last_checked": var["fetched_at"],
        },
        "source_url": existing_data.get("source_url", PRODUCT_URL_TEMPLATE.format(full_id=f"g{parent_mpn}")),
        "image_url":  var["color_variants"][0]["image_url"],
    }


def upsert_series_aggregate(parent_mpn: str, existing_data: Optional[dict] = None) -> Optional[str]:
    """集約 entry を生成 + catalog 投入.

    Returns:
        投入された product_id (例: 'workman:series:67335'). None if 失敗.
    """
    agg = _aggregate_to_series_entry(parent_mpn, existing_data)
    if not agg:
        return None
    api.upsert(
        category=CATEGORY,
        product_id=agg["product_id"],
        name=agg["name_jp"],
        name_jp=agg["name_jp"],
        set_name=agg["specs"]["category_name"],
        specs=agg["specs"],
        images=[agg["image_url"]] if agg["image_url"] else [],
        source=SOURCE,
        source_url=agg["source_url"],
    )
    return agg["product_id"]


def backfill_parent_series_id() -> dict:
    """Phase 1 既存 100 SKU の各 entry に specs.parent_series_id 補完.

    各 individual entry に対し、その hinban の image_url から prefix 抽出 →
    `workman:series:<prefix>` を parent_series_id として specs に追加.

    Returns:
        統計 dict (processed / backfilled / errors / skipped).
    """
    import sqlite3 as _sql
    conn = _sql.connect(str(api._DB_PATH))
    conn.row_factory = _sql.Row
    cur = conn.cursor()
    cur.execute("""SELECT product_id, specs FROM products WHERE category=?
                   AND product_id NOT LIKE 'workman:series:%'""", (CATEGORY,))
    rows = cur.fetchall()
    stats = {"processed": 0, "backfilled": 0, "errors": 0, "skipped_no_change": 0}
    for r in rows:
        stats["processed"] += 1
        try:
            s = json.loads(r["specs"]) if r["specs"] else {}
        except Exception:
            stats["errors"] += 1
            continue
        hinban = s.get("hinban")
        if not hinban:
            stats["errors"] += 1
            continue
        new_psid = f"workman:series:{hinban}"
        if s.get("parent_series_id") == new_psid:
            stats["skipped_no_change"] += 1
            continue
        s["parent_series_id"] = new_psid
        cur.execute("UPDATE products SET specs=? WHERE category=? AND product_id=?",
                    (json.dumps(s, ensure_ascii=False), CATEGORY, r["product_id"]))
        stats["backfilled"] += 1
    conn.commit()
    conn.close()
    return stats


def reorganize_phase1_to_series() -> dict:
    """Phase 1 投入済 100 SKU 各 entry を起点に集約 entry 生成 + parent_series_id backfill.

    1) 既存 individual entry を全件 fetch
    2) 各 hinban の parent_mpn を image_url 経由 (or URL fallback) で推定
    3) AJAX で variation 取得 → 集約 entry 生成 → catalog 投入
       (同じ series 内の複数 individual entry は AJAX cache で重複 fetch 抑制)
    4) backfill_parent_series_id で全 individual entry に parent_series_id 補完
    """
    import sqlite3 as _sql
    conn = _sql.connect(str(api._DB_PATH))
    conn.row_factory = _sql.Row
    cur = conn.cursor()
    cur.execute("""SELECT product_id, specs FROM products WHERE category=?
                   AND product_id NOT LIKE 'workman:series:%'""", (CATEGORY,))
    rows = cur.fetchall()
    conn.close()

    seen_parents: set[str] = set()
    stats = {"total_individual": len(rows), "ajax_calls": 0,
             "aggregates_upserted": 0, "ajax_errors": 0, "no_parent_mpn": 0}
    for r in rows:
        s = json.loads(r["specs"]) if r["specs"] else {}
        # parent_mpn を full_id (= g + 13 桁) から復元
        full_id = s.get("full_id", "")
        if full_id.startswith("g") and len(full_id) == 14:
            parent_mpn = full_id[1:]
        else:
            stats["no_parent_mpn"] += 1
            continue
        if parent_mpn in seen_parents:
            continue
        seen_parents.add(parent_mpn)
        stats["ajax_calls"] += 1
        # existing_data として現 individual entry の specs を渡す
        existing_data = {
            "name_jp":       s.get("hinban") and r["product_id"].split(":")[-1] or "",  # name_jp は別取得
            "price_jpy":     s.get("price_jpy"),
            "brand":         s.get("brand", "Workman"),
            "material_jp":   s.get("material_jp", ""),
            "features":      s.get("features", []),
            "description":   s.get("description", ""),
            "gender":        s.get("gender", "Men"),
            "category_code": s.get("category_code", ""),
            "source_url":    f"https://workman.jp/shop/g/{full_id}/",
        }
        # name_jp は DB から
        cur2 = conn.cursor() if False else None  # placeholder
        # 簡易: r["product_id"] が "workman:<hinban>" 形式、name は別途 DB から
        import sqlite3 as _s2
        _conn2 = _s2.connect(str(api._DB_PATH))
        _conn2.row_factory = _s2.Row
        _r2 = _conn2.execute("SELECT name, name_en FROM products WHERE category=? AND product_id=?",
                              (CATEGORY, r["product_id"])).fetchone()
        _conn2.close()
        if _r2:
            existing_data["name_jp"] = _r2["name"]
        pid = upsert_series_aggregate(parent_mpn, existing_data)
        if pid:
            stats["aggregates_upserted"] += 1
            # name_en propagation: individual entry に name_en あれば 集約 entry にも copy
            if _r2 and _r2["name_en"]:
                _conn3 = _s2.connect(str(api._DB_PATH))
                _conn3.execute("UPDATE products SET name_en=?, name_en_source=? WHERE category=? AND product_id=?",
                                (_r2["name_en"], "individual_entry_copy", CATEGORY, pid))
                _conn3.commit()
                _conn3.close()
        else:
            stats["ajax_errors"] += 1
        time.sleep(0.5)  # rate limit safety

    # 全 individual entry に parent_series_id backfill
    bk = backfill_parent_series_id()
    stats["backfill"] = bk
    return stats


# ============================================================================
# size_chart parser (HQ Phase 2 spec 追加、2026-05-17)
# ============================================================================
# 日本語 size chart label → そのまま catalog 保存 (英訳は HQ 側 _SIZE_CHART_LABEL_EN)
_SIZE_CHART_ROW_LABELS = [
    "ウエスト", "ヒップ", "わたり巾", "わたり幅", "股下", "総丈",
    "胸囲", "肩幅", "袖丈", "着丈", "首回り", "裄丈",
    "対応身長", "対応胸囲", "対応ウエスト",
]


def fetch_size_chart(parent_mpn: str, timeout: int = 15) -> dict:
    """Workman 個別商品 page の「サイズ・スペック」table を parse して size_chart dict 返却.

    Returns:
        {label: {size: value}}.
        例: {"ウエスト": {"M": "76-84", "L": "84-92"}, ...}
        size chart 取得不能なら {} (空 dict).

    全角 → 半角、`〜` → `-`、`cm` 等の単位除去 で値正規化.
    """
    import requests as _req, html as _html_mod

    url = PRODUCT_URL_TEMPLATE.format(full_id=f"g{parent_mpn}")
    try:
        r = _req.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
    except Exception:
        return {}
    if r.status_code != 200:
        return {}

    text = _html_mod.unescape(r.text)
    # 「サイズ・スペック」section を切出し
    sec_m = re.search(r"サイズ・スペック[\s\S]{0,5000}?(?=注意事項|商品説明|お取扱|使用上のご注意|機能|$)", text)
    section = sec_m.group(0) if sec_m else text

    # <table>...<tr>...</tr>...</table> を抽出
    table_m = re.search(r"<table[^>]*>([\s\S]+?)</table>", section)
    if not table_m:
        return {}
    table_html = table_m.group(1)

    # 各 <tr> を行として処理
    rows = re.findall(r"<tr[^>]*>([\s\S]+?)</tr>", table_html)
    if not rows:
        return {}

    # 1 行目 = header (size labels)
    header_cells = _extract_cells(rows[0])
    if not header_cells:
        return {}
    # 先頭セル (空 or 「サイズ」) を除外
    if header_cells and (not header_cells[0] or "サイズ" in header_cells[0]):
        size_headers = [_normalize_size(c.strip()) for c in header_cells[1:] if c.strip()]
    else:
        size_headers = [_normalize_size(c.strip()) for c in header_cells if c.strip()]

    out: dict = {}
    for row in rows[1:]:
        cells = _extract_cells(row)
        if len(cells) < 2:
            continue
        label = cells[0].strip()
        # 既知 label のみ採用
        if not any(label.startswith(lbl) or lbl in label for lbl in _SIZE_CHART_ROW_LABELS):
            continue
        values = cells[1:]
        if len(values) < len(size_headers):
            continue
        row_dict = {}
        for i, sz in enumerate(size_headers):
            if i >= len(values):
                break
            v = _normalize_chart_value(values[i])
            if v:
                row_dict[sz] = v
        if row_dict:
            out[label] = row_dict
    return out


def _extract_cells(row_html: str) -> list[str]:
    """<tr> 内の <td> / <th> を順番に text 抽出."""
    cells = []
    for c_m in re.finditer(r"<t[dh][^>]*>([\s\S]+?)</t[dh]>", row_html):
        raw = c_m.group(1)
        plain = re.sub(r"<[^>]+>", " ", raw)
        plain = re.sub(r"\s+", " ", plain).strip()
        cells.append(plain)
    return cells


def _normalize_chart_value(v: str) -> str:
    """size chart value 正規化: 全角数字 → 半角、〜→ -、単位 'cm' 除去."""
    if not v or v == "-" or v == "ー":
        return ""
    s = v.strip()
    # 全角数字 / 全角ハイフン / 全角チルダ → 半角
    full2half = str.maketrans("０１２３４５６７８９－〜.",
                               "0123456789-~.")
    s = s.translate(full2half)
    # チルダ → ハイフン
    s = s.replace("~", "-").replace("～", "-")
    # 単位 / 空白除去
    s = re.sub(r"\s*cm\s*$", "", s)
    s = re.sub(r"\s*センチ\s*$", "", s)
    s = re.sub(r"\s+", "", s)
    return s


def backfill_size_chart() -> dict:
    """全 workman:series:* 集約 entry に specs.size_chart 投入.

    Rate limit 配慮: 各 fetch 間 0.5s sleep.
    """
    import sqlite3 as _sql
    conn = _sql.connect(str(api._DB_PATH))
    conn.row_factory = _sql.Row
    cur = conn.cursor()
    cur.execute("""SELECT product_id, specs FROM products WHERE category=?
                   AND product_id LIKE 'workman:series:%'""", (CATEGORY,))
    rows = cur.fetchall()
    stats = {"total": len(rows), "fetched": 0, "with_chart": 0, "empty": 0, "errors": 0}
    for r in rows:
        s = json.loads(r["specs"]) if r["specs"] else {}
        parent_mpn = s.get("parent_mpn", "")
        if not parent_mpn:
            stats["errors"] += 1
            continue
        chart = fetch_size_chart(parent_mpn)
        stats["fetched"] += 1
        if chart:
            stats["with_chart"] += 1
        else:
            stats["empty"] += 1
        s["size_chart"] = chart
        cur.execute("UPDATE products SET specs=? WHERE category=? AND product_id=?",
                    (json.dumps(s, ensure_ascii=False), CATEGORY, r["product_id"]))
        time.sleep(0.5)
    conn.commit()
    conn.close()
    return stats


# ============================================================================
# color_en 英訳 (sku_matrix dedup 後の修正用、HQ 2026-05-17 依頼)
# ============================================================================
def backfill_color_en_via_api() -> dict:
    """全 集約 entry の color_variants で color_en が日本語残のものを Claude API 英訳.

    例: 'Ｒブルー：トレッキング' → 'R Blue: Trekking'
        'Ｏホワイト：スタンダード' → 'O White: Standard'
    """
    import anthropic
    import sqlite3 as _sql
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        for p in (Path("C:/dev/iMak_data/credentials/api_key.txt"),
                  Path("C:/dev/iMak/iMakTCG/API key.txt")):
            if p.exists():
                api_key = p.read_text(encoding="utf-8").strip()
                break
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    client = anthropic.Anthropic(api_key=api_key)

    # 1) 翻訳対象の distinct color_jp 抽出 (color_en が ja 残 = 同値 or 空)
    conn = _sql.connect(str(api._DB_PATH))
    conn.row_factory = _sql.Row
    rows = conn.execute("""SELECT product_id, specs FROM products WHERE category=?
                            AND product_id LIKE 'workman:series:%'""", (CATEGORY,)).fetchall()

    needs_translate: set[str] = set()
    for r in rows:
        s = json.loads(r["specs"]) if r["specs"] else {}
        for cv in s.get("color_variants", []):
            cj = cv.get("color_jp", "")
            ce = cv.get("color_en", "")
            # ja 残判定: color_en が空 or color_jp と完全同値 or ASCII 文字 0
            if not ce or ce == cj or not any(c.isascii() and c.isalpha() for c in ce):
                needs_translate.add(cj)
    needs_translate.discard("")
    print(f"distinct color_jp to translate: {len(needs_translate)}")

    # 2) Claude API batch (50/batch)
    translation_map: dict[str, str] = {}
    name_list = sorted(needs_translate)
    SYSTEM = """You are translating Japanese Workman product color names to natural English.

CONVENTIONS:
1. Compound color "<color>：<model>" pattern → "<English color>: <English model>"
   例: Ｒブルー：トレッキング → "R Blue: Trekking"
       Ｏホワイト：スタンダード → "O White: Standard"
       Ｄグリーン：スタンダード → "D Green: Standard"
2. Color prefix (Ｒ Ｏ Ｄ Ｓ Ｂ 等 半角化) is brand-internal code → keep as English letter
   Ｒ → R, Ｏ → O, Ｄ → D, Ｂ → B, Ｓ → S
3. Simple color (ブラック / ホワイト / ネイビー etc) → "Black", "White", "Navy"
4. Full-width letters → half-width (Ｒ → R, "：" → ":")
5. Title Case

OUTPUT: JSON only, no markdown.
Format: {"japanese_name_1": "english_name_1", ...}"""
    BATCH = 50
    for i in range(0, len(name_list), BATCH):
        batch = name_list[i:i+BATCH]
        prompt = f"Translate {len(batch)} Japanese Workman color names to English (eBay-ready):\n\n" + \
                 "\n".join(f"  - {n}" for n in batch) + \
                 "\n\nReturn JSON only: {name_jp: name_en, ...}"
        try:
            resp = client.messages.create(
                model="claude-sonnet-4-6", max_tokens=4000, system=SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            txt = resp.content[0].text.strip()
            m = re.search(r"\{[\s\S]*\}", txt)
            if m:
                txt = m.group(0)
            d = json.loads(txt)
            for k, v in d.items():
                if isinstance(v, str) and v.strip():
                    translation_map[k] = v.strip()
            print(f"  [{i+len(batch)}/{len(name_list)}] translated {len(d)}")
        except Exception as e:
            print(f"  ERR: {type(e).__name__}: {str(e)[:120]}")
        time.sleep(0.3)

    # 3) DB 反映: 集約 entry の color_variants[].color_en 更新
    cur = conn.cursor()
    updated_entries = 0
    for r in rows:
        s = json.loads(r["specs"]) if r["specs"] else {}
        changed = False
        for cv in s.get("color_variants", []):
            cj = cv.get("color_jp", "")
            new_en = translation_map.get(cj)
            if new_en and cv.get("color_en") != new_en:
                cv["color_en"] = new_en
                changed = True
        if changed:
            cur.execute("UPDATE products SET specs=? WHERE category=? AND product_id=?",
                        (json.dumps(s, ensure_ascii=False), CATEGORY, r["product_id"]))
            updated_entries += 1
    conn.commit()
    conn.close()
    return {"distinct_translated": len(translation_map),
            "entries_updated": updated_entries,
            "total_aggregate_entries": len(rows)}


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
    p.add_argument("--ajax", help="parent_mpn を渡して AJAX 単発 fetch")
    p.add_argument("--reorganize", action="store_true",
                    help="Phase 1 既存 100 SKU を集約 entry に re-organize + parent_series_id backfill")
    p.add_argument("--backfill-psid", action="store_true",
                    help="individual entry の parent_series_id のみ backfill (集約 entry 投入なし)")
    p.add_argument("--backfill-size-chart", action="store_true",
                    help="全 集約 entry に specs.size_chart 投入 (個別商品 page parse)")
    p.add_argument("--backfill-color-en", action="store_true",
                    help="集約 entry の color_variants 各 color_en を Claude API で英訳")
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
    elif args.ajax:
        d = fetch_variations_via_ajax(args.ajax)
        print(json.dumps(d, ensure_ascii=False, indent=2))
    elif args.reorganize:
        stats = reorganize_phase1_to_series()
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    elif args.backfill_psid:
        stats = backfill_parent_series_id()
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    elif args.backfill_size_chart:
        stats = backfill_size_chart()
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    elif args.backfill_color_en:
        stats = backfill_color_en_via_api()
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        p.print_help()
