#!/usr/bin/env python3
"""
iMak Trading Japan - Tシャツリスティング
スプシのItemIDブランク行を読み込み → Claude APIでリスティング生成 → eBay FileExchange CSV出力

使い方:
  python tshirt_listing.py
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

# Google Sheets (2026-04-20 統合Hightシートに移行、R列カテゴリ"Tシャツ"でフィルタ)
GSHEET_CREDS = os.path.join(SCRIPT_DIR, "..", "double-hold-421922-7c0d38d3f73d.json")
TSHIRT_SHEET_ID = "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk"  # 統合Hight
TSHIRT_GID = 851100680
CATEGORY_FILTER = "Tシャツ"  # R列(18) で絞り込み

# 出力
DESCRIPTION_FILE = os.path.join(SCRIPT_DIR, "NEW.txt")
MODEL = "claude-sonnet-4-6"
SCHEDULE_WEEKS = 2
DEFAULT_PRICE = 100.00

# eBay固定値
RETURN_POLICY = "customer1"
PAYMENT_POLICY = "SALE"
LOCATION = "Osaka"
# ストアカテゴリ（コラボ別）
STORE_CATEGORIES_TSHIRT = {
    "HUNTER×HUNTER": 42143726010,
    "HUNTERxHUNTER": 42143726010,
    "Yu Yu Hakusho": 42143723010,
    "Jujutsu Kaisen": 41923120010,
    "ONE PIECE": 41827407010,
    "One Piece": 41827407010,
    "Pokemon": 41827408010,
    "Pokémon": 41827408010,
    "Dragon Ball": 41827406010,
    "Demon Slayer": 41827411010,
    "Zelda": 41923127010,
    "Kaiju No. 8": 41923138010,
    "Kaiju No.8": 41923138010,
    "Kaiju": 41923138010,
    "Attack on Titan": 41827410010,
    "Gundam": 41827409010,
    "Naruto": 41827412010,
    "Star Wars": 41905480010,
    "Evangelion": 41923115010,
    "Final Fantasy": 41923116010,
    "SPYxFAMILY": 41923124010,
    "SPY×FAMILY": 41923124010,
    "Oshi no Ko": 41923126010,
    "Ghost in the Shell": 41923128010,
    "KAWS": 41923129010,
    "My Hero Academia": 41923131010,
    "Dandadan": 41937256010,
    "DANDADAN": 41937256010,
    "Chainsaw Man": 41959364010,
    "Band": 41832372010,
    "URUSEI YATSURA": 41923136010,
    "Berserk": 41827413010,
    "Disney": 41827413010,
    "Marvel": 41827413010,
}
STORE_CATEGORY_DEFAULT = 41827413010  # others

# DDP送料テーブル
SHIPPING_POLICIES = [
    (39, "<39"), (60, "40-60"), (100, "60-100"), (200, "100-200"),
    (300, "200-300"), (400, "300-400"), (500, "400-500"),
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
PROFIT_CATEGORY = "Tシャツ(UT)"
PRICE_FLOOR_USD = 30
# 後方互換用（既存コードが参照していた場合のため）
EXCHANGE_RATE = get_exchange_rate()
SHIPPING_JPY = get_category_params(PROFIT_CATEGORY)["shipping_jpy"]

# UNIQLO公式API
UNIQLO_API = "https://www.uniqlo.com/jp/api/commerce/v5/ja/products"

# eBay API（Item Specifics参照のみ。価格計算には使わない）
EBAY_KEYS_FILE = os.path.join(SCRIPT_DIR, "..", "iMakeBayAPI", "ebay keys.txt")
TOP_SELLER_MIN_FEEDBACK = 500
TOP_SELLER_MIN_PERCENTAGE = 98.0

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://jp.mercari.com/",
}


def _size_type(size, department):
    """eBay が受け付ける Size Type (共通実装に委譲。ここで作り直さない)。"""
    try:
        from listing_common import size_type_for
    except ImportError:
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "..", "iMakeBayAPI"))
        from listing_common import size_type_for
    return size_type_for(size, department)


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
    """eBay検索してTOPセラーのItem Specificsを取得"""
    # 検索
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

        # 全セラー中央値
        prices = [float(i.get("price", {}).get("value", 0)) for i in items if float(i.get("price", {}).get("value", 0)) > 0]
        median = sorted(prices)[len(prices)//2] if prices else 0

        # TOPセラーのアイテムIDを取得
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

        # 各アイテム詳細からItem Specifics取得
        from collections import Counter
        all_specs = []
        for iid in top_ids:
            try:
                detail_url = f"https://api.ebay.com/buy/browse/v1/item/{iid}"
                resp2 = requests.get(detail_url, headers=headers, timeout=15)
                if resp2.status_code == 200:
                    aspects = resp2.json().get("localizedAspects", [])
                    specs = {a["name"]: a["value"] for a in aspects if a.get("name") and a.get("value")}
                    if specs:
                        all_specs.append(specs)
                time.sleep(0.3)
            except Exception:
                pass

        # 集約（最頻値）
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

# 研究メタデータ（PDF/TOPセラー調査記録、四半期更新時に再調査）
RESEARCH_METADATA = {
    "last_updated": "2026-04-22",
    "status": "researched",
    "pdf_top30_note": "Clothing_Shoes_Accessories_2026Q1.pdf 上位30はLouis Vuitton/Coach等の高級バッグ寡占。UNIQLO/T-Shirtは上位外。Theme(Anime/Music/Video Games)とCharacter Familyで検索される傾向",
    "top_seller_samples": [
        "leopardspotboutique fb=2385: Brand=UNIQLO UT, Theme='Retro, Music', Features='Breathable, Lightweight, Stretch'",
        "therandomfashionstore fb=5002: Brand=Uniqlo, Product Line=Uniqlo UT, Character Family=Doraemon, Year Manufactured='2010-2019', Season='Spring, Summer, Fall', Accents=Logo",
        "terrasu fb=16155: Department=Men, Theme='Video Games, Space, Retro', Country of Origin=Bangladesh, Features='All Seasons, Tagless'",
        "タイトル: 'UNIQLO UT [Collab] [Character] T Shirt [Color] [Size]' or 'Uniqlo UT [Character] Mens [Size] [Color] [Theme] Graphic Tee'"
    ],
    "note": "2026-04-22 PDF + 3 TOPセラー(leopardspotboutique/therandomfashionstore/terrasu)調査済"
}

SYSTEM_PROMPT = """You are an expert eBay listing assistant for iMak Trading Japan.
Generate eBay listing content for UNIQLO UT T-shirts.
※ TOPセラー(fb>2000) 調査結果を反映 (2026-04-22)

