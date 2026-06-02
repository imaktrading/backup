"""workman_listing - ワークマン公式 → eBay FileExchange variation CSV (Phase 2).

Phase 2 仕様書 v2 準拠 (2026-05-17 着手 GO):
  - 入力源: ★公式在庫要チェック スプシ シート1 C列空行 pickup
  - catalog lookup: `workman:series:<hinban>` (集約 entry) 優先
  - cache miss 時 AJAX endpoint fresh fetch (1h cache、catalog 経由)
  - variation listing CSV (親 1 + 子 N 行、Relationship/RelationshipDetails)
  - Title pattern: `[Name] [Color] [Features] Workman [SubBrand] Japan Limited New`
  - Description: NEW.txt テンプレ (= generic、商品個別情報は Item Specifics で表現)
  - Country/Region of Manufacture: 固定 `Does not apply` (CLAUDE.md 原則)
  - sku_matrix 空 entry → skip + ログ
  - color別画像: 親 PicURL = `Black=URL|Blue=URL|Gray=URL` format

使い方:
  python workman_listing.py                # dry-run なし (= シート1 全件 pickup → CSV)
  python workman_listing.py --dry-run      # CSV 生成のみ、shell に summary
  python workman_listing.py --pid workman:series:21117  # 単発 (test 用)
"""
from __future__ import annotations
import argparse
import csv
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import gspread
import requests
from bs4 import BeautifulSoup
from google.oauth2.service_account import Credentials

_HERE = os.path.dirname(os.path.abspath(__file__))
_EBAY_API = os.path.normpath(os.path.join(_HERE, "..", "iMakeBayAPI"))
for p in (_HERE, _EBAY_API):
    if p not in sys.path:
        sys.path.insert(0, p)

# ============================================================================
# スプシ / DB / output / API 設定
# ============================================================================
# ★公式在庫要チェック (シート1 = listing 単位管理)
SHEET_ID = "101KL6KxMugKqZeSp2W5L2ykTvT0Zwd3RzlfsHgiJsg0"
SHEET1_TAB_NAMES = ("メイン", "main", "Main", "Sheet1", "シート1")
CREDS_PATH = r"c:\dev\iMak\double-hold-421922-7c0d38d3f73d.json"
GSCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# シート1 列 (= Inventory sheet_updater.py と一致、1-based → 0-based 変換)
COL_FLG = 0          # A: 1=除外
COL_TITLE = 1        # B
COL_LISTING_ID = 2   # C: 空 = 未出品
COL_EBAY_URL = 4     # E
COL_URL = 5          # F: 仕入元 URL
COL_CHK_DATE = 6     # G

# Catalog DB
DB_PATH = r"C:/dev/iMak_data/catalog/products.sqlite"

# AJAX endpoint (= Harvest/Inventory 発見、Phase 2 確定)
AJAX_ENDPOINT = "https://workman.jp/shop/goods/ajaxgoodsstock.aspx"
AJAX_TIMEOUT = 20
AJAX_UA = "Mozilla/5.0 iMakHQ/Workman-Listing"
CACHE_TTL_SEC = 3600  # 1h cache

# 出力
OUTPUT_DIR = os.path.normpath(os.path.join(_HERE, "..", "iMakHQ", "csv_output"))

# eBay 共通設定
RETURN_PROFILE = "customer1"
PAYMENT_PROFILE = "SALE"
DURATION = "GTC"
FORMAT_FIXED = "FixedPrice"
CONDITION_ID = "1000"  # New with tags
SCHEDULE_DAYS = 14     # ScheduleTime = 2 週間後 UTC (CLAUDE.md 共通固定値)


def schedule_time() -> str:
    dt = datetime.now(timezone.utc) + timedelta(days=SCHEDULE_DAYS)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

# Description テンプレ (NEW_workman.txt = Workman 専用、{{PRODUCT_NAME}} / {{PRODUCT_SPECIFIC_SECTION}} placeholder 含む)
NEW_TXT_PATH = os.path.join(_HERE, "NEW_workman.txt")

# ============================================================================
# eBay カテゴリ mapping (Workman 商品カテゴリ → eBay category ID)
# 不明 / 未確認のカテゴリは 暫定 (= dry-run 後に正確化)
# ============================================================================
CATEGORY_MAP = {
    "c5202": ("185076", "Men's Activewear Pants"),     # メンズ/ボトムス (= 確認済 leaf)
    "c5201": ("185099", "Men's Activewear Tops"),      # メンズ/トップス (= 暫定 leaf)
    "c5200": ("57988", "Men's Coats, Jackets & Vests"),  # メンズ/アウター
    "c5104": ("57988", "Men's Coats, Jackets & Vests"),  # ペルチェ/ファンウエア
    "c5107": ("57988", "Men's Coats, Jackets & Vests"),  # レイン
}
DEFAULT_CATEGORY = ("185076", "Men's Activewear (default)")

# ============================================================================
# eBay color enum → SKU code (variant SKU 一意性)
# ============================================================================
EBAY_COLOR_TO_SKU_CODE = {
    "Black": "BLK", "Blue": "BLU", "Gray": "GRY", "Grey": "GRY",
    "Green": "GRN", "White": "WHT", "Red": "RED", "Yellow": "YEL",
    "Orange": "ORG", "Pink": "PNK", "Purple": "PRP", "Brown": "BRN",
    "Beige": "BEI", "Navy": "NVY", "Silver": "SLV", "Gold": "GLD",
    "Multicolor": "MUL",
}

