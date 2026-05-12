"""seller_hub_tier - Active listings から改善対象を抽出するツール.

5/12 ユーザー判定軸 (論点 2):
  改善対象 = 出品 30日超 AND (
    views == 0
    OR
    (views < 5 AND watchers == 0)
  )

出品から 30日超えて View が伸びてない listing = 検索ヒットしてない可能性。
タイトル/価格を 1回見直し → 30日後 再評価 → 改善なければ END。

入力: seller_hub_view.py で取得した Active snapshot CSV (iMak_data/seller_hub/)
出力: improvement_targets_YYYYMMDD.csv (iMak_data/seller_hub/)

使い方:
  python seller_hub_tier.py                                  # 最新 Active snapshot 自動選択
  python seller_hub_tier.py --snapshot path/to/snapshot.csv  # 明示指定
  python seller_hub_tier.py --min-days 30 --max-views 5      # 閾値カスタム
"""
from __future__ import annotations

import argparse
import csv
import glob
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SNAPSHOT_DIR = r"C:\dev\iMak_data\seller_hub"


def find_latest_active_snapshot() -> str | None:
    pattern = os.path.join(SNAPSHOT_DIR, "snapshot_active_*.csv")
    candidates = sorted(glob.glob(pattern))
    return candidates[-1] if candidates else None


def parse_date(s: str) -> datetime | None:
    """listed_date 列の文字列を datetime に変換. 失敗時は None."""
    if not s or not s.strip():
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None


def _int(v: str) -> int:
    try:
        return int(v.strip())
    except (ValueError, AttributeError):
        return 0


def filter_improvement_targets(rows: list[dict],
                                 min_days: int = 30,
                                 max_views_for_zero_watch: int = 5,
                                 today: datetime | None = None) -> list[dict]:
    """5/12 判定軸でフィルタ.

    対象:
      出品 min_days 超 AND (
        views == 0
        OR
        (views < max_views_for_zero_watch AND watchers == 0)
      )
    """
    if today is None:
        today = datetime.now()
    threshold_date = today - timedelta(days=min_days)
    targets = []
    for r in rows:
        # listed_date がない or parse 失敗 → skip
        listed = parse_date(r.get("listed_date", ""))
        if listed is None:
            continue
        if listed > threshold_date:
            continue  # 30日経ってない、まだ評価早い

        v = _int(r.get("views", ""))
        w = _int(r.get("watchers", ""))
        # 条件: views=0 OR (views<max AND watchers=0)
        if v == 0 or (v < max_views_for_zero_watch and w == 0):
            r["_days_listed"] = (today - listed).days
            r["_reason"] = "views=0" if v == 0 else f"views<{max_views_for_zero_watch}+watch=0"
            targets.append(r)
    return targets


def categorize_by_keyword(title: str) -> str:
    """Title から大分類カテゴリを推定."""
    t = title.lower()
    if "porter" in t or "yoshida" in t:
        return "Porter"
    if "g-shock" in t or "gshock" in t or "casio g" in t:
        return "G-Shock"
    if "psa 10" in t or "psa10" in t:
        return "PSA10 TCG"
    if "ichiban kuji" in t or "kuji" in t:
        return "Ichiban Kuji"
    if any(k in t for k in ("shimano", "daiwa", "reel", "spinning", "baitcast")):
        return "Reel"
    if "tomica" in t:
        return "Tomica"
    if "uniqlo" in t or "ut " in t:
        return "UNIQLO UT"
    return "Other"


def save_targets(targets: list[dict], out_path: str) -> None:
    if not targets:
        return
    fields = list(targets[0].keys())
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, quoting=csv.QUOTE_NONNUMERIC,
                           extrasaction="ignore")
        w.writeheader()
        for r in targets:
            w.writerow(r)


def summarize(targets: list[dict]) -> dict:
    """カテゴリ別件数 + 平均経過日数 サマリー."""
    by_cat: dict[str, list[dict]] = {}
    for r in targets:
        cat = categorize_by_keyword(r.get("title", ""))
        by_cat.setdefault(cat, []).append(r)
    summary = {}
    for cat, lst in by_cat.items():
        days = [r.get("_days_listed", 0) for r in lst]
        summary[cat] = {
            "count": len(lst),
            "avg_days": sum(days) // len(days) if days else 0,
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=str, default=None,
                        help="Active snapshot CSV path (省略時は最新自動選択)")
    parser.add_argument("--min-days", type=int, default=30,
                        help="出品からの最低経過日数 (default: 30)")
    parser.add_argument("--max-views", type=int, default=5,
                        help="watcher=0 時の views 上限 (default: 5)")
    args = parser.parse_args()

    snapshot_path = args.snapshot or find_latest_active_snapshot()
    if not snapshot_path or not os.path.exists(snapshot_path):
        print(f"❌ Active snapshot が見つかりません: {snapshot_path}")
        print(f"   先に seller_hub_view.py --status active --all-pages --save を実行")
        return 1

    print(f"📂 snapshot: {os.path.basename(snapshot_path)}")
    with open(snapshot_path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    print(f"   読込 {len(rows)} listings")

    targets = filter_improvement_targets(rows,
                                          min_days=args.min_days,
                                          max_views_for_zero_watch=args.max_views)
    print(f"\n🔍 改善対象: {len(targets)} 件 / 全 {len(rows)} 件 = {len(targets)*100//max(len(rows),1)}%")
    print(f"   条件: 出品 {args.min_days} 日超 + (views=0 OR (views<{args.max_views} AND watchers=0))")

    # カテゴリ別サマリー
    if targets:
        summary = summarize(targets)
        print(f"\n--- カテゴリ別 ---")
        for cat, info in sorted(summary.items(), key=lambda x: -x[1]["count"]):
            print(f"  {cat:>14s}: {info['count']:>4} 件 (avg {info['avg_days']}日経過)")

    # 出力
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(SNAPSHOT_DIR, f"improvement_targets_{ts}.csv")
    save_targets(targets, out_path)
    print(f"\n💾 保存: {out_path}")

    # 上位 10 件サンプル (経過日数長い順)
    targets.sort(key=lambda r: -r.get("_days_listed", 0))
    print(f"\n--- TOP 10 (経過日数長い順) ---")
    print(f"  {'days':>4} {'views':>5} {'watch':>5} {'price':>7}  Title")
    for r in targets[:10]:
        print(f"  {r['_days_listed']:>4} {_int(r['views']):>5} {_int(r['watchers']):>5} "
              f"${r['price_usd']:>6} {r['title'][:60]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
