#!/usr/bin/env python3
"""
iMak Trading Japan - モンベルリスティング
スプシのItemIDブランク行を読み込み → Claude APIでリスティング生成 → eBay FileExchange CSV出力

使い方:
  python montbell_listing.py
"""
import csv
import sys
import os
import re
import json
import base64
import time
import requests
from datetime import datetime, timedelta
from collections import Counter

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# API keys
try:
    with open(os.path.join(SCRIPT_DIR, "API key.txt"), "r", encoding="utf-8") as f:
        ANTHROPIC_API_KEY = f.read().strip()
except FileNotFoundError:
    ANTHROPIC_API_KEY = None

# Google Sheets
GSHEET_CREDS = os.path.join(SCRIPT_DIR, "..", "double-hold-421922-7c0d38d3f73d.json")
MONTBELL_SHEET_ID = "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk"  # 統合Hight (2026-04-20移行)
MONTBELL_GID = 851100680
CATEGORY_FILTER = "アウトドア・ジャケット"  # R列(18)

# 出力
DESCRIPTION_FILE = os.path.join(SCRIPT_DIR, "USED.txt")
MODEL = "claude-sonnet-4-20250514"
SCHEDULE_WEEKS = 2

# eBay固定値
RETURN_POLICY = "customer1"
PAYMENT_POLICY = "SALE"
LOCATION = "Japan"
STORE_CATEGORY = 41828939010  # Outdoor Jackets
EBAY_CATEGORY = 57988  # Men's Coats, Jackets & Vests

# eBay API
EBAY_KEYS_FILE = os.path.join(SCRIPT_DIR, "..", "iMakeBayAPI", "ebay keys.txt")
TOP_SELLER_MIN_FEEDBACK = 500
TOP_SELLER_MIN_PERCENTAGE = 98.0

# DDP送料テーブル
SHIPPING_POLICIES = [
    (39, "<39"), (60, "40-60"), (100, "60-100"), (200, "100-200"),
    (300, "200-300"), (400, "300-400"), (500, "400-500"),
    (600, "500-600"), (800, "600-800"), (1000, "800-1000"),
]

# 利益計算パラメータ（SSOT: iMakeBayAPI/profit_params.py 経由で利益計算シートv2を参照）
sys.path.insert(0, os.path.join(SCRIPT_DIR, "..", "iMakeBayAPI"))
from profit_params import compute_min_price_usd, get_exchange_rate, get_category_params
# 共通リスティング処理ライブラリ (2026-04-23 統合)
from listing_common import (
    normalize_title, audit_csv_row, determine_condition_id,
    is_new_condition, get_default_condition_description,
    fetch_amazon_title, extract_sku_from_url as _extract_sku,
    CONDITION_MASTER,
)

# iMakCatalog (2026-05-04 連携): 型番→公式 spec lookup
# memory: catalog_separation_completed.md / category_specialization_principle.md
sys.path.insert(0, os.path.join(SCRIPT_DIR, "..", "iMakCatalog"))
try:
    from api import lookup as _catalog_lookup
except Exception:
    _catalog_lookup = None


# ============================================================================
# iMakCatalog spec → eBay Item Specifics マッピング (2026-05-04)
# ============================================================================
# Color / Size は実物バリエーションなのでメルカリ/Vision 結果を優先 (catalog 上書きしない).
# Brand / Type / Style / 素材 / 機能 / 用途 等は公式値 (catalog) で確定 → whitelist 違反ゼロ.
_CATALOG_SPEC_MAP = {
    "outer_shell_material": "Outer Shell Material",
    "lining_material": "Lining Material",
    "insulation_material": "Insulation Material",
    "fabric_type": "Fabric Type",
    "performance_activity": "Performance/Activity",
    "garment_care": "Garment Care",
    "jacket_coat_length": "Jacket/Coat Length",
    "type": "Type",
    "style": "Style",
    "country_of_origin": "Country/Region of Manufacture",
    "department": "Department",
    "theme": "Theme",
    "fit": "Fit",
    "brand": "Brand",
    "size_type": "Size Type",
    "pattern": "Pattern",
    "accents": "Accents",
    "vintage": "Vintage",
    "handmade": "Handmade",
    "closure": "Closure",
}