# ============================================================================
# DDP shipping policy (CLAUDE.md DDP 送料テーブル準拠)
# ============================================================================
def pick_shipping_profile(price_usd: float) -> str:
    """V6/V5/Free モード別 Shipping Profile 名 (listing_common 経由).
    Workman = アパレル系 → Group C (= Tシャツ/Montbell と同 Policy 構造)."""
    try:
        from listing_common import get_shipping_policy_name
        return get_shipping_policy_name(price_usd, "Tシャツ(UT)")
    except Exception:
        if price_usd < 39:    return "<39"
        if price_usd < 60:    return "40-60"
        if price_usd < 100:   return "60-100"
        if price_usd < 200:   return "100-200"
        if price_usd < 300:   return "200-300"
        if price_usd < 400:   return "300-400"
        if price_usd < 500:   return "400-500"
        if price_usd < 600:   return "500-600"
        if price_usd < 800:   return "600-800"
        return "800-1000"


# ============================================================================
# material_jp → eBay Material enum (CLAUDE.md フィルタ正規化)
# ============================================================================
def material_jp_to_detail_en(material_jp: str) -> str:
    """`ポリエステル90％・ポリウレタン10％` → `Polyester 90% / Polyurethane 10%`.

    eBay description 内で素材組成の詳細を英語表記.
    """
    if not material_jp:
        return ""
    s = material_jp
    repl = [
        ("ポリエステル", "Polyester"),
        ("ポリウレタン", "Polyurethane"),
        ("ポリプロピレン", "Polypropylene"),
        ("コットン", "Cotton"),
        ("綿", "Cotton"),
        ("ナイロン", "Nylon"),
        ("ウール", "Wool"),
        ("羊毛", "Wool"),
        ("アクリル", "Acrylic"),
        ("レーヨン", "Rayon"),
        ("リネン", "Linen"),
        ("麻", "Linen"),
        ("和紙", "Washi Paper"),
        ("シルク", "Silk"),
        ("絹", "Silk"),
        ("％", "%"),
        ("・", " / "),
        ("(本体)", " (Body)"),
        ("(別布)", " (Trim)"),
        ("(裏地)", " (Lining)"),
        ("(中わた)", " (Filling)"),
    ]
    for jp, en in repl:
        s = s.replace(jp, en)
    # 英単語と数字の間にスペース挿入 (Polyester90% → Polyester 90%)
    s = re.sub(r"([A-Za-z])(\d)", r"\1 \2", s)
    return s.strip()


def material_jp_to_ebay(material_jp: str) -> str:
    if not material_jp:
        return ""
    has_poly = "ポリエステル" in material_jp
    has_pu = "ポリウレタン" in material_jp
    has_cotton = "綿" in material_jp or "コットン" in material_jp
    has_nylon = "ナイロン" in material_jp
    has_wool = "ウール" in material_jp or "羊毛" in material_jp
    if has_poly and (has_pu or has_nylon):
        return "Polyester Blend"
    if has_cotton and has_poly:
        return "Cotton Blend"
    if has_poly:
        return "Polyester"
    if has_cotton:
        return "Cotton"
    if has_nylon:
        return "Nylon"
    if has_wool:
        return "Wool"
    return ""  # 推測しない (eBay AI に補完させない)


# ============================================================================
# Workman カテゴリ → Item Specifics 推定マッピング
# ============================================================================
def derive_type_from_category(category_code: str, name_en: str) -> str:
    """商品 type (= eBay Item Specifics C:Type) 推定."""
    n = (name_en or "").lower()
    if category_code == "c5202":  # ボトムス
        if "jogger" in n: return "Joggers"
        if "cargo" in n: return "Cargo Pants"
        if "short" in n: return "Shorts"
        return "Pants"
    if category_code == "c5201":  # トップス
        if "polo" in n: return "Polo Shirt"
        if "long" in n and "sleeve" in n: return "Long Sleeve T-Shirt"
        if "t-shirt" in n or "tshirt" in n or "shirt" in n: return "T-Shirt"
        return "Shirt"
    if category_code == "c5200":  # アウター
        if "jacket" in n: return "Jacket"
        if "parka" in n: return "Parka"
        if "vest" in n: return "Vest"
        return "Outerwear"
    if category_code == "c5104":  # ペルチェ/ファンウエア
        if "vest" in n: return "Vest"
        if "jacket" in n: return "Jacket"
        return "Cooling Wear"
    if category_code == "c5107":  # レイン/ヤッケ
        if "suit" in n: return "Rain Suit"
        if "jacket" in n: return "Rain Jacket"
        if "pants" in n: return "Rain Pants"
        return "Rain Wear"
    return ""


def derive_activity(category_code: str, features: list) -> str:
    """C:Performance/Activity 推定."""
    fs = set(features or [])
    if category_code in ("c5202", "c5201") and "Quick-Dry" in fs:
        return "Running"
    if category_code == "c5107":
        return "Outdoor"
    if category_code == "c5104":
        return "Outdoor"
    if category_code in ("c5200", "c5201", "c5202"):
        return "Outdoor"
    return ""


def derive_season(features: list, category_code: str) -> str:
    """C:Season 推定."""
    fs = set(features or [])
    if "Cooling" in fs or "Heat-Reduction" in fs or "Peltier Cooling" in fs:
        return "Spring/Summer"
    if "Insulation" in fs or "Heater" in fs:
        return "Fall/Winter"
    return "All Season"


