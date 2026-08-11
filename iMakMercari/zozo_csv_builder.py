"""zozo 出品 CSV builder (minius 1ブランド限定 POC).

依頼書: C:/dev/iMak_data/harvest/requests/2026-08-10_zozo_preorder_detection_confirmed_response.md

## 決定事項 (窓口 [IMPLEMENT-GO]):
- 置き場: iMakMercari/zozo_scraper.py + zozo_csv_builder.py (graniph parity)
- ブランド: **minius 1ブランドだけ** (他ブランドは都度 feasibility)
- 予約: **variation 単位で除外**、商品単位で reject しない
- 予約混在フラグ: **CSV に列を足さない**。別レポート (`.preorder_report.md`) に出す

## 完成条件:
「minius の URL を1本渡すと、予約 variation を落とした入稿 CSV が出る」

## 構造:
- ZOZO は 1 URL に **多色 × 多サイズ** が載る (graniph は 1 URL = 1 色と異なる)
- 出力: **色ごとに1リスティング** (parent + Size variation 子行)
- 全リスティングを同一 CSV に append

Usage:
    python zozo_csv_builder.py <URL>
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import uuid
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
API_DIR = os.path.join(SCRIPT_DIR, "..", "iMakeBayAPI")
for _p in (SCRIPT_DIR, API_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zozo_scraper import ZozoProduct, ZozoSku, fetch_product  # noqa: E402


# ============================================================================
# 定数
# ============================================================================
# minius 限定 (回答書 §決定「実装は minius 1ブランドだけ」)
ALLOWED_SHOPS = {"minius"}

CATEGORY_MEN = 15687        # Men's Clothing > T-Shirts
CATEGORY_WOMEN = 53159      # Women's Clothing > Tops

# minius 実測 (2026-08-10 窓口 fetch): 全 8 SKU が InStock、価格 ¥4,950 均一
# → cost-plus 経由で必要 (compute_listing_price に渡す)
# 仕入送料: ZOZO は購入金額 ¥3,300 以上で送料無料 (公式 shipping guide、2026-08-10 参照時点)
# 未満の場合 ¥330 → cost に足す
ZOZO_PROCUREMENT_SHIPPING_JPY = 330
ZOZO_FREE_SHIPPING_THRESHOLD_JPY = 3300

# 出品カテゴリ判定用の pricing_engine キー (共通 SSOT "Tシャツ(UT)" と同 fvf/shipping)
PRICING_CATEGORY = "Tシャツ(UT)"

# Brand: minius は eBay Brand フィルタ (aspectValues) に無い → free text
BRAND_FREE_TEXT = "minius"

# eBay プロファイル (プロジェクト規約)
RETURN_POLICY = "customer1"
PAYMENT_POLICY = "SALE"
LOCATION = "Osaka"

# 画像上限 (eBay 制限)
MAX_PIC_URLS = 12


def procurement_shipping(item_total_jpy: int) -> int:
    """ZOZO 仕入送料。¥3,300 以上で無料、未満は ¥330。

    ★ 「item_total」は1点の商品代金 (単品購入前提)。まとめ買いは想定しない
      (無在庫は SKU 単位で購入・発送するため常に単品換算)。
    """
    return 0 if item_total_jpy >= ZOZO_FREE_SHIPPING_THRESHOLD_JPY else ZOZO_PROCUREMENT_SHIPPING_JPY


# ----------------------------------------------------------------------------
# JP → US サイズ変換 (T-shirt 用、ZOZO ラベルは MEDIUM / LARGE / X-LARGE / XX-LARGE)
# ----------------------------------------------------------------------------
SIZE_JP_TO_US = {
    # フルネーム系 (ZOZO 標準)
    "SMALL":     "XS",
    "MEDIUM":    "S",
    "LARGE":     "M",
    "X-LARGE":   "L",
    "XLARGE":    "L",
    "XX-LARGE":  "XL",
    "XXLARGE":   "XL",
    "XXX-LARGE": "2XL",
    # 短縮系
    "XS":  "XXS",
    "S":   "XS",
    "M":   "S",
    "L":   "M",
    "XL":  "L",
    "XXL": "XL",
    "3XL": "2XL",
}


def jp_size_to_us(size_jp: str) -> str:
    """ZOZO サイズラベルを US 換算。未知なら原文 (fail-closed)."""
    if not size_jp:
        return ""
    key = size_jp.strip().upper()
    return SIZE_JP_TO_US.get(key, size_jp.strip())


# ----------------------------------------------------------------------------
# 色 (JP → EN 一般値マップ)
# ----------------------------------------------------------------------------
COLOR_JP_TO_EN = {
    "ブラック":   "Black",
    "ホワイト":   "White",
    "グレー":     "Gray",
    "ネイビー":   "Navy Blue",
    "レッド":     "Red",
    "ブルー":     "Blue",
    "グリーン":   "Green",
    "ピンク":     "Pink",
    "イエロー":   "Yellow",
    "オレンジ":   "Orange",
    "パープル":   "Purple",
    "ブラウン":   "Brown",
    "カーキ":     "Khaki",
    "ベージュ":   "Beige",
    "チャコール": "Charcoal Gray",
    "ナチュラル": "Natural",
}


def color_jp_to_en(color_jp: str) -> str:
    if not color_jp:
        return ""
    return COLOR_JP_TO_EN.get(color_jp.strip(), color_jp.strip())


# ----------------------------------------------------------------------------
# 素材 (JP → EN)
# ----------------------------------------------------------------------------
_MATERIAL_MAP = {
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


def material_jp_to_en(material_jp: str) -> str:
    """例: "ポリエステル 65%  綿 35%" → "65% Polyester, 35% Cotton"."""
    if not material_jp:
        return ""
    parts = re.findall(r"([぀-ヿ一-鿿]+)\s*(\d+)\s*%", material_jp)
    if not parts:
        return material_jp
    out = []
    for name_jp, pct in parts:
        en = _MATERIAL_MAP.get(name_jp.strip(), name_jp.strip())
        out.append(f"{pct}% {en}")
    return ", ".join(out)


def primary_material_en(material_jp: str) -> str:
    """一番割合の大きい素材 (英語)。取れなければ 'Cotton' fallback."""
    if not material_jp:
        return "Cotton"
    parts = re.findall(r"([぀-ヿ一-鿿]+)\s*(\d+)\s*%", material_jp)
    if not parts:
        return "Cotton"
    parts.sort(key=lambda p: int(p[1]), reverse=True)
    return _MATERIAL_MAP.get(parts[0][0].strip(), parts[0][0].strip())


# ----------------------------------------------------------------------------
# タイトル / Item Specifics 推定 (name_jp からのキーワード検出)
# ----------------------------------------------------------------------------
def derive_type_from_name(name_jp: str) -> str:
    n = name_jp or ""
    if "パーカー" in n or "パーカ" in n or "フーディ" in n:
        return "Hoodie"
    if "スウェット" in n:
        return "Sweatshirt"
    if "ニット" in n or "セーター" in n:
        return "Pullover Sweater"
    return "T-Shirt"


def derive_sleeve_length(name_jp: str) -> str:
    n = name_jp or ""
    if "長袖" in n:
        return "Long Sleeve"
    if "半袖" in n:
        return "Short Sleeve"
    if "ノースリーブ" in n:
        return "Sleeveless"
    if "スウェット" in n or "パーカ" in n or "ニット" in n or "セーター" in n:
        return "Long Sleeve"
    return "Short Sleeve"


def derive_fit(name_jp: str) -> str:
    n = name_jp or ""
    if "ビッグシルエット" in n or "オーバーサイズ" in n or "ビッグ" in n:
        return "Relaxed"
    return "Regular"


def derive_neckline(name_jp: str) -> str:
    n = name_jp or ""
    if "Vネック" in n:
        return "V-Neck"
    if "モックネック" in n:
        return "Mock Neck"
    if "タートル" in n:
        return "Turtleneck"
    if "クルーネック" in n or "クルー" in n:
        return "Crew Neck"
    return "Crew Neck"


def derive_closure(name_jp: str) -> str:
    n = name_jp or ""
    if "ジップ" in n:
        return "Zipper"
    if "ボタン" in n:
        return "Button"
    return "Pullover"


# ----------------------------------------------------------------------------
# タイトル生成 (80 字 hard cap)
# ----------------------------------------------------------------------------
def build_title(brand_name: str, name_jp: str, color_en: str) -> str:
    fit = "Oversized " if derive_fit(name_jp) == "Relaxed" else ""
    type_str = derive_type_from_name(name_jp)
    sleeve = derive_sleeve_length(name_jp)
    parts = [
        brand_name,
        fit.strip() if fit else "",
        sleeve if sleeve != "Short Sleeve" else "",
        type_str,
        color_en,
        "Graphic Tee" if type_str == "T-Shirt" else "",
        "Japan Exclusive",
        "NWT",
        "Unisex",
    ]
    title = " ".join(w for w in parts if w).strip()
    if len(title) > 80:
        title = title[:77] + "..."
    return title


# ============================================================================
# CSV 定義
# ============================================================================
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


def _schedule_time(weeks: int = 2) -> str:
    """UTC で weeks 週先 (CLAUDE.md 共通固定値)."""
    return (datetime.utcnow() + timedelta(weeks=weeks)).strftime("%Y-%m-%d %H:%M:%S")


# ----------------------------------------------------------------------------
# 送料プロファイル (DDP tier)
# ----------------------------------------------------------------------------
def pick_shipping_profile(price_usd: float) -> str:
    """price → DDP-* tier 名。global.yaml の ddp_shipping_tiers を参照。"""
    try:
        from config_loader import get_ddp_shipping_tiers
        tiers = get_ddp_shipping_tiers()
    except Exception:
        tiers = []
    if not tiers:
        # fallback (CLAUDE.md グローバル固定値)
        tiers = [
            {"max_usd": 39, "profile": "DDP-39"},
            {"max_usd": 60, "profile": "DDP-40-60"},
            {"max_usd": 100, "profile": "DDP-60-100"},
            {"max_usd": 200, "profile": "DDP-100-200"},
            {"max_usd": 300, "profile": "DDP-200-300"},
            {"max_usd": 400, "profile": "DDP-300-400"},
            {"max_usd": 500, "profile": "DDP-400-500"},
            {"max_usd": 600, "profile": "DDP-500-600"},
            {"max_usd": 800, "profile": "DDP-600-800"},
            {"max_usd": 1000, "profile": "DDP-800-1000"},
        ]
    for t in tiers:
        if price_usd <= t["max_usd"]:
            return t["profile"]
    return tiers[-1]["profile"]


def compute_listing_price_usd(price_jpy: int) -> dict:
    """cost = 商品代 + 仕入送料 を pricing_engine に渡して出品価格を決める.

    ★ 仕入送料をここで一括加算 (呼出側で足し忘れる事故防止)。
    """
    from pricing_engine import compute_listing_price
    total_cost = price_jpy + procurement_shipping(price_jpy)
    return compute_listing_price(total_cost, 0, PRICING_CATEGORY)


# ----------------------------------------------------------------------------
# 説明文 (NEW.txt テンプレに Product Specs + Size table を差し込む)
# ----------------------------------------------------------------------------
_SIZE_LABEL_JP_TO_EN = {
    "着丈": "Length",
    "身丈": "Length",
    "身幅": "Chest",
    "肩幅": "Shoulder",
    "袖丈": "Sleeve",
    "総丈": "Total Length",
}


def build_description_html(
    brand_name: str,
    p: ZozoProduct,
    color_jp: str,
    sizes_available_jp: list,
    template_path: str = None,
) -> str:
    """NEW.txt テンプレの Shipping マーカー直前に Product Specs / About ブロック挿入."""
    if template_path is None:
        template_path = os.path.join(SCRIPT_DIR, "NEW.txt")
    with open(template_path, encoding="utf-8") as f:
        template = f.read()

    color_en = color_jp_to_en(color_jp)
    material_en = material_jp_to_en(p.material_jp)
    fit_en = derive_fit(p.name_jp)
    type_en = derive_type_from_name(p.name_jp)

    specs_html = (
        "<p><span style='text-decoration: underline;'><strong>"
        "Product Specifications</strong></span></p>"
        "<ul>"
        f"<li><b>Brand:</b> {brand_name}</li>"
        f"<li><b>Type:</b> {type_en}</li>"
        f"<li><b>Material:</b> {material_en or 'See product photos'}</li>"
        f"<li><b>Color:</b> {color_en}</li>"
        f"<li><b>Fit:</b> {fit_en}</li>"
        f"<li><b>Available sizes:</b> {', '.join(jp_size_to_us(s) for s in sizes_available_jp)}</li>"
        "<li><b>Condition:</b> Brand new with tags</li>"
        "</ul>"
    )
    about_html = (
        "<p><span style='text-decoration: underline;'><strong>"
        f"About {brand_name}</strong></span></p>"
        f"<p>{brand_name} is a Japanese apparel brand available on ZOZOTOWN. "
        "Not officially sold outside Japan &mdash; this is a Japan-exclusive item.</p>"
    )
    block = specs_html + "\n" + about_html

    marker = '<p><span style="text-decoration: underline;"><strong>Shipping'
    if marker in template:
        return template.replace(marker, block + "\n" + marker)
    return template + "\n" + block


def _build_pic_url(image_urls: list) -> str:
    return "|".join((image_urls or [])[:MAX_PIC_URLS])


# ============================================================================
# 色ごとの listing 生成
# ============================================================================
def group_skus_by_color(skus) -> dict:
    """SKU を色ごとに集約 (excluded=True は落とす). Returns: {color_jp: [ZozoSku, ...]}."""
    out = {}
    for s in skus:
        if s.excluded:
            continue
        if not s.in_stock:
            continue
        color_key = s.color or "(no color)"
        out.setdefault(color_key, []).append(s)
    return out


def build_parent_row(
    p: ZozoProduct,
    color_jp: str,
    sku_group: list,
    listing_price_usd: float,
    shipping_profile: str,
    parent_sku: str,
) -> list:
    brand_name = BRAND_FREE_TEXT if p.shop.lower() == "minius" else p.brand_jp or p.shop
    sizes_jp = [s.size for s in sku_group]
    color_en = color_jp_to_en(color_jp)
    title = build_title(brand_name, p.name_jp, color_en)
    desc = build_description_html(brand_name, p, color_jp, sizes_jp)

    type_str = derive_type_from_name(p.name_jp)
    material = primary_material_en(p.material_jp)
    sleeve = derive_sleeve_length(p.name_jp)
    fit = derive_fit(p.name_jp)
    closure = derive_closure(p.name_jp)
    neckline = derive_neckline(p.name_jp)

    size_pipe = ";".join(
        f"{jp_size_to_us(s.size)} (JP {s.size})" for s in sku_group
    )
    rel_details = f"Size={size_pipe}"

    return [
        "Add", CATEGORY_MEN, title, desc, 1000, "FixedPrice", "GTC",
        LOCATION, "JP",
        _build_pic_url(p.image_urls),
        "", "",  # StartPrice / Quantity は親空欄
        parent_sku,
        "", rel_details,
        1, shipping_profile, RETURN_POLICY, PAYMENT_POLICY,
        _schedule_time(), "",
        brand_name,                             # C:Brand
        type_str,                                # C:Type
        "Regular",                               # C:Size Type
        "",                                      # C:Size (variation 側)
        color_en,                                # C:Color
        "Unisex Adults",                         # C:Department
        "Graphic Tee",                           # C:Style
        material,                                # C:Material
        material,                                # C:Fabric Type
        "Graphic Print",                         # C:Pattern
        "Breathable, Lightweight",               # C:Features
        fit,                                     # C:Fit
        closure,                                 # C:Closure
        sleeve,                                  # C:Sleeve Length
        neckline,                                # C:Neckline
        "Spring, Summer, Fall",                  # C:Season
        "Anime",                                 # C:Theme
        "",                                      # C:Product Line
        "No",                                    # C:Vintage
        "No",                                    # C:Personalize
        "No",                                    # C:Handmade
        "Japan",                                 # C:Country/Region of Manufacture
        "Machine Washable",                      # C:Garment Care
    ]


def build_variation_rows(sku_group: list, listing_price_usd: float, parent_sku: str) -> list:
    rows = []
    for s in sku_group:
        us_sz = jp_size_to_us(s.size)
        size_display = f"{us_sz} (JP {s.size})"
        variant_sku = str(uuid.uuid4())
        rows.append([
            "Add", "", "", "", "", "", "", "", "",
            "",  # PicURL (色ごとに 1 リスティングにまとめるため variation ごとの色画像は無い)
            f"{listing_price_usd:.2f}",
            "1",
            variant_sku,
            "Variation",
            f"Size={size_display}",
            "", "", "", "",
            "", "",
            "", "", "",
            size_display,
            "",
            "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "",
        ])
    return rows


# ============================================================================
# 予約 variation レポート (窓口指示: CSV に列を足さない・別レポートで出す)
# ============================================================================
def build_preorder_report(p: ZozoProduct) -> str:
    """PreOrder / excluded な SKU の目視レビュー用 markdown を返す (空なら空文字)."""
    excluded_skus = [s for s in p.skus if s.excluded]
    if not excluded_skus and not p.has_preorder_flag:
        return ""

    lines = [
        f"# 予約 variation レポート — {p.goods_id} ({p.shop})",
        "",
        f"- URL: {p.url}",
        f"- 商品名: {p.name_jp}",
        f"- 取得時刻: {p.fetched_at}",
        f"- has_preorder_flag (HTML sellType): {p.has_preorder_flag}",
        f"- 全 SKU 数: {len(p.skus)}",
        f"- 除外 SKU 数: {len(excluded_skus)}",
        "",
        "## 除外 variation (CSV から落としたもの)",
        "",
        "| 色 | サイズ | availability | 理由 | sku_code |",
        "|---|---|---|---|---|",
    ]
    for s in excluded_skus:
        lines.append(
            f"| {s.color or '?'} | {s.size or '?'} | {s.availability} | {s.stock_label} | {s.sku_code} |"
        )
    lines.append("")
    lines.append("## 対応")
    lines.append(
        "- 予約分は無在庫と噛み合わないため CSV に含めていない。"
        "本商品の入稿判断は目視で行うこと (在庫あり分だけで listing 数が妥当かをチェック)。"
    )
    return "\n".join(lines)


# ============================================================================
# CSV 生成本体
# ============================================================================
def build_csv(url: str, out_path: str = None, report_path: str = None) -> dict:
    """URL → CSV。色ごとに1リスティング。予約 variation は除外し別レポートに出す.

    Returns: {"csv_path": ..., "report_path": str_or_None, "listings": int, "excluded": int}
    """
    p = fetch_product(url)

    if p.shop.lower() not in ALLOWED_SHOPS:
        raise ValueError(
            f"未許可の shop: {p.shop!r}。minius 以外は都度 feasibility "
            f"(回答書 §2本目のブランド)"
        )

    groups = group_skus_by_color(p.skus)
    if not groups:
        raise ValueError(
            f"在庫 SKU がありません (全 SKU 除外)。URL={url} "
            f"excluded={sum(1 for s in p.skus if s.excluded)}/{len(p.skus)}"
        )

    listing_price = compute_listing_price_usd(
        # 全 SKU 同価格前提だが、混在なら最初の1件を代表として採用
        next(iter(groups.values()))[0].price_jpy or 0
    )
    price_usd = listing_price["price"]
    ship_profile = pick_shipping_profile(price_usd)

    if out_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join(SCRIPT_DIR, f"ebay_zozo_{p.shop}_{p.goods_id}_{ts}.csv")

    all_rows = []
    for color_jp in sorted(groups):
        sku_group = groups[color_jp]
        parent_sku = str(uuid.uuid4())
        parent = build_parent_row(
            p, color_jp, sku_group, price_usd, ship_profile, parent_sku,
        )
        children = build_variation_rows(sku_group, price_usd, parent_sku)
        all_rows.append(parent)
        all_rows.extend(children)

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        w.writerow(CSV_HEADERS)
        for row in all_rows:
            w.writerow(row)

    # 予約混在レポート (窓口指示: CSV に列を足さない・別レポート)
    report_written = None
    report_md = build_preorder_report(p)
    if report_md:
        if report_path is None:
            report_path = out_path + ".preorder_report.md"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_md)
        report_written = report_path

    return {
        "csv_path": out_path,
        "report_path": report_written,
        "listings": len(groups),
        "excluded": sum(1 for s in p.skus if s.excluded),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", help="ZOZO goods URL (例 https://zozo.jp/shop/minius/goods/103638934/)")
    ap.add_argument("--out", help="CSV 出力先")
    ap.add_argument("--report", help="予約レポート出力先")
    args = ap.parse_args()

    result = build_csv(args.url, out_path=args.out, report_path=args.report)
    print(f"CSV written: {result['csv_path']}  listings={result['listings']}")
    if result["report_path"]:
        print(f"予約レポート: {result['report_path']}  除外={result['excluded']}件")
    elif result["excluded"]:
        print(f"除外={result['excluded']}件 (レポートは build_preorder_report が空文字 → 無出力)")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
