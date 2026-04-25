#!/usr/bin/env python3
import sys, io, requests, csv, re
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

url = "https://docs.google.com/spreadsheets/d/1MufEUweIJcLv-NwT3KZsEJ_k_yl1rKryaqBZjUH7c2U/export?format=csv&gid=1814510799"
resp = requests.get(url, timeout=30)
lines = resp.text.split("\n")

categories = defaultdict(lambda: {"count": 0, "revenue": 0, "profit": 0})

for line in lines[1:]:
    if not line.strip():
        continue
    try:
        parts = list(csv.reader([line]))[0]
        if len(parts) < 16:
            continue
        title = parts[2]
        price_str = re.sub(r"[^0-9.]", "", parts[6])
        price = float(price_str) if price_str else 0

        # 営業利益列 (index 15)
        profit_raw = parts[15]
        profit_clean = re.sub(r"[^\d.\-]", "", profit_raw)
        profit = float(profit_clean) if profit_clean else 0

        # カテゴリ列 (index 17)
        cat = parts[17].strip() if len(parts) > 17 and parts[17].strip() else ""

        if not cat:
            t = title.lower()
            if "g-shock" in t or "casio" in t:
                cat = "G-SHOCK"
            elif "uniqlo" in t or " ut " in t:
                cat = "UNIQLO UT"
            elif "montbell" in t or "mont-bell" in t:
                cat = "Montbell"
            elif "porter" in t:
                cat = "Porter"
            elif "pop mart" in t:
                cat = "POP MART"
            elif "daiso" in t:
                cat = "Daiso"
            elif "figuarts" in t:
                cat = "フィギュア"
            elif "sanrio" in t or "pilot" in t:
                cat = "サンリオ"
            else:
                cat = "その他"

        categories[cat]["count"] += 1
        categories[cat]["revenue"] += price
        categories[cat]["profit"] += profit
    except Exception as e:
        pass

print(f"{'カテゴリ':<15} {'件数':>5} {'売上($)':>10} {'利益(JPY)':>12} {'平均利益':>10} {'平均単価($)':>10}")
print("-" * 70)
total_count = 0
total_rev = 0
total_profit = 0
for cat, d in sorted(categories.items(), key=lambda x: -x[1]["count"]):
    avg_profit = d["profit"] / d["count"] if d["count"] > 0 else 0
    avg_price = d["revenue"] / d["count"] if d["count"] > 0 else 0
    print(f"{cat:<15} {d['count']:>5} {d['revenue']:>10.0f} {d['profit']:>12.0f} {avg_profit:>10.0f} {avg_price:>10.0f}")
    total_count += d["count"]
    total_rev += d["revenue"]
    total_profit += d["profit"]

print("-" * 70)
print(f"{'合計':<15} {total_count:>5} {total_rev:>10.0f} {total_profit:>12.0f}")