def derive_closure(category_code: str, name_en: str) -> str:
    """C:Closure 推定."""
    n = (name_en or "").lower()
    if category_code == "c5202":  # pants
        if "zip" in n: return "Zipper"
        return "Drawstring"
    if category_code in ("c5200", "c5104", "c5107"):  # jacket/vest/rain
        if "pullover" in n or "anorak" in n: return "Pullover"
        return "Zipper"
    return ""


def derive_style(category_code: str, name_en: str, features: list) -> str:
    """C:Style 推定."""
    n = (name_en or "").lower()
    fs = set(features or [])
    if "Peltier Cooling" in fs:
        return "Cooling"
    if category_code == "c5107":
        return "Outdoor"
    if "stretch" in n:
        return "Athletic"
    return "Activewear"


# ============================================================================
# Title 生成
# ============================================================================
MAX_TITLE = 80


def build_title(name_en: str, color_count: int, features: list, brand_jp: str) -> str:
    """`[Name] [Features] Workman [SubBrand] Japan Limited New` 80 字以内.

    短縮 戦略 (= 単語境界遵守、途中切断なし):
      1. features 2 個 + name 全文
      2. features 1 個
      3. features 0 個
      4. name を単語末尾から削除
      5. 最終: name 1 word
    """
    sub_brand = _brand_jp_to_en(brand_jp)
    suffix_parts = ["Workman"]
    if sub_brand:
        suffix_parts.append(sub_brand)
    suffix_parts += ["Japan", "Limited", "New"]
    suffix = " ".join(suffix_parts)

    def _compose(name: str, feats: list) -> str:
        parts = [name.strip()]
        if feats:
            parts.append(" ".join(feats))
        parts.append(suffix)
        return " ".join(parts)

    # 試行順: features 数を減らしていく
    for nfeat in (min(2, len(features)), 1, 0):
        t = _compose(name_en, features[:nfeat])
        if len(t) <= MAX_TITLE:
            return t
    # name 単語末尾から削除 (= word-boundary 遵守、途中切断なし)
    words = name_en.split()
    while len(words) > 1:
        words.pop()
        t = _compose(" ".join(words), [])
        if len(t) <= MAX_TITLE:
            return t
    # 最終: name 1 word 強制 trim
    t = _compose(words[0] if words else name_en[:20], [])
    return t[:MAX_TITLE]


def _brand_jp_to_en(brand_jp: str) -> str:
    """Workman 内 sub-brand 日本語 → 英語. 全角/半角括弧両対応."""
    if not brand_jp:
        return ""
    m = {
        "ワーク": "WORK", "デイズ": "DAYS", "アウトドア": "OUTDOOR",
        "スポーツ": "SPORTS", "ファインドアウト": "Find-Out",
        "ワークマンベスト": "BEST", "イージス": "AEGIS",
        "ジーベック": "Xebec", "寅壱": "Toraichi",
    }
    # 括弧 (全角/半角) より前の部分で match
    prefix = re.split(r"[\s（(]", brand_jp.strip(), maxsplit=1)[0]
    if prefix in m:
        return m[prefix]
    # fallback: 括弧内英字抽出 (= 公式 ASCII 名がある場合)
    mm = re.search(r"[（(]([A-Za-z][A-Za-z0-9\- ]*)[)）]", brand_jp)
    if mm:
        return mm.group(1).strip()
    return ""


# ============================================================================
# Description: 商品固有 section + NEW.txt generic
# ============================================================================
_DESC_CACHE: dict = {}


def load_description_template() -> str:
    if "html" not in _DESC_CACHE:
        with open(NEW_TXT_PATH, "r", encoding="utf-8") as f:
            _DESC_CACHE["html"] = f.read()
    return _DESC_CACHE["html"]


# Workman brand line の説明 (= 海外バイヤー向け差別化訴求)
_BRAND_LINE_DESC = {
    "AEGIS": "Workman's premium waterproof line. Engineered for heavy rain and outdoor conditions.",
    "WindCore": "Fan-powered cooling wear and battery-heated apparel — Workman's flagship climate tech.",
    "FieldCore": "All-season outdoor and casual wear with durable performance fabrics.",
    "Find-Out": "Lightweight active line for everyday athletic use.",
    "BEST": "Workman BEST — premium tier of Workman's value workwear collection.",
    "WORK": "Heavy-duty professional workwear engineered for real job sites.",
    "DAYS": "Casual everyday wear with Workman's signature performance fabrics.",
    "OUTDOOR": "Outdoor-focused performance wear — camping, hiking, trail-ready.",
    "SPORTS": "Sports & athletic performance line — running, training, active use.",
    "Xebec": "Xebec — premium Japanese workwear brand carried by Workman.",
    "Toraichi": "Toraichi — iconic Japanese tobi-style workwear.",
}