def _merge_catalog_spec(specs, catalog_spec):
    """iMakCatalog の specs (snake_case) を eBay Item Specifics (PascalCase) に変換して上書き.
    catalog_spec は確証ある公式値なので、Claude Vision の推測値を上書きする.
    Color / Size はメルカリ商品の実物バリエーションなので touch しない.
    """
    out = dict(specs)
    for cat_key, ebay_key in _CATALOG_SPEC_MAP.items():
        val = catalog_spec.get(cat_key)
        if val:
            out[ebay_key] = val
    # Features (multi, list → カンマ区切り文字列)
    features = catalog_spec.get("features")
    if features:
        out["Features"] = ", ".join(features) if isinstance(features, list) else features
    return out
PROFIT_CATEGORY = "Montbell(ジャケット)"
PRICE_FLOOR_USD = 50
EXCHANGE_RATE = get_exchange_rate()
SHIPPING_JPY = get_category_params(PROFIT_CATEGORY)["shipping_jpy"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://jp.mercari.com/",
}

SYSTEM_PROMPT = """You are an expert eBay listing assistant for iMak Trading Japan.
Generate eBay listing content for montbell outdoor jackets.
※ 2026-04-23 eBay cat 57988 (Men's Coats, Jackets & Vests) フィルタ全項目検証反映

## RULES
- Brand: **montbell** (lowercase, no hyphen) - eBay公式登録ブランド名 (835件主流)
- Title format: montbell [Product Name] [Color] US [Size] (JP [Size]) Pre-owned Japan
- Max 80 characters. STRICT: Never exceed 80.
- Size: JP→US conversion: JP S→US XS, JP M→US S, JP L→US M, JP XL→US L, JP XXL→US XL, JP 3XL→US 2XL
- "Pre-owned Japan" at end (mandatory)
- eBay top keywords: jacket, outdoor, lightweight, hooded, waterproof (if applicable)

## MODEL NUMBER EXTRACTION (最重要・必須)
ユーザーは型番タグが写っている商品のみを選定している。必ず画像から読み取れる前提で探すこと。
- 全ての画像を走査し、洗濯タグ・ブランドタグ・内側ラベル・品質表示に注目する
- モンベルの型番は7桁数字（例: 1128293, 1106654, 1106621）。タグに "No.XXXXXXX" や "品番: XXXXXXX" の形式で記載
- 見つけた型番は必ず item_specifics.Model と model_number に記入する
- 80文字以内に収まる場合のみ、title にも型番を商品名の直後に挿入
- 読み取れない場合のみ空欄（推測・Web検索での補完は禁止）

## ITEM SPECIFICS — eBay公式フィルタ正規値のみ使用
必須:
- Brand: **"montbell"** 固定
- Type: **Jacket / Coat / Vest / Cape / Coatigan** から1つ（Jacket(731)主流）
- Style: 14値enum **only**
  3-in-1 Jacket / Anorak / Biker / Bomber Jacket / Military Jacket / Motorcycle Jacket / Overcoat / **Parka(163)** / **Puffer Jacket(220)** / Quilted / Rain Coat / Trench Coat / Varsity Jacket / **Windbreaker(126)**
  ※ "Shell"/"Soft Shell"/"Hard Shell" は無効 → "Windbreaker"or"Rain Coat"
  ※ "Down Jacket" は無効 → "Puffer Jacket"
  ※ "Light Shell" "Cycle Jacket" 等は "Windbreaker"
- Outer Shell Material: Cotton / Cotton Blend / **Nylon(419)** / Polyamide / **Polyester(189)** / Tweed / Viscose / Wool
- Lining Material: Acetate / Cotton / **Nylon(237)** / Polyamide / Polyester / Wool
- Insulation Material: **Down(364)** / Polyester / Synthetic / Wool
- Closure: 7値enum **only**
  Button / Drawstring / Hook & Eye / Hook & Loop / Lace Up / Snap / **Zip(331)圧倒的**
  ※ "Full Zip"/"Half Zip"/"1/4 Zip" は **Closure フィールド** ではなく **Features フィールド** で使う
  ※ Tシャツの "Pullover" は Jacket では無効
- Pattern: 3値only — **Solid(206)圧倒的** / Camouflage / Geometric
  ※ "Colorblock" は無効 → "Geometric" に正規化
- Department: **Men(734)** / Unisex Adults / Women
- Size: XS / S(120) / M(241) / L(206) / XL(96) / 2XL（"XXL"は無効、"2XL"へ）
- Color: 16色enum
- Theme: **"Outdoor"(364)圧倒的** / 80s / 90s / Classic / City 等
- Performance/Activity: 17値enum **only** (multi可)
  Hiking(314)圧倒的 / Walking(125) / Skiing(53) / Cycling / Golf / Gym & Training / Hockey / Hunting 等
  ※ "Outdoor" は **Performance/Activity フィールドには無効** → "Hiking" に正規化
  ※ "Trekking"/"Camping"/"Trail" も "Hiking" に
- Fabric Type: 8値enum
  Canvas / Denim / Flannel / **Fleece(89)** / Knit / Microfiber / **Softshell(57)** / Tweed
  ※ Outer Shell Material と混同しない（Fabric Type は構造、Outer Shell は素材）
  ※ Nylon/Polyester は Outer Shell Material 側、Fabric Type 側ではない
- Features: 36値enum (multi、カンマ区切り)
  Hooded(115) / Lightweight(364) / **Waterproof(85)** / Windproof(92) / **Full Zip(140)** / Insulated(72) / Pockets(72) / Water Resistant(60) / Packable(40) / Zipped Pockets(44) / Lined(35) / Wind-Resistant(26) / Stretch(16) 等
- Fit: Athletic / Classic / **Regular(307)** / Relaxed / Slim
- Accents: Button / Embroidered / Fur Trim / Glitter / **Logo(152)** / Quilted / Zipper
- Country/Region of Manufacture: タグ確認できれば国名（Japan(151) / China(49) / Vietnam(30) 等）、不明なら "Does not apply"
- Jacket/Coat Length: Short / **Mid-Length(125)** / Long
- Garment Care: Dry Clean Only / Hand Wash Only / **Machine Washable(77)**
- Size Type: Regular(714) / Big & Tall
- Occasion: Business / **Casual(384)** / Formal / Party/Cocktail / Travel(146) / Workwear
固定:
- Vintage: No
- Handmade: No

## OUTPUT FORMAT
Return ONLY valid JSON:
{
  "title": "montbell [Product] [Color] US [Size] (JP [Size]) Pre-owned Japan",
  "product_name": "product name in English",
  "model_number": "7-digit model number from tag if found, else empty",
  "color": "color in English (eBay 16色enumから)",
  "size_jp": "Japanese size",
  "size_us": "US size",
  "condition_description": "Pre-owned. [describe specific condition from seller description]. Please review all photos carefully before purchasing. Sold as-is.",
  "waterproof": true/false,
  "item_specifics": {
    "Brand": "montbell",
    "Type": "Jacket",
    "Size Type": "Regular",
    "Size": "US size (XS/S/M/L/XL/2XL)",
    "Color": "from eBay 16色enum",
    "Department": "Men",
    "Outer Shell Material": "Nylon/Polyester/Cotton等",
    "Style": "from 14値enum (Windbreaker/Parka/Puffer Jacket/Rain Coat等)",
    "Lining Material": "Nylon/Polyester/Cotton等",
    "Insulation Material": "Down/Polyester/Synthetic（断熱材無いjacketは省略）",
    "Theme": "Outdoor",
    "Features": "Hooded, Lightweight, Waterproof等カンマ区切り (36値enumから)",
    "Fabric Type": "Fleece/Softshell/Canvas等（構造系。素材種類はOuter Shell側）",
    "Pattern": "Solid/Camouflage/Geometric の3値のみ",
    "Accents": "Logo",
    "Model": "from model_number",
    "Product Line": "product line name or empty",
    "Closure": "Zip/Button/Drawstring等（"Full Zip"等はFeatures側）",
    "Performance/Activity": "Hiking, Cycling, Skiing等カンマ区切り (Outdoorは無効、Hikingに正規化)",
    "Fit": "Regular",
    "Jacket/Coat Length": "Short/Mid-Length/Long",
    "Vintage": "No",
    "Handmade": "No",
    "Country/Region of Manufacture": "国名 or 'Does not apply'",
    "Garment Care": "Machine Washable"
  }
}
"""


