#!/usr/bin/env python3
# iMak Trading Japan - メルカリ商品管理シート → eBay CSV 自動生成
# 必要: pip install anthropic requests pillow

import csv
import re
import json
import base64
import time
import requests
from datetime import datetime, timedelta

# ===== 設定 =====
# API key.txt から読み込む（同じフォルダに置いてください）
try:
    with open("API key.txt", "r", encoding="utf-8") as f:
        ANTHROPIC_API_KEY = f.read().strip()
except FileNotFoundError:
    print("エラー: 'API key.txt' が見つかりません。スクリプトと同じフォルダに置いてください。")
    input("Enterで終了...")
    exit()
INPUT_CSV = "商品管理シート.csv"
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "iMakeBayAPI"))
from listing_core import get_csv_output_path as _gcop
OUTPUT_CSV = _gcop("mercari", "upload")

# ===== 専用スプシ ===== (Tシャツと同じ列構成: A=URL/B=ItemID/C=タイトル/D=売り切れ/E=状態/F=価格/G=写真URL/H=説明)
SHEET_REGISTRY = {
    "porter": {
        "sheet_id": "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk",
        "gid": 851100680,
        "category_filter": "バッグ",
        "label": "Porter",
        "ebay_category": 52357,
        "store_category": 41828940010,
        "profit_category": "Porter",
        "condition_id": 3000,
        "description_template": "USED.txt",
        "keyword_pdf": "Clothing_Shoes_Accessories_2026Q1.pdf",
        "research_metadata": {
            "last_updated": "2026-04-22",
            "status": "researched",
            "pdf_top30_note": "Clothing_Shoes_Accessories_2026Q1 上位30はLouis Vuitton/Coach/Chanel等の高級ブランドで占有。Porter本体は上位外。一般バッグキーワードを参照",
            "pdf_top30": [
                "louis vuitton handbags", "coach", "coach handbags", "chanel bag",
                "coach bag", "gucci bag", "vintage coach bag", "coach purse",
                "michael kors handbag", "fendi bag", "kate spade handbag",
                "prada bag", "coach shoulder bag", "vera bradley", "ysl handbag",
                "hermes bag", "balenciaga city bag", "tory burch handbag",
                "dooney bourke handbags", "bottega veneta"
            ],
            "top_seller_samples": [
                "TOPセラー(fb>800) Item Specifics: Brand=Porter, Material=Nylon, Style(Messenger Bag/Shoulder Bag/Belt Bag), Size, Color, Theme, Closure(Zip), Bag Width/Height/Depth(in or cm), Country of Origin=Japan, Department=Unisex Adults",
                "Recommended: Pattern, Handle Style, Occasion, Vintage=No, Personalize=No, Features",
                "タイトル: 'YOSHIDA PORTER Tanker [Style] [Size] [Color] Used Japan' or 'PORTER Tanker [Style] [Spec] [Color]'"
            ],
            "note": "2026-04-22 PDF + 3 TOPセラー(ururu2019/wa-wonders-jpn/fx.123-48)調査済"
        },
    },
    "tomica": {
        "sheet_id": "1jF9vggbfUCddjneROMO2GGN-jTAPRbq6Qe2cbgr37B0",
        "gid": 851100680,
        "category_filter": "tomica",
        "label": "Tomica",
        "ebay_category": 222,  # Toys & Hobbies > Diecast & Toy Vehicles > Cars, Trucks & Vans
        "store_category": 41857896010,  # Vintage Japanese Retro Items（Tomica暫定収納先）
        "profit_category": "Tomica",
        "condition_id": 3000,  # 中古黒箱が主流
        "description_template": "USED.txt",
        "keyword_pdf": "Toys_Hobbies_2026Q1.pdf",
        "research_metadata": {
            "last_updated": "2026-04-22",
            "status": "researched",
            "pdf_top30_note": "Toys_Hobbies_2026Q1 上位30は Pokemon/TCG/PSA で占有。Tomica本体は上位外。Diecast/Vintage Japan系のキーワードと組合せ推奨",
            "pdf_top30": [
                "pokemon", "pokemon cards", "pokemon psa 10", "charizard", "psa 10 pokemon",
                "psa 10", "mega charizard ex", "psa", "charizard ex 151",
                "pokemon card", "pikachu", "yugioh", "mtg", "magic the gathering"
            ],
            "top_seller_samples": [
                "TOPセラー(fb>2500) Item Specifics: Brand=Tomica, Vehicle Type=Car, Vehicle Make(Toyota/Nissan/Chevrolet等), Material(Diecast/Metal), Scale(1:60/1:64/1:65), Color, Year of Manufacture, Country of Origin=Japan",
                "Recommended: Series, Model, Vehicle Year, Theme, Modified Item=No, Customized=No, Recommended Age Range=+3",
                "タイトル: 'Tomica [No.X] [Make] [Model] [Color] [Scale] Vintage Japan' or 'Vintage TOMICA No.[X] [Color] [Make] [Model] Made in Japan'"
            ],
            "note": "2026-04-22 PDF + 3 TOPセラー(modernvintageworld/mbor9626/matts90sho)調査済"
        },
    },
    "ichibankuji": {
        "sheet_id": "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk",
        "gid": 851100680,
        "category_filter": "一番くじ",
        "label": "Ichibankuji",
        "ebay_category": 261055,
        "store_category": 41861579010,
        "profit_category": "一番くじ",
        "condition_id": 1000,
        "description_template": "NEW.txt",
        "keyword_pdf": "Collectibles_2026Q1.pdf",
        "research_metadata": {
            "last_updated": "2026-04-21",
            "status": "researched",
            "pdf_top30": [
                "anime figure", "nendoroid", "one piece", "hello kitty", "pokemon plush",
                "pikachu", "super sonico figure", "jujutsu kaisen", "chainsaw man", "vintage sanrio",
                "hetalia", "chiikawa", "miku figure", "jojo", "sh figuarts dragon ball",
                "sanrio", "monchhichi", "miku", "hatsune miku", "pokedoll",
                "sailor moon", "one piece figure", "twisted wonderland", "snoopy", "dragon ball"
            ],
            "top_seller_samples": [
                "Format: Ichiban Kuji [IP] [Prize] [Character] [FigureType] Bandai New",
                "Item Specifics: Brand=Bandai, Material=PVC, Theme=Anime & Manga, Type=Figure, Series=Ichiban Kuji"
            ],
            "note": "ichibankuji_to_csv.py 内で実装済み（mercari_to_ebay_csv.py 経由ではなく独立スクリプト）"
        },
    },
    "reel": {
        "sheet_id": "1jF9vggbfUCddjneROMO2GGN-jTAPRbq6Qe2cbgr37B0",
        "gid": 851100680,
        "category_filter": "リール",
        "label": "Reel",
        "ebay_category": 261030,  # Sporting Goods > Fishing > Reels (既存imax-64出品も全て261030)
        "store_category": 41828943010,
        "profit_category": "リール",
        "condition_id": 3000,
        "description_template": "USED.txt",
        "keyword_pdf": "Sporting_goods_2026Q1.pdf",
        "research_metadata": {
            "last_updated": "2026-04-22",
            "status": "researched",
            "pdf_top30": [
                "fly rod", "fly reel", "fishing", "fishing rod", "fishing reels",
                "shimano spinning reel", "shimano stradic", "shimano baitcasting reel",
                "shimano stella", "spinning reel", "abu garcia ambassadeur", "megabass",
                "abu garcia", "baitcasting reel", "shimano", "daiwa spinning reel",
                "lews baitcasting reel", "fishing reel", "abel fly reel", "shimano reel", "daiwa"
            ],
            "top_seller_samples": [
                "TOP seller (fb>500) Item Specifics: Brand, Reel Type(Baitcasting/Spinning eBay正規値), Model, Series, Reel Size, Hand Retrieve, Gear Ratio, Country of Origin",
                "Recommended: Maximum Drag, Drag Style, Material, Line Capacity, Ball Bearings, Item Weight, Fish Species, Fishing Type, Features, MPN",
                "Fixed: Vintage=No, Personalize=No, Department=Unisex Adults"
            ],
            "official_db": {
                "daiwa": "daiwa_jp.py via gr-search.com (公式サイト直接、年式違い時はtype_only マッチ)",
                "shimano": "shimano_jp.py via naturum.co.jp (公式は Akamai ブロックのため Naturum 経由)"
            },
            "note": "2026-04-22 リール初実装+Daiwa/Shimano公式DB統合。Sporting_goods_2026Q1.pdf + 6 TOPセラー調査済"
        },
    },
}