# Workman の主要機能 (= 公式 features) の英語説明
_FEATURE_DESC = {
    "Stretch": "4-way stretch fabric for unrestricted movement.",
    "UV Protection": "Blocks 90%+ UV rays — UPF rated for sun protection.",
    "Water-Repellent": "Repels light rain and stains; treated water-repellent finish.",
    "Waterproof": "Fully waterproof construction — keeps you dry in heavy rain.",
    "Cooling": "Contact-cooling fabric (cold-to-touch) for hot-weather comfort.",
    "Quick-Dry": "Moisture-wicking — dries quickly after sweat or rain.",
    "Deodorizing": "Built-in odor control — stays fresh through long days.",
    "Windproof": "Wind-blocking layer — retains warmth in cold winds.",
    "Heat-Reduction": "Advanced heat-reflection — keeps body temperature down.",
    "Peltier Cooling": "Electronic Peltier cooling system (battery-powered) — Workman's signature cooling vest tech.",
    "Reflective": "Reflective accents for visibility in low light.",
    "Breathable": "High air-flow fabric — vents heat and moisture.",
}


def _build_product_specific_section(rec: dict) -> str:
    """商品固有 section HTML (= NEW.txt の "Brand New" 段落の直後に挿入).

    Brand New / We handle genuine は NEW.txt 既存 generic 段落で扱うため
    ここでは重複追加しない。商品価値情報のみ集約.

    順序: Features → Product Line → Size Chart → Material → Color options
          → Japan Exclusive (= 希少性 CTA).

    各 section データなければ自動スキップ (= 100 SKU 再現性).
    """
    s = rec["specs"]
    brand_line = _brand_jp_to_en(s.get("brand", ""))
    color_variants = s.get("color_variants", [])
    size_variants = s.get("size_variants", [])
    features = s.get("features", [])
    material_en = material_jp_to_ebay(s.get("material_jp", ""))

    h = ['<div style="font-family:Arial,sans-serif;margin-top:16px;">']

    # 1. Technical Features
    if features:
        h.append("<p><span style='text-decoration:underline;'><strong>Technical Features</strong></span></p><ul>")
        for f in features:
            desc = _FEATURE_DESC.get(f, "")
            if desc:
                h.append(f"<li><b>{f}:</b> {desc}</li>")
            else:
                h.append(f"<li><b>{f}</b></li>")
        h.append("</ul>")

    # 2. Product Line box (mobile responsive padding)
    if brand_line and brand_line in _BRAND_LINE_DESC:
        h.append(f"<div style='background:#f0f7ff;padding:10px 14px;border-left:4px solid #003366;margin:12px 0;font-size:14px;'>"
                 f"<b>Product Line: {brand_line}</b><br>{_BRAND_LINE_DESC[brand_line]}</div>")

    # 3. Size Chart
    chart = s.get("size_chart") or _DEMO_SIZE_CHART.get(s.get("representative_hinban", ""))
    if chart and size_variants:
        h.append("<p><span style='text-decoration:underline;'><strong>Size Chart</strong></span></p>")
        h.append(build_size_chart_html(chart, size_variants))
        h.append("<p style='color:#888;font-size:14px;'>"
                 "* Sizes shown as US (Japan equivalent in parentheses). "
                 "Japanese-brand garments typically run one size smaller than US.</p>")

    # 4. Material
    if material_en:
        detail = material_jp_to_detail_en(s.get("material_jp", ""))
        h.append(f"<p><b>Material:</b> {material_en}")
        if detail and detail != material_en:
            h.append(f" <span style='color:#888;'>({detail})</span>")
        h.append("</p>")

    # 5. Color options (variation dropdown 補足)
    if color_variants:
        colors = ", ".join(cv["ebay_color"] for cv in color_variants)
        h.append(f"<p style='font-size:14px;color:#666;'><b>Color options:</b> {colors} "
                 "<i>(select from variation dropdown above)</i></p>")

    # 6. Japan Exclusive (= 希少性 CTA、mobile responsive padding)
    h.append("<div style='background:#fff5e6;padding:10px 14px;border-left:4px solid #cc6600;margin:16px 0;font-size:14px;'>"
             "<b>🇯🇵 Japan Exclusive:</b> Workman products are sold exclusively in Japan. "
             "Imported directly for international customers — limited stock available.</div>")

    h.append("</div>")
    return "".join(h)


def build_description_html(rec: dict) -> str:
    """NEW_workman.txt template に placeholder 置換で description を生成.

    - {{PRODUCT_NAME}}            → name_en (= 灰背景の title-part に)
    - {{PRODUCT_SPECIFIC_SECTION}} → 商品固有 section (= image-gallery の下、policy の上)
    """
    name_en = rec["name_en"] or rec["name_jp"]
    template = load_description_template()
    section = _build_product_specific_section(rec)
    out = template.replace("{{PRODUCT_NAME}}", name_en).replace(
        "{{PRODUCT_SPECIFIC_SECTION}}", section
    )
    return out


# JP サイズ → US 相当併記 (= ワンサイズダウン、Workman 公式チャート準拠)
# 日本ブランドは US より小さめ表記、JP M ≈ US S 相当
_JP_SIZE_TO_US_EQUIV = {
    "S": "US XS",
    "M": "US S",
    "L": "US M",
    "LL": "US L",
    "3L": "US XL",
    "4L": "US XXL",
    "5L": "US 3XL",
    "フリー": "One Size",
    "Free": "One Size",
}


def cm_to_inch(cm_val) -> str:
    """`78` or `76-84` を inch 表記併記."""
    if cm_val is None or cm_val == "":
        return ""
    s = str(cm_val).strip()
    # 範囲 (例: "76-84")
    if "-" in s or "〜" in s:
        sep = "-" if "-" in s else "〜"
        parts = s.replace("〜", "-").split("-")
        try:
            a, b = float(parts[0]), float(parts[1])
            return f'{int(a)}-{int(b)} cm ({a/2.54:.1f}-{b/2.54:.1f}")'
        except Exception:
            return f"{s} cm"
    try:
        v = float(s)
        return f'{int(v) if v.is_integer() else v} cm ({v/2.54:.1f}")'
    except Exception:
        return f"{s} cm"


