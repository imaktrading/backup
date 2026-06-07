"""
verify_v8_alignment.py - V8 反映後の Group C listing 強制照合

V8 FIX 後の信頼性回復 script (2026-05-24)。 リバイスくん aligned 判定の信頼性が崩れた
ため、 HQ 側で元 iMak pricing_engine を直接呼んで eBay snapshot と照合し、 V8 と
乖離してる listing を抽出する。

対象: snapshot で Shipping Policy が DDP-C-Pxx の listing (= Group C、 V8 反映対象)

カテゴリ推定: Title 文字列から
  - "Montbell" → Montbell(軽) (= 簡略、 軽/重 区別困難なので軽で計算、 重は shipping 4500 で差)
  - "UNIQLO UT" / "Uniqlo UT" → Tシャツ(UT)
  - "GU" / "ユニクロ" → ユニクロ(非UT)
  - "sneaker" → スニーカー
  - default: Tシャツ(UT)

cost_jpy 取得: 価格管理スプシ (HIGH/LOW/公式) の itemID 列から

照合基準:
  - actual_price vs expected_price (= 差 > $0.5)
  - actual_policy vs expected_policy

出力:
  - mismatch_<ts>.csv: 詳細
  - revise_v8_force_<ts>.csv: FileExchange Revise 形式
"""
from __future__ import annotations
import csv, sys, re
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(r"c:/dev/iMak")
sys.path.insert(0, str(ROOT / "iMakeBayAPI"))
from pricing_engine import compute_listing_price_v6  # noqa: E402

SNAPSHOT_DIR = Path(r"c:/dev/iMak_data/snapshots")
OUT_DIR = Path(r"c:/dev/iMak/iMakHQ/tools/v8_verify_output")
OUT_DIR.mkdir(parents=True, exist_ok=True)
JST = timezone(timedelta(hours=9))


def latest_snapshot() -> Path:
    return sorted(SNAPSHOT_DIR.glob("ebay_active_*.csv"))[-1]


def guess_category(title: str) -> str:
    t = title.lower()
    if "montbell" in t:
        if any(k in t for k in ["jacket", "parka", "down"]):
            return "Montbell(重)"
        return "Montbell(軽)"
    if re.search(r"uniqlo\s*ut\b|uniqlo ut", title, re.IGNORECASE):
        return "Tシャツ(UT)"
    if any(k in t for k in ["sneaker", "shoes"]):
        return "スニーカー"
    if "gu " in t or "uniqlo" in t or "ユニクロ" in t:
        return "ユニクロ(非UT)"
    return "Tシャツ(UT)"  # default Group C