def _validate_research_metadata(sheet_key, cfg):
    """新カテゴリ追加時に research_metadata 必須化（Claudeの調査漏れを物理的に防ぐ）"""
    rm = cfg.get("research_metadata")
    if not rm:
        print(f"\n❌ FATAL: SHEET_REGISTRY['{sheet_key}'] に research_metadata がありません")
        print(f"  → Claude に依頼: '{sheet_key}カテゴリのキーワードPDF + TOPセラー3件を調査して research_metadata を埋めて'")
        print(f"  → 調査せずに新カテゴリ運用は禁止（プロンプト精度が低下するため）")
        _sys.exit(1)

    required = ["last_updated", "status", "pdf_top30", "top_seller_samples"]
    missing = [k for k in required if k not in rm]
    if missing:
        print(f"\n❌ FATAL: SHEET_REGISTRY['{sheet_key}'].research_metadata に以下が不足: {missing}")
        _sys.exit(1)

    status = rm.get("status", "")
    if status == "legacy_pending_review":
        print(f"\n⚠️ {sheet_key}: 旧カテゴリで正式調査未実施。次回プロンプト改善時に PDF + TOPセラー調査推奨")
    elif status == "researched":
        print(f"  ✓ {sheet_key} research_metadata: 最終更新 {rm.get('last_updated')} (PDF{len(rm.get('pdf_top30',[]))}件, TOPセラー{len(rm.get('top_seller_samples',[]))}件)")

    # PDF更新検出（mtime > last_updated なら警告）
    pdf_name = cfg.get("keyword_pdf")
    if pdf_name:
        pdf_path = _os.path.join(r"C:\Users\imax2\OneDrive\デスクトップ\iMak_workspace\iMakKeywords", pdf_name)
        if _os.path.exists(pdf_path):
            from datetime import datetime as _dt
            pdf_mtime = _dt.fromtimestamp(_os.path.getmtime(pdf_path)).date()
            try:
                last_dt = _dt.strptime(rm["last_updated"], "%Y-%m-%d").date()
                if pdf_mtime > last_dt:
                    print(f"\n⚠️ {pdf_name} が更新されてます ({pdf_mtime})")
                    print(f"   前回反映: {rm['last_updated']}")
                    print(f"   → Claude に '{sheet_key}カテゴリのプロンプト更新' 依頼推奨\n")
            except ValueError:
                pass
# 注: PDF/TOPセラー調査結果は SYSTEM_PROMPT 内に直接埋め込み（一番くじ方式）
# 四半期更新時のみ、調査→プロンプト更新の作業をする（ランタイム読込なし、I/Oゼロ）
GSHEET_CREDS = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "double-hold-421922-7c0d38d3f73d.json")
LOCATION = "Osaka"
RETURN_POLICY = "customer1"
PAYMENT_POLICY = "SALE"

SHIPPING_POLICIES = [
    (39, "<39"), (60, "40-60"), (100, "60-100"), (200, "100-200"),
    (300, "200-300"), (400, "300-400"), (500, "400-500"),
    (600, "500-600"), (800, "600-800"),
]


def get_shipping_policy(price):
    for threshold, policy in SHIPPING_POLICIES:
        if price <= threshold:
            return policy
    return "800-1000"


def get_schedule_time():
    future = datetime.utcnow() + timedelta(weeks=SCHEDULE_WEEKS)
    return future.strftime("%Y-%m-%d %H:%M:%S")


def build_description_with_specs(template_path, specs):
    """USED.txtテンプレを読み込み、Shippingマーカー直前にSpecsブロック挿入"""
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            template = f.read()
    except FileNotFoundError:
        template = "<html><body><p>Item description</p></body></html>"

    # Specs HTML 構築
    spec_lines = []
    for k, v in (specs or {}).items():
        if v and str(v).strip():
            spec_lines.append(f'<li><b>{k}:</b> {v}</li>')
    specs_html = (
        '<p><span style="text-decoration: underline;"><strong>Specifications</strong></span></p>'
        '<ul>' + "".join(spec_lines) + '</ul>'
    )
    # Shippingマーカー直前に挿入
    marker = '<p><span style="text-decoration: underline;"><strong>Shipping'
    if marker in template:
        return template.replace(marker, specs_html + marker, 1)
    return template + specs_html


# === listing_common.py に集約済 → 共通ライブラリから import (2026-04-23) ===
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "iMakeBayAPI"))
from listing_common import (
    SKU_PREFIX_BY_CATEGORY as _SKU_PREFIX_BY_CATEGORY,
    extract_sku_from_url,
    is_new_condition,
    determine_condition_id,
    fetch_amazon_title,
    enforce_title_coherence,
    pad_title_to_target,
    normalize_title,
    audit_csv_row,
    CONDITION_MASTER,
    detect_condition_id_from_state,
    get_default_condition_description,
)
MODEL = "claude-sonnet-4-20250514"
MAX_IMAGES = 4
SCHEDULE_WEEKS = 2

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://jp.mercari.com/",
}

def get_schedule_time():
    future = datetime.utcnow() + timedelta(weeks=SCHEDULE_WEEKS)
    return future.strftime("%Y-%m-%d %H:%M:%S")