# Size chart label の日本語 → 英語
_SIZE_CHART_LABEL_EN = {
    "ウエスト": "Waist",
    "胸囲": "Chest",
    "肩幅": "Shoulder",
    "袖丈": "Sleeve",
    "着丈": "Length",
    "股下": "Inseam",
    "股上": "Rise",
    "ヒップ": "Hip",
    "もも": "Thigh",
    "もも周り": "Thigh",
    "わたり": "Thigh Width",
    "わたり巾": "Thigh Width",
    "裾": "Hem",
    "裾巾": "Hem Width",
    "首回り": "Neck",
    "Waist": "Waist", "Hip": "Hip", "Inseam": "Inseam",
    "Thigh Width": "Thigh Width", "Chest": "Chest",
}


def build_size_chart_html(size_chart: dict, size_variants: list) -> str:
    """size_chart = {"Waist": {"M": "76-84", ...}, ...} → HTML table.

    mobile responsive: overflow-x:auto wrapper + relative font-size (vw).
    """
    if not size_chart or not size_variants:
        return ""
    h = []
    # responsive wrapper (mobile で横スクロール、PC は table 100%)
    h.append("<div style='overflow-x:auto;-webkit-overflow-scrolling:touch;margin:8px 0;'>")
    h.append("<table style='border-collapse:collapse;min-width:100%;font-size:13px;border:1px solid #ddd;'>")
    # header row
    h.append("<thead><tr style='background:#003366;color:#fff;'>")
    h.append("<th style='padding:6px 8px;border:1px solid #ddd;text-align:left;white-space:nowrap;'>Measurement</th>")
    for sz in size_variants:
        h.append(f"<th style='padding:6px 8px;border:1px solid #ddd;white-space:nowrap;'>{size_jp_to_jp_us(sz)}</th>")
    h.append("</tr></thead><tbody>")
    # body rows
    for label_key, by_size in size_chart.items():
        en = _SIZE_CHART_LABEL_EN.get(label_key, label_key)
        h.append("<tr>")
        h.append(f"<td style='padding:6px 8px;border:1px solid #ddd;font-weight:bold;white-space:nowrap;'>{en}</td>")
        for sz in size_variants:
            v = by_size.get(sz, "")
            h.append(f"<td style='padding:6px 8px;border:1px solid #ddd;white-space:nowrap;'>{cm_to_inch(v)}</td>")
        h.append("</tr>")
    h.append("</tbody></table>")
    h.append("</div>")
    h.append("<p style='color:#888;font-size:12px;margin-top:4px;'>* Measurements from Workman official spec. Slight variations may occur.</p>")
    return "".join(h)


# === Demo size chart (Catalog SSOT 完了までの暫定、21117 のみ) ===
# 本番運用時は catalog `specs.size_chart` に置換される
_DEMO_SIZE_CHART = {
    "21117": {
        "Waist": {"M": "76-84", "L": "84-92", "LL": "92-100", "3L": "100-108"},
        "Hip":   {"M": "100",   "L": "104",   "LL": "108",    "3L": "112"},
        "Thigh Width": {"M": "31", "L": "32", "LL": "33", "3L": "34"},
        "Inseam": {"M": "64",   "L": "65",    "LL": "66",     "3L": "67"},
    }
}


def size_jp_to_jp_us(size_jp: str) -> str:
    """`M` → `US S (JP M)` 形式 (UNIQLO/montbell と同 pattern、US 表記がメイン)."""
    if not size_jp:
        return ""
    if size_jp in ("One Size", "Free"):
        return size_jp
    us = _JP_SIZE_TO_US_EQUIV.get(size_jp, "")
    # us は "US S" 等のフルラベル
    if us:
        return f"{us} (JP {size_jp})"
    return f"JP {size_jp}"


# ============================================================================
# AJAX fresh fetch (catalog cache miss 時) + 1h cache
# ============================================================================
_AJAX_CACHE: dict = {}


def fetch_ajax_variations_cached(parent_mpn: str) -> Optional[dict]:
    """1h cache + AJAX endpoint fresh fetch.

    Returns dict like catalog 集約 entry's specs (color_variants, size_variants, sku_matrix).
    """
    now = time.time()
    if parent_mpn in _AJAX_CACHE:
        cached_at, data = _AJAX_CACHE[parent_mpn]
        if now - cached_at < CACHE_TTL_SEC:
            return data
    try:
        resp = requests.post(
            AJAX_ENDPOINT,
            data={"goods": parent_mpn, "is_preview": ""},
            headers={"X-Requested-With": "XMLHttpRequest", "User-Agent": AJAX_UA},
            timeout=AJAX_TIMEOUT,
        )
        resp.raise_for_status()
        data = _parse_ajax_html(resp.text)
        _AJAX_CACHE[parent_mpn] = (now, data)
        return data
    except Exception as e:
        print(f"    ⚠️ AJAX 失敗 (parent_mpn={parent_mpn}): {type(e).__name__}: {e}")
        return None