## TITLE RULES
- Max 80 characters, English only
- Format: UNIQLO UT [Collab/Series] [Character] T-Shirt [Color] US [Size] (JP [Size]) NWT Japan
- Size MUST be in format: "US L (JP XL)" — always show both
- MUST INCLUDE: "T-Shirt", "Short Sleeve" (もしくは "Tee" のみ可), "Men" (Department明確化)
- "T-Shirt" 推奨 (検索ボリューム高)、"Tee" は補助
- NWT = New With Tags
- 80字超過時: "Short Sleeve" → "Men's" → collab/character短縮 の順で削減
- 70字未満なら "Graphic" "Anime" "Music" "Video Games" 等で埋める
- Size: JP→US: JP S→US XS, JP M→US S, JP L→US M, JP XL→US L, JP XXL→US XL, JP 3XL→US 2XL, JP 4XL→US 3XL
- "Japan" at end (Japan exclusive)

## MODEL NUMBER EXTRACTION
- 画像から型番（UNIQLO UTは6桁数字、例 471234）を読み取れた場合のみ item_specifics.Model と model_number に記入
- **タイトルには型番を含めない**（ユーザー指示）
- 読み取れない場合は空欄（推測禁止）

## ITEM SPECIFICS — TOPセラー(fb>2000) 標準構成
必須:
- Brand: **"Uniqlo" 固定**（eBay公式登録ブランド名は "Uniqlo" のみ、19,799件。"UNIQLO UT" は eBayに無いブランド名なので絶対禁止 - フィルタヒットせず売上機会喪失）
- Type: T-Shirt
- Size Type: Regular
- Size: US表記 (XS/S/M/L/XL/2XL/3XL)
- Color
- Department: "Unisex Adults" 推奨 (TOPセラー leopardspotboutique慣習)。性別明示なら "Men"/"Women"
- Theme: **eBay公式フィルタ値のみ使用**（複数値カンマ区切り可）
  有効値: Anime / Music / Retro / Cars / Quotes / Movie / Hip Hop / Rock / Cartoon / Comics / Cosplay / Video Games / Funny / Space / Nature / Sports / Holiday / Travel
  ※ "Anime & Manga" は無効（eBayフィルタ値は "Anime" のみ）。"Manga" 単独も不可
  ※ コラボ性質に応じて: アニメ→"Anime"、音楽→"Music, Retro"、ゲーム→"Video Games, Retro"、映画→"Movie, Retro"
- Character: キャラ名を記入。**eBay公式フィルタリストにある名前は完全一致で記入**（フィルタヒットする）。リスト外でも記入する（フィルタは効かないが検索インデックスには載る）
  ホワイトリスト（UT関連の主要キャラ抜粋。完全一致時はフィルタヒット）:
    Doraemon / Hatsune Miku / Hello Kitty / Pochacco / Astro Boy / Snoopy / Garfield /
    Mickey Mouse / Minnie Mouse / Donald Duck / Goofy / Pluto / Stitch / Bambi / Belle /
    Cinderella / Elsa / Rapunzel / Tinker Bell / Winnie The Pooh / Eeyore /
    Buzz Lightyear / Lightning McQueen / WALL-E /
    Yoda / Darth Vader / Luke Skywalker / Chewbacca / Boba Fett / Stormtrooper / Kylo Ren / R2-D2 / C-3PO /
    Spider-Man / Iron Man / Captain America / Black Panther / Black Widow / Wolverine / Deadpool / Venom /
    The Hulk / Hero / Groot / Star-Lord / Vision / Scarlet Witch / Storm / Cyclops / Gambit / Cable /
    Captain Marvel / Aquaman / Batman / Superman / Wonder Woman / Harley Quinn /
    Eevee / Squirtle / Articuno / Kirby / Luigi / Bowser / Donkey Kong / Link /
    SpongeBob SquarePants / Bart Simpson / Stewie Griffin / Brian Griffin / Cartman / Kenny / Kyle /
    Harry Potter / Draco Malfoy / Gandalf / Godzilla / E.T. / Frankenstein / Dracula /
    Bugs Bunny / Daffy Duck / Tweety / Scooby-Doo / Optimus Prime
  ※ Goku / Luffy / Tanjiro / Gojo / Naruto / Eren / Pikachu 等は eBay フィルタリストに無いが、**そのまま記入**（検索インデックス用）。フィルタ完全一致は逃すが空欄よりマシ
  ※ ホワイトリスト一致を優先するため、表記ゆれは正規化: Hello Kitty (× HelloKitty) / Spider-Man (× Spiderman) / The Hulk (× Hulk)
- Character Family: 自由文字列（公式フィルタリスト無し）。シリーズ/franchise名を入れる
  例: "Dragon Ball" / "One Piece" / "Demon Slayer" / "Jujutsu Kaisen" / "Naruto" / "Pokémon" / "Doraemon" / "Star Wars" / "Marvel" / "DC Comics" / "Disney"