# ===== iMak出品ルール =====
SYSTEM_PROMPT = """
You are an expert eBay listing assistant for iMak Trading Japan (eBay ID: imax-64).
All items are pre-owned Japanese products sold to international buyers.
Generate eBay listing content based on Mercari product data and images provided.

## CRITICAL RULES (apply to ALL categories)
- Title: Max 80 characters, English only, NO symbols (!, ★, ※)
- All pre-owned items: title must end with "Pre-owned Japan"
- Never use Japanese marketing language in titles
- Size format: "US L (JP XL)" - never "US Size L"
- JP to US size conversion: JP XS→US XXS, JP S→US XS, JP M→US S, JP L→US M, JP XL→US L
- Country of Origin: **厳格ルール（全カテゴリ共通）**
  - 確証あり（Mercari description「Made in XX」明記、画像タグ判読、OFFICIAL SPECS記載）→ 国名
  - 確証なし（推測しかできない）→ "Does not apply" 固定
  - **空欄禁止**。空欄なら必ず "Does not apply"
- Condition Description: 渡される「Condition」値（メルカリ商品状態）の段階を厳守して英訳する。
  Condition値 → 英訳マッピング（厳守）:
    新品、未使用 / 新品 → "Brand new, unused condition. Comes with original packaging."
    未使用に近い → "Like new condition with minimal handling."
    目立った傷や汚れなし → "Excellent condition with no visible flaws."
    やや傷や汚れあり → "Shows minor scratches and signs of use from normal handling."
    傷や汚れあり → "Visible scratches and signs of wear from regular use."
    全体的に状態が悪い → "Significant wear and noticeable damage throughout."
  ※ "やや" の有無で強弱が変わる点に注意。"やや"無し版はより明確な傷を表現すること。
  ※ Mercari description に具体的な傷の記述があれば、上記文の後に追記してOK
  ※ 中古(やや傷あり以下)は末尾に "Please review all photos carefully before purchasing. Sold as-is." を付ける
  ※ 新品（新品/新品、未使用）の場合は "Sold as-is" は不要、"Brand new" 系の表現で完結
- Title 末尾の表記:
  - **新品商品（Condition="新品" or "新品、未使用"）→ "New" or "Brand New" で締める**（"Pre-owned Japan" は使わない）
  - 中古商品 → "Pre-owned Japan" で締める（既存通り）
  - Conditionの値に応じて Claude が自動で適切な末尾表記を選ぶこと

## PORTER (吉田カバン) RULES — 2026-04-23 eBayカテゴリ52357フィルタ全項目検証反映
### Title format (TOPセラー fb>800パターン採用)
"YOSHIDA PORTER [Series] [Style] [Size] [Color] Used Japan" or
"PORTER [Series] [Style] [Spec] [Color] Pre-owned Japan"
例: "YOSHIDA PORTER Tanker Shoulder Bag S Black Used Japan"
例: "PORTER Tanker 2Way Helmet Bag Black Nylon Pre-owned Japan"

### KEYWORD PRIORITY
- Porter本体は Clothing_Shoes_Accessories_2026Q1.pdf 上位30外（高級ブランド寡占）
- 一般バッグキーワード活用: "Shoulder Bag" "Tote" "Messenger Bag" "Belt Bag" "Briefcase"
- TOPセラー慣習: "YOSHIDA" 冠（ブランド明確化）, "Used Japan" / "Pre-owned Japan"
- Series 必須: Tanker/Heat/Smoky/Lift/Current/Force/2Way等
- Color (Black/Olive/Navy等) buyersフィルタ対象

### Item Specifics (eBayフィルタ正規値に完全準拠)
必須:
- Brand: **"Porter"** 固定（3,514件主戦場。"Yoshida & Co."378件・"HEAD PORTER"80件は別ブランド扱い、HEAD PORTERタグ視認時のみ"HEAD PORTER"使用）
- Style: 以下のeBay公式値のみ使用
  Backpack / Belt Bag & Fanny Pack / **Briefcase/Document Case** / Clutch / Crossbody / Duffle / Gym Bag / Laptop Bag / **Messenger Bag(973)** / Saddle Bag / Satchel / **Shoulder Bag(915)** / Top Handle Bag / Tote
  ※ "Tote Bag"でなく"Tote"、"Briefcase"でなく"Briefcase/Document Case"
- Material: 以下から1つ
  **Nylon(2,001)圧倒的** / Leather(344) / Polyester(298) / Canvas(217) / Cotton(217) / PVC / Polyurethane / Suede
  ※ Tanker系=Nylon、Heat系=Polyester、Smoky系=Cotton、レザーシリーズ=Leather
- Color: 以下のeBay公式16色enum のみ
  Beige / **Black(1,643)** / Blue / Brown / Gold / Gray / Green / Ivory / Multicolor / Orange / Pink / Purple / Red / Silver / White / Yellow
  ※ "Olive"等は無効 → "Green"に正規化、"Navy"→"Blue"に正規化
- Size: Mini / Small / Medium(416) / Large / **Extra Large**（"XL"でなく"Extra Large"）
- Department: **"Men"(1,826)** または "Unisex Adults"(1,321) — Porterは男性ユース多数派なので基本"Men"、ハンドバッグ系のみ"Unisex Adults"
- Country of Origin: "Japan" 固定（eBayフィルタ自体は機能薄いが検索インデックス用）
- Bag Width / Bag Height / Bag Depth: cm 数値のみ
推奨（フィルタヒット率高）:
- Closure: **"Zip"(901)圧倒的** / Buckle(95) / Drawstring(49) / Snap(42) / Push Lock(8)
- Pattern: **"Solid"(819)圧倒的** / Camouflage(84) / Striped(7)
- Handle Style: ShoulderBag/MessengerBag→**"Shoulder Strap"(371)** / Tote→"Double Handles" / Briefcase→"Top Handle" / Crossbody→"Crossbody Strap"
- Handle/Strap Material: **"Nylon"(759)圧倒的** / Leather(112) / Polyester(68) / Cotton(25) / Nickel(16)
  ※ Tanker系=Nylon、革持ち手=Leather
- Theme: シリーズ別出し分け
  Tanker系→**"City"(304)** または "Classic"
  Heat/Smoky/Lift系→"Classic"(97)
  Force/Filter等アウトドア系→"Outdoor"(88)
  カラフルコラボ→"Colorful"(124)
  90sヴィンテージ→"90s"(52)
  ミリタリー系→"Army"(37)
- Occasion: Tanker/Heat/Smoky→**"Casual"(1,172)圧倒的** / Briefcase/Document Case→"Business"(599) / Travel系→"Travel"(477) / フォーマル革→"Formal"(139)
- Features: Porter共通自動付与（カンマ区切り複数値）
  全Porter共通: "Pockets, Inner Pockets, Outer Pockets, Adjustable Strap"
  Nylon系追加: "Lightweight, Water Resistant"
  Heat/PCバッグ追加: "Padded, Laptop Sleeve/Protection"
  2Way追加: "Detachable Strap, Cross-Body Strap"
  限定/コラボ追加: "Limited Edition"
  ※ eBay有効値以外（"Roomy"等）は禁止
固定:
- Vintage: No（90sヴィンテージタグ確認できる場合のみ "Yes"）
- Personalize: No
- Handmade: No

## TOMICA VINTAGE (旧トミカ黒箱) RULES — 2026-04-23 eBayカテゴリ222 全項目検証反映
### Title format
"Tomica No. [X] [Make] [Model] [Color] [Scale] Vintage Japan" or
"Vintage TOMICA No. [X] [Color] [Make] [Model] Made in Japan"
例: "Tomica No.47 Blue Nissan Gloria Van 1:64 Vintage Japan"  ※"1:65"は使わない、"1:64"に正規化
例: "Vintage TOMICA No.47 Blue NISSAN GLORIA VAN Made in Japan"

### KEYWORD PRIORITY
- Tomica本体は Toys_Hobbies_2026Q1.pdf 上位30外（Pokemon/TCG寡占）
- "Vintage Japan" / "Made in Japan" / "Diecast" を組合せ必須
- "Tomica" + 番号 + メーカー名 で検索ヒット率↑
- SKIP判定: 復刻/復刻版/USED復刻 in title, no black box visible, 中国製 mentioned

### Item Specifics (eBay公式フィルタ正規値のみ使用)
必須:
- Brand: **"Tomica"** (33K件主流) / "Takara" (22K件) / "TOMY" (23K件) / "Tomytec" (3K件) のいずれか
  ※ 黒箱期 = "Tomica" or "Takara"、現行 = "Tomica"、技術系 = "Tomytec"
- Vehicle Type: **eBay 33値enum**
  Car(36K圧倒的) / Bus / Truck / Truck/Lorry / Van / Pickup Truck / Tow Truck / Delivery Truck / Fire Vehicle / Police Vehicle / Ambulance / School Bus / Tanker Truck / Garbage Truck / Dump Truck / Dump Truck/Tipper / Trailer / Container / Limousine / Hearse / Motorhome/Camper 等
  ※ "SUV"/"Sedan"/"Wagon"/"Coupe"/"Sports Car" は無効 → "Car"に正規化
  ※ "Police Car" は無効 → "Police Vehicle"
  ※ "Fire Truck" は無効 → "Fire Vehicle"
- Vehicle Make: **eBay 97値enum** (Toyota/Honda/Nissan/Mazda/Mitsubishi/Subaru/Daihatsu/Suzuki 主要日本車、Ferrari/Lamborghini/Porsche/BMW/Mercedes-Benz/Audi/Volkswagen/Lotus/McLaren 主要外国車、Mack/Peterbilt/Komatsu/CAT 商用車)
  ※ "Citroën" はアクサン付き必須（"Citroen"は無効）
  ※ "Hino" はeBay非フィルタ値 → 自由文字列扱い（記入は可）
- Material: **eBay 11値enum**
  Diecast(21K圧倒的) / Plastic / Metal / Cast Iron / ABS / Resin / Pressed Steel / Tin / White Metal / Wood / Zamak
  ※ "Steel" は無効 → "Pressed Steel" or "Metal"
- Scale: **eBay 32値enum**
  1:64(14K圧倒的) / **1:60(2K)** / **1:66(799)** / 1:43 / 1:50 / 1:55 / 1:6 / 1:8 / 1:10 / 1:12 / 1:18 / 1:24 / 1:32 / 1:43 / 1:48 等
  ※ **"1:65" は無効** (eBayフィルタリストに無し) → "1:64" に正規化（最大派閥）
  ※ 1:65表記は box には残るが Item Specifics では1:64使用、Description で「Scale: 1:65 (per box)」明記
- Color: **eBay 15値enum** (Beige/Ivory無し！)
  Black / Blue / Brown / Clear / Gold / Gray / Green / **Multi-Color(5.8K)** / Orange / Pink / Purple / Red / Silver / White / Yellow
  ※ "Multicolor"(ハイフン無し)は無効 → "Multi-Color"
  ※ "Olive"/"Khaki"/"Navy" は無効 → 近い色に正規化
- Year of Manufacture: **西暦4桁整数** (1959-2026 enum)
- Country/Region of Manufacture: "Japan" (タグ確認、不明なら "Does not apply")
推奨:
- Vehicle Year (実車の年式、製造年と異なる場合あり、4桁整数)
- Model (フルモデル名、自由文字列)
- Series: **eBay enum**
  **"Tomica Common Series"(8.3K圧倒的)** / "Tomica Limited Series"(2.6K=TLV復刻) / "Tomica Domestic Series"(647=黒箱国産車) / "Tomica Foreign Series"(671=黒箱外国車)
  ※ 黒箱国産車 → "Tomica Domestic Series"、黒箱外国車 → "Tomica Foreign Series"、現行 → "Tomica Common Series"
- Character Family: **eBay 51値enum**、デフォルト "**Cars**"(24K圧倒的、汎用車向け)
  特殊: "Disney Pixar Cars" / "Pokemon"(éなし注意) / "Star Wars" / "Thomas & Friends" / "Toy Story" / "Hello Kitty" / "Doraemon" / "Speed Racer" / "The Fast and the Furious" 等
  ※ 通常Tomicaは "Cars" 入れる（"省略"でなく明記）
- Features: **eBay 12値enum** (multi)
  **"Unopened Box"(13K)** / "Limited Edition"(6.2K) / "Special Edition"(2.7K) / "With Case"(2.3K) / "Chase"(524=シークレットカラー) / "With Stand"(68) / "Advertising Specimen"(253=広告用)
  ※ 新品箱付き → "Unopened Box"
  ※ 限定品/特別仕様 → "Limited Edition" / "Special Edition"
- Recommended Age Range: "3+"（"+3"は無効、"3+"形式）
- Theme: 通常省略可、特殊Themeなら "Cars"/"Movie"/"Anime" 等
固定:
- Modified Item: No
- Customized: No
- Autographed: No
- Vintage: 黒箱・1980年代以前なら "Yes"、現行品 "No"
- Gender: "Boys & Girls"

## UNIQLO UT RULES
Title format: UNIQLO UT [Series] [Character] Tee [Color] US [Size] (JP [Size]) Pre-owned Japan
- Item Specifics: Brand (Uniqlo), Size Type (Regular), Size, Color, Department,
  Type (T-Shirt), Theme (Anime & Manga), Character, Character Family,
  Pattern (Graphic Print), Neckline (Crew Neck), Material (Cotton),
  Fit (Regular), Product Line (Uniqlo UT), Vintage (No),
  Garment Care (Machine Washable), Year Manufactured (2020-2029)

## MONTBELL RULES
- Brand: montbell (lowercase, no hyphen)
- Title format: montbell [Product Name] [Color] [Size] Pre-owned Japan
- Country of Origin: Japan

## VINTAGE TOYS (ビンテージおもちゃ) RULES
- Title: [Brand] [Item Type] [Character/Subject] [Era] Vintage Japan
- Identify: manufacturer, era, material (tin/plastic/diecast)

## FISHING REEL (釣りリール) RULES — 2026Q1 PDF & TOPセラー調査反映
### Title format
[Brand] [Year/Model] [Series] [Size/Spec] [Hand] [Reel Type] Pre-owned Japan
例: "Daiwa 23 Steez A TW 1000XH Right Hand Baitcast Reel Pre-owned Japan"
例: "Shimano 23 Vanquish 4000XG Spinning Reel High Gear Pre-owned Japan"

### MANDATORY keywords (Sporting_goods_2026Q1.pdf 上位)
- "Spinning Reel" (#16) or "Baitcast Reel" (#21) ← Reel Type を明記必須
- "Fishing Reel" (#27) は文字数余れば追加
- Brand 必須: Shimano (#23), Daiwa (#30) ← 完全一致で
- Series がランクインしていれば優先: "Stradic" (#11), "Stella" (#15), "Twin Power", "Vanquish", "Tatula", "STEEZ"
- Reel Size (1000/4000等) はタイトルに含める ← buyers が絞り込む

### MODEL NUMBER 厳格ルール（最重要・違反厳禁）
- **入力タイトル（Mercariタイトル or Amazon正式タイトル）に書かれた型番を一字一句そのまま使用する**
- **型番に suffix（ギア比表記 H/HG/XG/XH/P/PG等）を勝手に追加してはいけない**
- 例:
  - 入力: "ジリオン SV TW 1000 右ハンドル" → 出力: "Zillion SV TW 1000" ✓
  - 入力: "ジリオン SV TW 1000 右ハンドル" → 出力: "Zillion SV TW 1000H" ❌ ("H"は推測、入力に無い)
  - 入力: "PR100L 左ハンドル" → 出力: "PR100L" ✓ ("L"は入力にあるのでOK)
  - 入力: "LT2000S-XH" → 出力: "LT2000S-XH" ✓ (入力通りそのまま)
- 型番の文字列は**写真からも推定不可**（モデル番号はタイトル/タグ/公式DB由来のみ）
- 不明な suffix を勝手に "H"(High Gear)/"XH"(Extra High)/"P"(Power) と推測すると別商品扱いになる → バイヤークレーム

### TITLE 文字数最適化（厳守）
- eBay 80字制限内で、**バイヤーが実際に検索するキーワードのみ**で詰める
- **PDF (Sporting_goods_2026Q1.pdf) 上位30に掲載された語のみ追加可**
- 70字未満でも、PDF掲載語で埋められない場合は埋めない（パディング禁止）
- PDF掲載で追加可能な語の例:
  - "Fishing Reel" (#27) ← "Reel"既入なら "Baitcast Fishing Reel" 等に拡張
  - "Spinning Reel" (#16) / "Baitcast Reel" (#21) ← 既にReel Type明記で必須
  - Series名 (Stradic #11, Stella #15 等)
  - "Fishing" (#3) 単独
- **禁止する追加語**（PDF未掲載＝検索ヒット根拠なし）:
  - "Made in [Japan/Thailand/Malaysia/etc]" ← Item Specificsへ
  - "Authentic" / "Mint" / "Excellent" / "Direct from Japan" / "JDM" ← 推測パディング
  - ギア比 "HG"/"XG"/"PG" 単独 ← モデル番号に既に含まれる場合冗長、含まれてない場合推測禁止
- 詰めるためだけの根拠なきキーワード追加は **機会損失（バイヤー印象悪化）** として扱う
- 結果として60字台で終わるなら、それで完成とする

### reel_type 判定 (JSON必須)
- "bait" → eBayカテゴリ 32885 (Bait Casting)
- "spinning" → eBayカテゴリ 36147 (Spinning)
- 判定: "ベイト"/"Bait"/"TW"/"Tatula"/"BasX"/"両軸"/"Bait Casting" → bait
        "スピニング"/"Spinning"/"Vanquish"/"Stella"/"Stradic"/"Twin Power"/"Vanford"/"Caldia"/"Ultegra"/"Sienna" → spinning

### Item Specifics (eBay 261030 公式必須/推奨フィールド準拠)

【REQUIRED】
- Brand: Daiwa / Shimano / etc.

【ADDITIONAL（検索ボリューム順、可能な限り全て埋める）】
- UPC: バーコード番号があれば（無ければ "Does not apply"）
- Reel Type (~238K検索): **"Baitcasting" or "Spinning" のみ**（"Reel" suffix禁止 = "Baitcast Reel"/"Spinning Reel" は無効）
  eBay公式フィルタ正規値リスト: Baitcasting / Spinning / Conventional / Fly / Spincast / Trolling
- Reel Size (~111K): 数値のみ "100" / "1000" / "4000" / "C2000" 等
- Ball Bearings (~92K): **整数のみ "6" / "7" 等**（eBayフィルタは整数で絞込のため "6+1" 形式禁止）
  ← OFFICIAL ball_bearings = "6+1" の場合、"+1" の部分（ローラーベアリング）を除いた **BBの数のみ** 出力。
  例: official "6+1" → Item Specifics "6"
  ローラーベアリング情報は Description に "6BB + 1RB" 形式で記載可
- Hand Retrieve (~63K): **"Right" / "Left" / "Right/Left Interchangeable" のみ**
  ※ "Both" は無効 → "Right/Left Interchangeable" に正規化（左右ハンドル交換可能機種の場合）
- Fish Species (~16K): "Bass" / "All Freshwater" / "All Saltwater" / "Trout" 等
- Fishing Type (Trending): "Freshwater Fishing" / "Saltwater Fishing"
- Gear Ratio (Trending): "6.2:1" 形式  ← OFFICIAL gear_ratio
- Drag Style (Trending): "Star Drag" (ベイト標準) / "Front Drag" (スピニング標準)
- Material: **eBay公式フィルタ値から選択** → "Aluminum" / "Alloy" / "Metal" / "Stainless Steel" / "Carbon Fiber" / "Plastic" / "Graphite"
  Daiwa/Shimano リールは大半 "Aluminum" or "Alloy"（軽合金）。"Aluminum Alloy" はNG（フィルタヒットせず "Alloy" にする）
- Maximum Drag: "11 lb" or "5kg"  ← OFFICIAL max_drag_kg → "5 kg" 形式に
- **Item Weight**: "195 g" ← OFFICIAL weight_g に "g" 単位付けて出力（必須）
- Department: "Unisex Adults" 固定
- Line Recovery: 巻取長 "81 cm/turn" ← OFFICIAL line_per_turn_cm
- Line Capacity: ナイロン糸巻量 (e.g., "3lb/125m, 4lb/100m, 5lb/75m") ← OFFICIAL line_capacity_nylon
- Braid Capacity: PE糸巻量 (e.g., "PE 0.6-150m, 0.8-110m, 1-80m") ← OFFICIAL line_capacity_pe
- Model (~77K): フルモデル名 "DAIWA 24 BASS X 100H" 等（大文字推奨、TOPセラー慣習）
- Number of Pieces (~68K): "1" 固定
- Color (~18K): 画像から色判定（"Black" / "Silver" / "Multicolor" 等）
- Features (~12K): "Anti-Reverse, Aluminum Spool" 等。**eBay制限: 65文字以内必須**（超過するとAdd失敗）。
  例OK (37字): "Anti-Reverse, Aluminum Spool, Front Drag"
  例NG (70字): "Anti-Reverse, Aluminum Spool, Front Drag, Cold Forged Aluminum Spool" ← 4つ目で超過
  → 機能を3項目以内に絞る or 短い表現使う ("Cold Forged Aluminum Spool"→"Cold Forged Spool")
- Country of Origin (~3K): **厳格ルール**
  - **確証あり** (Mercari descriptionに「Made in XX」明記、または画像のタグから読み取り可、またはOFFICIAL SPECSに記載) → 国名 (Japan/Thailand/Malaysia/Vietnam等)
  - **確証なし** (推測しかできない場合) → "Does not apply" 固定
  - **絶対に空欄禁止**。空欄なら "Does not apply" を必ず入れる
  - Daiwa/Shimano メーカーのデフォルト国を推測で入れない（モデルにより異なるため）
- Vintage (~1.6K): "No" 固定
- Pre-Spooled (~1.4K): "No" 固定（中古は通常糸抜き出品）
- MPN: 商品コードあれば（OFFICIAL JAN や メーカー品番）

### OFFICIAL SPECS 反映ルール（厳守）
プロンプトに `=== OFFICIAL MANUFACTURER SPECS ===` セクションがある場合:
1. **OFFICIAL の値を Item Specifics に必ず全て反映**（推奨フィールドに収まる項目は全て）
2. line_capacity_pe → "Braid Capacity"
3. line_capacity_nylon → "Line Capacity"
4. line_per_turn_cm → "Line Recovery"
5. max_drag_kg=5 → "5 kg"
6. ball_bearings="6+1" → そのまま
7. Claude推測より公式値を絶対優先

### OFFICIAL SPECS が無い / フィールドが空欄の場合（厳守）

【数値スペック=推測禁止】
- Gear Ratio / Item Weight / Ball Bearings / Maximum Drag / Line Capacity / Braid Capacity / Line Recovery / Reel Size
- これらは official_specs か Mercari description「ギア比: X.X:1」等の明記がある場合のみ出力
- 写真や常識からの推測補完は禁止（不正確値で返品リスク）
- 該当なし → 該当フィールドを **省略**

【画像/外観で確認可能なフィールド=推測OK】
- Features (Anti-Reverse / Aluminum Spool / T-Wing System / Lightweight 等)
  → 画像見ればわかる、または Mercari description に記載 → 必ず出力
- Color → 画像から判定
- Material → 画像から判定 (Aluminum / Carbon)
- Drag Style → リール形状から判定 (Spinning→Front Drag, Baitcast→Star Drag が標準)
- Hand Retrieve → モデル名から判定 (R/L サフィックス, 例 "100H"=Right, "100HL"=Left)
- Fish Species → モデルカテゴリから判定 (Bass系→Bass, 大物系→All Saltwater)
- Fishing Type → 同上

【Country of Origin】上記のCRITICAL RULES参照（確証なし→"Does not apply"）

【Features の標準項目（画像で確認したものを必ず入れる）】
ベイトリール: Anti-Reverse, Aluminum Spool, Quick Set Anti-Reverse, T-Wing System (TWS, TW モデル), Star Drag
スピニングリール: Anti-Reverse, Aluminum Spool, Front Drag, Anti-Twist, Cold Forged Aluminum Spool

## OTHER CATEGORIES
- Apply general pre-owned Japan listing rules
- Identify category, brand, key features from images and description

## OUTPUT FORMAT
Return ONLY valid JSON (no markdown, no explanation):
{
  "title": "eBay title max 80 chars ending with Pre-owned Japan",
  "category_identified": "Porter/Tomica/UNIQLO/montbell/Vintage Toy/Fishing Reel/Other",
  "reel_type": "bait or spinning (only when category_identified=Fishing Reel)",
  "condition_description": "Condition description in English ending with Please review all photos carefully before purchasing. Sold as-is.",
  "item_specifics": {
    "field_name": "value"
  },
  "notes": "Any warnings (e.g. skip if Tomica reprint detected)"
}
"""

