"""seller_hub_view - eBay Seller Hub Active Listings を分析するツール (HQ Claude 用).

iMakInventory の chrome_profile_ebay (eBay ログイン状態 cookie 永続化済) を流用して
Selenium で Seller Hub にアクセスし、HTML から listing データを抽出 + 分析する。

機能:
  - Active Listings をカテゴリ別 (Porter / G-Shock / TCG / 一番くじ / Reel) で絞込
  - View 数 / Watchers 抽出
  - TOP 20 by Views / Watchers / 死蔵件数 統計を出力

注意:
  - iMakInventory が cron で Chrome 起動中だと profile lock で失敗する
  - 視覚要素 (グラフ・色分け) は取れない、HTML テキストのみ
  - 2FA 切れたら再ログイン必要 (iMakInventory --login で対応)

使い方:
  python seller_hub_view.py --category porter
  python seller_hub_view.py --category gshock --analyze
  python seller_hub_view.py --keyword "PSA 10" --analyze
"""
from __future__ import annotations

import argparse
import re
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By

EBAY_CHROME_PROFILE_DIR = r"C:\Users\imax2\local_data\iMakInventory\chrome_profile_ebay"

# カテゴリ → 検索 keyword マッピング
CATEGORY_KEYWORDS = {
    "porter":      "Porter",
    "gshock":      "G-Shock",
    "tcg":         "PSA 10",
    "ichibankuji": "Ichiban Kuji",
    "reel":        "Fishing Reel",
}

URL_BASE = "https://www.ebay.com/sh/lst/active"


def open_active(keyword: str | None, wait_seconds: int = 18):
    url = URL_BASE
    if keyword:
        url = f"{URL_BASE}?keyword={keyword.replace(' ', '+')}"
    options = uc.ChromeOptions()
    options.add_argument(f"--user-data-dir={EBAY_CHROME_PROFILE_DIR}")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    driver = uc.Chrome(options=options)
    print(f"[INFO] open: {url}")
    driver.get(url)
    time.sleep(wait_seconds)
    return driver


def parse_listing_row(row_text: str) -> dict:
    """row.text から listing 情報を抽出.

    column 順 (eBay Active 標準):
      0: 編集
      1: Title
      2: Format · ItemID (例: "今すぐ買う · 358545495042")
      3: SKU
      4: Watchers (1つ目の単独数字)
      5: Price USD
      6: Price JPY
      ...
      -3: Available
      -2: Sold (or 別 column、推測)
      最後付近: "リンク。ビュー数X" 含む行
    """
    lines = [l for l in row_text.strip().split("\n") if l.strip()]
    out = {"title": "", "item_id": "", "price": "", "watchers": None,
           "views": 0, "available": None, "sold": None}

    if len(lines) < 5:
        return out
    out["title"] = lines[1][:80]

    # ItemID (12桁数字 in 行内)
    for L in lines:
        m = re.search(r"(\d{12})", L)
        if m:
            out["item_id"] = m.group(1)
            break

    # Price USD
    for L in lines:
        m = re.search(r"US\s*\$([0-9,.]+)", L)
        if m:
            out["price"] = m.group(1)
            break

    # Views (regex 確実マッチ)
    m = re.search(r"ビュー数(\d+)", row_text)
    if m:
        out["views"] = int(m.group(1))

    # 単独数字 line 群: Watchers / Available / Sold を順序ベースで推定
    # ユーザー判断 (5/12) に基づき、num_lines[-1] = Watchers としてラベル付け
    num_lines = [l.strip() for l in lines if re.fullmatch(r"\d+", l.strip())]
    if len(num_lines) >= 3:
        # 構造: [ItemID 内の数字行?, ..., Available, Sold/Watchers]
        # 5/12 観察: TOP listing で num_lines[-1] が watcher 数として現実的
        out["watchers"] = int(num_lines[-1])
        out["available"] = int(num_lines[-2])
    elif len(num_lines) == 2:
        out["available"] = int(num_lines[0])
        out["watchers"] = int(num_lines[1])

    return out


def extract_listings(driver) -> list[dict]:
    rows = driver.find_elements(By.CSS_SELECTOR, "tr.grid-row")
    items = []
    for r in rows:
        try:
            parsed = parse_listing_row(r.text)
            if parsed["item_id"]:
                items.append(parsed)
        except Exception:
            continue
    # ItemID 単位デドゥープ (multi-language 同型番除外したい場合は title でも可)
    seen = set()
    uniq = []
    for it in items:
        if it["item_id"] not in seen:
            seen.add(it["item_id"])
            uniq.append(it)
    return uniq