def _parse_ajax_html(html: str) -> dict:
    """AJAX HTML 断片を catalog 集約 entry schema 互換 dict に."""
    soup = BeautifulSoup(html, "html.parser")
    colors = []
    for dl in soup.select(".block-color--item"):
        color_jp = dl.get("title", "").strip()
        img = dl.select_one("img")
        img_url = img.get("src", "") if img else ""
        if img_url and img_url.startswith("/"):
            img_url = "https://workman.jp" + img_url
        available = "color-enable-stock" in dl.get("class", [])
        colors.append({
            "color_jp": color_jp,
            "image_url": img_url,
            "available": available,
        })
    sizes_seen = []
    sku_matrix = []
    for pat in soup.select(".block-pattern, .block-pattern.no-stock"):
        size_el = pat.select_one(".block-pattern--size-text")
        size = (size_el.text.strip() if size_el else "").translate(
            str.maketrans("ＳＭＬ", "SML")
        )
        if size and size not in sizes_seen:
            sizes_seen.append(size)
        link = pat.select_one("a[href*='sku=']")
        sku_mpn = ""
        if link:
            m = re.search(r"sku=(\d+)", link.get("href", ""))
            if m:
                sku_mpn = m.group(1)
        in_stock = "no-stock" not in pat.get("class", [])
        sku_matrix.append({
            "variant_sku_mpn": sku_mpn,
            "size_normalized": size,
            "in_stock": in_stock,
        })
    return {
        "color_variants": colors,
        "size_variants": sizes_seen,
        "sku_matrix": sku_matrix,
    }


# ============================================================================
# Catalog lookup
# ============================================================================
def lookup_series_entry(parent_mpn: str) -> Optional[dict]:
    """parent_mpn 13桁 → catalog `workman:series:<hinban>` lookup.

    parent_mpn 形式 `2300067335038` → hinban = 中央 6 桁から zero-strip = `67335`.
    """
    m = re.match(r"^\d{4}(\d{6})\d{3}$", parent_mpn)
    if not m:
        return None
    hinban = m.group(1).lstrip("0")
    pid = f"workman:series:{hinban}"
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "SELECT product_id, name, name_en, specs, source_url FROM products WHERE product_id=?",
        (pid,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "product_id": row[0], "name_jp": row[1], "name_en": row[2],
        "specs": json.loads(row[3]), "source_url": row[4],
    }


# ============================================================================
# 価格計算 (= pricing_engine 流用 or fallback)
# ============================================================================
def compute_listing_price_usd(jpy: int) -> float:
    """compute_listing_price() dispatcher (V6/V5/V4 自動切替) 経由.
    Workman カテゴリは V5 HTS_RATE 未登録のため Tシャツ(UT) (Group C) で代替."""
    try:
        from pricing_engine import compute_listing_price
        r = compute_listing_price(jpy, 0, "Tシャツ(UT)")
        if isinstance(r, dict) and r.get("price"):
            return round(float(r["price"]), 2)
    except Exception:
        pass
    # fallback
    usd = (jpy / 140.0 + 15.0) / 0.72
    return round(usd + 0.98, 2)


# ============================================================================
# シート1 入力源 (= 出品候補 pickup)
# ============================================================================
def load_targets() -> list[dict]:
    creds = Credentials.from_service_account_file(CREDS_PATH, scopes=GSCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SHEET_ID)
    ws = None
    for nm in SHEET1_TAB_NAMES:
        try:
            ws = sh.worksheet(nm)
            break
        except Exception:
            continue
    if ws is None:
        ws = sh.get_worksheet(0)
    rows = ws.get_all_values()
    targets = []
    for i, r in enumerate(rows[1:], start=2):
        if len(r) <= COL_URL:
            continue
        flg = (r[COL_FLG] or "").strip()
        if flg == "1":
            continue
        listing_id = (r[COL_LISTING_ID] or "").strip() if len(r) > COL_LISTING_ID else ""
        if listing_id:
            continue  # 出品済 SKIP
        url = (r[COL_URL] or "").strip()
        if "workman.jp/shop/g/" not in url:
            continue
        title_jp = (r[COL_TITLE] or "").strip() if len(r) > COL_TITLE else ""
        m = re.search(r"/g(\d{13})/?", url)
        if not m:
            continue
        parent_mpn = m.group(1)
        targets.append({
            "row_idx": i,
            "url": url,
            "title_jp": title_jp,
            "parent_mpn": parent_mpn,
        })
    return targets


# ============================================================================
# CSV header (= variation listing format、29 columns)
# ============================================================================
HEADERS = [
    "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)",
    "*Category", "*Title", "*Description", "*ConditionID", "*Format", "*Duration",
    "*Location", "*Country", "PicURL", "*StartPrice", "*Quantity",
    "CustomLabel", "Relationship", "RelationshipDetails",
    "BestOfferEnabled", "ShippingProfileName", "ReturnProfileName", "PaymentProfileName",
    "ScheduleTime", "StoreCategoryID",
    # Item Specifics 23 fields
    "C:Brand", "C:Type", "C:Size Type", "C:Size", "C:Color", "C:Department",
    "C:Style", "C:Material", "C:Fabric Type", "C:Pattern", "C:Features",
    "C:Fit", "C:Closure", "C:Performance/Activity", "C:Season", "C:Theme",
    "C:Product Line", "C:Model", "C:Vintage", "C:Personalize", "C:Handmade",
    "C:Country/Region of Manufacture", "C:Garment Care",
]