def get_images_base64(photo_url_str, max_images=MAX_IMAGES):
    """写真URLから画像をbase64に変換"""
    urls = [u.strip() for u in photo_url_str.split('|') if u.strip()]
    images = []
    for url in urls[:max_images]:
        # メルカリShops (assets.mercari-shops-static.com) はURLをそのまま使う
        if 'mercari-shops-static.com' in url:
            try_urls = [url]
        else:
            # 通常メルカリ: 元のURL → クエリなしの順で試行
            base_url = url.split('?')[0]
            try_urls = [url, base_url]

        for try_url in try_urls:
            try:
                resp = requests.get(try_url, headers=HEADERS, timeout=15)
                if resp.status_code == 200 and len(resp.content) > 1000:
                    b64 = base64.standard_b64encode(resp.content).decode('utf-8')
                    images.append(b64)
                    print(f"    画像取得OK ({len(resp.content)//1024}KB): ...{try_url[-50:]}")
                    break
            except Exception as e:
                continue
        else:
            print(f"    画像取得失敗: {url[-50:]}")
    return images

def call_claude_api(title_jp, description_jp, condition_jp, price_jpy, images_b64,
                    official_specs=None, category=None, max_retries=2):
    """Claude APIを呼び出してeBayリスティングを生成。
    category 指定時は whitelist_registry でホワイトリスト検証＋違反時リトライ。"""
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # ホワイトリスト検証（category指定時のみ）
    validate_fn = None
    feedback_fn = None
    if category:
        try:
            _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "iMakeBayAPI"))
            from whitelist_registry import validate_and_normalize, build_retry_feedback, WHITELISTS
            if category in WHITELISTS:
                validate_fn = validate_and_normalize
                feedback_fn = build_retry_feedback
        except Exception as _e:
            print(f"    ⚠️ whitelist_registry 読込失敗（検証スキップ）: {_e}")

    content = []
    for img_b64 in images_b64:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": img_b64,
            }
        })

    # 公式スペック取得済の場合はAUTHORITATIVE SPECSセクション追加
    official_block = ""
    if official_specs:
        lines = ["", "=== OFFICIAL MANUFACTURER SPECS (use as ground truth, override Mercari description if conflict) ==="]
        for k, v in official_specs.items():
            if v and k not in ("source_url", "matched_item", "match_quality"):
                lines.append(f"  {k}: {v}")
        if official_specs.get("source_url"):
            lines.append(f"  source: {official_specs['source_url']}")
        if official_specs.get("match_quality"):
            lines.append(f"  match_quality: {official_specs['match_quality']} (exact=完全一致, type_only=同型番異年式)")
        lines.append("=== END OFFICIAL ===")
        official_block = "\n".join(lines)

    content.append({
        "type": "text",
        "text": f"""Mercari Product Information:
Title (Japanese): {title_jp}
Condition: {condition_jp}
Price (JPY): {price_jpy}
Description: {description_jp}
{official_block}

Analyze the images and product information, then generate an eBay listing following iMak Trading Japan rules.
If OFFICIAL SPECS section is provided, those values are authoritative for Item Specifics (weight, gear ratio, ball bearings, max drag, line capacity, country of origin)."""
    })

    messages = [{"role": "user", "content": content}]
    last_result = None
    retries = max_retries if validate_fn else 0  # 検証無しなら1回だけ

    for attempt in range(retries + 1):
        try:
            message = client.messages.create(
                model=MODEL,
                max_tokens=1500,
                system=SYSTEM_PROMPT,
                messages=messages,
            )
            text = message.content[0].text.strip()
            text = re.sub(r'^```json\s*', '', text)
            text = re.sub(r'\s*```$', '', text)
            result = json.loads(text)
        except json.JSONDecodeError as e:
            print(f"    JSONパース失敗 (attempt {attempt+1}): {e}")
            return last_result
        except Exception as e:
            print(f"    APIエラー詳細 (attempt {attempt+1}): {type(e).__name__}: {e}")
            return last_result

        # 検証無しなら即返却
        if not validate_fn:
            return result

        # ホワイトリスト検証＋正規化
        specs = result.get("item_specifics", {})
        normalized, violations = validate_fn(specs, category)
        result["item_specifics"] = normalized
        last_result = result

        if not violations:
            if attempt > 0:
                print(f"    ✓ ホワイトリスト合格 (attempt {attempt+1})")
            return result

        if attempt >= retries:
            print(f"    ⚠️ {retries+1}回試行後も違反{len(violations)}件:")
            for f, o, _ex, r in violations:
                print(f"       - {f}: '{o}' ({r})")
            print(f"    → 正規化値で進行")
            return result

        # フィードバック付き再リクエスト
        feedback = feedback_fn(violations)
        print(f"    ↻ ホワイトリスト違反{len(violations)}件、再試行 {attempt+1}/{retries}")
        for vf, vo, _ve, vr in violations:
            print(f"       - {vf}: '{vo}' ({vr})")
        messages.append({"role": "assistant", "content": text})
        messages.append({"role": "user", "content": feedback})

    return last_result

