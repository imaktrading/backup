"""workman_listing - ワークマン公式商品 → eBay FileExchange CSV 生成.

5/16 ユーザー判断「HQ完結で完走」反映。
ワークマン公式 (workman.jp/shop/g/g<13桁>/) を仕入元として、JSON-LD 経由で商品データ
取得 → eBay listing 生成。

特徴:
  - 既存 tshirt_listing.py より単純 (Claude API / Vision 不要、JSON-LD で完結)
  - 価格: 仕入 JPY × pricing_engine (G-shock pattern 流用)
  - title: 商品名 + Workman + Color + Size + Japan / New
  - Item Specifics: Outdoor/Workwear 系 (Material / Water Resistance / 等)

使い方:
  python workman_listing.py
  → スプシ R='Workman' 行を全件処理 → csv_output/workman_upload_<ts>.csv
"""
from __future__ import annotations

import csv
import os
import re
import sys
from datetime import datetime, timedelta, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import gspread
from google.oauth2.service_account import Credentials

_HERE = os.path.dirname(os.path.abspath(__file__))
_EBAY_API = os.path.normpath(os.path.join(_HERE, "..", "iMakeBayAPI"))
for p in (_HERE, _EBAY_API):
    if p not in sys.path:
        sys.path.insert(0, p)

from workman_scraper import fetch_workman_product, is_workman_url

# スプシ設定 (= Low シート、R='Workman' 行が対象)
SHEET_ID = "1jF9vggbfUCddjneROMO2GGN-jTAPRbq6Qe2cbgr37B0"
GID = 851100680
CREDS_PATH = r"c:\dev\iMak\double-hold-421922-7c0d38d3f73d.json"

# 列 (0-indexed)
COL_URL = 0       # A
COL_ITEM_ID = 1   # B (= 空欄なら未出品)
COL_TITLE_JP = 2  # C
COL_SOLD = 3      # D
COL_COND = 4      # E
COL_PRICE_F = 5   # F (商品価格 仕入¥)
COL_PHOTO = 6     # G
COL_R_CAT = 17    # R (= 'Workman' のみ対象)

# eBay 出品設定
EBAY_CAT = "57988"  # Activewear T-shirts / Outdoor (= UNIQLO UT と近い、要調整可能)
SHIPPING_PROFILE = "DDP_to_$50"  # 仕入安価ゾーン用
RETURN_PROFILE = "customer1"
PAYMENT_PROFILE = "SALE"
LOCATION = "Japan"
QTY_PER_LISTING = 1
DURATION = "GTC"
FORMAT = "FixedPrice"

# 出力先
OUTPUT_DIR = os.path.normpath(os.path.join(_HERE, "..", "iMakHQ", "csv_output"))

# Title 80 文字制約
MAX_TITLE = 80


