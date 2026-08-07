# -*- coding: utf-8 -*-
"""eBay 全 active listings CSV から US 出品をカテゴリ別に分類サマリー"""
import csv
from collections import Counter, defaultdict
from pathlib import Path

CSV_PATH = Path(r"C:\Users\imax2\OneDrive\デスクトップ\eBay-all-active-listings-report-2026-05-20-13302285935.csv")

# カテゴリ判定: Title キーワード優先、なければ eBay category
def detect_group(title: str, ebay_cat: str, sku: str = ""):
    """Title/カテゴリから グループ A/B/C を判定。"""
    t = (title or "").lower()
    cat = (ebay_cat or "").lower()
    sku_l = (sku or "").lower()

    # グループ B (中関税: バッグ/Porter/リール HTS 7-15%)
    if any(k in t for k in ["porter", "anello", "アネロ"]):
        return "B"
    if any(k in cat for k in ["handbag", "bag"]):
        return "B"
    if "reel" in t or "リール" in t or "fishing" in cat:
        return "B"

    # グループ C (高関税: Tシャツ/Montbell HTS 16-32%)
    if any(k in t for k in ["uniqlo", "ut t-shirt", "ut tshirt"]):
        return "C"
    if "montbell" in t:
        return "C"
    if any(k in cat for k in ["t-shirt", "tshirt", "coat", "jacket", "vest", "shirts"]):
        return "C"

    # デフォルト: グループ A (低関税: TCG/玩具/時計/文具 HTS 0-13%)
    return "A"


def price_tier(price: float):
    """価格 → tier P01-P31"""
    bins = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100,
            120, 140, 160, 180, 200, 220, 240, 260, 280, 300,
            350, 400, 450, 500, 550, 600,
            700, 800, 900, 1000, 1500]
    for i, upper in enumerate(bins, 1):
        if price <= upper:
            return f"P{i:02d}"
    return "P31"  # > $1500 はP31扱い


# 集計
sites = Counter()
groups = Counter()
group_tier = defaultdict(int)
records = []

with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
    reader = csv.DictReader(f)
    for row in reader:
        site = row.get("Listing site", "").strip()
        sites[site] += 1
        if site != "US":
            continue
        title = row.get("Title", "")
        ebay_cat = row.get("eBay category 1 name", "")
        sku = row.get("Custom label (SKU)", "")
        try:
            price = float(row.get("Current price", "") or row.get("Start price", "") or 0)
        except ValueError:
            continue
        if price <= 0:
            continue
        group = detect_group(title, ebay_cat, sku)
        tier = price_tier(price)
        groups[group] += 1
        group_tier[(group, tier)] += 1
        records.append({
            "itemid": row["Item number"],
            "title": title[:60],
            "ebay_cat": ebay_cat,
            "sku": sku,
            "price": price,
            "group": group,
            "tier": tier,
            "policy": f"DDP-{group}-{tier}",
        })

print(f"Total listings: {sum(sites.values())}")
print(f"By site: {dict(sites)}")
print()
print(f"US listings: {sum(groups.values())}")
print(f"By group: {dict(groups)}")
print()
print(f"=== Group × Tier 分布 (件数) ===")
print(f"{'Tier':>6} | {'A':>5} | {'B':>5} | {'C':>5}")
print("-" * 30)
bins = ["P01","P02","P03","P04","P05","P06","P07","P08","P09","P10",
        "P11","P12","P13","P14","P15","P16","P17","P18","P19","P20",
        "P21","P22","P23","P24","P25","P26","P27","P28","P29","P30","P31"]
for t in bins:
    a = group_tier.get(("A", t), 0)
    b = group_tier.get(("B", t), 0)
    c = group_tier.get(("C", t), 0)
    if a + b + c > 0:
        print(f"{t:>6} | {a:>5} | {b:>5} | {c:>5}")