def load_targets_from_sheet(sheet_cfg):
    """統合Hight/Low スプシから R列カテゴリで絞り込み + ItemIDブランク行を取得"""
    import gspread
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_file(
        GSHEET_CREDS, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(sheet_cfg["sheet_id"])
    ws = sh.get_worksheet_by_id(sheet_cfg["gid"])
    all_values = ws.get_all_values()
    cat_filter = sheet_cfg.get("category_filter")
    targets = []
    for i, row in enumerate(all_values[1:], start=2):
        url = row[0] if row and row[0] else ""
        item_id = row[1] if len(row) > 1 else ""
        title_jp = row[2] if len(row) > 2 else ""
        sold = row[3] if len(row) > 3 else ""
        condition = row[4] if len(row) > 4 else ""
        price = row[5] if len(row) > 5 else ""
        photo_urls = row[6] if len(row) > 6 else ""
        description = row[7] if len(row) > 7 else ""
        condition_id = row[11] if len(row) > 11 else ""  # L列 ConditionID (1000=新品/3000=中古)
        category = row[17] if len(row) > 17 else ""  # R列
        # カテゴリフィルタ + ItemIDブランク & 売り切れでない
        if url and not item_id and not sold and (not cat_filter or category == cat_filter):
            targets.append({
                "URL": url,
                "タイトル": title_jp,
                "状態": condition,
                "ConditionID": condition_id,
                "商品価格": price,
                "写真URL": photo_urls,
                "商品説明": description,
            })
    return targets


def main():
    print("=== iMak Trading Japan - メルカリ → eBay CSV 自動生成 ===\n")

    # --sheet フラグでスプシ指定 (Tシャツと同じ運用)
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--sheet", choices=list(SHEET_REGISTRY.keys()),
                        help="読込スプシ (porter/tomica)。指定なしは商品管理シート.csv (ローカル)")
    args, _ = parser.parse_known_args()

    # --sheet 指定時はカテゴリ別ファイル名に変更（例: reel_upload_*.csv, porter_upload_*.csv）
    global OUTPUT_CSV
    if args.sheet:
        OUTPUT_CSV = _gcop(args.sheet, "upload")

    rows = []
    if args.sheet:
        cfg = SHEET_REGISTRY[args.sheet]
        # 新カテゴリ研究データ強制チェック（漏れがあるとここでエラー終了）
        _validate_research_metadata(args.sheet, cfg)
        print(f"📊 スプシ読込: {cfg['label']} ({cfg['sheet_id'][:12]}...)\n")
        try:
            rows = load_targets_from_sheet(cfg)
        except Exception as e:
            print(f"エラー: スプシ読込失敗: {e}")
            input("Enterで終了...")
            return
    else:
        try:
            with open(INPUT_CSV, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
        except FileNotFoundError:
            print(f"エラー: {INPUT_CSV} が見つかりません。")
            input("Enterで終了...")
            return

    print(f"{len(rows)}件を処理します。\n")

    # リール用: Daiwa公式スペック取得用 driver を共有（Selenium起動コスト分散）
    spec_driver = None
    if args.sheet == "reel":
        try:
            import undetected_chromedriver as uc
            opts = uc.ChromeOptions()
            opts.add_argument("--no-sandbox")
            opts.add_argument("--headless=new")
            spec_driver = uc.Chrome(options=opts, version_main=146)
            print("✅ 公式スペック取得用 driver 起動完了\n")
        except Exception as e:
            print(f"⚠️ spec_driver 起動失敗 (Claude推測のみで続行): {e}\n")

    results = []
    errors = []

    for idx, row in enumerate(rows):
        url = row.get('URL', '')
        title_jp = row.get('タイトル', '')
        condition_jp = row.get('状態', '')
        condition_id_sheet = str(row.get('ConditionID', '')).strip()  # L列の明示指定
        price_jpy = row.get('商品価格', '')
        description_jp = row.get('商品説明', '')
        photo_urls = row.get('写真URL', '')

        print(f"[{idx+1}/{len(rows)}] {title_jp[:40]}...")

        # Amazon URL なら specific variation 名を取得して title_jp を上書き（サイズ・ハンドル等識別用）
        if 'amazon' in url.lower():
            amz_title = fetch_amazon_title(url)
            if amz_title and amz_title != title_jp:
                print(f"    📌 Amazon正式タイトル: {amz_title}")
                title_jp = amz_title

        # 画像取得
        images_b64 = get_images_base64(photo_urls)
        if not images_b64:
            print(f"    [WARN] 画像取得できず -> スキップ")
            errors.append({'url': url, 'title': title_jp, 'reason': '画像取得失敗'})
            continue

        # リール: 公式スペック取得（Daiwa/Shimano 対応）
        official_specs = None
        if args.sheet == "reel" and spec_driver:
            tlow = title_jp.lower()
            try:
                if "daiwa" in tlow or "ダイワ" in title_jp:
                    from daiwa_jp import fetch_reel_specs as _fetch_daiwa
                    official_specs = _fetch_daiwa(spec_driver, title_jp)
                    if official_specs:
                        print(f"    ✓ Daiwa公式: {official_specs.get('matched_item','')[:40]} ({official_specs.get('match_quality')})")
                elif "shimano" in tlow or "シマノ" in title_jp:
                    from shimano_jp import fetch_reel_specs as _fetch_shimano
                    official_specs = _fetch_shimano(spec_driver, title_jp)
                    if official_specs:
                        print(f"    ✓ Shimano公式(Naturum): {official_specs.get('matched_item','')[:40]} ({official_specs.get('match_quality')})")
            except Exception as e:
                print(f"    ⚠️ 公式スペック取得失敗: {e}")

        # Claude API呼び出し（--sheet 指定時はカテゴリ名をホワイトリスト検証に渡す）
        validate_category = args.sheet if args.sheet in ("porter", "reel", "tomica", "ichibankuji") else None
        print(f"    Claude API送信中（画像{len(images_b64)}枚, 検証={validate_category or 'なし'}）...")
        result = call_claude_api(title_jp, description_jp, condition_jp, price_jpy, images_b64,
                                 official_specs=official_specs, category=validate_category)

        if result:
            title_en = result.get('title', '')
            item_specifics = result.get('item_specifics', {})

            # --sheet 指定時: 完全eBay CSV行を生成
            if args.sheet and args.sheet in SHEET_REGISTRY:
                cfg = SHEET_REGISTRY[args.sheet]
                # 新品/中古判定: L列(ConditionID)優先 → なければE列(状態)から推定 → なければcfg
                if condition_id_sheet in ("1000", "1500", "2000", "2010", "2020", "2030", "2500", "2750", "3000", "4000", "5000", "6000", "7000"):
                    # L列に明示的なConditionID入ってる → それを採用
                    final_condition_id = int(condition_id_sheet)
                    is_new = (final_condition_id == 1000)
                else:
                    # L列空欄 → E列(状態)から推定
                    is_new = is_new_condition(condition_jp)
                    final_condition_id = 1000 if is_new else cfg['condition_id']
                # ピックURL (max 12枚)
                pic_urls = [u.strip() for u in (photo_urls or '').split('|') if u.strip()][:12]
                pic_url = '|'.join(pic_urls)
                # 価格決定 (pricing_engine 共通) — eBay市場中央値を取得して反映
                price_str = re.sub(r"[^0-9]", "", str(price_jpy))
                cost_jpy = int(price_str) if price_str else 5000
                _ebay_median = 0.0
                _price_status = "GO"
                try:
                    _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "iMakeBayAPI"))
                    from pricing_engine import compute_listing_price
                    # 市場中央値取得（PRICE_CHECK_CONFIG.enabled なカテゴリのみ。porter等は API 節約のためスキップ）
                    from listing_common import PRICE_CHECK_CONFIG
                    if PRICE_CHECK_CONFIG.get(validate_category, {}).get("enabled"):
                        try:
                            from check_csv_core import fetch_ebay_market_median
                            _kw = " ".join(title_en.split()[:5]) if title_en else ""
                            _ebay_median, _hits = fetch_ebay_market_median(
                                keywords=_kw, category_ids=str(cfg['ebay_category']),
                                condition_id=str(final_condition_id), limit=30,
                            )
                            if _ebay_median > 0:
                                print(f"    📊 eBay median ${_ebay_median:.2f} (hits={_hits}) for '{_kw}'")
                        except Exception as _me:
                            print(f"    ⚠️ median取得失敗→median=0で続行: {_me}")
                    pricing = compute_listing_price(cost_jpy, _ebay_median, cfg['profit_category'])
                    listing_price = max(pricing.get('price', 0), 9.98)
                    _price_status = pricing.get('status', 'GO')
                except Exception as _e:
                    listing_price = max(round(cost_jpy / 100, 2), 9.98)
                # SKU
                sku = extract_sku_from_url(url, category=args.sheet)
                # Description: 新品なら NEW.txt、中古なら cfg指定（USED.txt等）
                desc_template = "NEW.txt" if is_new else cfg.get('description_template', 'USED.txt')
                tpl_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), desc_template)
                desc_html = build_description_with_specs(tpl_path, item_specifics)
                # 送料
                ship_policy = get_shipping_policy(listing_price)
                # 行構築
                # リール: 既存imax-64出品も全て 261030 (Sporting Goods > Fishing > Reels)
                # Claude reel_type は Item Specifics の Reel Type 用に保持
                ebay_cat = cfg['ebay_category']
                # ConditionID は判定ロジック結果を採用
                condition_id = final_condition_id

                # === Title整合性保証 + パディング（listing_common.normalize_title）===
                # 旧: reel限定 if 文 → 全カテゴリ自動適用
                title_en = normalize_title(
                    title_en, is_new=is_new, item_specifics=item_specifics,
                    category=args.sheet, target_min=70, max_chars=80,
                )

                row_data = {
                    "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)": "Add",
                    "*Category": ebay_cat,
                    "*Title": title_en,
                    "PicURL": pic_url,
                    "*StartPrice": listing_price,
                    "ConditionID": condition_id,
                    "ScheduleTime": get_schedule_time(),
                    "CustomLabel": sku,
                    "*Description": desc_html,
                    "*Format": "FixedPrice",
                    "*Duration": "GTC",
                    "*Quantity": 1,
                    "*Location": LOCATION,
                    "BestOfferEnabled": 1,
                    "ShippingProfileName": ship_policy,
                    "ReturnProfileName": RETURN_POLICY,
                    "PaymentProfileName": PAYMENT_POLICY,
                    # 新品(1000)はConditionDescription不要（eBayが無視）、中古のみ記入
                    "ConditionDescription": "" if is_new else result.get('condition_description', ''),
                    "StoreCategoryID": cfg['store_category'],
                }
                # Item Specifics を C: プレフィックスで追加
                for k, v in item_specifics.items():
                    row_data[f"C:{k}"] = v

                # === Layer 4: 妥当性ゲート (CSV出力前) ===
                hold_reasons = []
                if validate_category:
                    try:
                        from whitelist_registry import validate_and_normalize as _v
                        _, plaus_violations = _v(item_specifics, validate_category)
                        # plausibility_range 系の違反だけ HOLD 対象（フォーマット違反は別途で対応済）
                        for f, o, _ex, r in plaus_violations:
                            if "範囲外" in r or "異種商品混入" in r:
                                hold_reasons.append(f"{f}='{o}' {r}")
                    except Exception as _e:
                        pass

                # === 物理ゲート: listing_common.audit_csv_row でerror検出 → HOLDへ ===
                from listing_common import gate_row_or_hold as _gate
                _allowed, _viol = _gate(row_data, category=validate_category,
                                         mercari_state=condition_jp, sku=sku,
                                         price_status=_price_status, median_usd=_ebay_median)
                if not _allowed:
                    _err_msgs = [f"{f}={i}" for f, i, s in _viol if s == "error"]
                    hold_reasons.extend(_err_msgs)

                if hold_reasons:
                    # HOLD: CSV出力せず。jsonl への追記は gate_row_or_hold 内部で完結（SSOT=listing_common.append_to_hold_queue）
                    print(f"    🟠 HOLD ({len(hold_reasons)}件の妥当性違反、CSV除外): {title_en}")
                    for hr in hold_reasons:
                        print(f"       - {hr}")
                    errors.append({'url': url, 'title': title_jp, 'reason': f'HOLD: {hold_reasons}'})
                    continue

                results.append(row_data)
                t_ok = "OK" if len(title_en) <= 80 else f"WARN:{len(title_en)}chars"
                print(f"    {t_ok} ({len(title_en)}字) ${listing_price} SKU={sku} {title_en}")
            else:
                # 旧: 中間CSV形式
                output_row = {
                    'URL': url,
                    'Mercari Title': title_jp,
                    'Category': result.get('category_identified', ''),
                    'eBay Title': title_en,
                    'Title Length': len(title_en),
                    'ScheduleTime': get_schedule_time(),
                    'Condition Description': result.get('condition_description', ''),
                    'Notes': result.get('notes', ''),
                }
                for k, v in item_specifics.items():
                    output_row[f'IS: {k}'] = v
                results.append(output_row)
                t_ok = "OK" if len(title_en) <= 80 else f"WARN:{len(title_en)}chars"
                print(f"    {t_ok} ({len(title_en)}字) {title_en}")
        else:
            errors.append({'url': url, 'title': title_jp, 'reason': 'API失敗'})
            print(f"    [NG] 生成失敗")

        time.sleep(3)

    # CSV出力
    if results:
        all_keys = []
        for r in results:
            for k in r.keys():
                if k not in all_keys:
                    all_keys.append(k)

        with open(OUTPUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(results)

        # Step 8 拡張: decision_log に config_version + 使用値を刻印
        try:
            import sys as _sys_dl
            _sys_dl.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "iMakeBayAPI"))
            from decision_log import log_csv_batch as _log_batch
            _log_batch(project="iMakMercari", category="Tシャツ(UT)",
                       output_path=OUTPUT_CSV, row_count=len(results))
        except Exception as _e:
            print(f"⚠️ decision_log 失敗 (Mercari): {type(_e).__name__}: {_e}")

        print(f"\n[OK] 完了! 出力: {OUTPUT_CSV}")
        print(f"成功: {len(results)}件 / 失敗・HOLD: {len(errors)}件")
    else:
        print("\n[NG] 出力データなし")

    # HOLDキュー件数サマリー
    hold_count = sum(1 for e in errors if 'HOLD' in str(e.get('reason', '')))
    if hold_count:
        print(f"\n🟠 HOLDキュー追加: {hold_count}件 → iMakHQ/review_logs/csv_hold_queue.jsonl で人間レビュー")
    if errors:
        print(f"\n失敗一覧:")
        for e in errors:
            print(f"  {e['title'][:30]} → {e['reason']}")

    # spec_driver クリーンアップ
    if spec_driver:
        try:
            spec_driver.quit()
        except Exception:
            pass

    try:
        input("\nEnterで終了...")
    except EOFError:
        pass  # subprocess 実行時(stdin無し)は何もせず終了

if __name__ == "__main__":
    main()