- Pattern: Graphic Print (基本) / Floral / Solid
- Sleeve Length: Short Sleeve
- Neckline: Crew Neck
- Material: Cotton (基本) / 100% Cotton
- Fit: Regular
- Style: "Basic Tee" / "Graphic Tee" (デフォルトは "Graphic Tee" — UT はキャラ柄が主)
- Closure: "Pullover" 固定 (Tシャツは被るタイプなのでこれが eBay フィルタ正規値)
- Product Line: Uniqlo UT (Brand=Uniqloの場合は必須)
推奨:
- Fabric Type: Jersey
- Features: 複数値カンマ区切り (例: "Breathable, Lightweight, Stretch" / "All Seasons, Tagless")
- Accents: "Logo" (UNIQLO UT は logo付き多い)
- Season: "Spring, Summer, Fall" (春夏秋向け)
- Year Manufactured: 範囲表記 "2010-2019" / "2020-2029"
- Country of Origin: "Bangladesh" / "Vietnam" / "China" / "Indonesia" (UNIQLO海外生産。タグから読めれば。読めなければ "Does not apply")
固定:
- Vintage: No
- Personalize: No
- Handmade: No
- Garment Care: Machine Washable

## OUTPUT FORMAT
Return ONLY valid JSON:
{
  "title": "eBay title max 80 chars",
  "collab": "collaboration name in English",
  "character": "character name. If in eBay whitelist (Doraemon/Stitch/Yoda/Spider-Man/Eevee etc) use exact spelling for filter hit. If not in whitelist (Goku/Luffy/Tanjiro/Pikachu etc) still fill in for search index — never leave blank when character is identifiable",
  "character_family": "series/franchise name, free text (e.g. Dragon Ball, One Piece, Demon Slayer, Pokémon, Doraemon, Star Wars, Marvel)",
  "color": "color in English",
  "size_jp": "Japanese size",
  "size_us": "US size",
  "model_number": "6-digit product number from tag if readable, else empty",
  "theme_keywords": "comma-separated eBay filter values only (e.g. 'Anime' or 'Video Games, Retro' or 'Music, Retro'). NEVER 'Anime & Manga'",
  "country_of_origin": "Bangladesh/Vietnam/China/Indonesia if readable from tag, else 'Does not apply'",
  "year_range": "2020-2029 (recent) or 2010-2019 (older collab) - guess from collab era",
  "condition_description": "Brand new with tags. Shipped directly from Japan.",
  "about_collab": "1-3 English sentences translating the official collaboration text if one is given in the catalog facts, else empty",
  "item_specifics": {
    "Brand": "Uniqlo",
    "Type": "T-Shirt",
    "Size Type": "Regular",
    "Size": "US size",
    "Color": "color",
    "Department": "Unisex Adults",
    "Theme": "from theme_keywords",
    "Character": "character name",
    "Character Family": "from character_family",
    "Style": "Graphic Tee",
    "Pattern": "Graphic Print",
    "Neckline": "Crew Neck",
    "Sleeve Length": "Short Sleeve",
    "Closure": "Pullover",
    "Material": "Cotton",
    "Fabric Type": "Jersey",
    "Fit": "Regular",
    "Model": "from model_number",
    "Product Line": "Uniqlo UT",
    "Features": "Breathable, Lightweight",
    "Accents": "Logo",
    "Season": "Spring, Summer, Fall",
    "Year Manufactured": "from year_range",
    "Vintage": "No",
    "Personalize": "No",
    "Handmade": "No",
    "Country/Region of Manufacture": "from country_of_origin",
    "Garment Care": "Machine Washable"
  }
}
"""


def get_schedule_time():
    future = datetime.utcnow() + timedelta(weeks=SCHEDULE_WEEKS)
    return future.strftime("%Y-%m-%d %H:%M:%S")


def get_shipping_policy(price):
    """V6/V5/Free モード別 Shipping Profile 名 (listing_common 経由)."""
    try:
        from listing_common import get_shipping_policy_name
        return get_shipping_policy_name(price, "Tシャツ(UT)")
    except Exception:
        for threshold, policy in SHIPPING_POLICIES:
            if price <= threshold:
                return policy
        return "400-500"


def load_description():
    try:
        with open(DESCRIPTION_FILE, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "Brand new item shipped from Japan."


def build_description(template, collab, color, size_jp, size_us, cat=None, about_en=""):
    """NEW.txtテンプレートにスペックブロックを挿入

    cat: 目視で特定した行のカタログの値 (ut_catalog_values.build_values)。
         ★2026-09-11: ある時は素材・原産国・実寸を **カタログから** 出す (無い時は従来どおり)。
         ★2026-09-13: ある時は **スキルの形** (コラボ紹介 / Specs / 全サイズ実測表 / Fit note / 透け感)。
           サイズ表記は US が先 (ユーザー「タイトルと逆。タイトルに合わせて」)
    """
    marker = '<p><span style="text-decoration: underline;"><strong>Shipping'
    if cat:
        import ut_catalog_values as _UCV
        block = _UCV.description_html(cat, collab_en=cat.get("work_en") or collab, about_en=about_en)
        return template.replace(marker, block + marker) if marker in template else template + block
    material = (cat or {}).get("material_line") or "100% Cotton"
    origin = (cat or {}).get("origin_line") or ""
    chart = (cat or {}).get("chart_html") or ""
    note_tail = ("See the actual measurements below." if chart
                 else "Please refer to the size chart images for detailed measurements.")
    specs_html = f"""
