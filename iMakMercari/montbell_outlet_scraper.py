#!/usr/bin/env python3
"""モンベル公式アウトレット スクレイパー
全カテゴリを巡回 → 商品ID + サイズ×カラー在庫マトリクスを取得
→ Google Sheet（管理シート）とローカルCSVに出力

使い方:
  python montbell_outlet_scraper.py                    # 全カテゴリ、スプシ書込み
  python montbell_outlet_scraper.py --categories 2,5   # 特定カテゴリのみ
  python montbell_outlet_scraper.py --limit 10         # 各カテゴリ先頭N商品のみ
  python montbell_outlet_scraper.py --no-sheet         # スプシ書込せずCSVのみ
"""
import csv
import os
import re
import sys
import time
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "..", "iMakHQ", "csv_output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE_URL = "https://webshop.montbell.jp"
OUTLET_TOP = f"{BASE_URL}/outlet/"

# 管理シート（Google Sheet）
SHEET_ID = "1LDlJuEbqy3wmwRSlTqgCzqcZxzu8phO4PITm7nYRoNw"
SHEET_GID = 851100680
GSHEET_CREDS = os.path.join(SCRIPT_DIR, "..", "double-hold-421922-7c0d38d3f73d.json")

# 列マッピング（既存15列 + 拡張4列 = 19列）
COL_MAP = {
    "URL": 1, "itemID": 2, "タイトル": 3, "売り切れ": 4, "状態": 5,
    "商品価格": 6, "写真URL": 7, "商品説明": 8, "Title": 9, "Description": 10,
    "出品する価格（ドル）": 11, "ConditionID": 12, "価格上昇有無": 13,
    "仕入れ価格（円）": 14, "売り切れチェック時間": 15,
    "サイズ": 16, "カラー": 17, "在庫数": 18, "商品ID": 19,
    "取下げ推奨": 20,
}


def _open_sheet():
    """管理シートを開く。"""
    import gspread
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_file(
        GSHEET_CREDS, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SHEET_ID)
    return sh.get_worksheet_by_id(SHEET_GID)


def _load_existing_keys(ws):
    """既存行の (商品ID, サイズ, カラー) キーをロード。重複防止・更新用。"""
    all_vals = ws.get_all_values()
    keys = {}  # key -> row_index (1-based)
    for i, row in enumerate(all_vals[1:], start=2):  # 2行目から
        if len(row) < max(COL_MAP["商品ID"], COL_MAP["サイズ"], COL_MAP["カラー"]):
            continue
        pid = row[COL_MAP["商品ID"] - 1] if len(row) >= COL_MAP["商品ID"] else ""
        sz = row[COL_MAP["サイズ"] - 1] if len(row) >= COL_MAP["サイズ"] else ""
        co = row[COL_MAP["カラー"] - 1] if len(row) >= COL_MAP["カラー"] else ""
        if pid and sz and co:
            keys[(pid, sz, co)] = i
    return keys


def _mark_takedown(ws, failed_product_ids):
    """指定商品IDの既存行すべてに「取下げ推奨=○」をマーク。"""
    all_vals = ws.get_all_values()
    updates = []
    col_pid = COL_MAP["商品ID"]
    col_td = COL_MAP["取下げ推奨"]
    col_td_letter = chr(ord('A') + col_td - 1)  # T列 = 20
    for i, row in enumerate(all_vals[1:], start=2):
        if len(row) >= col_pid:
            pid = row[col_pid - 1]
            if pid in failed_product_ids:
                updates.append({
                    "range": f"{col_td_letter}{i}",
                    "values": [["○"]],
                })
    if updates:
        ws.batch_update(updates)
    return len(updates)


def _upsert_rows(ws, rows):
    """新規は追記、既存は該当行を更新。rows: list of dict。"""
    existing = _load_existing_keys(ws)
    new_rows = []
    updates = []  # [(row_idx, values_list)]
    for r in rows:
        key = (r["商品ID"], r["サイズ"], r["カラー"])
        record = [r.get(col, "") for col in COL_MAP.keys()]
        if key in existing:
            updates.append((existing[key], record))
        else:
            new_rows.append(record)

    # 既存行更新（バッチ）
    if updates:
        batch = []
        for row_idx, record in updates:
            end_col = chr(ord('A') + len(record) - 1)
            batch.append({
                "range": f"A{row_idx}:{end_col}{row_idx}",
                "values": [record],
            })
        ws.batch_update(batch)
    # 新規行追加
    if new_rows:
        ws.append_rows(new_rows, value_input_option="USER_ENTERED")
    return len(new_rows), len(updates)


