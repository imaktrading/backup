#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ユニクロ公式の購入履歴 (商品一覧) を読む (2026-09-24)。注文 → 仕入れ の管理 (order_purchase_sync.py) が使う。

★ユーザー (2026-09-24): UT はユニクロ公式で仕入れる →「うん」(メルカリと同じく購入履歴から結ぶ)。
  仕入れアカウントでログインした **専用の Chrome (PROFILE)** で読む。ログインは人が手でした。

読むのは「商品一覧」(店舗・オンラインの両方) の1ページ目。窓なしだと直近5件しか出ない (2026-09-24 実測。
  下へ送っても増えない)。結べなかった注文はチェック無しのまま残る (間違った注文には結ばない)。
結び方: eBay の出品番号 → 在庫監視シート (F列 仕入元URL) の 商品番号 + 色 → 購入の 商品番号 + 色 + サイズ。

    python uniqlo_purchases.py --login    # ログインが切れた時 (窓でログインしたら自動で閉じる)
    python uniqlo_purchases.py            # 読めるかの確認
"""
from __future__ import annotations

import datetime as dt
import re
import time

try:                                     # 後片付けで uc が quit を2回呼び「ハンドルが無効」を出す (結果には無害)。
    import undetected_chromedriver as _uc   # こちらは必ず明示的に quit するので、GC 時の quit は止める
    _uc.Chrome.__del__ = lambda self: None
except Exception:                        # noqa: BLE001
    pass

PROFILE = r"C:\Users\imax2\local_data\iMakHQ\uniqlo_buyer_profile"
URL = "https://www.uniqlo.com/jp/ja/member/orders/products"
MONITOR_SHEET_ID = "101KL6KxMugKqZeSp2W5L2ykTvT0Zwd3RzlfsHgiJsg0"   # 在庫監視シート (iMakeBayAPI/inventory_monitor)
MONITOR_COL_ID, MONITOR_COL_URL = 2, 5                              # C 出品番号 / F 仕入元URL (0 始まり)


def parse_purchases(text):
    """購入履歴 (商品一覧) の画面の文字 → [{"pid", "color", "size", "day", "place", "name"}] (純関数)。"""
    lines = [x.strip() for x in (text or "").splitlines()]
    out = []
    for i, ln in enumerate(lines):
        m = re.match(r"商品番号[:：]\s*(\d{6})", ln)
        if not m:
            continue
        rec = {"pid": m.group(1), "name": lines[i - 1] if i else "", "color": "", "size": "", "day": None, "place": ""}
        for x in lines[i + 1:i + 6]:
            if x.startswith("カラー"):
                c = re.search(r"[:：]\s*(\d{2})", x)
                rec["color"] = c.group(1) if c else ""
            elif x.startswith("サイズ"):
                rec["size"] = x.split(":", 1)[-1].split("：", 1)[-1].strip()
            elif x.startswith("購入日"):
                d = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})", x)
                rec["day"] = dt.date(*map(int, d.groups())) if d else None
            elif x.startswith("購入場所"):
                rec["place"] = x.split(":", 1)[-1].split("：", 1)[-1].strip()
        out.append(rec)
    return out


def size_key(s):
    """'MEN XXL' / 'US XL(JP XXL)' / 'KIDS 140(10-11歳)' → 比べる形 ('XXL' / '140')。"""
    s = (s or "").upper()
    m = re.search(r"JP\s*([0-9A-Z]+)", s)                     # eBay の 'US XL(JP XXL)' は日本サイズで比べる
    if m:
        return m.group(1)
    s = re.sub(r"^(MEN|WOMEN|KIDS|BABY|UNISEX)\s+", "", s.strip())
    return re.split(r"[\s(（]", s)[0] if s else ""


def official_keys(urls):
    """在庫監視シートの仕入元 URL → {(商品番号, 色)} (純関数)。色が無い URL は色 ''。"""
    out = set()
    for u in urls:
        m = re.search(r"/products/E(\d{6})-\d{3}(?:/\d{2})?", u or "")
        if not m:
            continue
        c = re.search(r"colorDisplayCode=(\d{2})", u or "")
        out.add((m.group(1), c.group(1) if c else ""))
    return out


def match(orders, purchases):
    """注文の行と購入を結ぶ (純関数)。

    orders   : [(行番号, 注文日 date, {(商品番号, 色)}, サイズ key)]
    返り値   : {行番号: 購入}。1つの購入は1つの注文にだけ。注文日より前の購入は結ばない。
    色・サイズが分かっている時は一致を必須にする (同じ UT の色違い・サイズ違いを取り違えない)。
    """
    used, out = set(), {}
    buys = sorted((p for p in purchases if p.get("day")), key=lambda p: p["day"])
    for row, day, keys, size in sorted(orders, key=lambda o: (o[1], o[0])):
        for k, p in enumerate(buys):
            if k in used or p["day"] < day:
                continue
            ok_item = any(p["pid"] == pid and (not col or p["color"] == col) for pid, col in keys)
            if ok_item and (not size or size_key(p["size"]) == size):
                out[row] = p
                used.add(k)
                break
    return out


def monitor_urls():
    """在庫監視シート → {出品番号: [仕入元URL]} (I/O)。"""
    import gspread
    from google.oauth2.service_account import Credentials
    import sheet_io as S
    gc = gspread.authorize(Credentials.from_service_account_file(
        S.CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"]))
    sh = gc.open_by_key(MONITOR_SHEET_ID)
    ws = next((w for w in sh.worksheets() if w.title in ("メイン", "main", "Main", "Sheet1")), sh.get_worksheet(0))
    out = {}
    for r in ws.get_all_values()[1:]:
        if len(r) > MONITOR_COL_URL and r[MONITOR_COL_ID].strip() and "uniqlo.com" in r[MONITOR_COL_URL]:
            out.setdefault(r[MONITOR_COL_ID].strip(), []).append(r[MONITOR_COL_URL].strip())
    return out


def _driver(headless=True):
    import undetected_chromedriver as uc
    from mercari_psa_resource import _chrome_major, _quiet_chromedriver
    _quiet_chromedriver()
    o = uc.ChromeOptions()
    for a in (f"--user-data-dir={PROFILE}", "--lang=ja-JP", "--window-size=1280,1400"):
        o.add_argument(a)
    if headless:
        o.add_argument("--headless=new")
    maj = _chrome_major()
    return uc.Chrome(options=o, version_main=maj) if maj else uc.Chrome(options=o)


def fetch_purchases():
    """ログイン済みの専用 Chrome (窓なし) で読む (I/O)。ログインが切れていたら例外。"""
    d = _driver()
    try:
        d.get(URL)
        text, last = "", -1
        for _ in range(15):                                    # 件数が増えなくなるまで待つ (途中で読むと5件になる)
            time.sleep(2)
            d.execute_script("window.scrollTo(0, document.body.scrollHeight)")   # 下へ送ると続きが出る
            text = d.find_element("tag name", "body").text
            n = text.count("商品番号")
            if n and n == last:
                break
            last = n
        if "/member/orders" not in d.current_url:
            raise RuntimeError("ユニクロのログインが切れています")
        return parse_purchases(text)
    finally:
        d.quit()


def login():
    """ログインが切れた時に人が1回ログインする窓を開く (I/O)。購入履歴が出たら閉じる (最大15分)。"""
    d = _driver(headless=False)
    try:
        d.get(URL)
        for _ in range(90):
            time.sleep(10)
            if "/member/orders" in d.current_url and "商品番号" in d.find_element("tag name", "body").text:
                print("ログインできました")
                return True
        print("15分でログインが終わりませんでした")
        return False
    finally:
        d.quit()


if __name__ == "__main__":
    import sys
    if "--login" in sys.argv:
        sys.exit(0 if login() else 1)
    for p in fetch_purchases():
        print(p["day"], p["pid"], p["color"], p["size"], p["place"], p["name"][:30])