def get_schedule_time():
    return (datetime.utcnow() + timedelta(weeks=SCHEDULE_WEEKS)).strftime("%Y-%m-%d %H:%M:%S")


def get_shipping_policy(price):
    for threshold, policy in SHIPPING_POLICIES:
        if price <= threshold:
            return policy
    return "800-1000"


def load_description():
    try:
        with open(DESCRIPTION_FILE, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "Pre-owned item shipped from Japan."


def build_description(template, product_name, model, color, size_jp, size_us, material, waterproof):
    """USED.txtテンプレートにスペックブロックを挿入"""
    waterproof_text = "Yes (Fully sealed seams)" if waterproof else "No (Water-resistant)"
    specs_html = f"""
<p><span style="text-decoration: underline;"><strong>Product Specifications</strong></span></p>
<ul>
<li><b>Brand:</b> montbell</li>
<li><b>Product:</b> {product_name}</li>
{"<li><b>Model:</b> " + model + "</li>" if model else ""}
<li><b>Material:</b> {material}</li>
<li><b>Color:</b> {color}</li>
<li><b>Size:</b> Japan {size_jp} (US {size_us}), Regular fit</li>
<li><b>Waterproof:</b> {waterproof_text}</li>
<li><b>Condition:</b> Pre-owned</li>
</ul>
<p><strong>⚠ Size Note:</strong> This item is Japan size {size_jp}. The actual fit is equivalent to US size {size_us}. Japanese sizing runs one size smaller than US sizing.</p>
"""
    marker = '<p><span style="text-decoration: underline;"><strong>Shipping'
    if marker in template:
        return template.replace(marker, specs_html + marker)
    return template + specs_html


def get_listing_targets():
    """スプシからItemIDブランクの行を取得"""
    import gspread
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_file(
        GSHEET_CREDS, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(MONTBELL_SHEET_ID)
    ws = sh.get_worksheet_by_id(MONTBELL_GID)
    all_values = ws.get_all_values()

    targets = []
    for i, row in enumerate(all_values[1:], start=2):
        url = row[0] if row[0] else ""
        item_id = row[1] if len(row) > 1 else ""
        title_jp = row[2] if len(row) > 2 else ""
        sold = row[3] if len(row) > 3 else ""
        condition = row[4] if len(row) > 4 else ""
        price = row[5] if len(row) > 5 else ""
        photo_urls = row[6] if len(row) > 6 else ""
        description = row[7] if len(row) > 7 else ""
        model = row[8].strip() if len(row) > 8 else ""  # I列: 型番 (ユーザー手動入力, 7桁数字)

        category = row[17] if len(row) > 17 else ""  # R列
        if url and not item_id and not sold and category == CATEGORY_FILTER:
            targets.append({
                "row": i, "url": url, "title_jp": title_jp,
                "condition": condition, "price_jpy": price,
                "photo_urls": photo_urls, "description": description,
                "model": model,
            })
    return targets


def download_image_b64(url):
    try:
        for try_url in [url, url.split("?")[0]]:
            resp = requests.get(try_url, headers=HEADERS, timeout=15)
            if resp.status_code == 200 and len(resp.content) > 1000:
                return base64.standard_b64encode(resp.content).decode("utf-8")
    except Exception:
        pass
    return None


def call_claude_api(title_jp, description_jp, condition_jp, price_jpy, images_b64, max_retries=2):
    """Claude APIでリスティング情報生成 + ホワイトリスト検証 + 違反時リトライ"""
    import anthropic
    # 2026-05-03 専門化: 共有 whitelist_registry から montbell_whitelist (専用) に切替
    # memory: category_specialization_principle.md / no_modification_chain.md
    try:
        from montbell_whitelist import validate_and_normalize, build_retry_feedback
        validate_fn = validate_and_normalize
        feedback_fn = build_retry_feedback
    except Exception:
        validate_fn = None
        feedback_fn = None

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    content = []
    for img in images_b64:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": img},
        })
    content.append({
        "type": "text",
        "text": f"""Mercari Product:
Title (Japanese): {title_jp}
Condition: {condition_jp}
Price (JPY): {price_jpy}
Description: {description_jp}

Generate an eBay listing for this montbell jacket.""",
    })

    messages = [{"role": "user", "content": content}]
    last_result = None
    retries = max_retries if validate_fn else 0

    for attempt in range(retries + 1):
        try:
            message = client.messages.create(
                model=MODEL, max_tokens=1500, system=SYSTEM_PROMPT,
                messages=messages,
            )
            text = message.content[0].text.strip()
            text = re.sub(r"^```json\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            result = json.loads(text)
        except Exception as e:
            print(f"    ⚠️ Claude API attempt {attempt+1}: {e}")
            return last_result

        if not validate_fn:
            return result

        specs = result.get("item_specifics", {})
        # montbell_whitelist は category 引数不要 (montbell 専用なので)
        normalized, violations = validate_fn(specs)
        result["item_specifics"] = normalized
        last_result = result

        if not violations:
            if attempt > 0:
                print(f"    ✓ ホワイトリスト合格 (attempt {attempt+1})")
            return result

        if attempt >= retries:
            print(f"    ⚠️ {retries+1}回試行後も違反{len(violations)}件:")
            for f, o, _e, r in violations:
                print(f"       - {f}: '{o}' ({r})")
            print(f"    → 正規化値で進行")
            return result

        feedback = feedback_fn(violations)
        print(f"    ↻ ホワイトリスト違反{len(violations)}件、再試行 {attempt+1}/{retries}")
        for vf, vo, _ve, vr in violations:
            print(f"       - {vf}: '{vo}' ({vr})")
        messages.append({"role": "assistant", "content": text})
        messages.append({"role": "user", "content": feedback})

    return last_result


# ===== eBay API =====
def load_ebay_keys():
    keys = {}
    try:
        with open(EBAY_KEYS_FILE, "r") as f:
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    keys[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return keys


def get_ebay_token(app_id, app_secret):
    creds = base64.b64encode(f"{app_id}:{app_secret}".encode()).decode()
    resp = requests.post(
        "https://api.ebay.com/identity/v1/oauth2/token",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": f"Basic {creds}"},
        data={"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_top_seller_specs(token, query, max_items=3):
    url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
    params = {"q": query, "filter": "buyingOptions:{FIXED_PRICE}", "sort": "price", "limit": 50}
    headers = {"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        if resp.status_code != 200:
            return {}, 0, 0
        data = resp.json()
        items = data.get("itemSummaries", [])
        total = data.get("total", 0)
        if not items:
            return {}, total, 0

        prices = [float(i.get("price", {}).get("value", 0)) for i in items if float(i.get("price", {}).get("value", 0)) > 0]
        median = sorted(prices)[len(prices) // 2] if prices else 0

        top_ids = []
        for item in items:
            seller = item.get("seller", {})
            score = seller.get("feedbackScore", 0)
            pct = float(seller.get("feedbackPercentage", "0") or "0")
            if score >= TOP_SELLER_MIN_FEEDBACK and pct >= TOP_SELLER_MIN_PERCENTAGE:
                iid = item.get("itemId", "")
                if iid:
                    top_ids.append(iid)
            if len(top_ids) >= max_items:
                break
        if not top_ids:
            top_ids = [i.get("itemId", "") for i in items[:max_items] if i.get("itemId")]

        all_specs = []
        for iid in top_ids:
            try:
                resp2 = requests.get(f"https://api.ebay.com/buy/browse/v1/item/{iid}", headers=headers, timeout=15)
                if resp2.status_code == 200:
                    aspects = resp2.json().get("localizedAspects", [])
                    specs = {a["name"]: a["value"] for a in aspects if a.get("name") and a.get("value")}
                    if specs:
                        all_specs.append(specs)
                time.sleep(0.3)
            except Exception:
                pass

        merged = {}
        if all_specs:
            all_keys = set()
            for s in all_specs:
                all_keys.update(s.keys())
            for key in all_keys:
                values = [s[key] for s in all_specs if key in s]
                if values:
                    merged[key] = Counter(values).most_common(1)[0][0]

        return merged, total, median
    except Exception as e:
        print(f"    ⚠️ eBay API: {e}")
        return {}, 0, 0


def main():
    print("=== iMak Trading Japan - モンベルリスティング ===\n")

    if not ANTHROPIC_API_KEY:
        print("エラー: API key.txt が見つかりません")
        return

    print("スプシ読み込み中...")
    targets = get_listing_targets()
    print(f"リスティング対象: {len(targets)}件\n")

    if not targets:
        print("リスティング対象がありません。")
        return

    description_template = load_description()

    # eBay API準備
    ebay_keys = load_ebay_keys()
    ebay_token = None
    if ebay_keys.get("AppID") and ebay_keys.get("AppSecret"):
        try:
            ebay_token = get_ebay_token(ebay_keys["AppID"], ebay_keys["AppSecret"])
            print("✓ eBay API接続OK\n")
        except Exception as e:
            print(f"⚠️ eBay API接続失敗: {e}\n")

    # CSV ヘッダー
    csv_headers = [
        "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)",
        "*Category", "*Title", "PicURL", "*StartPrice", "ConditionID",
        "ScheduleTime", "CustomLabel",
        "*Description", "*Format", "*Duration", "*Quantity", "*Location",
        "BestOfferEnabled", "ShippingProfileName", "ReturnProfileName", "PaymentProfileName",
        "ConditionDescription", "StoreCategoryID",
        "C:Brand", "C:Type", "C:Size Type", "C:Size", "C:Color", "C:Department",
        "C:Outer Shell Material", "C:Style", "C:Lining Material", "C:Insulation Material",
        "C:Theme", "C:Features", "C:Fabric Type", "C:Pattern", "C:Accents",
        "C:Model", "C:Product Line", "C:Closure",
        "C:Performance/Activity", "C:Season", "C:Vintage",
        "C:Country/Region of Manufacture", "C:Garment Care",
    ]

    rows = [csv_headers]

    for idx, target in enumerate(targets):
        title_jp = target["title_jp"]
        print(f"[{idx + 1}/{len(targets)}] {title_jp[:60]}")
        print(f"    URL: {target['url']}")

        # === iMakCatalog 連携 (2026-05-04): 型番 lookup → MISS なら SKIP ===
        # 方針 (memory: dropshipping_model_premise / id_strict_with_explicit_rescue):
        #   - catalog HIT → 公式値で Item Specifics 確定、Vision 不要 (画像送信なし)
        #   - catalog MISS → SKIP (Precision 100% / Recall 諦める = CLAUDE.md 大原則)
        #     スプシ I 列に型番未入力 or DB 未登録 = 確証なき出品はしない
        catalog_result = None
        catalog_model = target.get("model")  # スプシ I 列の型番
        if catalog_model and _catalog_lookup is not None:
            try:
                catalog_result = _catalog_lookup("montbell", catalog_model)
            except Exception as e:
                print(f"    ⚠️ iMakCatalog lookup failed: {type(e).__name__}: {e}")
                catalog_result = None

        if not (catalog_result and catalog_result.get("specs")):
            # catalog MISS = SKIP (Vision 推測による誤出品を構造的に禁止)
            print(f"    ⏭️ iMakCatalog miss: {catalog_model or '(型番なし)'} → SKIP (推測出品しない)")
            continue

        cat_name = catalog_result.get("name_jp", "")
        print(f"    🎯 iMakCatalog hit: {catalog_model} ({cat_name})")

        # Claude API (画像送信なし = Vision 不要、title/color/condition_desc 生成のみ)
        images_b64 = []  # catalog 公式値があるので画像不要
        result = call_claude_api(
            title_jp, target["description"], target["condition"],
            target["price_jpy"], images_b64,
        )

        if not result:
            print(f"    ⚠️ 生成失敗 → スキップ")
            continue

        title_en = result.get("title", "")
        specs = result.get("item_specifics", {})
        condition_desc = result.get("condition_description", "")
        product_name = result.get("product_name", "")
        model = catalog_model  # catalog 型番を確定使用
        color = result.get("color", specs.get("Color", ""))
        size_jp = result.get("size_jp", "")
        size_us = result.get("size_us", specs.get("Size", ""))
        waterproof = result.get("waterproof", False)

        # catalog 公式 spec で Item Specifics を確定 (Claude の推測を上書き)
        specs = _merge_catalog_spec(specs, catalog_result["specs"])

        material = specs.get("Outer Shell Material", "Nylon")

        # 80字セーフガード
        if len(title_en) > 80:
            title_en = title_en[:77] + "..."

        # === Title整合性 + 70字パディング (listing_common.normalize_title) ===
        # Mont-bell は条件混在 (新品/中古)、condition_jp から判定
        is_new_montbell = is_new_condition(target.get("condition", ""))
        title_en = normalize_title(
            title_en, is_new=is_new_montbell, item_specifics=specs,
            category="montbell", target_min=70, max_chars=80,
        )
        print(f"    ✨ {title_en} ({len(title_en)}字)")

        # TOPセラーItem Specifics参照
        ebay_median = 0
        if ebay_token:
            ebay_query = f"montbell {product_name} jacket"
            top_specs, ebay_total, ebay_median = fetch_top_seller_specs(ebay_token, ebay_query)
            if top_specs:
                print(f"    📊 eBay {ebay_total}件 中央値${ebay_median:.0f}")
                for key, val in top_specs.items():
                    if key not in specs and val:
                        print(f"    ℹ️ TOPセラー '{key}' = '{val}'（参考）")
                for key, val in top_specs.items():
                    if key in specs and not specs[key] and val:
                        specs[key] = val
                        print(f"    📋 '{key}' をTOPセラー値で補完: {val}")
            time.sleep(0.5)

        # PicURL: メルカリ1枚目のみ
        mercari_urls = [u.strip() for u in target["photo_urls"].split("|") if u.strip()]
        pic_url = mercari_urls[0] if mercari_urls else ""

        # 出品価格
        price_str = re.sub(r"[^0-9]", "", target["price_jpy"])
        cost_jpy = int(price_str) if price_str else 5000
        # SSOT: profit_params経由で利益計算シートv2から算出
        min_price = compute_min_price_usd(cost_jpy, PROFIT_CATEGORY)
        price = max(min_price, PRICE_FLOOR_USD)
        price = round(price, 2)
        price = int(price) + 0.98 if price > 10 else price
        # 価格 status 判定（pricing_engine による相場乖離チェック - SSOT）
        _price_status = "GO"
        try:
            sys.path.insert(0, os.path.join(SCRIPT_DIR, "..", "iMakeBayAPI"))
            from pricing_engine import compute_listing_price as _clp
            _pr = _clp(cost_jpy, ebay_median, PROFIT_CATEGORY)
            _price_status = _pr.get("status", "GO")
            if _price_status == "ALERT":
                print(f"    ⚠️ 価格ALERT: {_pr.get('alert_msg', '')}")
        except Exception as _pe:
            pass

        shipping = get_shipping_policy(price)
        custom_label = f"MB-{datetime.now().strftime('%m%d')}-{idx + 1}"

        print(f"    💲 ${price} (仕入¥{cost_jpy})")

        # Description
        desc = build_description(
            description_template, product_name, model, color,
            size_jp, size_us, material, waterproof,
        )

        # セルフチェック（CSV出力前）
        from listing_validator import validate_and_report
        if not validate_and_report(
            idx + 1, title_en, specs, model, EBAY_CATEGORY, 3000,
            price, pic_url, condition_desc
        ):
            continue

        # CSV行
        row = [
            "Add", EBAY_CATEGORY, title_en, pic_url, price, 3000,
            get_schedule_time(), custom_label,
            desc, "FixedPrice", "GTC", 1, LOCATION,
            1, shipping, RETURN_POLICY, PAYMENT_POLICY,
            condition_desc, STORE_CATEGORY,
            specs.get("Brand", "montbell"),
            specs.get("Type", "Jacket"),
            specs.get("Size Type", "Regular"),
            size_us,
            color,
            specs.get("Department", "Men"),
            specs.get("Outer Shell Material", "Not Specified"),  # 推測NG, 確証ない時は eBay 公式値 Not Specified
            specs.get("Style", "Parka"),
            specs.get("Lining Material", "Not Specified"),
            specs.get("Insulation Material", "Not Specified"),
            specs.get("Theme", "Outdoor"),
            specs.get("Features", "Hooded, Lightweight"),
            specs.get("Fabric Type", "Not Specified"),  # Fabric Type は織り方 (Softshell等)、素材 Nylon は Outer Shell Material 列
            specs.get("Pattern", "Solid"),
            specs.get("Accents", "Logo"),
            model,
            specs.get("Product Line", ""),
            specs.get("Closure", "Full Zip"),
            specs.get("Performance/Activity", "Hiking"),
            specs.get("Season", "Spring, Fall"),
            specs.get("Vintage", "No"),
            specs.get("Country/Region of Manufacture", "Not Specified"),
            specs.get("Garment Care", "Not Specified"),
        ]
        # === 物理ゲート: audit_csv_row error なら HOLDキューへ隔離 ===
        from listing_common import gate_row_or_hold as _gate
        _row_dict = dict(zip(csv_headers, row))
        _allowed, _viol = _gate(_row_dict, category="montbell",
                                 mercari_state=target.get("condition", ""),
                                 sku=custom_label,
                                 price_status=_price_status, median_usd=ebay_median)
        if not _allowed:
            _errs = [f"{f}={i}" for f, i, s in _viol if s == "error"]
            print(f"    🟠 HOLD: {custom_label} → {_errs}")
            continue
        rows.append(row)
        print()
        time.sleep(2)

    # CSV出力
    if len(rows) > 1:
        sys.path.insert(0, os.path.join(SCRIPT_DIR, "..", "iMakeBayAPI"))
        from listing_core import get_csv_output_path
        output_file = get_csv_output_path("montbell", "upload")
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
            writer.writerows(rows)
        print(f"\n完了！出力: {output_file}")
        print(f"成功: {len(rows) - 1}件")

        # チェッカー自動実行
        print(f"\n{'═' * 60}")
        print("  CSVチェックを開始します...")
        print(f"{'═' * 60}\n")
        try:
            import subprocess
            subprocess.run(
                [sys.executable, "check_csv.py", output_file],
                cwd=SCRIPT_DIR,
            )
        except Exception as e:
            print(f"⚠️ チェッカー実行エラー: {e}")

        print(f"\n出品後、スプシのB列にItemIDを手動入力してください。")
    else:
        print("\n出力データなし")


if __name__ == "__main__":
    main()
