"""competitor_gap_finder - ライバルセラーの売れ筋 listing で、うちが未出品のものを抽出.

5/15 ユーザー要望: ライバル listing で watchCount 多い (= 実需要シグナル) のうち、
うちで未出品のものを「出品候補」として浮かび上がらせる。

Browse API 限界:
- watchCount: 取得可
- View 数 / Sold 数 (per item): API では非公開
→ watchCount のみで需要 proxy として使う

使い方:
  python competitor_gap_finder.py \\
      --rivals pesa_japan qbks_89 \\
      --my-seller imax-64 \\
      --watch-threshold 3 \\
      --max-per-rival 1000

  ※ 事前に各 seller の listing CSV を ebay_seller_store_scraper.py で取得しておく
    (= seller_analysis/<seller>_listings_<ts>.csv が必要)

出力:
  C:/dev/iMak_data/seller_analysis/gap_candidates_<ts>.csv
"""
from __future__ import annotations

import argparse
import csv
import glob
import os
import re
import sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

OUTPUT_DIR = r"C:\dev\iMak_data\seller_analysis"


def latest_listings_csv(seller_id: str) -> str:
    files = sorted(glob.glob(os.path.join(OUTPUT_DIR, f"{seller_id}_listings_*.csv")))
    return files[-1] if files else ""


def fetch_seller_if_missing(seller_id: str, max_listings: int) -> str:
    """既存 CSV がなければ scraper 起動して取得."""
    p = latest_listings_csv(seller_id)
    if p:
        return p
    print(f"  📡 {seller_id} の CSV なし、scrape 起動")
    import subprocess
    subprocess.run(
        ["python", "ebay_seller_store_scraper.py", seller_id,
         "--max", str(max_listings)],
        cwd=os.path.dirname(os.path.abspath(__file__)),
        check=False,
    )
    return latest_listings_csv(seller_id)


def load_listings(csv_path: str) -> list[dict]:
    if not csv_path or not os.path.exists(csv_path):
        return []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


# 同一商品判定用 keyword 抽出 (= ファジー Title 一致)
_STOPWORDS = {
    "psa10", "psa", "the", "and", "for", "with", "from", "japanese", "english",
    "japan", "new", "rare", "card", "pokemon", "yu-gi-oh", "yugioh", "weiss",
    "schwarz", "dragon", "ball", "one", "piece", "tcg", "10", "9", "graded",
}


def title_keywords(title: str, k: int = 5) -> set[str]:
    """Title から特徴語 (上位 k 個) を抽出. stopwords / 数字短語 除外."""
    if not title:
        return set()
    words = re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}", title.lower())
    keys = []
    for w in words:
        if w in _STOPWORDS:
            continue
        if w.isdigit() and len(w) < 4:
            continue
        if len(w) < 3:
            continue
        keys.append(w)
        if len(keys) >= k:
            break
    return set(keys)


def cert_number(title: str) -> str:
    """PSA cert number (8 桁数字) があれば返す."""
    if not title:
        return ""
    m = re.search(r"\b(\d{8,10})\b", title)
    return m.group(1) if m else ""


def listing_in_my_store(rival_title: str, my_keys_list: list[set], my_certs: set) -> bool:
    """rival_title が my store の listing と同一 product か判定."""
    # 1) PSA cert 完全一致 → 同一物理カード確定
    c = cert_number(rival_title)
    if c and c in my_certs:
        return True
    # 2) ファジー keyword 一致 (= 同 product)
    rk = title_keywords(rival_title, k=5)
    if not rk:
        return False
    for mk in my_keys_list:
        if rk and len(rk & mk) >= 3:
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rivals", nargs="+", required=True,
                        help="ライバル seller ID 一覧 (例: pesa_japan qbks_89)")
    parser.add_argument("--my-seller", default="imax-64",
                        help="自店 seller ID (default: imax-64)")
    parser.add_argument("--watch-threshold", type=int, default=3,
                        help="watchCount >= この値の listing のみ候補化 (default: 3)")
    parser.add_argument("--max-per-rival", type=int, default=1000,
                        help="ライバル毎の取得上限 (default: 1000)")
    parser.add_argument("--no-fetch", action="store_true",
                        help="既存 CSV だけ使う (新規 scrape skip)")
    args = parser.parse_args()

    # 自店 listing 読込
    print(f"=== competitor gap finder ===")
    print(f"  rivals: {args.rivals}")
    print(f"  my_seller: {args.my_seller}")
    print(f"  watch threshold: {args.watch_threshold}")

    my_csv = latest_listings_csv(args.my_seller)
    if not my_csv and not args.no_fetch:
        my_csv = fetch_seller_if_missing(args.my_seller, args.max_per_rival)
    my_listings = load_listings(my_csv)
    print(f"\n📂 自店 {args.my_seller}: {len(my_listings)} 件 ({os.path.basename(my_csv)})")
    my_keys_list = [title_keywords(r.get("title", ""), k=5) for r in my_listings]
    my_certs = {cert_number(r.get("title", "")) for r in my_listings}
    my_certs.discard("")
    print(f"  自店 PSA cert 数: {len(my_certs)}")

    # ライバル listing 読込 + gap 抽出
    candidates = []
    for rival in args.rivals:
        rival_csv = latest_listings_csv(rival)
        if not rival_csv and not args.no_fetch:
            rival_csv = fetch_seller_if_missing(rival, args.max_per_rival)
        rival_listings = load_listings(rival_csv)
        print(f"\n📂 {rival}: {len(rival_listings)} 件 ({os.path.basename(rival_csv) if rival_csv else 'N/A'})")
        gap_count = 0
        for r in rival_listings:
            try:
                watch_n = int(r.get("watch_count", "") or 0)
            except (ValueError, TypeError):
                watch_n = 0
            if watch_n < args.watch_threshold:
                continue
            t = r.get("title", "")
            if listing_in_my_store(t, my_keys_list, my_certs):
                continue  # うちで既に出品済
            candidates.append({
                "rival_seller": rival,
                "rival_item_id": r.get("item_id", ""),
                "watch_count": watch_n,
                "rival_price_usd": r.get("price_value", ""),
                "title": t,
                "category": r.get("category_path", "").split(" > ")[-1],
                "rival_url": r.get("item_web_url", ""),
                "image": r.get("image_url", ""),
            })
            gap_count += 1
        print(f"  → gap (= watch>={args.watch_threshold} & うち未出品): {gap_count} 件")

    # watchCount 降順で並べる
    candidates.sort(key=lambda x: -x["watch_count"])
    print(f"\n🎯 候補総数: {len(candidates)}")

    # 出力
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = os.path.join(OUTPUT_DIR, f"gap_candidates_{ts}.csv")
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        cols = ["rival_seller", "watch_count", "rival_price_usd", "title",
                "category", "rival_item_id", "rival_url", "image"]
        w = csv.DictWriter(f, fieldnames=cols, quoting=csv.QUOTE_NONNUMERIC,
                           extrasaction="ignore")
        w.writeheader()
        w.writerows(candidates)
    print(f"\n💾 出力: {out}")
    try:
        os.startfile(out)
    except Exception:
        pass

    if candidates:
        print(f"\n=== TOP 10 候補 (watch 降順) ===")
        for c in candidates[:10]:
            print(f"  watch {c['watch_count']:>3d}  ${c['rival_price_usd']:>7s}  [{c['rival_seller']:15s}]  {c['title'][:70]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