def _make_driver():
    import undetected_chromedriver as uc
    opts = uc.ChromeOptions()
    opts.add_argument("--lang=ja-JP")
    opts.add_argument("--window-size=1400,900")
    return uc.Chrome(options=opts)


def get_outlet_categories(driver):
    """アウトレットトップから主要カテゴリIDを取得。"""
    driver.get(OUTLET_TOP)
    time.sleep(6)
    from selenium.webdriver.common.by import By
    links = driver.find_elements(By.CSS_SELECTOR, "a[href*='category_fo.php']")
    cats = {}
    for a in links:
        href = a.get_attribute("href") or ""
        m = re.search(r'category=(\d+)', href)
        name = a.text.strip()[:50]
        if m and name:
            cid = int(m.group(1))
            cats[cid] = name
    return cats


def get_products_in_category(driver, cat_id):
    """category_fo.phpページ経由でlist_fo.phpのサブカテゴリを探し、商品IDを収集。"""
    from selenium.webdriver.common.by import By
    driver.get(f"{BASE_URL}/goods/category_fo.php?category={cat_id}")
    time.sleep(5)
    # list_fo.php へのリンク取得
    list_urls = set()
    for a in driver.find_elements(By.CSS_SELECTOR, "a[href*='list_fo.php']"):
        href = a.get_attribute("href") or ""
        m = re.search(r'category=(\d+)', href)
        if m:
            list_urls.add(f"{BASE_URL}/goods/list_fo.php?category={m.group(1)}")
    # 各list_fo.phpを訪問して商品ID抽出
    product_ids = set()
    for lurl in list_urls:
        driver.get(lurl)
        time.sleep(4)
        for _ in range(3):
            driver.execute_script("window.scrollBy(0, 800)")
            time.sleep(0.8)
        imgs = driver.find_elements(By.CSS_SELECTOR, "img[src*='prod_s']")
        for im in imgs:
            src = im.get_attribute("src") or ""
            m = re.search(r's_(\d+)_', src)
            if m:
                product_ids.add(m.group(1))
    return sorted(product_ids)


