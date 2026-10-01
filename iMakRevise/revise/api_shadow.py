"""api_shadow.py - API 版 (api_revise.py) を影で回し、FileExchange 用 CSV と突き合わせる.

eBay には何も送らない (読むのは送料ポリシー一覧だけ)。
毎朝の run_daily が作った CSV 3本と、その直前の snapshot (variations.json) を入力に、
API 版が「どの itemID / SKU を いくらに・どの送料ポリシーに」するかを組み立て、CSV の意図と比べる。

使い方:
  python -X utf8 revise/api_shadow.py            # 最新の1回分
  python -X utf8 revise/api_shadow.py --days 7   # 過去7日分 (日ごとの最後の走行)
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent.parent
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from revise.api_revise import (_norm_specifics, _read_csv, build_all_xml,  # noqa: E402
                               build_plan, fetch_shipping_policy_ids,
                               load_current_profiles)

CSV_DIR = PKG_ROOT / "csv_output"
SNAPSHOT_DIR = Path(r"C:/dev/iMak_data/snapshots")
LOG_PATH = PKG_ROOT / "decision_log" / "api_shadow.log"


def _runs(days: int) -> list:
    """revise_combined_<ts>.csv の ts を日ごとに最後の1本ずつ、新しい順に days 件."""
    by_day = {}
    for p in CSV_DIR.glob("revise_combined_2*.csv"):
        m = re.fullmatch(r"revise_combined_(\d{8})_(\d{6})\.csv", p.name)
        if m:
            by_day[m.group(1)] = max(by_day.get(m.group(1), ""), m.group(1) + "_" + m.group(2))
    return [by_day[d] for d in sorted(by_day, reverse=True)[:days]]


def _near_ts(prefix: str, ts: str) -> Path | None:
    """同じ走行の variation CSV (ts が ±2秒ずれることがある)."""
    base = datetime.strptime(ts, "%Y%m%d_%H%M%S")
    for p in CSV_DIR.glob(f"{prefix}_{ts[:8]}_*.csv"):
        t = datetime.strptime(p.stem[len(prefix) + 1:], "%Y%m%d_%H%M%S")
        if abs((t - base).total_seconds()) <= 5:
            return p
    return None


def _snapshot_before(ts: str) -> Path | None:
    run = datetime.strptime(ts, "%Y%m%d_%H%M%S")
    best = None
    for p in SNAPSHOT_DIR.glob("ebay_active_*.variations.json"):
        t = datetime.strptime(p.name[len("ebay_active_"):len("ebay_active_") + 17], "%Y-%m-%d_%H%M%S")
        if t <= run and (best is None or t > best[0]):
            best = (t, p)
    return best[1] if best else None


def _csv_intent(single, var_price, var_ship):
    """CSV が eBay にさせたいこと (API 版とは別に、CSV だけから読む)."""
    prices, ships = {}, {}
    for r in _read_csv(single):
        if r.get("*StartPrice"):
            prices[(r["ItemID"], None)] = float(r["*StartPrice"])
        if r.get("ShippingProfileName"):
            ships[r["ItemID"]] = r["ShippingProfileName"]
    parent = None
    for r in _read_csv(var_price):
        if r.get("ItemID"):
            parent = r["ItemID"]
        elif r.get("Relationship") == "Variation" and r.get("*StartPrice"):
            prices[(parent, _norm_specifics(r["RelationshipDetails"]))] = float(r["*StartPrice"])
    for r in _read_csv(var_ship):
        if r.get("ShippingProfileName"):
            ships[r["ItemID"]] = r["ShippingProfileName"]
    return prices, ships


def shadow_one(ts: str, policy_ids: dict) -> dict:
    single = CSV_DIR / f"revise_combined_{ts}.csv"
    var_price = _near_ts("revise_variation_price", ts)
    var_ship = _near_ts("revise_variation_shipping", ts)
    snap = _snapshot_before(ts)
    plan = build_plan(single, var_price, var_ship, snap, policy_ids)
    xmls = build_all_xml(plan)  # 許可外タグがあれば例外で止まる
    snap_csv = snap.with_name(snap.name.replace(".variations.json", ".csv")) if snap else None
    cur = load_current_profiles(snap_csv)
    slim = build_plan(single, var_price, var_ship, snap, policy_ids, current_profiles=cur)
    slim_calls = len(build_all_xml(slim))

    want_p, want_s = _csv_intent(single, var_price, var_ship)
    got_p = {(c.item_id, _norm_specifics(c.specifics) if c.specifics else None): c.price
             for c in plan.prices}
    got_s = {s.item_id: s.profile_name for s in plan.shippings if s.profile_id}
    p_ok = sum(1 for k, v in want_p.items() if got_p.get(k) == v)
    s_ok = sum(1 for k, v in want_s.items() if got_s.get(k) == v)
    extra = len(set(got_p) - set(want_p)) + len(set(got_s) - set(want_s))
    total = len(want_p) + len(want_s)
    return {
        "ts": ts, "snapshot": snap.name if snap else None,
        "price_want": len(want_p), "price_ok": p_ok,
        "ship_want": len(want_s), "ship_ok": s_ok, "extra": extra,
        "match_pct": round(100 * (p_ok + s_ok) / total, 2) if total else 100.0,
        "api_calls": len(xmls), "api_calls_slim": slim_calls,
        "ship_slim": len(slim.shippings), "problems": plan.problems,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1)
    args = ap.parse_args()

    policy_ids = fetch_shipping_policy_ids()
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    worst = 100.0
    for ts in _runs(args.days):
        r = shadow_one(ts, policy_ids)
        worst = min(worst, r["match_pct"])
        line = (f"{datetime.now():%Y-%m-%d %H:%M:%S} [shadow] {r['ts']} 一致 {r['match_pct']}% "
                f"値段 {r['price_ok']}/{r['price_want']} 送料 {r['ship_ok']}/{r['ship_want']} "
                f"余分 {r['extra']} API呼出 {r['api_calls']}→絞込後 {r['api_calls_slim']} (送料 {r['ship_slim']}) 組めない {len(r['problems'])} "
                f"snapshot={r['snapshot']}")
        print(line)
        for p in r["problems"][:20]:
            print("   -", p)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            for p in r["problems"]:
                f.write(f"   - {p}\n")
    return 0 if worst == 100.0 else 1


if __name__ == "__main__":
    sys.exit(main())