def analyze(items: list[dict], label: str = "Active") -> None:
    print(f"\n=== {label}: {len(items)} listings ===\n")
    if not items:
        return

    # TOP by Views
    by_views = sorted(items, key=lambda x: x["views"], reverse=True)
    print(f"--- TOP 15 by Views ---")
    print(f"  {'views':>5} {'watch':>5} {'price':>7}  Title")
    for it in by_views[:15]:
        w = it.get("watchers")
        wstr = str(w) if w is not None else "-"
        print(f"  {it['views']:>5} {wstr:>5} ${it['price']:>6} {it['title']}")

    # TOP by Watchers
    with_watch = [it for it in items if it.get("watchers") and it["watchers"] > 0]
    with_watch.sort(key=lambda x: x["watchers"], reverse=True)
    print(f"\n--- TOP 10 by Watchers ({len(with_watch)} 件に watcher あり) ---")
    print(f"  {'watch':>5} {'views':>5} {'price':>7}  Title")
    for it in with_watch[:10]:
        print(f"  {it['watchers']:>5} {it['views']:>5} ${it['price']:>6} {it['title']}")

    # 死蔵 (views=0)
    dead = [it for it in items if it["views"] == 0]
    print(f"\n--- 死蔵候補 (views=0): {len(dead)} 件 / 全体 {len(items)} 件 = {len(dead)*100//len(items)}% ---")
    if dead:
        # 最初の 5件サンプル
        for it in dead[:5]:
            print(f"  ${it['price']:>6} #{it['item_id']} {it['title']}")
        if len(dead) > 5:
            print(f"  ... 他 {len(dead) - 5} 件")

    # Watcher/View 比率高い (購買意欲強)
    candidates = [it for it in items if it["views"] >= 10 and it.get("watchers")]
    candidates_sorted = sorted(
        candidates,
        key=lambda x: x["watchers"] / x["views"] if x["views"] else 0,
        reverse=True,
    )
    print(f"\n--- 購買意欲強 TOP 5 (views>=10, watch/view 比率順) ---")
    print(f"  {'watch%':>6} {'watch':>5} {'views':>5} {'price':>7}  Title")
    for it in candidates_sorted[:5]:
        ratio = it["watchers"] * 100 / it["views"] if it["views"] else 0
        print(f"  {ratio:>5.1f}% {it['watchers']:>5} {it['views']:>5} ${it['price']:>6} {it['title']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", choices=CATEGORY_KEYWORDS.keys(),
                        help="プリセットカテゴリで絞込")
    parser.add_argument("--keyword", type=str, default=None,
                        help="任意 keyword で絞込 (--category 優先)")
    parser.add_argument("--wait", type=int, default=18,
                        help="SPA hydration 待機秒数")
    parser.add_argument("--analyze", action="store_true",
                        help="分析モード (TOP Views/Watchers/死蔵候補/購買意欲)")
    parser.add_argument("--limit", type=int, default=20,
                        help="生 dump 時の表示件数上限 (--analyze なし時)")
    args = parser.parse_args()

    keyword = None
    label = "Active (all)"
    if args.category:
        keyword = CATEGORY_KEYWORDS[args.category]
        label = f"Active [{args.category}={keyword}]"
    elif args.keyword:
        keyword = args.keyword
        label = f"Active [keyword={keyword}]"

    driver = None
    try:
        driver = open_active(keyword, wait_seconds=args.wait)
        print(f"[INFO] page title: {driver.title}")
        print(f"[INFO] current url: {driver.current_url}")

        if "signin.ebay.com" in driver.current_url or "Sign in" in driver.title:
            print("[ERROR] eBay ログイン未完了 → iMakInventory --login で再ログイン")
            return 1

        items = extract_listings(driver)

        if args.analyze:
            analyze(items, label=label)
        else:
            print(f"\n=== {label}: {len(items)} listings ===")
            for i, it in enumerate(items[:args.limit], 1):
                w = it.get("watchers")
                wstr = str(w) if w is not None else "-"
                print(f"#{i:>3} views={it['views']:>4} watch={wstr:>3} ${it['price']:>6} {it['title']}")
        return 0
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
