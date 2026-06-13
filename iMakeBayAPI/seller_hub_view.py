"""seller_hub_view - eBay Seller Hub Active/Ended Listings 分析 + snapshot 保存ツール.

iMakInventory の chrome_profile_ebay (eBay ログイン状態 cookie 永続化済) を流用して
Selenium で Seller Hub にアクセスし、HTML から listing データを抽出 + 分析 + 保存する。

機能:
  - Active / Ended listings をカテゴリ別 (Porter / G-Shock / TCG / 一番くじ / Reel) で絞込
  - 15 項目を parse + 集計 + CSV snapshot 保存
  - 月次 snapshot 蓄積で View / Watchers 推移分析 (eBay 90日消失対策)

注意:
  - iMakInventory が cron で Chrome 起動中だと profile lock で失敗
  - 視覚要素 (画像本体) は取らない (無在庫モデルで写真は仕入元出品者所有)
  - 2FA 切れたら iMakInventory --login で再ログイン

使い方:
  python seller_hub_view.py --category porter
  python seller_hub_view.py --category porter --analyze
  python seller_hub_view.py --category porter --status ended --save
  python seller_hub_view.py --status active --save        # 全件 snapshot
  python seller_hub_view.py --keyword "PSA 10" --analyze
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By

from chrome_util import detect_chrome_major  # uc version_main を実Chromeから検出 (数値ハードコード禁止)

EBAY_CHROME_PROFILE_DIR = r"C:\Users\imax2\local_data\iMakInventory\chrome_profile_ebay"
SNAPSHOT_DIR = r"C:\dev\iMak_data\seller_hub"

CATEGORY_KEYWORDS = {
    "porter":      "Porter",
    "gshock":      "G-Shock",
    "tcg":         "PSA 10",
    "ichibankuji": "Ichiban Kuji",
    "reel":        "Fishing Reel",
}

URL_BASE = {
    "active": "https://www.ebay.com/sh/lst/active",
    "ended":  "https://www.ebay.com/sh/lst/ended",
}

CSV_FIELDS = [
    "snapshot_date",
    "status",
    "item_id",
    "sku",
    "title",
    "price_usd",
    "price_raw",        # 元通貨表記 (US $189 / AU $200 / EUR €100 等)
    "listing_site",     # US / AU / UK / DE / FR / IT / ES / JP / EU / unknown (5/12 cross-listing 拡大想定)
    "views",
    "watchers",
    "quantity_available",
    "listed_date",
    "ended_date",
    "promoted_rate",
    "format",
    "best_offer_enabled",
    "search_keyword",
]


# 通貨表記 → site code マッピング
CURRENCY_TO_SITE = {
    "US": "US",
    "AU": "AU",
    "C": "CA",     # CA $
    "GBP": "UK",
    "EUR": "EU",   # DE/FR/IT/ES/NL... 個別判定は別 source 必要
    "JPY": "JP",
    "HK": "HK",
}


def open_listing_page(status: str, keyword: str | None, wait_seconds: int = 18,
                       site: str | None = None):
    """site: 'US' or None (= 全 site).

    eBay Seller Hub の Marketplaces filter URL パラメータ:
      sites=0 → US, sites=3 → UK, sites=15 → AU, sites=77 → DE, etc.
    """
    url = URL_BASE[status]
    params = []
    if keyword:
        params.append(f"keyword={keyword.replace(' ', '+')}")
    if site == "US":
        params.append("sites=0")
        params.append("source=filterbar")
        params.append("action=search")
    if params:
        url = f"{url}?{'&'.join(params)}"
    options = uc.ChromeOptions()
    options.add_argument(f"--user-data-dir={EBAY_CHROME_PROFILE_DIR}")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    driver = uc.Chrome(options=options, version_main=detect_chrome_major())
    print(f"[INFO] open: {url}")
    driver.get(url)
    time.sleep(wait_seconds)
    return driver


def parse_listing_row(row_text: str, status: str = "active",
                       search_keyword: str = "",
                       snapshot_date: str = "") -> dict:
    """row.text から listing 情報を抽出 (15 項目)."""
    lines = [l for l in row_text.strip().split("\n") if l.strip()]
    out = {f: "" for f in CSV_FIELDS}
    out["status"] = status
    out["search_keyword"] = search_keyword
    out["snapshot_date"] = snapshot_date

    if len(lines) < 5:
        return out
    # Title: Active は lines[1]、Ended は lines[1] = "出品<Title>" / lines[2] = 純 Title
    # status=ended で「出品」prefix がある場合は次の line を使う
    title = lines[1]
    if status == "ended" and title.startswith("出品") and len(lines) > 2:
        title = lines[2]
    # prefix 除去 (念のため両対応)
    if title.startswith("出品"):
        title = title[len("出品"):].strip()
    out["title"] = title[:200]

    # ItemID (12桁数字)
    for L in lines:
        m = re.search(r"(\d{12})", L)
        if m:
            out["item_id"] = m.group(1)
            break

    # Price 抽出: 通貨記号から site 判定 + price_usd は USD のみ
    # eBay Seller Hub の表示: "US $189.98" / "AU $200" / "EUR €100" / "£50" / "JPY 1500" 等
    for L in lines:
        # USD
        m = re.search(r"US\s*\$([0-9,.]+)", L)
        if m:
            out["price_usd"] = m.group(1)
            out["price_raw"] = L.strip()
            out["listing_site"] = "US"
            break
        # AUD
        m = re.search(r"AU\s*\$([0-9,.]+)", L)
        if m:
            out["price_raw"] = L.strip()
            out["listing_site"] = "AU"
            break
        # CAD
        m = re.search(r"C\s*\$([0-9,.]+)", L)
        if m:
            out["price_raw"] = L.strip()
            out["listing_site"] = "CA"
            break
        # GBP
        m = re.search(r"£([0-9,.]+)", L)
        if m:
            out["price_raw"] = L.strip()
            out["listing_site"] = "UK"
            break
        # EUR
        m = re.search(r"(?:EUR|€)\s*([0-9,.]+)", L)
        if m:
            out["price_raw"] = L.strip()
            out["listing_site"] = "EU"
            break
        # その他通貨 (HK $/SGD/etc) は後で拡張可
    # US fallback (5/17 追加): 既存 prefix 判定で unknown だった listing を救済.
    # eBay US listing で "US " prefix なし "$XX.XX" or 範囲表示 "$XX.XX to $YY.YY"
    # 形式の listing を US と判定 (= 他通貨記号が一切ない行のみ).
    if not out["listing_site"]:
        for L in lines:
            if "$" not in L:
                continue
            if any(c in L for c in ("AU", "C$", "£", "€", "EUR", "JPY", "HK", "SGD")):
                continue
            m = re.search(r"\$\s*([0-9,.]+)", L)
            if m:
                out["price_usd"] = m.group(1)
                out["price_raw"] = L.strip()
                out["listing_site"] = "US"
                break
    if not out["listing_site"]:
        out["listing_site"] = "unknown"

    # SKU: ItemID 行の次行 (英数字、数字単独除く、長さ制限なし)
    # zaiko / m12345 / 短い custom label 等も拾うため文字数制限を撤廃 (5/13)
    for i, L in enumerate(lines):
        if re.search(r"\d{12}", L):
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if re.fullmatch(r"[A-Za-z0-9_-]+", next_line) and not next_line.isdigit():
                    out["sku"] = next_line
            break

    # Views (regex 確実マッチ、日本語 + 英語 両対応)
    # 5/17 観測: eBay UI 英語化で「ビュー数」label 消失、Views N or N Views 等
    m = re.search(r"(?:ビュー数|Views?)\s*[:\s]*(\d+)", row_text, re.IGNORECASE)
    if not m:
        m = re.search(r"(\d+)\s+Views?\b", row_text, re.IGNORECASE)
    if m:
        out["views"] = m.group(1)

    # 数字 line 配置 (UI 言語で異なる、item_id 12桁は除外):
    # - 日本語 UI: num_lines = [0, qty, watchers, 0] の常に 4 件 (= 5/29 dump 検証済)
    #   [0] = ad/offer flag? [3] = ad/priority flag? いずれも 0 default
    #   views は "ビュー数N" regex で別途取得済
    # - 英語 UI (5/17 確認): [0]=Offer, [1]=qty, [2]=Views, [3]=Watchers
    # 判別: 日本語 UI なら regex で views 既に取得済 → out["views"] not empty
    num_lines = [l.strip() for l in lines if re.fullmatch(r"\d{1,5}", l.strip())]
    if out.get("views"):
        # 日本語 UI (= "ビュー数N" regex hit)
        if len(num_lines) >= 3:
            out["quantity_available"] = num_lines[1]
            out["watchers"] = num_lines[2]
        elif len(num_lines) == 2:
            # 想定外 fallback
            out["quantity_available"] = num_lines[0]
            out["watchers"] = num_lines[1]
        elif len(num_lines) == 1:
            out["watchers"] = num_lines[0]
    else:
        # 英語 UI (= ラベルなし、数字単独で 4 件並ぶ)
        if len(num_lines) >= 4:
            out["quantity_available"] = num_lines[1]
            out["views"] = num_lines[2]
            out["watchers"] = num_lines[3]
        elif len(num_lines) == 3:
            out["quantity_available"] = num_lines[1]
            out["views"] = num_lines[2]
            out["watchers"] = "0"
        elif len(num_lines) == 2:
            out["quantity_available"] = num_lines[1]
            out["watchers"] = "0"
        elif len(num_lines) == 1:
            out["quantity_available"] = num_lines[0]
            out["watchers"] = "0"

    # Format (今すぐ買う / オークション / Best Offer)
    if "今すぐ買う" in row_text:
        out["format"] = "BIN"
    elif "オークション" in row_text or "Auction" in row_text:
        out["format"] = "Auction"

    # Best Offer
    if "ベストオファー" in row_text or "Best Offer" in row_text:
        out["best_offer_enabled"] = "yes"
    else:
        out["best_offer_enabled"] = "no"

    # Promoted rate (例: "お客様の広告費率： 7%")
    m = re.search(r"広告費率[:\s：]*([0-9.]+)\s*%", row_text)
    if m:
        out["promoted_rate"] = m.group(1)

    # Listed date / Ended date
    # 旧形式: "5 11, 2026, 14:55 PDT"
    # 新形式 (5/17 観測): "May 11, 2026" / "May 10, 2025, 14:55 PDT" 等の月名表記
    _MONTH = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,
              "Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}
    mo = d = y = None
    # 新形式 (= 月名)
    m = re.search(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),\s+(20\d{2})", row_text)
    if m:
        mo, d, y = _MONTH[m.group(1)], int(m.group(2)), int(m.group(3))
    else:
        # 旧形式 fallback (= 数字 数字)
        m = re.search(r"\b(\d{1,2})\s+(\d{1,2}),\s+(20\d{2}),\s+\d{1,2}:\d{2}\s+P[DS]T", row_text)
        if m:
            try:
                mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            except Exception:
                pass
    if mo and d and y and 1 <= mo <= 12 and 1 <= d <= 31:
        date_str = f"{y:04d}-{mo:02d}-{d:02d}"
        if status == "ended":
            out["ended_date"] = date_str
        else:
            out["listed_date"] = date_str

    return out


def extract_listings(driver, status: str = "active",
                      search_keyword: str = "",
                      snapshot_date: str | None = None) -> list[dict]:
    if snapshot_date is None:
        snapshot_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = driver.find_elements(By.CSS_SELECTOR, "tr.grid-row")
    items = []
    for r in rows:
        try:
            parsed = parse_listing_row(r.text, status=status,
                                       search_keyword=search_keyword,
                                       snapshot_date=snapshot_date)
            # tr.data-id attribute から item_id を確実に取得 (Ended は text に無いため)
            if not parsed["item_id"]:
                data_id = r.get_attribute("data-id") or ""
                if re.fullmatch(r"\d{10,15}", data_id):
                    parsed["item_id"] = data_id
            # 5/29: watchers は専用 td (= shui-dt-column__watchCount) で取得
            # row.text には含まれないため td-level CSS selector で override
            try:
                _wc = r.find_element(By.CSS_SELECTOR, "td.shui-dt-column__watchCount")
                _wt = (_wc.text or "").strip()
                if re.fullmatch(r"\d+", _wt):
                    parsed["watchers"] = _wt
            except Exception:
                pass
            if parsed["item_id"]:
                items.append(parsed)
        except Exception:
            continue
    return items


def fetch_all_pages(driver, status: str = "active",
                    search_keyword: str = "",
                    page_wait: int = 8,
                    max_pages: int = 50) -> list[dict]:
    """`.pagination__next` をクリックしながら全ページ取得 + item_id デドゥープ.

    各ページで:
      1. extract_listings で grid-row を parse
      2. Next ボタン find → enabled なら click → wait → 次 page
      3. Next なし / disabled で break
    """
    snapshot_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    all_items: list[dict] = []
    page = 1
    while page <= max_pages:
        items = extract_listings(driver, status=status,
                                  search_keyword=search_keyword,
                                  snapshot_date=snapshot_date)
        all_items.extend(items)
        print(f"[INFO] page {page}: {len(items)} items, cumulative {len(all_items)}")

        # Next ボタン 試行
        try:
            next_btns = driver.find_elements(By.CSS_SELECTOR, ".pagination__next")
            if not next_btns:
                print("[INFO] Next button なし → 最終ページ")
                break
            next_btn = next_btns[0]
            if not next_btn.is_enabled() or next_btn.get_attribute("aria-disabled") == "true":
                print("[INFO] Next button disabled → 最終ページ")
                break
            # Click via JavaScript で安定化 (重なり Element ハック回避)
            driver.execute_script("arguments[0].click();", next_btn)
            time.sleep(page_wait)
            page += 1
        except Exception as e:
            print(f"[WARN] Next click 失敗: {e}")
            break

    # ItemID 単位デドゥープ (同 listing が複数 page で出る可能性低だが念のため)
    seen = set()
    uniq = []
    for it in all_items:
        if it["item_id"] not in seen:
            seen.add(it["item_id"])
            uniq.append(it)
    print(f"[INFO] 全 {page} page 処理完了、unique {len(uniq)} listings")
    return uniq


def analyze(items: list[dict], label: str = "Active") -> None:
    print(f"\n=== {label}: {len(items)} listings ===\n")
    if not items:
        return

    def _int(v):
        try: return int(v)
        except: return 0

    by_views = sorted(items, key=lambda x: _int(x["views"]), reverse=True)
    print(f"--- TOP 15 by Views ---")
    print(f"  {'views':>5} {'watch':>5} {'price':>7}  Title")
    for it in by_views[:15]:
        print(f"  {_int(it['views']):>5} {_int(it['watchers']):>5} ${it['price_usd']:>6} {it['title'][:60]}")

    with_watch = [it for it in items if _int(it["watchers"]) > 0]
    with_watch.sort(key=lambda x: _int(x["watchers"]), reverse=True)
    print(f"\n--- TOP 10 by Watchers ({len(with_watch)} 件に watcher あり) ---")
    print(f"  {'watch':>5} {'views':>5} {'price':>7}  Title")
    for it in with_watch[:10]:
        print(f"  {_int(it['watchers']):>5} {_int(it['views']):>5} ${it['price_usd']:>6} {it['title'][:60]}")

    dead = [it for it in items if _int(it["views"]) == 0]
    print(f"\n--- 死蔵候補 (views=0): {len(dead)} 件 / 全体 {len(items)} 件 = {len(dead)*100//len(items)}% ---")
    for it in dead[:5]:
        print(f"  ${it['price_usd']:>6} #{it['item_id']} {it['title'][:60]}")
    if len(dead) > 5:
        print(f"  ... 他 {len(dead) - 5} 件")

    candidates = [it for it in items if _int(it["views"]) >= 10 and _int(it["watchers"]) > 0]
    candidates_sorted = sorted(candidates,
        key=lambda x: _int(x["watchers"]) / _int(x["views"]) if _int(x["views"]) else 0,
        reverse=True)
    print(f"\n--- 購買意欲強 TOP 5 (views>=10, watch/view 比率順) ---")
    print(f"  {'watch%':>6} {'watch':>5} {'views':>5} {'price':>7}  Title")
    for it in candidates_sorted[:5]:
        v, w = _int(it["views"]), _int(it["watchers"])
        ratio = w * 100 / v if v else 0
        print(f"  {ratio:>5.1f}% {w:>5} {v:>5} ${it['price_usd']:>6} {it['title'][:60]}")


def save_to_csv(items: list[dict], status: str, keyword: str | None) -> str:
    r"""snapshot CSV を C:\dev\iMak_data\seller_hub\ に保存."""
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    cat = keyword.replace(" ", "_").lower() if keyword else "all"
    out_path = os.path.join(SNAPSHOT_DIR, f"snapshot_{status}_{cat}_{ts}.csv")
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, quoting=csv.QUOTE_NONNUMERIC)
        w.writeheader()
        for it in items:
            w.writerow({k: it.get(k, "") for k in CSV_FIELDS})
    return out_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", choices=CATEGORY_KEYWORDS.keys(),
                        help="プリセットカテゴリで絞込")
    parser.add_argument("--keyword", type=str, default=None,
                        help="任意 keyword で絞込 (--category 優先)")
    parser.add_argument("--status", choices=["active", "ended"], default="active",
                        help="Active or Ended (default: active)")
    parser.add_argument("--wait", type=int, default=18,
                        help="SPA hydration 待機秒数")
    parser.add_argument("--analyze", action="store_true",
                        help="分析モード (TOP Views/Watchers/死蔵候補/購買意欲)")
    parser.add_argument("--save", action="store_true",
                        help=f"snapshot CSV を {SNAPSHOT_DIR} に保存")
    parser.add_argument("--all-pages", action="store_true",
                        help="ページ送りで全件取得 (Ended 1011件等の全 page 取得)")
    parser.add_argument("--limit", type=int, default=20,
                        help="生 dump 時の表示件数上限 (--analyze なし時)")
    parser.add_argument("--site", choices=["US"], default=None,
                        help="Marketplaces filter (= US 指定で sites=0 → US 限定 scrape)")
    args = parser.parse_args()

    keyword = None
    label = f"{args.status} (all)"
    if args.category:
        keyword = CATEGORY_KEYWORDS[args.category]
        label = f"{args.status} [{args.category}={keyword}]"
    elif args.keyword:
        keyword = args.keyword
        label = f"{args.status} [keyword={keyword}]"

    driver = None
    try:
        driver = open_listing_page(args.status, keyword, wait_seconds=args.wait,
                                     site=args.site)
        print(f"[INFO] page title: {driver.title}")
        print(f"[INFO] current url: {driver.current_url}")

        if "signin.ebay.com" in driver.current_url or "Sign in" in driver.title:
            print("[ERROR] eBay ログイン未完了 → iMakInventory --login で再ログイン")
            return 1

        if args.all_pages:
            items = fetch_all_pages(driver, status=args.status,
                                     search_keyword=keyword or "")
        else:
            items = extract_listings(driver, status=args.status,
                                     search_keyword=keyword or "")

        if args.analyze:
            analyze(items, label=label)
        else:
            print(f"\n=== {label}: {len(items)} listings ===")
            for i, it in enumerate(items[:args.limit], 1):
                print(f"#{i:>3} views={it['views']:>4} watch={it['watchers']:>3} qty={it['quantity_available']:>2} ${it['price_usd']:>6} {it['title'][:80]}")

        if args.save:
            path = save_to_csv(items, args.status, keyword)
            print(f"\n[SAVE] snapshot CSV: {path}")
            print(f"[SAVE] 保存 {len(items)} listings")

        return 0
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