def load_targets() -> list[dict]:
    """スプシから R='Workman' AND B 空欄 AND D 空欄 の行を取得."""
    creds = Credentials.from_service_account_file(
        CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.get_worksheet_by_id(GID)
    rows = ws.get_all_values()
    targets = []
    for i, r in enumerate(rows[1:], start=2):
        if len(r) <= COL_R_CAT:
            continue
        cat = (r[COL_R_CAT] or "").strip()
        url = (r[COL_URL] or "").strip()
        iid = (r[COL_ITEM_ID] or "").strip() if len(r) > COL_ITEM_ID else ""
        sold = (r[COL_SOLD] or "").strip() if len(r) > COL_SOLD else ""
        if cat != "Workman" or not url or iid or sold:
            continue
        if not is_workman_url(url):
            continue
        price_jpy = 0
        try:
            p = (r[COL_PRICE_F] or "").strip().replace("¥", "").replace(",", "").replace("円", "")
            price_jpy = int(p) if p.isdigit() else 0
        except Exception:
            pass
        targets.append({
            "row_idx": i, "url": url,
            "title_jp": r[COL_TITLE_JP] if len(r) > COL_TITLE_JP else "",
            "condition_jp": r[COL_COND] if len(r) > COL_COND else "",
            "price_jpy_sheet": price_jpy,
            "photo_url": r[COL_PHOTO] if len(r) > COL_PHOTO else "",
        })
    return targets


def compute_listing_price_usd(cost_jpy: int) -> float:
    """仕入 JPY → 出品 USD (= G-shock pattern と同 pricing_engine)."""
    try:
        from pricing_engine import compute_listing_price
        return compute_listing_price(cost_jpy, "Workman").get("price_usd", 0.0)
    except Exception:
        # fallback: shipping + fees + margin
        usd = (cost_jpy / 140.0 + 15) / 0.72  # 簡易、$15送料 + 28% 諸費
        return round(usd + 0.98, 2)


def build_title(name_jp: str, color: str, sizes: list[str], release_date: str) -> str:
    """eBay 80 文字以内 タイトル. Workman + 商品名(英訳) + Color + Size + Japan New.

    名前は日本語のまま英字 + romanji を併記、最後の調整で 80字に収める.
    """
    base = name_jp[:30]  # 日本語商品名 (= バイヤーは画像で判断、SEO は brand 中心)
    parts = ["Workman"]
    if base:
        parts.append(base)
    if color:
        parts.append(color)
    # size 表記は variation 化前提では 1 listing に 1 size、ここでは省略
    parts += ["Japan", "New"]
    title = " ".join(parts)
    if len(title) > MAX_TITLE:
        # 商品名を短縮
        excess = len(title) - MAX_TITLE
        base = base[:max(5, len(base) - excess - 3)] + "..."
        title = " ".join(["Workman", base, color, "Japan New"])
    return title[:MAX_TITLE]


def get_schedule_time() -> str:
    """eBay ScheduleTime: 2 週間後 UTC."""
    dt = datetime.now(timezone.utc) + timedelta(days=14)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def build_row(target: dict, prod: dict) -> list:
    """Add CSV 1 行を生成."""
    cost_jpy = target["price_jpy_sheet"] or prod["price_jpy"]
    price_usd = compute_listing_price_usd(cost_jpy)
    sku = prod["mpn"][-12:] if prod["mpn"] else target["url"].split("/")[-2][:12]
    title = build_title(prod["name"], prod.get("color", ""), prod.get("sizes", []),
                          prod.get("release_date", ""))
    # Condition: 新品 (default)
    cond_id = "1000"  # New with tags

    # Description = template
    desc = (f"<div style='font-family:Arial'>"
            f"<h2>{prod['name']}</h2>"
            f"<p><b>Brand:</b> Workman (Japan-exclusive)</p>"
            f"<p><b>Color:</b> {prod.get('color', '')}</p>"
            f"<p><b>MPN:</b> {prod.get('mpn', '')}</p>"
            f"<p><b>Release Date:</b> {prod.get('release_date', '')}</p>"
            f"<p>Imported directly from Japan. Brand new with tags.</p>"
            f"</div>")
    # PicURL
    pic = prod.get("image_url_hi") or prod.get("image_url") or ""

    return [
        "Add", EBAY_CAT, title, pic, f"{price_usd:.2f}", cond_id,
        get_schedule_time(), sku,
        desc, FORMAT, DURATION, QTY_PER_LISTING, LOCATION,
        "true", SHIPPING_PROFILE, RETURN_PROFILE, PAYMENT_PROFILE,
        "Brand new with original tags. Imported from Japan.", "",
        # Item Specifics
        "Workman",                          # C:Brand
        "T-Shirt",                          # C:Type (要調整、商品により異なる)
        "Regular",                          # C:Size Type
        prod.get("sizes", ["M"])[0] if prod.get("sizes") else "M",  # C:Size
        prod.get("color", ""),              # C:Color
        "Unisex Adults",                    # C:Department
        "Outdoor",                          # C:Style
        "Solid",                            # C:Theme
        "", "", "",                         # Character / Family / Pattern
        "", "Short Sleeve",                 # Neckline / Sleeve Length
        "Polyester",                        # C:Material (要 catalog で精緻化)
        "Polyester",                        # C:Fabric Type
        "Quick Dry, Stretch",               # C:Features
        "Regular",                          # C:Fit
        prod.get("name", ""),               # C:Product Line
        prod.get("mpn", ""),                # C:Model
        "", "2026", "No",                   # Accents / Year / Personalize
        "No", "Japan",                      # Handmade / Country
        "Machine Wash", "All Season", "Pull On",  # Garment Care / Season / Closure
    ]


def main():
    print("=== Workman リスティング ===\n")
    print("📊 スプシ Low から R='Workman' 行取込中...")
    targets = load_targets()
    print(f"  対象: {len(targets)} 件\n")
    if not targets:
        print("対象 0 件、終了")
        return

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
        "C:Year Manufactured", "C:Personalize", "C:Handmade",
        "C:Country/Region of Manufacture", "C:Garment Care", "C:Season", "C:Closure",
    ]
    rows = [csv_headers]
    success = 0
    failed = 0

    for idx, t in enumerate(targets):
        print(f"[{idx+1}/{len(targets)}] {t['url']}")
        prod = fetch_workman_product(t["url"])
        if not prod:
            print("    ⚠️ 取得失敗 → SKIP")
            failed += 1
            continue
        if prod.get("availability") != "InStock":
            print(f"    ⚠️ {prod.get('availability', 'unknown')} → SKIP")
            failed += 1
            continue
        row = build_row(t, prod)
        rows.append(row)
        print(f"    ✨ {row[2]} (${row[4]})")
        success += 1

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = os.path.join(OUTPUT_DIR, f"workman_upload_{ts}.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        w.writerows(rows)
    print(f"\n完了！出力: {out}")
    print(f"成功: {success}件 / 失敗: {failed}件")


if __name__ == "__main__":
    main()
