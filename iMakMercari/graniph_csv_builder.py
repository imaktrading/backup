#!/usr/bin/env python3
"""graniph 出品 CSV builder (POC).

依頼書: C:/dev/iMak_data/hq/requests/2026-08-08_graniph_listing_poc_response.md

- 1 URL = 1 color = 1 listing、variation 軸 = Sizes
- Custom Label (SKU) = UUID (14 桁 sku_code は使わない)
- カテゴリ (Men's T-Shirt 15687 / Women's Tops 53159 / unisex は Men's に寄せる)
- Brand は eBay 正規値 (aspectValues) に無いので free text "Graniph"
- 価格帯 group C (hts_rate 0.43) — アパレル
- SS→XXS の one-down マッピング (回答書 Q3 承認)

Usage:
    python graniph_csv_builder.py <URL_or_ITEM_CODE>

Example:
    python graniph_csv_builder.py https://www.graniph.com/item-detail/019001564303
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import uuid
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "iMakeBayAPI"))

from graniph_scraper import GraniphProduct, scrape  # noqa: E402

# ============================================================================
# 定数
# ============================================================================
CATEGORY_MEN = 15687        # Men's Clothing > T-Shirts
CATEGORY_WOMEN = 53159      # Women's Clothing > Tops

# ----------------------------------------------------------------------------
# 仕入送料 (graniph 公式 guide-delivery より、2026-08-08 実取得)
#   https://www.graniph.com/guide/guide-delivery
#   「送料について 全国一律440円（税込）です。
#    ※1回の配送で商品代金とギフトバッグ料金の合計金額が5,000円（税込）以上の場合、
#      送料無料となります。」
# graniph は実店舗が近くにないので必ず通販 = 送料が仕入コストに乗る。
# 相互参照: 監視くん側 iMakeBayAPI/inventory_monitor/graniph_scraper.py にも
# 同じ規則あり (窓口が別途依頼)。片方だけ直る事故を防ぐため両方で同時に是正すること。
# ----------------------------------------------------------------------------
PROCUREMENT_SHIPPING_JPY = 440
FREE_SHIPPING_THRESHOLD_JPY = 5000


def procurement_shipping(item_price_jpy: int) -> int:
    """graniph は実店舗が近くにないので必ず通販 = 送料が仕入コストに乗る。
    公式 guide-delivery より 全国一律 ¥440 / ¥5,000 以上で無料 (2026-08-08 実取得)。
    閾値の判定は「商品代金」で行う (ギフトバッグは使わない、セール中はセール価格が商品代金)。
    """
    return 0 if item_price_jpy >= FREE_SHIPPING_THRESHOLD_JPY else PROCUREMENT_SHIPPING_JPY


# ----------------------------------------------------------------------------
# US unisex T-shirt 標準チャート
#   出典: Gildan 5000 Heavy Cotton Adult Unisex 公式スペック
#          https://www.gildan.com/products/style-5000/G500
#   body length HPS (inch) / chest width across (inch, half of circumference)
#   graniph は unisex ラベル中心なので UNIQLO women's ではなくこのチャートを基準に取る。
# ----------------------------------------------------------------------------
US_UNISEX_TSHIRT_CHART = [
    ("XS",  26.5, 16.5),
    ("S",   28.0, 18.0),
    ("M",   29.0, 20.0),
    ("L",   30.0, 22.0),
    ("XL",  31.0, 24.0),
    ("2XL", 32.0, 26.0),
    ("3XL", 33.0, 28.0),
]
# 距離計算の重み (chest = fit を決める / length = 二次的)
_CHEST_WEIGHT = 2.0
_LENGTH_WEIGHT = 1.0

# graniph JP size → US size (フォールバックのみ、実寸が取れなかった時)
# 実寸が取れる場合は `pick_us_size` 経由で Gildan チャート最近傍が使われる。
SIZE_JP_TO_US = {
    "SS":  "XXS",
    "S":   "XS",
    "M":   "S",
    "L":   "M",
    "XL":  "L",
    "XXL": "XL",
}

# 実測ラベル JP → EN (回答書 §承認した設計判断: 公式並び順を保つ)
# 着丈/身丈 は両方 "Length" にマップ (どちらも body length)
SIZE_LABEL_JP_TO_EN = {
    "着丈": "Length",
    "身丈": "Length",
    "身幅": "Chest",
    "肩幅": "Shoulder",
    "袖丈": "Sleeve",
    "裄丈": "Sleeve",     # 裄丈 = sleeve+shoulder combined、便宜的に Sleeve
    "総丈": "Total Length",
}

RETURN_POLICY = "customer1"
PAYMENT_POLICY = "SALE"
LOCATION = "Osaka"
BRAND_FREE_TEXT = "Graniph"

# CSV headers (workman variation format と同構造)
CSV_HEADERS = [
    "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)",
    "*Category", "*Title", "*Description", "*ConditionID", "*Format", "*Duration",
    "*Location", "*Country", "PicURL", "*StartPrice", "*Quantity",
    "CustomLabel", "Relationship", "RelationshipDetails",
    "BestOfferEnabled", "ShippingProfileName", "ReturnProfileName", "PaymentProfileName",
    "ScheduleTime", "StoreCategoryID",
    "C:Brand", "C:Type", "C:Size Type", "C:Size", "C:Color", "C:Department",
    "C:Style", "C:Material", "C:Fabric Type", "C:Pattern", "C:Features",
    "C:Fit", "C:Closure", "C:Sleeve Length", "C:Neckline",
    "C:Season", "C:Theme", "C:Product Line",
    "C:Vintage", "C:Personalize", "C:Handmade",
    "C:Country/Region of Manufacture", "C:Garment Care",
]


def cm_to_inch(cm: float, precision: int = 1) -> str:
    return f"{cm / 2.54:.{precision}f}"


def us_size_from_measurements(chest_inch: float, length_inch: float) -> str:
    """chest & length (inch) を Gildan 5000 チャート最近傍にマップ."""
    best = US_UNISEX_TSHIRT_CHART[0][0]
    best_dist = float("inf")
    for label, chart_len, chart_chest in US_UNISEX_TSHIRT_CHART:
        dist = (_CHEST_WEIGHT * abs(chest_inch - chart_chest)
                + _LENGTH_WEIGHT * abs(length_inch - chart_len))
        if dist < best_dist:
            best_dist = dist
            best = label
    return best


def _chest_length_inch(size_table, size_jp: str):
    """size_table から (chest_inch, length_inch) を取り出す。取れなければ (None, None)."""
    chest_cm = None
    length_cm = None
    for row in size_table or []:
        en = SIZE_LABEL_JP_TO_EN.get(row.label_jp)
        val = row.values_cm.get(size_jp)
        if val is None:
            continue
        if en == "Chest":
            chest_cm = val
        elif en == "Length":
            length_cm = val
    if chest_cm is None or length_cm is None:
        return None, None
    return chest_cm / 2.54, length_cm / 2.54


def pick_us_size(size_jp: str, size_table) -> str:
    """primary: 実測 (chest & length) から Gildan チャート最近傍。
    fallback: 実寸が取れない時のみ固定テーブル SIZE_JP_TO_US (one-down)。"""
    chest_in, length_in = _chest_length_inch(size_table, size_jp)
    if chest_in is not None and length_in is not None:
        return us_size_from_measurements(chest_in, length_in)
    return SIZE_JP_TO_US.get(size_jp, size_jp)


def _schedule_time(weeks: int = 2) -> str:
    return (datetime.utcnow() + timedelta(weeks=weeks)).strftime("%Y-%m-%d %H:%M:%S")


def gender_to_category(gender: str) -> int:
    g = (gender or "unisex").lower()
    if "female" in g or "women" in g:
        return CATEGORY_WOMEN
    return CATEGORY_MEN


def gender_to_department(gender: str) -> str:
    g = (gender or "unisex").lower()
    if "female" in g or "women" in g:
        return "Women"
    if "male" in g and "female" not in g and "unisex" not in g:
        return "Men"
    return "Unisex Adults"


def color_jp_to_en(color_jp: str) -> str:
    """JP color → eBay 一般値.

    fail-closed: 未知色は原文 (romaji 化しない). 空欄は避けて JP そのまま。
    Vision 補完を将来入れるならここを差替。
    """
    table = {
        "ベージュ": "Beige",
        "ブラック": "Black",
        "ホワイト": "White",
        "グレー": "Gray",
        "ネイビー": "Navy Blue",
        "レッド": "Red",
        "ブルー": "Blue",
        "グリーン": "Green",
        "ピンク": "Pink",
        "イエロー": "Yellow",
        "オレンジ": "Orange",
        "パープル": "Purple",
        "ブラウン": "Brown",
        "カーキ": "Khaki",
        "ナチュラル": "Natural",
        "チャコール": "Charcoal Gray",
    }
    return table.get(color_jp.strip(), color_jp)


def material_jp_to_en(material_jp: str) -> str:
    """"ポリエステル 65%  綿 35%" → "65% Polyester, 35% Cotton"."""
    if not material_jp:
        return ""
    import re
    parts = re.findall(r"([぀-ヿ一-鿿]+)\s*(\d+)\s*%", material_jp)
    if not parts:
        return material_jp
    fabric_map = {
        "綿": "Cotton", "コットン": "Cotton",
        "ポリエステル": "Polyester",
        "ポリウレタン": "Spandex",
        "レーヨン": "Rayon",
        "ナイロン": "Nylon",
        "ウール": "Wool",
        "アクリル": "Acrylic",
        "リネン": "Linen",
        "麻": "Linen",
        "キュプラ": "Cupro",
    }
    out = []
    for name_jp, pct in parts:
        en = fabric_map.get(name_jp.strip(), name_jp.strip())
        out.append(f"{pct}% {en}")
    return ", ".join(out)


def primary_material_en(material_jp: str) -> str:
    """Item Specifics C:Material 用 — 一番割合の大きい素材 (英語)."""
    if not material_jp:
        return "Cotton"
    import re
    parts = re.findall(r"([぀-ヿ一-鿿]+)\s*(\d+)\s*%", material_jp)
    if not parts:
        return "Cotton"
    fabric_map = {
        "綿": "Cotton", "コットン": "Cotton",
        "ポリエステル": "Polyester",
        "レーヨン": "Rayon", "ナイロン": "Nylon",
        "ウール": "Wool", "アクリル": "Acrylic",
        "リネン": "Linen", "麻": "Linen", "キュプラ": "Cupro",
    }
    parts.sort(key=lambda p: int(p[1]), reverse=True)
    return fabric_map.get(parts[0][0].strip(), parts[0][0].strip())


def derive_type_from_name(name_jp: str) -> str:
    n = name_jp
    if "スウェット" in n or "パーカー" in n or "パーカ" in n:
        # graniph の"ジップパーカー"は襟なしジップスウェット = Sweatshirt 扱い
        if "パーカー" in n or "パーカ" in n or "フーディ" in n:
            return "Hoodie"
        return "Sweatshirt"
    if "ニット" in n or "セーター" in n:
        return "Pullover Sweater"
    if "シャツ" in n or "Tシャツ" in n:
        return "T-Shirt"
    return "T-Shirt"


def derive_sleeve_length(name_jp: str) -> str:
    if "長袖" in name_jp:
        return "Long Sleeve"
    if "半袖" in name_jp:
        return "Short Sleeve"
    if "ノースリーブ" in name_jp:
        return "Sleeveless"
    if "スウェット" in name_jp or "パーカ" in name_jp or "ニット" in name_jp or "セーター" in name_jp:
        return "Long Sleeve"
    return "Short Sleeve"


def derive_closure(name_jp: str) -> str:
    if "ハーフジップ" in name_jp or "ジップ" in name_jp and "ハーフ" in name_jp:
        return "Zipper"
    if "フルジップ" in name_jp or "ジップアップ" in name_jp:
        return "Zipper"
    if "ジップ" in name_jp:
        return "Zipper"
    if "ボタン" in name_jp:
        return "Button"
    return "Pullover"


def derive_neckline(name_jp: str) -> str:
    if "Vネック" in name_jp:
        return "V-Neck"
    if "モックネック" in name_jp:
        return "Mock Neck"
    if "タートル" in name_jp:
        return "Turtleneck"
    if "ハーフジップ" in name_jp:
        return "Mock Neck"
    if "ジップアップ" in name_jp or "フルジップ" in name_jp:
        return "Full Zip"
    if "クルーネック" in name_jp or "クルー" in name_jp:
        return "Crew Neck"
    return "Crew Neck"


def derive_fit(name_jp: str) -> str:
    if "ビッグシルエット" in name_jp or "ビッグ" in name_jp or "オーバーサイズ" in name_jp:
        return "Relaxed"
    return "Regular"


def build_title(p: GraniphProduct) -> str:
    """タイトル生成 (80字以内、Graniph SEO + サイズ幅を親では明示せず variation で表現)."""
    fit = "Oversized " if derive_fit(p.name_jp) == "Relaxed" else ""
    type_str = derive_type_from_name(p.name_jp)
    sleeve = derive_sleeve_length(p.name_jp)
    color_en = color_jp_to_en(p.color_jp)
    # 例: "Graniph Oversized Half-Zip T-Shirt Beige Japan Exclusive NWT Unisex"
    if "ハーフジップ" in p.name_jp:
        style_word = "Half-Zip"
        parts = [BRAND_FREE_TEXT, fit + style_word, type_str, color_en,
                 "Japan Exclusive", "NWT", "Unisex"]
    else:
        parts = [BRAND_FREE_TEXT, fit.strip() if fit else "",
                 sleeve if sleeve != "Short Sleeve" else "",
                 type_str, color_en,
                 "Graphic Tee" if type_str == "T-Shirt" else "",
                 "Japan Exclusive", "NWT", "Unisex"]
    title = " ".join(w for w in parts if w).strip()
    # 80 字 hard cap
    if len(title) > 80:
        title = title[:77] + "..."
    return title


def build_size_table_html(size_table, sizes_available: list) -> str:
    """公式並び順 (label 順) をそのまま inch 表示."""
    if not size_table:
        return ""
    headers = ["Size"] + sizes_available
    lines = ["<table border='1' cellpadding='4' style='border-collapse:collapse;font-size:14px;'>"]
    lines.append("<tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr>")
    for row in size_table:
        label_en = SIZE_LABEL_JP_TO_EN.get(row.label_jp, row.label_jp)
        cells = [f"<td><b>{label_en} (inch)</b></td>"]
        for sz in sizes_available:
            cm = row.values_cm.get(sz)
            if cm is None:
                cells.append("<td>—</td>")
            else:
                cells.append(f"<td>{cm_to_inch(cm)}</td>")
        lines.append("<tr>" + "".join(cells) + "</tr>")
    lines.append("</table>")
    return "\n".join(lines)


ABOUT_GRANIPH = (
    "<p><span style='text-decoration: underline;'><strong>About Graniph</strong></span></p>"
    "<p>Graniph is a Japanese graphic T-shirt brand founded in Osaka in 2001, "
    "known for artist and character collaborations. Not officially sold outside "
    "Japan &mdash; this is a Japan-exclusive item.</p>"
)


def build_description_html(
    p: GraniphProduct,
    sizes_available: list,
    template_path: str = None,
) -> str:
    """template (NEW.txt) に Product Specs + About Graniph + Size table を差し込む."""
    if template_path is None:
        template_path = os.path.join(os.path.dirname(__file__), "NEW.txt")
    with open(template_path, encoding="utf-8") as f:
        template = f.read()

    color_en = color_jp_to_en(p.color_jp)
    material_en = material_jp_to_en(p.material_jp)
    fit_en = derive_fit(p.name_jp)
    type_en = derive_type_from_name(p.name_jp)

    specs_html = (
        "<p><span style='text-decoration: underline;'><strong>"
        "Product Specifications</strong></span></p>"
        "<ul>"
        f"<li><b>Brand:</b> Graniph</li>"
        f"<li><b>Type:</b> {type_en}</li>"
        f"<li><b>Material:</b> {material_en}</li>"
        f"<li><b>Color:</b> {color_en}</li>"
        f"<li><b>Fit:</b> {fit_en}</li>"
        f"<li><b>Condition:</b> Brand new with tags</li>"
        "</ul>"
    )
    size_html = (
        "<p><span style='text-decoration: underline;'><strong>"
        "Size Chart (finished garment, official)</strong></span></p>"
        + build_size_table_html(p.size_table, sizes_available)
        + "<p style='font-size:12px;'>Measurements are approximate. "
        "Convert to your usual size using the chart above.</p>"
    )

    block = specs_html + "\n" + size_html + "\n" + ABOUT_GRANIPH

    marker = '<p><span style="text-decoration: underline;"><strong>Shipping'
    if marker in template:
        return template.replace(marker, block + "\n" + marker)
    return template + "\n" + block


def build_pic_url(p: GraniphProduct) -> str:
    return "|".join(p.image_urls[:12])


def compute_listing_price_usd(price_jpy: int) -> tuple:
    """V6 pricing_engine で listing 価格を決める.

    graniph は「T-shirt / apparel」 = group C. gsheet cache に "graniph" は
    無いので "Tシャツ(UT)" (identical fvf/shipping/hts) を pass. yaml で
    category_to_group に "graniph": C を入れているのは、将来 gsheet 側に
    "graniph" を足したら第一級のカテゴリとして参照できるようにするため.

    ★ 仕入送料 (¥440 / 商品代 ¥5,000+ で無料) を必ず cost に足してから pricing_engine
      に渡す。関数外で足すのを忘れる事故を防ぐため、ここで一括加算する。
    """
    from pricing_engine import compute_listing_price
    total_cost_jpy = price_jpy + procurement_shipping(price_jpy)
    return compute_listing_price(total_cost_jpy, 0, "Tシャツ(UT)")


def pick_shipping_profile(price_usd: float) -> str:
    from listing_common import get_shipping_policy_name
    return get_shipping_policy_name(price_usd, "graniph")


def build_parent_row(
    p: GraniphProduct,
    sizes_available: list,
    listing_price_usd: float,
    shipping_profile: str,
    parent_sku: str,
) -> list:
    title = build_title(p)
    desc = build_description_html(p, sizes_available)
    category = gender_to_category(p.suggested_gender)
    department = gender_to_department(p.suggested_gender)
    type_str = derive_type_from_name(p.name_jp)
    material = primary_material_en(p.material_jp)
    sleeve = derive_sleeve_length(p.name_jp)
    fit = derive_fit(p.name_jp)
    closure = derive_closure(p.name_jp)
    neckline = derive_neckline(p.name_jp)
    size_pipe = ";".join(
        f"{pick_us_size(s, p.size_table)} (JP {s})" for s in sizes_available
    )
    color_en = color_jp_to_en(p.color_jp)
    rel_details = f"Size={size_pipe}"
    return [
        "Add", category, title, desc, 1000, "FixedPrice", "GTC",
        LOCATION, "JP",
        build_pic_url(p),
        "", "",  # StartPrice / Quantity blank on parent
        parent_sku,
        "", rel_details,
        1, shipping_profile, RETURN_POLICY, PAYMENT_POLICY,
        _schedule_time(), "",  # StoreCategoryID (POC は空)
        BRAND_FREE_TEXT,                    # C:Brand
        type_str,                            # C:Type
        "Regular",                           # C:Size Type
        "",                                  # C:Size (variation 側)
        color_en,                            # C:Color
        department,                          # C:Department
        "Graphic Tee",                       # C:Style
        material,                            # C:Material
        material,                            # C:Fabric Type
        "Graphic Print",                     # C:Pattern
        "Breathable, Lightweight",           # C:Features
        fit,                                 # C:Fit
        closure,                             # C:Closure
        sleeve,                              # C:Sleeve Length
        neckline,                            # C:Neckline
        "Spring, Summer, Fall",              # C:Season
        "Anime",                             # C:Theme (graniph はサブカル/アニメ寄り)
        "",                                  # C:Product Line (回答書 §Brand: 空欄で構いません)
        "No",                                # C:Vintage
        "No",                                # C:Personalize
        "No",                                # C:Handmade
        "Japan",                             # C:Country/Region of Manufacture (graniph は国内縫製多)
        "Machine Washable",                  # C:Garment Care
    ]


def build_variation_rows(
    p: GraniphProduct,
    sizes_available: list,
    listing_price_usd: float,
    parent_sku: str,
) -> list:
    rows = []
    for jp_sz in sizes_available:
        us_sz = pick_us_size(jp_sz, p.size_table)
        size_display = f"{us_sz} (JP {jp_sz})"
        variant_sku = str(uuid.uuid4())  # 回答書指示: 14桁 sku_code ではなく UUID
        rows.append([
            "Add", "", "", "", "", "", "", "", "",
            "",  # PicURL (variation ごとの色画像は無い = 親と同色)
            f"{listing_price_usd:.2f}",
            "1",
            variant_sku,
            "Variation",
            f"Size={size_display}",
            "", "", "", "",
            "", "",
            "", "", "",           # Brand / Type / Size Type
            size_display,          # C:Size = "XXS (JP SS)" etc.
            "",                    # Color (variation 内では 1 色固定)
            # Department..Garment Care = 18 空欄
            "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "",
        ])
    return rows


def build_csv(url: str, out_path: str = None) -> str:
    p = scrape(url)
    if not p.sizes:
        raise ValueError(f"No sizes in stock: {url}")
    sizes = list(p.sizes)  # in-stock only
    listing_price = compute_listing_price_usd(p.price_sale_jpy or p.price_regular_jpy)
    price_usd = listing_price["price"]
    ship_profile = pick_shipping_profile(price_usd)
    parent_sku = str(uuid.uuid4())
    parent = build_parent_row(p, sizes, price_usd, ship_profile, parent_sku)
    children = build_variation_rows(p, sizes, price_usd, parent_sku)

    if out_path is None:
        try:
            from listing_core import get_csv_output_path
            out_path = get_csv_output_path("graniph", "upload")
        except Exception:
            out_path = os.path.join(
                os.path.dirname(__file__),
                f"ebay_graniph_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            )
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        w.writerow(CSV_HEADERS)
        w.writerow(parent)
        for row in children:
            w.writerow(row)
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="graniph URL または 12桁 item_code")
    ap.add_argument("--out", help="CSV 出力先 (省略時は iMakHQ/csv_output/)")
    args = ap.parse_args()

    tgt = args.target
    if tgt.isdigit() and len(tgt) == 12:
        tgt = f"https://www.graniph.com/item-detail/{tgt}"

    out = build_csv(tgt, args.out)
    print(f"CSV written: {out}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