<p><span style="text-decoration: underline;"><strong>Product Specifications</strong></span></p>
<ul>
<li><b>Collaboration:</b> {collab}</li>
<li><b>Brand:</b> Uniqlo UT</li>
<li><b>Material:</b> {material}</li>
""" + (f"<li><b>Country of Origin:</b> {origin}</li>\n" if origin else "") + f"""<li><b>Color:</b> {color}</li>
<li><b>Size:</b> Japan {size_jp} (US {size_us}), Regular fit</li>
<li><b>Condition:</b> Brand new with tags</li>
</ul>
<p><strong>⚠ Size Note:</strong> This item is Japan size {size_jp}. The actual fit is equivalent to US size {size_us}. {note_tail}</p>
{chart}"""
    # Shipping セクションの直前にスペックブロックを挿入
    marker = '<p><span style="text-decoration: underline;"><strong>Shipping'
    if marker in template:
        return template.replace(marker, specs_html + marker)
    # マーカーが見つからなければ末尾に追加
    return template + specs_html


def get_listing_targets():
    """スプシからItemIDブランクの行を取得"""
    import gspread
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_file(
        GSHEET_CREDS, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(TSHIRT_SHEET_ID)
    ws = sh.get_worksheet_by_id(TSHIRT_GID)
    all_values = ws.get_all_values()
    header = all_values[0]

    # 再出品ボタン経由時の SKU filter (env var)
    only_skus = set(
        s.strip() for s in os.environ.get("SELLER_HUB_RELIST_ONLY_SKUS", "").split(",")
        if s.strip()
    )

    def _sku_of(u: str) -> str:
        return u.split("?")[0].split("#")[0].rstrip("/")[-12:].lstrip("/") if u else ""

    targets = []
    for i, row in enumerate(all_values[1:], start=2):
        url = row[0] if row[0] else ""
        item_id = row[1] if len(row) > 1 else ""
        title_jp = row[2] if len(row) > 2 else ""
        sold = row[3] if len(row) > 3 else ""
        condition = row[4] if len(row) > 4 else ""
        # 仕入参考: N列 (実コスト) 優先 / F列 (商品価格) fallback (2026-05-18)
        sys.path.insert(0, os.path.join(SCRIPT_DIR, "..", "iMakeBayAPI"))
        from listing_common import pick_cost_jpy as _pick_cost
        price = _pick_cost(row)  # 旧: row[5] (F商品価格のみ)
        photo_urls = row[6] if len(row) > 6 else ""
        description = row[7] if len(row) > 7 else ""
        category = row[17] if len(row) > 17 else ""  # R列
        size_text = row[19] if len(row) > 19 else ""  # T列 (目視で特定した行のサイズ)

        # 再出品 SKU filter 適用時は URL末尾12文字一致のみ通す
        if only_skus and _sku_of(url) not in only_skus:
            continue

        # カテゴリフィルタ + ItemIDブランク & 売り切れでない = リスティング対象
        if url and not item_id and not sold and category == CATEGORY_FILTER:
            targets.append({
                "row": i,
                "url": url,
                "title_jp": title_jp,
                "condition": condition,
                "price_jpy": price,
                "photo_urls": photo_urls,
                "description": description,
                "size_text": size_text,
            })
    return targets, ws, all_values


def get_uniqlo_official_image(collab_name):
    """UNIQLO公式APIからコラボ商品の画像URLを取得"""
    try:
        resp = requests.get(
            UNIQLO_API,
            params={"q": collab_name, "offset": 0, "limit": 5},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        items = resp.json().get("result", {}).get("items", [])
        collab_lower = collab_name.lower()
        matching = [i for i in items if collab_lower in i.get("name", "").lower()]
        if matching:
            pid = matching[0].get("productId", "").replace("E", "").split("-")[0]
            if pid:
                return f"https://image.uniqlo.com/UQ/ST3/jp/imagesgoods/{pid}/item/jpgoods_09_{pid}_3x4.jpg"
        return None
    except Exception:
        return None


def download_image_b64(url):
    """画像URLをbase64でダウンロード"""
    try:
        for try_url in [url, url.split("?")[0]]:
            resp = requests.get(try_url, headers=HEADERS, timeout=15)
            if resp.status_code == 200 and len(resp.content) > 1000:
                return base64.standard_b64encode(resp.content).decode("utf-8")
    except Exception:
        pass
    return None


def _detect_media_type(b64_data):
    """base64画像データの magic bytes から media_type を判定(2026-06-21)。

    mercari は webp 配信があり、image/jpeg 固定だと Claude API が
    'image appears to be a image/webp' で 400 拒否 → 生成失敗。実形式を渡して回避。
    Claude は jpeg/png/gif/webp 全対応。判定不能時は jpeg。
    """
    try:
        head = base64.b64decode(b64_data[:64])
    except Exception:
        return "image/jpeg"
    if head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/jpeg"


def _parse_json_lenient(text):
    """Claude応答 → dict。JSON の後に説明文が付く場合(Extra data error)に堅牢化(2026-06-21)。

    まず素直に loads、失敗したら先頭の '{' から raw_decode で 1個目の JSON value だけ取る
    (末尾の余分なテキストを無視)。
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start < 0:
            raise
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
        return obj


