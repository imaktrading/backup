# -*- coding: utf-8 -*-
"""ebaymag VAT 二重引き仮説 検証
US/UK/DE/AU の同一 SKU ペアで実価格比率を確認"""
import csv
from collections import defaultdict
from pathlib import Path

CSV = Path(r"C:\Users\imax2\OneDrive\デスクトップ\eBay-all-active-listings-report-2026-05-19-11307591140.csv")
FX = {"USD": 1.0, "GBP": 1.34, "EUR": 1.08, "AUD": 0.65}  # 1 unit → USD

rows = []
with open(CSV, encoding="utf-8-sig", newline="") as f:
    r = csv.DictReader(f)
    for row in r:
        try:
            price = float(row.get("Current price", "") or row.get("Start price", "") or 0)
        except ValueError:
            continue
        if price <= 0:
            continue
        rows.append({
            "item": row["Item number"],
            "title": row["Title"][:60],
            "sku": row.get("Custom label (SKU)", ""),
            "site": row.get("Listing site", ""),
            "currency": row.get("Currency", ""),
            "price": price,
        })

# title でグループ化 (SKU 空欄あるため)
by_title = defaultdict(list)
for x in rows:
    key = (x["title"], x["sku"])
    by_title[key].append(x)

pairs = []
for key, items in by_title.items():
    sites = {x["site"]: x for x in items}
    if "US" in sites and any(s in sites for s in ["GB", "DE", "AU", "UK"]):
        us = sites["US"]
        for other_site in ["GB", "UK", "DE", "AU"]:
            if other_site in sites:
                pairs.append((us, sites[other_site]))

print(f"US/非US ペア数: {len(pairs)}")
print()

# 各ペアで:
# 仮説1 (-30%): US × 0.70 / FX
# 仮説2 (-30% + VAT抜き UK/DE): US × 0.70 / FX / 1.20
# 実測比較
print(f"{'US$':>8} {'非US':>10} {'site':>4} {'比率':>6} {'実質割引':>8} {'仮説1':>8} {'仮説2':>8} {'仮説2合致?':>10}")
print("-" * 80)
for us, other in pairs[:30]:
    us_price = us["price"]
    other_price = other["price"]
    cur = other["currency"]
    fx = FX.get(cur, 1.0)
    other_usd_eq = other_price * fx
    ratio = other_usd_eq / us_price  # UK が US の何%
    discount = 1 - ratio
    # 仮説1: US × 0.70 / fx
    hyp1 = us_price * 0.70 / fx
    # 仮説2: US × 0.70 / fx / 1.20 (UK/DE は VAT 20%, AU は GST 10%)
    vat = 1.20 if cur in ("GBP", "EUR") else 1.10
    hyp2 = us_price * 0.70 / fx / vat
    h2_match = "Y" if abs(other_price - hyp2) / hyp2 < 0.05 else "N"
    h1_match = "Y" if abs(other_price - hyp1) / hyp1 < 0.05 else "N"
    print(f"${us_price:>7.2f} {other_price:>9.2f}{cur[:1]} {other['site']:>4} {ratio:>6.2%} {discount:>7.1%} {hyp1:>7.2f} {hyp2:>7.2f}   h1={h1_match} h2={h2_match}")

# 集計
n = len(pairs)
h1_hit = sum(1 for us, o in pairs if abs(o["price"] - us["price"]*0.70/FX.get(o["currency"],1)) / (us["price"]*0.70/FX.get(o["currency"],1)) < 0.05)
h2_hit = sum(1 for us, o in pairs if abs(o["price"] - us["price"]*0.70/FX.get(o["currency"],1)/(1.20 if o["currency"] in ("GBP","EUR") else 1.10)) / (us["price"]*0.70/FX.get(o["currency"],1)/(1.20 if o["currency"] in ("GBP","EUR") else 1.10)) < 0.05)
print()
print(f"仮説1 (-30%のみ) 合致率: {h1_hit}/{n} = {h1_hit/n:.1%}")
print(f"仮説2 (-30% + VAT抜き) 合致率: {h2_hit}/{n} = {h2_hit/n:.1%}")

# 平均実質割引率
avg_disc_gbp = sum(1 - o["price"]*FX["GBP"]/us["price"] for us, o in pairs if o["currency"]=="GBP") / max(1, sum(1 for us, o in pairs if o["currency"]=="GBP"))
avg_disc_eur = sum(1 - o["price"]*FX["EUR"]/us["price"] for us, o in pairs if o["currency"]=="EUR") / max(1, sum(1 for us, o in pairs if o["currency"]=="EUR"))
avg_disc_aud = sum(1 - o["price"]*FX["AUD"]/us["price"] for us, o in pairs if o["currency"]=="AUD") / max(1, sum(1 for us, o in pairs if o["currency"]=="AUD"))
print()
print(f"平均実質割引率 GBP: {avg_disc_gbp:.1%}")
print(f"平均実質割引率 EUR: {avg_disc_eur:.1%}")
print(f"平均実質割引率 AUD: {avg_disc_aud:.1%}")