# ============================================================================
# 親行 build
# ============================================================================
def build_parent_row(rec: dict, ajax_data: Optional[dict]) -> Optional[list]:
    s = rec["specs"]
    # variation source: catalog cache → ajax fresh の優先順位
    color_variants = s.get("color_variants", []) or (ajax_data or {}).get("color_variants", [])
    size_variants = s.get("size_variants", []) or (ajax_data or {}).get("size_variants", [])
    sku_matrix = s.get("sku_matrix", []) or (ajax_data or {}).get("sku_matrix", [])
    if not sku_matrix:
        return None  # caller で skip

    price_usd = compute_listing_price_usd(s.get("price_jpy", 0))
    ship = pick_shipping_profile(price_usd)

    cat_code = s.get("category_code", "")
    cat_id, cat_label = CATEGORY_MAP.get(cat_code, DEFAULT_CATEGORY)

    title = build_title(
        rec["name_en"] or rec["name_jp"],
        color_count=len(color_variants),
        features=s.get("features", []),
        brand_jp=s.get("brand", ""),
    )
    desc = build_description_html(rec)
    material = material_jp_to_ebay(s.get("material_jp", ""))
    features_str = ", ".join(s.get("features", []))
    type_str = derive_type_from_category(cat_code, rec.get("name_en", ""))
    activity = derive_activity(cat_code, s.get("features", []))
    season = derive_season(s.get("features", []), cat_code)
    closure = derive_closure(cat_code, rec.get("name_en", ""))
    style = derive_style(cat_code, rec.get("name_en", ""), s.get("features", []))
    department = _gender_to_department(s.get("gender", "Men"))

    # 親 PicURL = 全 color 画像 pipe 連結 (= listing 全体の画像群、URL のみ)
    # (color別画像の dropdown 切替対応は別途 VariationSpecificsSet 列要、Phase 2.5)
    pic_url = "|".join(
        cv["image_url"] for cv in color_variants if cv.get("image_url")
    )
    if not pic_url:
        pic_url = s.get("image_url", "")

    # RelationshipDetails (親) = Color=A;B;C|Size=M (Japan/US L);L (Japan/US XL);...
    color_pipe = ";".join(cv["ebay_color"] for cv in color_variants)
    size_pipe = ";".join(size_jp_to_jp_us(sz) for sz in size_variants)
    rel_details = f"Color={color_pipe}|Size={size_pipe}"

    parent_sku = f"WORKMAN-{s.get('representative_hinban','')}"

    return [
        "Add", cat_id, title, desc, CONDITION_ID, FORMAT_FIXED, DURATION,
        "Japan", "JP",
        pic_url,
        "", "",  # StartPrice/Quantity blank on parent
        parent_sku,
        "", rel_details,
        "",  # BestOffer
        ship, RETURN_PROFILE, PAYMENT_PROFILE,
        schedule_time(),   # ScheduleTime = 2 週間後 UTC (CLAUDE.md 共通固定値)
        "",  # StoreCategoryID
        "Workman",          # C:Brand
        type_str,           # C:Type
        "Regular",          # C:Size Type
        "",                 # C:Size (variation 別)
        "",                 # C:Color (variation 別)
        department,         # C:Department
        style,              # C:Style
        material,           # C:Material
        material,           # C:Fabric Type (= material 同等)
        "Solid",            # C:Pattern
        features_str,       # C:Features
        "Regular",          # C:Fit
        closure,            # C:Closure
        activity,           # C:Performance/Activity
        season,             # C:Season
        "Outdoor",          # C:Theme
        _brand_jp_to_en(s.get("brand", "")),  # C:Product Line
        s.get("representative_hinban", ""),    # C:Model
        "No",               # C:Vintage
        "No",               # C:Personalize
        "No",               # C:Handmade
        "Does not apply",   # C:Country/Region of Manufacture (CLAUDE.md 原則)
        "Machine Wash",     # C:Garment Care
    ]


def _gender_to_department(gender: str) -> str:
    g = (gender or "Men").lower()
    if "women" in g or "lady" in g or "レディ" in g:
        return "Women"
    if "kid" in g or "child" in g or "キッズ" in g:
        return "Kids"
    return "Men"


# ============================================================================
# 子行 build
# ============================================================================
def build_variation_rows(rec: dict, ajax_data: Optional[dict], price_usd: float) -> list:
    s = rec["specs"]
    color_variants = s.get("color_variants", []) or (ajax_data or {}).get("color_variants", [])
    sku_matrix = s.get("sku_matrix", []) or (ajax_data or {}).get("sku_matrix", [])
    color_map = {cv["color_jp"]: cv for cv in color_variants}
    # === sku_matrix dedup: (color_jp, size) tuple で uniq ===
    # Catalog 側で同 color×size が複数 mpn 投入されているケースあり (= 35840 例)。
    # eBay variation listing は同組合せ禁止のため、HQ 層で 1 つだけ採用。
    seen = set()
    unique_sku_matrix = []
    for sku in sku_matrix:
        key = (sku.get("color_jp", ""), sku.get("size_normalized", ""))
        if key in seen or not key[0] or not key[1]:
            continue
        seen.add(key)
        unique_sku_matrix.append(sku)
    sku_matrix = unique_sku_matrix
    rows = []
    for sku in sku_matrix:
        cv = color_map.get(sku.get("color_jp", ""))
        if not cv:
            continue
        if not sku.get("variant_sku_mpn") or not sku.get("size_normalized"):
            continue
        color_code = EBAY_COLOR_TO_SKU_CODE.get(cv["ebay_color"], "XXX")
        size_display = size_jp_to_jp_us(sku["size_normalized"])  # M → "M (Japan/US L)"
        variant_sku = (
            f"WORKMAN-{s.get('representative_hinban','')}-"
            f"{color_code}-{sku['size_normalized']}"  # SKU は短く JP のみ
        )
        rows.append([
            "Add", "", "", "", "", "", "", "", "",
            cv.get("image_url", ""),  # PicURL = color別画像
            f"{price_usd:.2f}",  # StartPrice
            "1",                 # Quantity
            variant_sku,
            "Variation",
            f"Color={cv['ebay_color']}|Size={size_display}",  # RelationshipDetails = 親と一致必須
            "", "", "", "", "", "",
            "",  # Brand
            "",  # Type
            "",  # Size Type
            size_display,        # C:Size = JP+US 併記
            cv["ebay_color"],    # C:Color
            "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "",
        ])
    return rows