def load_sheet_costs() -> dict[str, int]:
    """価格管理スプシ 3 sheet から itemID → cost_jpy 取得"""
    import gspread
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_file(
        r"c:/dev/iMak/double-hold-421922-7c0d38d3f73d.json",
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    gc = gspread.authorize(creds)
    cost_map = {}
    targets = [
        ("19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk", "商品管理シート", "HIGH"),
        ("1jF9vggbfUCddjneROMO2GGN-jTAPRbq6Qe2cbgr37B0", "商品管理シート", "LOW"),
        ("101KL6KxMugKqZeSp2W5L2ykTvT0Zwd3RzlfsHgiJsg0", "SKU詳細", "公式"),
    ]
    for sid, tab, label in targets:
        try:
            sh = gc.open_by_key(sid)
            ws = sh.worksheet(tab)
            rows = ws.get_all_values()
        except Exception as e:
            print(f"  [WARN] {label}: {e}")
            continue
        if not rows:
            continue
        header = rows[0]
        # itemID 列 (HIGH/LOW="itemID", 公式 SKU詳細="listing ID")
        col_iid = next((i for i, h in enumerate(header) if h.replace(" ", "").lower() in ("itemid", "itemnumber", "listingid")), None)
        # cost 列 (HIGH/LOW="仕入れ価格（円）", 公式 SKU詳細="仕入元価格")
        # 「仕入元在庫」 を誤検出しないため「価格」 か「円」 を必須
        col_cost = next((i for i, h in enumerate(header) if "仕入" in h and ("価格" in h or "円" in h) and "在庫" not in h), None)
        if col_cost is None:
            col_cost = next((i for i, h in enumerate(header) if h in ("N", "現N", "現仕入¥", "現仕入")), None)
        if col_iid is None or col_cost is None:
            print(f"  [WARN] {label}: ItemID={col_iid} cost={col_cost} → skip")
            continue
        cnt = 0
        for row in rows[1:]:
            if len(row) <= max(col_iid, col_cost):
                continue
            iid = (row[col_iid] or "").strip()
            cost_str = (row[col_cost] or "").strip().replace(",", "").replace("¥", "")
            if not iid or not cost_str:
                continue
            try:
                cost_map[iid] = int(float(cost_str))
                cnt += 1
            except ValueError:
                continue
        print(f"  [{label}] tab='{tab}' → {cnt} 件 cost 取得")
    return cost_map


def main() -> int:
    print(f"[{datetime.now(JST).strftime('%H:%M:%S')}] verify_v8_alignment.py 開始")

    snap = latest_snapshot()
    print(f"snapshot: {snap.name}")

    # 価格管理 cost
    print("\n=== スプシ cost 取得 ===")
    cost_map = load_sheet_costs()
    print(f"合計 ItemID → cost: {len(cost_map)} 件")

    # snapshot から Group C listing 抽出 + 照合
    mismatches = []
    no_cost = []
    matches = 0
    with snap.open("r", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            policy = r.get("Shipping profile name", "")
            if not policy.startswith("DDP-C-"):
                continue
            iid = r.get("Item number")
            title = r.get("Title") or ""
            actual_price = float(r.get("Current price") or 0)
            cost_jpy = cost_map.get(iid)
            if cost_jpy is None:
                no_cost.append((iid, policy, actual_price, title[:40]))
                continue
            category = guess_category(title)
            try:
                calc = compute_listing_price_v6(cost_jpy=cost_jpy, median_usd=0, category=category)
            except Exception as e:
                no_cost.append((iid, policy, actual_price, f"calc_err:{e}"))
                continue
            exp_price = calc.get("price")
            exp_policy = calc.get("shipping_profile_name")
            price_diff = abs(actual_price - (exp_price or 0))
            policy_match = policy == exp_policy
            if price_diff > 0.5 or not policy_match:
                mismatches.append({
                    "ItemID": iid, "Title": title[:60], "Category": category, "cost_jpy": cost_jpy,
                    "actual_price": actual_price, "expected_price": exp_price,
                    "actual_policy": policy, "expected_policy": exp_policy,
                    "price_diff": round(price_diff, 2),
                    "reason": ("price" if price_diff > 0.5 else "") + ("+policy" if not policy_match else ""),
                })
            else:
                matches += 1

    total_c = matches + len(mismatches) + len(no_cost)
    print(f"\n=== Group C 照合結果 ({total_c} 件) ===")
    print(f"  ✅ 一致 (= V8 OK): {matches} 件")
    print(f"  ❌ mismatch (= V7 残存疑い): {len(mismatches)} 件")
    print(f"  ⚠ cost 取得不可: {len(no_cost)} 件")

    ts = datetime.now(JST).strftime("%Y%m%d_%H%M%S")
    mm_csv = OUT_DIR / f"mismatch_{ts}.csv"
    with mm_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ItemID","Title","Category","cost_jpy","actual_price","expected_price","actual_policy","expected_policy","price_diff","reason"])
        w.writeheader()
        for m in mismatches:
            w.writerow(m)
    print(f"\nmismatch CSV: {mm_csv}")

    # FileExchange revise CSV (= リバイスくん format に合わせる)
    rev_csv = OUT_DIR / f"revise_v8_force_{ts}.csv"
    with rev_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        w.writerow(["*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)","ItemID","ShippingProfileName","*StartPrice","BestOfferAutoAcceptPrice","MinimumBestOfferPrice"])
        for m in mismatches:
            w.writerow(["Revise", m["ItemID"], m["expected_policy"], f"{m['expected_price']:.2f}", "", ""])
    print(f"revise CSV (FileExchange): {rev_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