def call_claude_api(title_jp, description_jp, condition_jp, price_jpy, images_b64, max_retries=2,
                    facts=""):
    """Claude APIでリスティング情報生成 + ホワイトリスト検証 + 違反時リトライ.
    違反があればフィードバックを添えて再リクエスト（最大max_retries回）。
    最後まで違反残れば正規化値で進めて警告表示。"""
    import anthropic
    sys.path.insert(0, os.path.join(SCRIPT_DIR, "..", "iMakeBayAPI"))
    from whitelist_registry import validate_and_normalize, build_retry_feedback
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    content = []
    for img in images_b64:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": _detect_media_type(img), "data": img},
        })
    content.append({
        "type": "text",
        "text": f"""Mercari Product:
Title (Japanese): {title_jp}
Condition: {condition_jp}
Price (JPY): {price_jpy}
Description: {description_jp}
{facts}
Generate an eBay listing for this UNIQLO UT T-shirt.""",
    })

    messages = [{"role": "user", "content": content}]
    last_result = None
    for attempt in range(max_retries + 1):
        try:
            message = client.messages.create(
                model=MODEL, max_tokens=1500, system=SYSTEM_PROMPT,
                messages=messages,
            )
            text = message.content[0].text.strip()
            text = re.sub(r"^```json\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            result = _parse_json_lenient(text)
        except Exception as e:
            print(f"    ⚠️ Claude API attempt {attempt+1}: {e}")
            return last_result  # 直前成功結果があればそれを返す

        # ホワイトリスト検証＋正規化
        specs = result.get("item_specifics", {})
        normalized, violations = validate_and_normalize(specs, "tshirt")
        result["item_specifics"] = normalized
        last_result = result

        if not violations:
            if attempt > 0:
                print(f"    ✓ ホワイトリスト合格 (attempt {attempt+1})")
            return result

        if attempt >= max_retries:
            # 最大リトライ後も違反残るなら警告して進行
            print(f"    ⚠️ {max_retries+1}回試行後も違反{len(violations)}件:")
            for f, o, _e, r in violations:
                print(f"       - {f}: '{o}' ({r})")
            print(f"    → 正規化値で進行")
            return result

        # 違反あり → フィードバック付き再リクエスト
        feedback = build_retry_feedback(violations)
        print(f"    ↻ ホワイトリスト違反{len(violations)}件、再試行 {attempt+1}/{max_retries}")
        for vf, vo, _ve, vr in violations:
            print(f"       - {vf}: '{vo}' ({vr})")
        messages.append({"role": "assistant", "content": text})
        messages.append({"role": "user", "content": feedback})

    return last_result


def build_pic_url(mercari_photo_urls):
    """メルカリTOP画像1枚のみ（サイズチャートは手動アップロード）"""
    mercari_urls = [u.strip() for u in mercari_photo_urls.split("|") if u.strip()]
    if mercari_urls:
        return mercari_urls[0]
    return ""


def main():
    print("=== iMak Trading Japan - Tシャツリスティング ===\n")

    if not ANTHROPIC_API_KEY:
        print("エラー: API key.txt が見つかりません")
        return

    # ★2026-09-13 ユーザー「目視が入るから、自動で動かそう」: PSA の 🤖自動
    #   (PSA_VERIFY_BEFORE_BUILD=1 / PSA_BATCH_LIMIT=20) と同じ形。**先に目視** → 人が選んだ行
    #   だけが商品管理シートに入る → それを生成する。目視を閉じた / 時間切れでも止めない
    #   (選ばれなかった行はシートに入らないので、生成に紛れ込む経路が無い)。
    _batch = 0
    try:
        _batch = max(0, int(os.environ.get("UT_BATCH_LIMIT") or 0))
    except ValueError:
        _batch = 0
    if os.environ.get("UT_IDENTIFY_BEFORE_BUILD") == "1":
        import subprocess
        _tools = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "iMakHQ", "tools"))
        _cmd = [sys.executable, "ut_identify.py", "--new-only", f"--limit={_batch or 20}"]
        print(f"🔎 先に目視 (売れ筋順・新しく出す候補だけ {_batch or 20}件) …")
        _r = subprocess.run(_cmd, cwd=_tools)
        if _r.returncode != 0:
            print("⚠ 目視が確定されませんでした。シートに既にある分だけ生成します")

    # スプシからリスティング対象を取得
    print("スプシ読み込み中...")
    targets, ws, all_values = get_listing_targets()
    # ★2026-09-13: 🤖自動 は **目視で商品を決めた行だけ** 作る (PSA の「確定したカードだけ生成」と同じ)。
    #   決めていない行は カタログ画像も カタログの値も無く、仕入元の写真1枚 + AI の推測で出てしまう
    #   (ユーザー確定「メインはカタログ画像」に反する)。その行は目視特定か 新規ボタンで扱う
    if os.environ.get("UT_IDENTIFY_BEFORE_BUILD") == "1":
        import ut_catalog_values as _UCV0
        _led0 = _UCV0.load_ledger()
        _unid = [t for t in targets if _UCV0.decision_for(t["url"], _led0) != "go"]
        if _unid:
            print(f"⏭ 目視で商品を決めていない {len(_unid)}件は自動では出しません "
                  f"(行 {', '.join(str(t['row']) for t in _unid[:10])})")
        targets = [t for t in targets if _UCV0.decision_for(t["url"], _led0) == "go"]
    if _batch and len(targets) > _batch:
        print(f"⚠️ {len(targets)}件中 {_batch}件を処理 (残 {len(targets) - _batch}件は次回)")
        targets = targets[:_batch]
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

    # eBay FileExchange CSV ヘッダー
    csv_headers = [
        "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)",
        "*Category", "*Title", "PicURL", "*StartPrice", "ConditionID",
        "ScheduleTime", "CustomLabel",
        "*Description", "*Format", "*Duration", "*Quantity", "*Location",
        "BestOfferEnabled", "ShippingProfileName", "ReturnProfileName", "PaymentProfileName",
        "ConditionDescription", "StoreCategoryID",
        "C:Brand", "C:Type", "C:Size Type", "C:Size", "C:Color", "C:Department",
        "C:Style", "C:Theme", "C:Character", "C:Character Family", "C:Pattern",
        "C:Neckline", "C:Sleeve Length", "C:Material", "C:Fabric Type",
        "C:Features", "C:Fit", "C:Product Line", "C:Model", "C:Accents",
        "C:Year Manufactured", "C:Vintage", "C:Personalize", "C:Handmade",
        # ★2026-09-11 (№137): Tシャツ (15687) の eBay の項目名は "Country of Origin"。
        #   "Country/Region of Manufacture" はこのカテゴリに存在せず、フィルタに載っていなかった
        #   (Taxonomy API で確認: 244か国から選ぶ形 / "Does not apply" は選択肢に無い)
        "C:Country of Origin", "C:Garment Care", "C:Season", "C:Closure",
    ]

    rows = [csv_headers]

    # ★2026-09-11 ユーザー「カタログの値」: 目視で特定した行 (iMakHQ/tools/ut_identify.py) は
    #   色・素材・原産国・サイズ表などを **カタログから写す** (写真から AI に推測させない)。
    #   特定されていない行は従来どおり。
    import ut_catalog_values as UCV
    from whitelist_registry import validate_and_normalize as _wl_validate
    ut_ledger = UCV.load_ledger()
    # ★2026-09-12 ユーザー「補の概念とか重複出品とか PSA と同じ運用にするんだよ」(設計 iMakHQ/UT_FLOW.md):
    #   同じ商品・色・サイズが**既に出品中**なら出さない。捨てずに、その出品の補URLに足す
    #   (無在庫なので仕入元は多いほど強い。PSA の「2つ目は補URLへ」と同じ)
    ut_listed = UCV.listed_identities(all_values, ut_ledger)
    # 公式仕入で出している商品 (バリエーション出品) とも重ねない。同じ商品・色・サイズは eBay から見て同じ物
    ut_official = UCV.load_official_identities()
    ut_aux_add = {}
    ut_run = {}          # この走行で CSV に入れた分 (同じ走行に同じ物が2つある時も1つだけ出す)

    def _aux_of(sheet_row):
        r = all_values[sheet_row - 1] if len(all_values) >= sheet_row else []
        return [u.strip() for u in r[UCV.COL_AUX_START:UCV.COL_AUX_START + UCV.AUX_MAX]
                if u.strip()] if len(r) > UCV.COL_AUX_START else []

    for idx, target in enumerate(targets):
        title_jp = target["title_jp"]
        print(f"[{idx+1}/{len(targets)}] {title_jp[:50]}")
        print(f"    URL: {target['url']}")

        # ★2026-09-12: 目視で「対象外」「一致・見送り」にした行は出さない
        #   (まとめ売り・中古・今回は買わない と決めた物を、AI の推測で出してしまわないため)
        _dec = UCV.decision_for(target["url"], ut_ledger)
        if _dec in ("skip", "out"):
            print(f"    ⏸ 目視で{'見送り' if _dec == 'skip' else '対象外'}にした行 → スキップ")
            continue

        cat_v = None
        try:
            cat_v = UCV.values_for_url(target["url"], target.get("size_text", ""), ut_ledger,
                                       title=title_jp)
        except UCV.NotListable as e:
            # 特定済みなのに写せない = 推測に戻さない。その行は出さない
            print(f"    ⏸ 目視で特定済みだが カタログの値で出せない → スキップ: {e}")
            continue
        if cat_v:
            print(f"    📚 目視で特定済み {cat_v['product_id']} → 色/素材/原産国/サイズ表をカタログから写す")
            # KEY は出品に出す値 (CSV の C:Model / C:Color / C:Size) と同じ材料で作る
            _key = UCV.identity_key(cat_v["product_id"], cat_v["specs"]["Color"], cat_v["size_jp"])
            _off = ut_official.get(_key)
            if _off:
                # 公式仕入の出品が同じ商品・色・サイズを持っている → 出さない
                # (補URLの欄が無い出品なので、回す先も無い。仕入元は残るので後で使える)
                print(f"    ⏸ 公式仕入で出品中 ({_off['item_id']} / 公式在庫 {_off['official_stock'] or '?'}) "
                      f"→ 二重出品にしない")
                continue
            _live = ut_listed.get(_key) or ut_run.get(_key)
            if _live:
                # 二重出品にしない。この仕入元は既存の出品の補URLに回す
                _urls = UCV.merge_aux(_live["aux"], target["url"])
                if _urls != _live["aux"]:
                    ut_aux_add[_live["row"]] = _urls
                    _live["aux"] = _urls
                    print(f"    ♻ 同じ商品・色・サイズが出品中 ({_live['item_id']}) "
                          f"→ 出さずに補URLに足す")
                else:
                    print(f"    ⏸ 同じ商品・色・サイズが出品中 ({_live['item_id']}) "
                          f"/ 補URLは満杯かすでに登録済み → スキップ")
                continue

        # 画像取得
        photo_urls = target["photo_urls"]
        images_b64 = []
        if photo_urls:
            for url in photo_urls.split("|")[:3]:
                b64 = download_image_b64(url.strip())
                if b64:
                    images_b64.append(b64)

        if not images_b64:
            print(f"    ⚠️ 画像取得失敗 → スキップ")
            continue

        # Claude API
        print(f"    Claude API送信中（画像{len(images_b64)}枚）...")
        result = call_claude_api(
            title_jp, target["description"], target["condition"],
            target["price_jpy"], images_b64,
            facts=UCV.catalog_facts_text(cat_v) if cat_v else "",
        )

        if not result:
            print(f"    ⚠️ 生成失敗 → スキップ")
            continue

        title_en = result.get("title", "")
        collab = result.get("collab", "")
        specs = result.get("item_specifics", {})
        condition_desc = result.get("condition_description", "")
        if cat_v:
            try:
                specs = UCV.apply_to_specs(specs, cat_v, _wl_validate)
                # ★2026-09-13 ユーザー「除外したらあかんやん」: 実測表がカタログに無くても出品は止めない。
                #   表が無い時は説明文に表を出さない (嘘の案内も出さない)。表はカタログに依頼して後で差し替える
                if not UCV.has_size_chart(cat_v):
                    print("    ⚠ サイズ表 (実測) がカタログに無い → 表なしで出す (カタログに依頼済み)")
            except UCV.NotListable as e:
                print(f"    ⏸ スキップ: {e}")
                continue
            result["size_jp"] = cat_v["size_jp"]
            if cat_v["size_us"]:
                result["size_us"] = cat_v["size_us"]
            result["model_number"] = cat_v["specs"]["Model"]

        # 80字超過の場合、Short Sleeveを削って調整 (eBay制約)
        if len(title_en) > 80:
            title_en = title_en.replace(" Short Sleeve", "")
        if len(title_en) > 80:
            title_en = title_en[:77] + "..."

        # === Title整合性 + 70字パディング (listing_common.normalize_title) ===
        # Tシャツは UNIQLO UT 主軸で全件新品扱い (NWT = New With Tags)
        if cat_v:
            # ★2026-09-13 ユーザー「これまでのスキルも使ってる？」: 目視で特定した行は
            #   スキルの形 `[作品] [キャラ] Anime Graphic Tee UNIQLO UT Japan Exclusive [色] US M (JP L) NWT`
            #   をカタログの値で組み立てる。normalize_title を通すと末尾に「New」が足されて
            #   「NWT Japan New」になっていた (スキルにも既存出品にも無い形)
            try:
                title_en = UCV.title_for(cat_v, character=specs.get("Character") or result.get("character", ""))
            except UCV.NotListable as e:
                print(f"    ⏸ スキップ: {e}")
                continue
        else:
            title_en = normalize_title(
                title_en, is_new=True, item_specifics=specs,
                category="tshirt", target_min=70, max_chars=80,
            )
        print(f"    ✨ {title_en} ({len(title_en)}字)")
        # ★№138: 目視で特定した行は、作品名が対応表の英語表記どおりタイトルに入っていること
        #   (AI が別の綴りに言い換えると、買い手の検索語と一致しない)。入っていなければ出さない
        if cat_v and not UCV.title_has(title_en, cat_v["work_en"]):
            print(f"    ⏸ スキップ: タイトルに作品名 '{cat_v['work_en']}' が入っていない")
            continue

        # TOPセラーItem Specifics参照 + eBay中央値取得
        ebay_median = 0
        if ebay_token and collab:
            ebay_query = f"UNIQLO UT {collab} T-Shirt"
            top_specs, ebay_total, ebay_median = fetch_top_seller_specs(ebay_token, ebay_query)
            if top_specs:
                print(f"    📊 eBay {ebay_total}件 中央値${ebay_median:.0f}")
                # Claude APIの結果にない項目をTOPセラーから参考表示
                for key, val in top_specs.items():
                    csv_key = f"C:{key}"
                    if key not in specs and val:
                        print(f"    ℹ️ TOPセラー '{key}' = '{val}'（参考）")
                # 空欄の項目をTOPセラーで補完（参考値として）
                # ★2026-09-11: カタログから写した項目は補完しない (2か国の原産国を空欄に
                #   しているのに、他人の出品の値で埋め直してしまう)
                _from_cat = set((cat_v or {}).get("specs", {}))
                for key, val in top_specs.items():
                    if key in _from_cat:
                        continue
                    if key in specs and not specs[key] and val:
                        specs[key] = val
                        print(f"    📋 '{key}' をTOPセラー値で補完: {val}")
            else:
                print(f"    📊 eBay TOPセラーデータなし")
            time.sleep(0.5)

        pic_url = build_pic_url(photo_urls)
        # ★2026-09-13 ユーザー確定「メインはカタログ画像。出品者の画像は使うなら最後」:
        #   目視で特定した行は カタログ (選んだ色の表 → サブ) → メルカリの写真 の順・最大12枚。
        #   目視で「使わない」と外した画像は入れない。特定していない行は今までどおり
        if cat_v:
            _imgs = UCV.images_for_listing(
                cat_v, [u.strip() for u in (photo_urls or "").split("|") if u.strip()])
            if _imgs:
                pic_url = "|".join(_imgs)
                print(f"    🖼 画像 {len(_imgs)}枚 (カタログ {len(_imgs) - len([u for u in _imgs if 'mercdn' in u])}"
                      f" + 仕入元 {len([u for u in _imgs if 'mercdn' in u])})")

        # 出品価格（SSOT: pricing_engine = cost-plus + tier判定 + gap_limit）
        price_str = re.sub(r"[^0-9]", "", target["price_jpy"])
        cost_jpy = int(price_str) if price_str else 2000
        sys.path.insert(0, os.path.join(SCRIPT_DIR, "..", "iMakeBayAPI"))
        from pricing_engine import compute_listing_price
        pricing = compute_listing_price(cost_jpy, ebay_median, PROFIT_CATEGORY)
        price = max(pricing["price"], PRICE_FLOOR_USD)
        if pricing.get("status") == "ALERT":
            print(f"    ⚠️ 価格ALERT: {pricing.get('alert_msg', '')}")

        shipping = get_shipping_policy(price)

        # SKU: メルカリ=full m-ID / ラクマ=hash後半8文字
        url = target.get("url", "")
        sku_match = re.search(r'/item/(m\w+)', url)
        if sku_match:
            custom_label = sku_match.group(1)  # メルカリ
        else:
            fril_match = re.search(r'fril\.jp/([0-9a-f]+)', url)
            if fril_match:
                custom_label = fril_match.group(1)[-8:]  # ラクマ末尾8桁
            else:
                custom_label = f"UT-{datetime.now().strftime('%m%d')}-{idx+1}"

        # セルフチェック（CSV出力前）
        from listing_validator import validate_and_report
        model_for_check = specs.get("Model", "") or result.get("model_number", "")
        if not validate_and_report(
            idx + 1, title_en, specs, model_for_check, 15687, 1000,
            price, pic_url
        ):
            continue

        # CSV行（デフォルト値 — Claude結果が空なら補完。タグから読めた値は尊重）
        if not specs.get("Style"):
            specs["Style"] = "Graphic Tee"
        if not specs.get("Features"):
            specs["Features"] = "Breathable, Lightweight, Stretch"
        if not specs.get("Sleeve Length"):
            specs["Sleeve Length"] = "Short Sleeve"
        if not specs.get("Season"):
            specs["Season"] = "Spring, Summer, Fall"
        if not specs.get("Closure"):
            specs["Closure"] = "Pullover"
        # Country of Origin: タグから読めた国名は尊重、空なら "Does not apply"（推測禁止ルール）
        # ★2026-09-11: 目視で特定した行は カタログの値そのまま。2か国の商品は空欄のまま
        #   (説明文に両方書く。2026-09-09 決定)。写真の読み取りで埋め直さない。
        if not cat_v:
            coo = specs.get("Country/Region of Manufacture") or result.get("country_of_origin", "")
            specs["Country/Region of Manufacture"] = coo
        # Model: result.model_number から取得（タグから読めなければ空）
        if not specs.get("Model"):
            specs["Model"] = result.get("model_number", "")

        # ストアカテゴリ（コラボ名で自動選択）
        store_cat = STORE_CATEGORY_DEFAULT
        for collab_key, cat_id in STORE_CATEGORIES_TSHIRT.items():
            if collab_key.lower() in collab.lower():
                store_cat = cat_id
                break

        row = [
            "Add", 15687, title_en, pic_url, price, 1000,
            get_schedule_time(), custom_label,
            build_description(
                description_template, collab,
                specs.get("Color", ""),
                result.get("size_jp", ""),
                result.get("size_us", specs.get("Size", "")),
                cat=cat_v, about_en=result.get("about_collab", ""),
            ), "FixedPrice", "GTC", 1, LOCATION,
            1, shipping, RETURN_POLICY, PAYMENT_POLICY,
            "", store_cat,  # ConditionDescription空（新品には不要）
            specs.get("Brand", "Uniqlo"),
            specs.get("Type", "T-Shirt"),
            # ★2026-09-08: "Regular" 固定だと eBay が 3XL の組合せを弾き、日次の値段更新が
            #   毎日その1件だけ失敗していた (実害 itemID 356740464473)。サイズから決める。
            _size_type(result.get("size_us", specs.get("Size", "")),
                       specs.get("Department", "Unisex Adults")),
            result.get("size_us", specs.get("Size", "")),
            specs.get("Color", ""),
            specs.get("Department", "Unisex Adults"),
            specs.get("Style", "Graphic Tee"),
            specs.get("Theme", "Anime"),
            specs.get("Character", ""),
            specs.get("Character Family", ""),
            specs.get("Pattern", "Graphic Print"),
            specs.get("Neckline", "Crew Neck"),
            specs.get("Sleeve Length", "Short Sleeve"),
            specs.get("Material", "Cotton"),
            specs.get("Fabric Type", "Jersey"),
            specs.get("Features", "Breathable, Lightweight, Stretch"),
            specs.get("Fit", "Regular"),
            specs.get("Product Line", "Uniqlo UT"),
            specs.get("Model", ""),
            specs.get("Accents", "Logo"),
            specs.get("Year Manufactured", ""),
            specs.get("Vintage", "No"),
            specs.get("Personalize", "No"),
            specs.get("Handmade", "No"),
            # eBay の国名リストにある値だけ。"Does not apply" や読めない値は空欄 (required=False)
            UCV.country_value(specs.get("Country/Region of Manufacture", "")),
            specs.get("Garment Care", "Machine Washable"),
            specs.get("Season", "Spring, Summer, Fall"),
            specs.get("Closure", "Pullover"),
        ]
        # === 物理ゲート: audit_csv_row error なら HOLDキューへ隔離 ===
        from listing_common import gate_row_or_hold as _gate
        _row_dict = dict(zip(csv_headers, row))
        _allowed, _viol = _gate(_row_dict, category="tshirt",
                                 mercari_state=target.get("condition", ""),
                                 sku=custom_label,
                                 price_status=pricing.get("status", "GO"),
                                 median_usd=ebay_median)
        if not _allowed:
            _errs = [f"{f}={i}" for f, i, s in _viol if s == "error"]
            print(f"    🟠 HOLD: {custom_label} → {_errs}")
            continue
        rows.append(row)
        if cat_v:
            # この走行で出す分も「出品済み」と同じ扱いにする (同じ物の2つ目は補URLへ)
            ut_run[_key] = {"row": target["row"], "aux": _aux_of(target["row"]),
                            "item_id": "この走行で出品"}
        print(f"    💲 ${price} (仕入¥{cost_jpy})")
        print()

        time.sleep(2)

    # 二重出品を避けて補URLに回した分を書く (出品より先に書く = CSV が落ちても仕入元は残る)
    if ut_aux_add:
        n_aux = UCV.write_aux(ut_aux_add)
        print(f"\n♻ 出品中の商品に 補URL を追加: {n_aux}行")

    # CSV出力
    if len(rows) > 1:
        sys.path.insert(0, os.path.join(SCRIPT_DIR, "..", "iMakeBayAPI"))
        from listing_core import get_csv_output_path
        output_file = get_csv_output_path("tshirt", "upload")
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
            writer.writerows(rows)
        # Free Shipping 移行 (2026-05-18)
        try:
            from freeshipping_postprocess import transform_csv_to_freeshipping
            transform_csv_to_freeshipping(output_file)
        except Exception as _e:
            print(f"⚠️ Free Shipping post-process 失敗 (Tshirt): {type(_e).__name__}: {_e}")
        print(f"\n完了！出力: {output_file}")
        print(f"成功: {len(rows)-1}件")

        # チェッカー自動実行
        print(f"\n{'═'*60}")
        print("  CSVチェックを開始します...")
        print(f"{'═'*60}\n")
        try:
            import subprocess
            subprocess.run(
                [sys.executable, "check_csv.py", output_file],
                cwd=SCRIPT_DIR,
            )
        except Exception as e:
            print(f"⚠️ チェッカー実行エラー: {e}")

        # 生成時セルフ監査 (CSV監査くん) — check_csv に加え 4観点(整合/形式/SEO/文字数) を確認
        try:
            from listing_common import run_self_audit
            run_self_audit(output_file)
        except Exception as _e:
            print(f"⚠️ セルフ監査 起動失敗 (非致命): {type(_e).__name__}: {_e}")

        # スプシにメルカリURL追記（A列にURL, C列にタイトルは既にスプシにある）
        # → スプシは既にトラバホで管理。追記不要。
        print(f"\n出品後、スプシのB列にItemIDを手動入力してください。")
    else:
        print("\n出力データなし")


if __name__ == "__main__":
    main()