def get_product_inventory(driver, product_id):
    """商品詳細ページから size × color 在庫マトリクスを取得。
    戻り値: {
      "product_id": ...,
      "name": "商品名",
      "price": "¥9,900",
      "sizes": ["XS","S","M","L","XL"],
      "colors": ["BL","DGN","GRBL","WT"],
      "stock": {"XS_BL": 20, "XS_DGN": 0, ...}
    }
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select
    url = f"{BASE_URL}/goods/disp.php?product_id={product_id}"
    driver.get(url)
    time.sleep(5)

    # 商品名: ページタイトルから抽出
    title = driver.title.replace("モンベル", "").replace("｜", "").replace("オンラインストア", "").strip()

    # 価格: 最初の¥XX,XXX
    html = driver.page_source
    prices = re.findall(r'¥([\d,]+)', html)
    price = f"¥{prices[0]}" if prices else ""

    # all_color input
    try:
        color_input = driver.find_element(By.CSS_SELECTOR, "input[name='all_color']")
        colors = [c for c in (color_input.get_attribute("value") or "").split(",") if c]
    except Exception:
        colors = []

    # サイズはselectのname属性から逆引き
    sizes = []
    stock = {}
    for sel_el in driver.find_elements(By.CSS_SELECTOR, "select[name$='_num']"):
        name = sel_el.get_attribute("name") or ""
        m = re.match(r'^([A-Z0-9]+)_([A-Z0-9]+)_num$', name)
        if not m:
            continue
        sz, co = m.group(1), m.group(2)
        if sz not in sizes:
            sizes.append(sz)
        try:
            sel = Select(sel_el)
            options = [opt.get_attribute("value") for opt in sel.options if opt.get_attribute("value")]
            digits = [int(o) for o in options if o.isdigit()]
            stock[f"{sz}_{co}"] = max(digits) if digits else 0
        except Exception:
            stock[f"{sz}_{co}"] = None

    return {
        "product_id": product_id,
        "url": url,
        "name": title,
        "price": price,
        "sizes": sizes,
        "colors": colors,
        "stock": stock,
    }


def parse_args(argv):
    limit = None
    categories = None
    no_sheet = False
    for i, a in enumerate(argv):
        if a == "--limit" and i + 1 < len(argv):
            try: limit = int(argv[i+1])
            except: pass
        if a == "--categories" and i + 1 < len(argv):
            try: categories = [int(x) for x in argv[i+1].split(",") if x]
            except: pass
        if a == "--no-sheet":
            no_sheet = True
    return limit, categories, no_sheet


def main():
    limit, categories, no_sheet = parse_args(sys.argv)
    print("=== モンベル公式アウトレット スクレイパー ===\n")
    driver = _make_driver()
    try:
        if categories is None:
            print("カテゴリ一覧取得中...")
            cats = get_outlet_categories(driver)
            print(f"カテゴリ数: {len(cats)}")
        else:
            cats = {c: f"(ID:{c})" for c in categories}

        all_rows = []
        # スクレイプ失敗した商品IDを記録 → 既存行に「取下げ推奨」フラグ
        failed_products = []
        for cid, cname in cats.items():
            print(f"\n=== カテゴリ {cid} ({cname}) ===")
            try:
                pids = get_products_in_category(driver, cid)
                if limit is not None:
                    pids = pids[:limit]
                print(f"  商品: {len(pids)}件")
                for pid in pids:
                    try:
                        info = get_product_inventory(driver, pid)
                        # サニティチェック: サイズ/カラーが取得できなかった = HTML構造変化の可能性
                        if not info["sizes"] or not info["colors"]:
                            print(f"    ⚠️ [{pid}] サイズ/カラー取得失敗 → 取下げ推奨フラグ")
                            failed_products.append(pid)
                            continue
                        print(f"  [{pid}] {info['name'][:40]:40s} {info['price']} sizes={len(info['sizes'])} colors={len(info['colors'])}")
                        # サイズ×カラー別に1行ずつ追加
                        for sz in info["sizes"]:
                            for co in info["colors"]:
                                key = f"{sz}_{co}"
                                s = info["stock"].get(key, None)
                                # スプシ列構造に合わせたレコード（COL_MAPキー準拠）
                                all_rows.append({
                                    "URL": info["url"],
                                    "itemID": "",  # eBay出品後に記入
                                    "タイトル": f"{info['name']} {sz} {co}",
                                    "売り切れ": "○" if s == 0 else "",
                                    "状態": "新品（アウトレット）",
                                    "商品価格": info["price"],
                                    "写真URL": "",
                                    "商品説明": "",
                                    "Title": "",
                                    "Description": "",
                                    "出品する価格（ドル）": "",
                                    "ConditionID": "1000",
                                    "価格上昇有無": "",
                                    "仕入れ価格（円）": info["price"].replace("¥","").replace(",","") if info["price"] else "",
                                    "売り切れチェック時間": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    "サイズ": sz,
                                    "カラー": co,
                                    "在庫数": str(s) if s is not None else "",
                                    "商品ID": pid,
                                })
                        time.sleep(1)
                    except Exception as e:
                        print(f"    ERROR product {pid}: {e} → 取下げ推奨")
                        failed_products.append(pid)
            except Exception as e:
                print(f"  ERROR category {cid}: {e}")

        # 出力
        if all_rows:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            # CSV（バックアップ用）
            out = os.path.join(OUTPUT_DIR, f"montbell_outlet_inventory_{ts}.csv")
            with open(out, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
                writer.writeheader()
                writer.writerows(all_rows)
            print(f"\n✅ CSV出力: {out}")
            print(f"   行数: {len(all_rows)} (SKU数)")
            sold = sum(1 for r in all_rows if r["売り切れ"] == "○")
            print(f"   売切れ SKU: {sold}")

            # Google Sheet 書込
            if not no_sheet:
                try:
                    print("\n📤 スプシに書込中...")
                    ws = _open_sheet()
                    added, updated = _upsert_rows(ws, all_rows)
                    print(f"✅ スプシ更新完了: 新規{added}行 / 既存更新{updated}行")
                    # 失敗商品に「取下げ推奨」マーク
                    if failed_products:
                        print(f"\n⚠️ 取下げ推奨マーク付与: {len(failed_products)}商品")
                        _mark_takedown(ws, failed_products)
                except Exception as e:
                    print(f"⚠️ スプシ書込失敗（CSVは保存済）: {e}")
            else:
                print("   (--no-sheet指定のためスプシ書込スキップ)")
        else:
            print("\n対象データなし")
    finally:
        try: driver.quit()
        except: pass


if __name__ == "__main__":
    main()
