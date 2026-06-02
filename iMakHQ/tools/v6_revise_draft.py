# -*- coding: utf-8 -*-
"""V6 revise CSV 下書き生成
- eBay US active listings (2,095件) を読み込み
- カテゴリ判定 (A/B/C) + 価格帯 + Policy 名を割り当て
- ItemID + Title + Current price + Group + Tier + Policy 名 を CSV 出力
- 仕入¥ + V6 listing price は別途埋める (現段階では空欄)

パック商品 (×N) はマーキングのみ
"""
import csv
from pathlib import Path
from collections import Counter, defaultdict

CSV_PATH = Path(r"C:\Users\imax2\OneDrive\デスクトップ\eBay-all-active-listings-report-2026-05-20-13302285935.csv")
OUTPUT = Path(r"C:\Users\imax2\OneDrive\デスクトップ\V6_revise_draft.csv")

# パック商品 (ItemID → 個数)
PACK_ITEMS = {
    "356796294045": 3,
    "358280566084": 3,
    "358280633511": 3,
    "358388897815": 3,
    "358390003755": 5,
    "358390109249": 5,
}

# B グループ重複 (= A グループ Policy にマッピング)
B_TO_A_REMAP = {
    "DDP-B-P03": "DDP-A-P05",
    "DDP-B-P06": "DDP-A-P10",
    "DDP-B-P11": "DDP-A-P15",
    "DDP-B-P14": "DDP-A-P20",
    "DDP-B-P17": "DDP-A-P22",
    "DDP-B-P20": "DDP-A-P24",
    "DDP-B-P26": "DDP-A-P30",
    "DDP-B-P29": "DDP-A-P31",
}


def detect_group(title: str, ebay_cat: str, sku: str = "") -> str:
    """Title/カテゴリから グループ A/B/C を判定"""
    t = (title or "").lower()
    cat = (ebay_cat or "").lower()

    # B (中関税: バッグ/Porter/リール)
    if any(k in t for k in ["porter", "anello", "アネロ"]):
        return "B"
    if any(k in cat for k in ["handbag", "bag"]):
        return "B"
    if "reel" in t or "リール" in t or "fishing" in cat:
        return "B"

    # C (高関税: Tシャツ/Montbell)
    if any(k in t for k in ["uniqlo", "ut t-shirt", "ut tshirt"]):
        return "C"
    if "montbell" in t:
        return "C"
    if any(k in cat for k in ["t-shirt", "tshirt", "coat", "jacket", "vest", "shirts"]):
        return "C"

    # A (低関税: TCG/玩具/G-SHOCK/文具等)
    return "A"


def price_tier(price: float) -> tuple:
    """価格 → (tier番号, 上限$, ラベル)"""
    bins = [
        (10, "lt10"), (20, "10to20"), (30, "20to30"), (40, "30to40"), (50, "40to50"),
        (60, "50to60"), (70, "60to70"), (80, "70to80"), (90, "80to90"), (100, "90to100"),
        (120, "100to120"), (140, "120to140"), (160, "140to160"), (180, "160to180"),
        (200, "180to200"), (220, "200to220"), (240, "220to240"), (260, "240to260"),
        (280, "260to280"), (300, "280to300"),
        (350, "300to350"), (400, "350to400"), (450, "400to450"), (500, "450to500"),
        (550, "500to550"), (600, "550to600"),
        (700, "600to700"), (800, "700to800"), (900, "800to900"), (1000, "900to1000"),
        (1500, "1000to1500"),
    ]
    for i, (upper, label) in enumerate(bins, 1):
        if price <= upper:
            return f"P{i:02d}", upper, label
    return "P31", 1500, ">1500"


def main():
    # 1) eBay CSV 読込、ItemID 単位で集約 (variation listing は最初の行を採用)
    by_itemid = {}
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            site = row.get("Listing site", "").strip()
            if site != "US":
                continue
            itemid = row.get("Item number", "").strip().strip('"')
            if not itemid or itemid in by_itemid:
                continue  # 同 ItemID 2 行目以降は無視 (= variation 統合)
            title = row.get("Title", "").strip()
            sku = row.get("Custom label (SKU)", "").strip()
            ebay_cat = row.get("eBay category 1 name", "").strip()
            try:
                cur_price = float(row.get("Current price", "") or row.get("Start price", "") or 0)
            except ValueError:
                continue
            if cur_price <= 0:
                continue
            by_itemid[itemid] = {
                "Title": title, "SKU": sku, "eBay_Cat": ebay_cat, "CurrentPrice": cur_price,
            }

    out_rows = []
    stats = Counter()
    for itemid, info in by_itemid.items():
        title = info["Title"]
        sku = info["SKU"]
        ebay_cat = info["eBay_Cat"]
        cur_price = info["CurrentPrice"]

        group = detect_group(title, ebay_cat, sku)
        tier, upper, label = price_tier(cur_price)
        policy_raw = f"DDP-{group}-{tier}"
        policy = B_TO_A_REMAP.get(policy_raw, policy_raw)
        remapped = "★" if policy != policy_raw else ""

        pack_qty = PACK_ITEMS.get(itemid, 1)
        pack_mark = f"×{pack_qty}" if pack_qty > 1 else ""

        out_rows.append({
            "ItemID": itemid,
            "Title": title[:60],
            "SKU": sku,
            "eBay_Cat": ebay_cat[:30],
            "CurrentPrice": cur_price,
            "Group": group,
            "Tier": tier,
            "UpperUSD": upper,
            "PolicyName_raw": policy_raw,
            "PolicyName_assigned": policy,
            "Remap★": remapped,
            "Pack": pack_mark,
            "Cost_JPY": "",
            "V6_listing_price": "",
            "V6_shipping_cost": "",
        })
        stats[group] += 1

    skipped = 0
    group_stats = {}

    # CSV 出力
    if out_rows:
        with open(OUTPUT, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=out_rows[0].keys())
            writer.writeheader()
            writer.writerows(out_rows)

    print(f"Output: {OUTPUT}")
    print(f"Total: {len(out_rows)} listings (skipped: {skipped})")
    print(f"By group: {dict(stats)}")
    print(f"Remap (B→A): {sum(1 for r in out_rows if r['Remap★'])}")
    print(f"Pack items: {sum(1 for r in out_rows if r['Pack'])}")


if __name__ == "__main__":
    main()