# ============================================================================
# main
# ============================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", help="単発 mode (= workman:series:<hinban> 指定)")
    ap.add_argument("--dry-run", action="store_true",
                    help="シート1 pickup → CSV 生成のみ (= 上書きなし)")
    ap.add_argument("--max", type=int, default=0, help="処理件数上限 (0=制限なし)")
    args = ap.parse_args()

    rec_targets: list[tuple[dict, dict]] = []  # (target, rec)

    if args.pid:
        # 単発 mode (= test 用、シート1 経由しない)
        m = re.match(r"workman:series:(\d+)", args.pid)
        if not m:
            print(f"⚠️ --pid 形式エラー: {args.pid}")
            return
        hinban = m.group(1)
        # parent_mpn を catalog から逆引き
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute(
            "SELECT specs FROM products WHERE product_id=?", (args.pid,)
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            print(f"⚠️ catalog miss: {args.pid}")
            return
        specs = json.loads(row[0])
        parent_mpn = specs.get("parent_mpn", "")
        rec = lookup_series_entry(parent_mpn)
        if not rec:
            print(f"⚠️ lookup fail: {parent_mpn}")
            return
        rec_targets.append(({"parent_mpn": parent_mpn, "url": rec["source_url"],
                              "title_jp": rec["name_jp"], "row_idx": -1}, rec))
    else:
        # 通常 mode = シート1 pickup
        print("📊 シート1 から Workman 未出品 pickup 中...")
        targets = load_targets()
        print(f"  対象: {len(targets)} 件")
        if not targets:
            print("対象 0 件、終了")
            return
        if args.max:
            targets = targets[: args.max]
        for t in targets:
            rec = lookup_series_entry(t["parent_mpn"])
            if not rec:
                print(f"  ⚠️ catalog miss: {t['parent_mpn']} → SKIP (catalog 投入待ち)")
                continue
            rec_targets.append((t, rec))

    if not rec_targets:
        print("処理対象 0 件、終了")
        return

    rows = [HEADERS]
    success = 0
    skipped = 0
    failed = 0
    for idx, (t, rec) in enumerate(rec_targets):
        s = rec["specs"]
        hinban = s.get("representative_hinban", "")
        print(f"[{idx+1}/{len(rec_targets)}] workman:series:{hinban} | {rec['name_en'] or rec['name_jp']}")

        ajax_data = None
        if not s.get("sku_matrix"):
            print("    🔄 catalog sku_matrix 空 → AJAX fresh fetch")
            ajax_data = fetch_ajax_variations_cached(s.get("parent_mpn", t["parent_mpn"]))
            if not ajax_data or not ajax_data.get("sku_matrix"):
                print("    ⏭️ AJAX も空 → SKIP")
                skipped += 1
                continue

        parent_row = build_parent_row(rec, ajax_data)
        if not parent_row:
            print("    ⏭️ parent row 構築失敗 → SKIP")
            skipped += 1
            continue
        price_usd = compute_listing_price_usd(s.get("price_jpy", 0))
        variation_rows = build_variation_rows(rec, ajax_data, price_usd)
        if not variation_rows:
            print("    ⏭️ variation rows 空 → SKIP")
            skipped += 1
            continue
        rows.append(parent_row)
        rows.extend(variation_rows)
        print(f"    ✨ Title: {parent_row[2]}")
        print(f"    ✨ variation: {len(variation_rows)} 件 / ${price_usd}")
        success += 1

    if success == 0:
        print("\n生成行ゼロ、CSV 出力スキップ")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = "_dry" if args.dry_run else ""
    out = os.path.join(OUTPUT_DIR, f"workman_upload_var_{ts}{suffix}.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        w.writerows(rows)
    # Free Shipping 移行 (2026-05-18)
    # Workman は variation listing 主体、master 行のみ price 加算される (sub 行は price=0 で skip)
    try:
        import sys as _sys_fs
        _sys_fs.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "iMakeBayAPI"))
        from freeshipping_postprocess import transform_csv_to_freeshipping
        transform_csv_to_freeshipping(out)
    except Exception as _e:
        print(f"⚠️ Free Shipping post-process 失敗 (Workman): {type(_e).__name__}: {_e}")
    print(f"\n=== Workman Phase 2 出品 CSV ===")
    print(f"  出力: {out}")
    print(f"  parent listing: {success}件 / variation: {len(rows) - 1 - success}件")
    print(f"  skipped: {skipped}件 / failed: {failed}件")


if __name__ == "__main__":
    main()
