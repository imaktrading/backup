#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""注文 → 仕入れ の管理 (2026-09-24)。【NEW】販売実績 に注文を自動で足し、仕入れの列を持たせる。

★ユーザー (2026-09-24):「オーダーに対して仕入が出来ているかどうかを一覧で管理したい。仕入漏れを防ぐために」
  判定 = 手でチェック / 置き場所 = 販売実績シート / 注文の行は自動で足してよい (以後 行は手で足さない)。

やること (1回の走行で):
  1. eBay の注文 (直近 DAYS 日) を読み、販売実績に **無い注文番号** を行として足す
     (NO. / 商品ID / 商品名 / 注文番号 / 販売日 / country / 商品価格 / 営業利益の式 / カテゴリ)。
     手数料・仕入原価・追跡番号などは **今までどおり手で入れる**。
  2. 右に仕入れの列を持つ (V〜Z。U は手のメモが入っているので触らない):
       V 仕入済 (チェック欄) / W 仕入日 / X 買った先URL (メルカリの購入履歴から自動)
       Y 発送期限 (eBay) / Z 注文の状態 (未発送 / 発送済 / キャンセル / 返金。eBay から毎回更新)
  2b. メルカリの購入履歴 (mercari_purchases.py) を読み、売れた出品の仕入元・補URL と一致する購入があれば
      X に買った先・V にチェック・W に購入日を自動で入れる。候補に無い URL で買った分は手でチェック。
      ★2026-09-24 ユーザー「補も含めて最安を改めて探すから、どこの URL を入れているのかわからん」:
        以前は X に商品管理シートの A列を入れていたが、実際に買った先と違うので **買った先だけ** にした。
  3. 仕入れ待ち (V 未チェック かつ Z=未発送) を赤く塗り、件数を STATUS に書く (コンソールの知らせ)。

安全のため:
  - 足すのは **支払い済み・キャンセルでない** 注文だけ。足す前に表の注文番号を読み直して二重にしない
  - 既存の行で書くのは V〜Z だけ (手で入れた列 A〜U は触らない。例外: 足す行そのもの)
  - 足し始めは START_DATE 以降の注文 (それより前は手で入れてある)

    python order_purchase_sync.py            # 何をするかだけ出す
    python order_purchase_sync.py --write    # 書く
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r"C:\dev\iMak\iMakeBayAPI")

SALES_SHEET_ID = "1MufEUweIJcLv-NwT3KZsEJ_k_yl1rKryaqBZjUH7c2U"
SALES_GID = 1814510799                    # 販売実績
DAYS = 60
# 手で入れてある最後の注文は 2026/09/12 (NO.139)。それより後に作られた注文から足す。
# ★実測 (2026-09-24): 9/2・9/3・9/19 の注文も表に無かった。手で入れていない分も足すため、
#   足し始めを 9/1 にした (表にある注文番号は二重に足さない)。
START_DATE = dt.date(2026, 9, 1)
STATUS = r"C:/dev/iMak_data/hq/order_purchase_status.json"
JST = dt.timezone(dt.timedelta(hours=9))

# 0 始まりの列番号
C_NO, C_ITEM, C_TITLE, C_ORDER, C_DATE, C_COUNTRY, C_PRICE = 0, 1, 2, 3, 4, 5, 6
C_SHIP, C_TAX, C_FEE, C_AD, C_NET = 7, 8, 9, 10, 11
C_COST, C_TRACK, C_CAT = 12, 13, 17
C_DONE, C_DONE_AT, C_URL, C_SHIPBY, C_STATE = 21, 22, 23, 24, 25     # V W X Y Z
HEAD = ["仕入済", "仕入日", "買った先URL", "発送期限", "注文の状態"]

COUNTRY = {
    "US": "United States", "GB": "United Kingdom", "AU": "Australia", "DE": "Germany",
    "CA": "Canada", "IT": "Italy", "KR": "South Korea", "SA": "Saudi Arabia", "IL": "Israel",
    "BE": "Belgium", "GR": "Greece", "NO": "Norway", "DK": "Denmark", "AT": "Austria",
    "MX": "Mexico", "SG": "Singapore", "KW": "Kuwait", "IS": "Iceland", "ID": "Indonesia",
    "TW": "Taiwan", "PH": "Philippines", "FR": "France", "ES": "Spain", "NL": "Netherlands",
    "CH": "Switzerland", "SE": "Sweden", "FI": "Finland", "IE": "Ireland", "PT": "Portugal",
    "PL": "Poland", "NZ": "New Zealand", "HK": "Hong Kong", "MY": "Malaysia", "TH": "Thailand",
    "AE": "United Arab Emirates", "QA": "Qatar", "BH": "Bahrain", "CN": "China", "JP": "Japan",
    "BR": "Brazil", "CL": "Chile", "CZ": "Czech Republic", "HU": "Hungary", "RO": "Romania",
    "LU": "Luxembourg", "OM": "Oman", "VN": "Vietnam", "IN": "India",
}


# ---------------------------------------------------------------- 純関数
def norm_order(s):
    """表の注文番号は頭に改行が入っているもの有り ('\\r\\n24-15079-01897')。"""
    return re.sub(r"\s", "", s or "")


def category_of(title):
    """表の「カテゴリ」列と同じ呼び名。分からなければ '' (手で入れる)。"""
    t = (title or "").upper()
    if "PSA" in t:
        return "TCG"
    if "G-SHOCK" in t or "GSHOCK" in t or "CASIO" in t:
        return "G-shock"
    if "ICHIBAN KUJI" in t:
        return "一番くじ"
    if "MONTBELL" in t or "MONT-BELL" in t:
        return "Montbell"
    if ("UNIQLO" in t or re.search(r"\bGU\b", t)) and re.search(r"\bTEE\b|T-SHIRT|TSHIRT", t):
        return "Tシャツ"
    if "UNIQLO" in t:
        return "ユニクロ"
    return ""


def _jst_day(iso):
    try:
        d = dt.datetime.strptime((iso or "")[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None
    return d.astimezone(JST).date()


def item_price(li):
    """商品価格 = **注文の通貨のまま** (英国はポンド)。手で入れていた行と同じ (NO.135/136)。"""
    try:
        return round(float((li.get("lineItemCost") or {}).get("value")), 2)
    except (TypeError, ValueError):
        return ""


def _usd(amount, rate=None):
    """eBay の金額 → ドル。ドル以外は rate (SALE の exchangeRate) で直す。直せなければ None。"""
    try:
        v = float((amount or {}).get("value"))
    except (TypeError, ValueError):
        return None
    if (amount.get("currency") or "USD") == "USD":
        return v
    return v * float(rate) if rate else None


def money_cells(order, fin, tracking=""):
    """eBay の注文 + 入金明細 → 表の金額・追跡番号の列 {列: 値} (純関数)。

    手で入れていた行と同じ書き方 (2026-09-24 に NO.136/137/139 と突き合わせて確かめた):
      商品価格・送料・売上税 = 注文の通貨 / 取引手数料・広告料 = ドルのマイナス /
      収益 = 入金明細の SALE (手数料を引いた額) − 広告料。
    取れない項目は入れない (空のまま = 手で入れる)。
    """
    out = {}
    lis = order.get("lineItems") or []
    if not lis:
        return out
    li = lis[0]
    price = item_price(li)
    if price != "":
        out[C_PRICE] = price
    ps = order.get("pricingSummary") or {}
    try:
        ship = float((ps.get("deliveryCost") or {}).get("value") or 0)
    except ValueError:
        ship = 0.0
    if ship > 0:
        out[C_SHIP] = round(ship, 2)
    sale = next((t for t in fin or [] if t.get("transactionType") == "SALE"), None)
    ad = sum(float((t.get("amount") or {}).get("value") or 0) for t in fin or []
             if t.get("feeType") == "AD_FEE" and t.get("bookingEntry") == "DEBIT")
    if sale:
        rate = (sale.get("amount") or {}).get("exchangeRate")
        base = ((sale.get("orderLineItems") or [{}])[0].get("feeBasisAmount") or {}).get("value")
        try:
            tax = round(float(base) - (price or 0) - ship, 2) if base and price != "" else 0
        except ValueError:
            tax = 0
        if tax > 0:
            out[C_TAX] = tax
        fee = _usd(sale.get("totalFeeAmount"), rate)
        if fee is not None:
            out[C_FEE] = -round(fee, 2)
        net = _usd(sale.get("amount"))
        if net is not None:
            out[C_NET] = round(net - ad, 2)
    if ad:
        out[C_AD] = -round(ad, 2)
    if tracking:
        out[C_TRACK] = tracking
    return out


def order_state(order):
    """未発送 / 発送済 / キャンセル / 返金 / 未払い。"""
    if ((order.get("cancelStatus") or {}).get("cancelState") or "") == "CANCELED":
        return "キャンセル"
    pay = (order.get("orderPaymentStatus") or "").upper()
    if pay == "FULLY_REFUNDED":
        return "返金"
    if pay not in ("PAID", "PARTIALLY_REFUNDED"):
        return "未払い"
    return "発送済" if order.get("orderFulfillmentStatus") == "FULFILLED" else "未発送"


def ship_by(order):
    days = [_jst_day((li.get("lineItemFulfillmentInstructions") or {}).get("shipByDate"))
            for li in order.get("lineItems") or []]
    days = [d for d in days if d]
    return min(days) if days else None


def country_of(order):
    try:
        cc = order["fulfillmentStartInstructions"][0]["shippingStep"]["shipTo"]["contactAddress"]["countryCode"]
    except (KeyError, IndexError, TypeError):
        return ""
    return COUNTRY.get(cc, cc)


def new_rows(orders, existing, next_no, start=START_DATE):
    """表に足す行 (21列目まで + V〜Z)。existing = 表にある注文番号の集合。"""
    out = []
    for o in sorted(orders, key=lambda o: o.get("creationDate") or ""):
        oid = norm_order(o.get("orderId"))
        day = _jst_day(o.get("creationDate"))
        if not oid or oid in existing or not day or day < start:
            continue
        if order_state(o) not in ("未発送", "発送済"):
            continue
        sb = ship_by(o)
        for li in o.get("lineItems") or []:
            iid, title = str(li.get("legacyItemId") or ""), li.get("title") or ""
            r = [""] * (C_STATE + 1)
            r[C_NO], r[C_ITEM], r[C_TITLE], r[C_ORDER] = next_no, iid, title, oid
            r[C_DATE], r[C_COUNTRY], r[C_PRICE] = day.strftime("%Y/%m/%d"), country_of(o), item_price(li)
            r[C_CAT] = category_of(title)
            r[C_DONE] = order_state(o) == "発送済"             # 送ってある = 仕入れ済み
            r[C_SHIPBY] = sb.strftime("%Y/%m/%d") if sb else ""
            r[C_STATE] = order_state(o)
            out.append(r)
            next_no += 1
        existing.add(oid)
    return out


def profit_formula(row_no):
    """営業利益 (P列) の式。手で入れていた行と同じ形。"""
    return f"=L{row_no}*'為替レート'!$C$4-M{row_no}-O{row_no}"


def is_checked(v):
    return str(v).strip().upper() == "TRUE"


def waiting(rows):
    """仕入れ待ち = チェック無し かつ 未発送 の行 [(行番号, 行)]。"""
    return [(n, r) for n, r in enumerate(rows[1:], 2)
            if len(r) > C_STATE and r[C_STATE] == "未発送" and not is_checked(r[C_DONE])]


# ---------------------------------------------------------------- I/O
def fetch_orders(days=DAYS):
    import requests
    import ads_add_new_listings as A
    h = {"Authorization": f"Bearer {A._token()}", "Accept": "application/json"}
    end = dt.datetime.utcnow() - dt.timedelta(minutes=10)      # PC の時計が進んでいても弾かれない (sold_restock と同じ)
    params = {"filter": f"creationdate:[{end - dt.timedelta(days=days):%Y-%m-%dT%H:%M:%S.000Z}.."
                        f"{end:%Y-%m-%dT%H:%M:%S.000Z}]", "limit": "200"}
    url, out = "https://api.ebay.com/sell/fulfillment/v1/order", []
    while url:
        r = requests.get(url, headers=h, params=params, timeout=60)
        params = None
        r.raise_for_status()
        d = r.json()
        out += d.get("orders") or []
        url = d.get("next")
    return out


def _headers():
    import ads_add_new_listings as A
    return {"Authorization": f"Bearer {A._token()}", "Accept": "application/json"}


def fetch_finance(order_id, h):
    """その注文の入金明細 (SALE / 広告料)。読めなければ []。"""
    import requests
    try:
        r = requests.get("https://apiz.ebay.com/sell/finances/v1/transaction", headers=h,
                         params={"filter": "orderId:{%s}" % order_id}, timeout=60)
        return r.json().get("transactions") or [] if r.ok else []
    except Exception:                                          # noqa: BLE001
        return []


def fetch_tracking(order, h):
    """発送済みの注文の追跡番号 (複数なら空白区切り)。無ければ ''。"""
    import requests
    nums = []
    for href in order.get("fulfillmentHrefs") or []:
        try:
            f = requests.get(href, headers=h, timeout=60)
            if f.ok and f.json().get("shipmentTrackingNumber"):
                nums.append(f.json()["shipmentTrackingNumber"])
        except Exception:                                      # noqa: BLE001
            pass
    return " ".join(dict.fromkeys(nums))


def fill_money(ws, by_id, rows):
    """表の空欄 (商品価格〜収益・追跡番号) を eBay から埋める (I/O)。手で入れた値は上書きしない。書いたセル数。"""
    import gspread.utils as GU
    h, ups = None, []
    cols = (C_PRICE, C_SHIP, C_TAX, C_FEE, C_AD, C_NET, C_TRACK)
    for n, r in enumerate(rows[1:], 2):
        r = r + [""] * (C_STATE + 1 - len(r))
        o = by_id.get(norm_order(r[C_ORDER]))
        if not o or order_state(o) not in ("未発送", "発送済"):
            continue
        need_fin = not (r[C_FEE].strip() and r[C_NET].strip())
        need_track = not r[C_TRACK].strip() and order_state(o) == "発送済"
        if not (need_fin or need_track):
            continue
        h = h or _headers()
        fin = fetch_finance(norm_order(r[C_ORDER]), h) if need_fin else []
        tr = fetch_tracking(o, h) if need_track else ""
        for c, v in money_cells(o, fin, tr).items():
            if c in cols and not r[c].strip():
                ups.append({"range": GU.rowcol_to_a1(n, c + 1), "values": [[v]]})
    if ups:
        ws.batch_update(ups, value_input_option="USER_ENTERED")
    print(f"  eBay から埋めた空欄 {len(ups)}セル (手数料・広告料・収益・追跡番号など)")
    return len(ups)


def _ws():
    import gspread
    from google.oauth2.service_account import Credentials
    import sheet_io as S
    gc = gspread.authorize(Credentials.from_service_account_file(
        S.CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"]))
    return gc.open_by_key(SALES_SHEET_ID).get_worksheet_by_id(SALES_GID)


def _candidate_lookup():
    """(sku, itemId) → 売れた出品の仕入元 (A列 + 補URL) のメルカリ id の集合。読めなければ None。"""
    try:
        import sheet_io as S
        import sold_restock_worklist as W
        from mercari_purchases import mercari_id
        sheets = W._sheets()
    except Exception as e:                                     # noqa: BLE001
        print(f"  (商品管理シートを読めませんでした: {e} — 買った先は今回は結びません)")
        return None
    cols = [0] + [S.PRODUCT_COL_AUX_START + k for k in range(S.PRODUCT_AUX_MAX)]

    def f(sku, iid):
        _l, _n, row = W.find_row(sheets, (sku or "").strip(), (iid or "").strip())
        if not row:
            return set()
        return {mercari_id(row[c]) for c in cols if len(row) > c and mercari_id(row[c])}
    return f


def link_targets(rows, by_id):
    """買った先を結ぶ対象の行 [(行番号, 行, 注文)] (純関数)。

    未発送の注文だけ。発送済みは発送日より後の購入を結んでしまう
    (実例 2026-09-24: 9/19 に発送済みのヤドンに、9/23 の注文のための 9/24 の購入が結ばれた)。
    """
    out = []
    for n, r in enumerate(rows[1:], 2):
        r = r + [""] * (C_STATE + 1 - len(r))
        o = by_id.get(norm_order(r[C_ORDER]))
        if o and not r[C_URL].strip() and r[C_STATE] == "未発送":
            out.append((n, r, o))
    return out


def order_size(order):
    """eBay 注文のサイズ (変種の Size / Sizes)。無ければ ''。"""
    for li in order.get("lineItems") or []:
        for a in li.get("variationAspects") or []:
            if "size" in (a.get("name") or "").lower():
                return a.get("value") or ""
    return ""


def is_uniqlo_order(order):
    return any("UNIQLO" in (li.get("title") or "").upper() for li in order.get("lineItems") or [])


LINKED = r"C:/dev/iMak_data/hq/order_purchase_linked.json"   # 購入 → 結んだ注文番号


def purchase_keys(buys, kind):
    """購入ごとの見分けの鍵 (純関数)。同じ日に同じ物を2点買った時は #1 #2 で分ける。"""
    out, seen = [], {}
    for p in buys:
        if kind == "mercari":
            base = "mercari:" + str(p.get("id") or "")
        else:
            base = "uniqlo:%s|%s|%s|%s|%s" % (p.get("day"), p.get("pid"), p.get("color"), p.get("size"),
                                              p.get("url") or p.get("place") or "")
        seen[base] = seen.get(base, 0) + 1
        out.append(base + "#%d" % seen[base])
    return out


def unused_purchases(buys, keys, linked, rows_order):
    """ほかの注文にもう結んだ購入を除く (純関数)。

    ★2026-09-25 ユーザー「仕入れてないのに、仕入済となるのが一番きつい」。
      1回の走行の中でしか「使った」を覚えていなかったので、同じカードがもう1枚売れると、
      前の注文のために買った購入が新しい注文にも結ばれて仕入済になり得た。
    linked    : {鍵: 注文番号} (前の走行までに結んだ分)
    rows_order: {行番号: 注文番号} (今回の対象)
    返り値    : [(購入, 鍵)] 前に結んだ相手が今回の対象の注文そのものなら残す (やり直し)
    """
    mine = set(rows_order.values())
    return [(p, k) for p, k in zip(buys, keys) if not linked.get(k) or linked.get(k) in mine]


def _load_linked():
    try:
        with open(LINKED, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_linked(d):
    tmp = LINKED + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, LINKED)


def link_purchases(ws, by_id, today_rows):
    """買った先を結ぶ (I/O)。書いたセル数を返す。

    仕入れ待ち (チェック無し × 未発送) の注文がある時だけ、その注文に関係する購入履歴を読む:
    ユニクロの出品 → ユニクロ公式の購入履歴 / それ以外 → メルカリの購入履歴。
    """
    import gspread.utils as GU
    # 手でチェック済みでも、買った先が空なら 買った先・仕入原価 は埋める (チェックと仕入日は触らない)
    targets = link_targets(today_rows, by_id)
    if not targets:
        return 0
    hits = {}                                          # 行番号 → (日付, X に入れる値, 表示, 仕入値, 鍵)
    linked = _load_linked()
    # 表の X にもう入っているメルカリの購入も「使用済み」(台帳ができる前に結んだ分)
    for n, r in enumerate(today_rows[1:], 2):
        r = r + [""] * (C_STATE + 1 - len(r))
        m = re.search(r"jp\.mercari\.com/transaction/(m\d+)", r[C_URL])
        if m:
            linked.setdefault("mercari:%s#1" % m.group(1), norm_order(r[C_ORDER]))
    uq = [(n, r, o) for n, r, o in targets if is_uniqlo_order(o)]
    mc = [(n, r, o) for n, r, o in targets if not is_uniqlo_order(o)]
    if mc:
        hits.update(_link_mercari(mc, linked))
    if uq:
        hits.update(_link_uniqlo(uq, linked))
    ups = []
    for n, (day, url, note, price, key) in hits.items():
        linked[key] = norm_order(today_rows[n - 1][C_ORDER])
        if price and not (today_rows[n - 1][C_COST].strip() if len(today_rows[n - 1]) > C_COST else ""):
            ups.append({"range": GU.rowcol_to_a1(n, C_COST + 1), "values": [[price]]})   # 仕入原価 (ユニクロの注文詳細)
        _r = today_rows[n - 1] + [""] * (C_STATE + 1)
        if not is_checked(_r[C_DONE]):
            ups.append({"range": GU.rowcol_to_a1(n, C_DONE + 1), "values": [[True]]})
        if not _r[C_DONE_AT].strip() or not is_checked(_r[C_DONE]):
            ups.append({"range": GU.rowcol_to_a1(n, C_DONE_AT + 1), "values": [[day.strftime("%Y/%m/%d")]]})
        ups.append({"range": GU.rowcol_to_a1(n, C_URL + 1), "values": [[url]]})
        print(f"  買った先: {n}行目 ← {url} ({note})")
    if ups:
        ws.batch_update(ups, value_input_option="USER_ENTERED")
        _save_linked(linked)
    return len(ups)


def fill_mercari_cost(ws, rows):
    """買った先がメルカリで 仕入原価 (M列) が空の行に、商品ページの値段を入れる (I/O)。書いた件数。

    手で入れた値は上書きしない。値段が読めなかった行は空のまま (手で入れる)。
    """
    import gspread.utils as GU
    import mercari_purchases as MP
    want = {}
    for n, r in enumerate(rows[1:], 2):
        r = r + [""] * (C_STATE + 1 - len(r))
        m = re.search(r"jp\.mercari\.com/transaction/(m\d+)", r[C_URL])
        if m and not r[C_COST].strip():
            want[n] = m.group(1)
    if not want:
        return 0
    try:
        price = MP.item_prices(sorted(set(want.values())))
    except Exception as e:                                     # noqa: BLE001
        print(f"  ⚠ メルカリの値段を読めませんでした: {str(e)[:60]}")
        return 0
    ups = [{"range": GU.rowcol_to_a1(n, C_COST + 1), "values": [[price[mid]]]}
           for n, mid in want.items() if price.get(mid)]
    if ups:
        ws.batch_update(ups, value_input_option="USER_ENTERED")
    print(f"  仕入原価 (メルカリの値段) {len(ups)}件 / 読めなかった {len(want) - len(ups)}件")
    return len(ups)


def _link_mercari(targets, linked):
    import mercari_purchases as MP
    cand = _candidate_lookup()
    if cand is None:
        return {}
    try:
        buys = MP.fetch_purchases()
    except Exception as e:                                     # noqa: BLE001
        print(f"  ⚠ メルカリの購入履歴を読めませんでした: {str(e)[:60]}")
        print("    → ログインし直す: python iMakHQ/tools/mercari_purchases.py --login (窓でログインしたら自動で閉じます)")
        return {}
    orders = []
    for n, r, o in targets:
        ids = set()
        for li in o.get("lineItems") or []:
            ids |= cand(li.get("sku") or "", str(li.get("legacyItemId") or ""))
        day = _jst_day(o.get("creationDate"))
        if ids and day:
            orders.append((n, day, ids))
    free = unused_purchases(buys, purchase_keys(buys, "mercari"), linked,
                            {n: norm_order(r[C_ORDER]) for n, r, _o in targets})
    key_of = {id(p): k for p, k in free}
    hit = MP.match(orders, [p for p, _k in free])
    print(f"  メルカリ購入履歴 {len(buys)}件 (ほかの注文に結び済み {len(buys) - len(free)}件) / 結べた注文 {len(hit)}件")
    return {n: (p["at"].date(), p["url"], "%s %s" % (p["at"].strftime("%m/%d %H:%M"), p["title"][:30]),
                None, key_of[id(p)])
            for n, p in hit.items()}


def _link_uniqlo(targets, linked):
    import uniqlo_purchases as UQ
    try:
        mon = UQ.monitor_urls()
        buys = UQ.fetch_purchases()
    except Exception as e:                                     # noqa: BLE001
        print(f"  ⚠ ユニクロの購入履歴を読めませんでした: {str(e)[:60]}")
        print("    → ログインし直す: python iMakHQ/tools/uniqlo_purchases.py --login (窓でログインしたら自動で閉じます)")
        return {}
    orders = []
    for n, r, o in targets:
        keys = set()
        for li in o.get("lineItems") or []:
            keys |= UQ.official_keys(mon.get(str(li.get("legacyItemId") or ""), []))
        day = _jst_day(o.get("creationDate"))
        if keys and day:
            orders.append((n, day, keys, UQ.size_key(order_size(o))))
    free = unused_purchases(buys, purchase_keys(buys, "uniqlo"), linked,
                            {n: norm_order(r[C_ORDER]) for n, r, _o in targets})
    key_of = {id(p): k for p, k in free}
    hit = UQ.match(orders, [p for p, _k in free])
    print(f"  ユニクロ購入履歴 {len(buys)}件 (ほかの注文に結び済み {len(buys) - len(free)}件) / 結べた注文 {len(hit)}件"
          f" (在庫監視シートに仕入元がある注文 {len(orders)}件)")
    return {n: (p["day"], p.get("url") or UQ.URL, "%s %s %s %s" % (p["day"], p["place"], p["size"], p["name"][:20]),
                p.get("price"), key_of[id(p)])
            for n, p in hit.items()}


def _format(ws, last_row):
    """V列をチェック欄に、仕入れ待ちの行を赤く (書くたびに同じ規則で上書き)。"""
    sid = ws.id
    reqs = [
        {"setDataValidation": {
            "range": {"sheetId": sid, "startRowIndex": 1, "endRowIndex": max(last_row, 2),
                      "startColumnIndex": C_DONE, "endColumnIndex": C_DONE + 1},
            "rule": {"condition": {"type": "BOOLEAN"}, "showCustomUi": True}}},
    ]
    meta = ws.spreadsheet.fetch_sheet_metadata({"fields": "sheets(properties.sheetId,conditionalFormats)"})
    cur = next((s for s in meta.get("sheets", []) if s["properties"]["sheetId"] == sid), {})
    formula = '=AND($Z2="未発送",$V2<>TRUE)'
    for i, cf in reversed(list(enumerate(cur.get("conditionalFormats") or []))):
        vals = (((cf.get("booleanRule") or {}).get("condition") or {}).get("values") or [])
        if any(v.get("userEnteredValue") == formula for v in vals):
            reqs.append({"deleteConditionalFormatRule": {"sheetId": sid, "index": i}})
    reqs.append({"addConditionalFormatRule": {"index": 0, "rule": {
        "ranges": [{"sheetId": sid, "startRowIndex": 1, "endRowIndex": ws.row_count,
                    "startColumnIndex": 0, "endColumnIndex": C_STATE + 1}],
        "booleanRule": {"condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": formula}]},
                        "format": {"backgroundColor": {"red": 1, "green": 0.85, "blue": 0.85}}}}}})
    ws.spreadsheet.batch_update({"requests": reqs})


def _write_status(rows):
    w = waiting(rows)
    shipby = sorted(r[C_SHIPBY] for _n, r in w if r[C_SHIPBY])
    st = {"at": dt.datetime.now().isoformat(timespec="seconds"), "waiting": len(w),
          "earliest_ship_by": shipby[0] if shipby else "",
          "items": [{"row": n, "no": r[C_NO], "title": r[C_TITLE][:60], "ship_by": r[C_SHIPBY]} for n, r in w]}
    os.makedirs(os.path.dirname(STATUS), exist_ok=True)
    tmp = STATUS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATUS)
    return st


def main(argv):
    write = "--write" in argv
    import gspread.utils as GU
    orders = fetch_orders()
    by_id = {norm_order(o.get("orderId")): o for o in orders}
    ws = _ws()
    rows = ws.get_all_values()
    # 足す行の NO. は数字の最大 +1
    nos = [int(r[C_NO]) for r in rows[1:] if r and r[C_NO].strip().isdigit()]
    existing = {norm_order(r[C_ORDER]) for r in rows[1:] if len(r) > C_ORDER and norm_order(r[C_ORDER])}
    add = new_rows(orders, set(existing), (max(nos) if nos else 0) + 1)

    # 既存の行: V〜Z だけを更新
    updates = []
    today = dt.date.today().strftime("%Y/%m/%d")
    if not rows[0][C_DONE:C_STATE + 1] == HEAD:
        updates.append({"range": f"V1:Z1", "values": [HEAD]})
    for n, r in enumerate(rows[1:], 2):
        r = r + [""] * (C_STATE + 1 - len(r))
        o = by_id.get(norm_order(r[C_ORDER]))
        state = order_state(o) if o else ("発送済" if r[C_TRACK].strip() else r[C_STATE])
        cells = {}
        if state and state != r[C_STATE]:
            cells[C_STATE] = state
        if o and not r[C_SHIPBY].strip() and ship_by(o):
            cells[C_SHIPBY] = ship_by(o).strftime("%Y/%m/%d")
        if not is_checked(r[C_DONE]) and (r[C_TRACK].strip() or state == "発送済"):
            cells[C_DONE] = True                               # 追跡番号がある / 発送済 = 仕入れて送った
        # 仕入日 = 人が未発送のうちにチェックを付けた日 (発送済で自動で付けたチェックには日付を入れない)
        if is_checked(r[C_DONE]) and not r[C_DONE_AT].strip() and state == "未発送":
            cells[C_DONE_AT] = today
        for c, v in cells.items():
            updates.append({"range": GU.rowcol_to_a1(n, c + 1), "values": [[v]]})

    print(f"注文 {len(orders)}件を読みました / 表 {len(rows) - 1}行")
    for r in add:
        print(f"  足す: NO.{r[C_NO]} {r[C_DATE]} {r[C_COUNTRY]} ${r[C_PRICE]} {r[C_STATE]} 期限{r[C_SHIPBY]} "
              f"{r[C_TITLE][:50]}")
    print(f"  既存の行の更新 {len(updates)}セル")
    if not write:
        print("(--write で書きます)")
        return 0

    # 足す直前に読み直して二重を防ぐ (別の窓・手入力と重なった時)
    fresh = ws.get_all_values()
    have = {norm_order(r[C_ORDER]) for r in fresh[1:] if len(r) > C_ORDER}
    add = [r for r in add if norm_order(r[C_ORDER]) not in have]
    if len(fresh) != len(rows):
        print("  表の行数が読んだ後に変わりました。今回は足さずに終わります (次の走行で足します)")
        add, updates = [], []
    start = len(fresh) + 1
    if start + len(add) > ws.row_count:
        ws.add_rows(start + len(add) - ws.row_count + 50)
    for i, r in enumerate(add):
        rn = start + i
        r[15] = profit_formula(rn)
        updates.append({"range": f"A{rn}:Z{rn}", "values": [r]})
    if updates:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
    last = start + len(add) - 1
    _format(ws, last)
    fill_money(ws, by_id, ws.get_all_values())
    link_purchases(ws, by_id, ws.get_all_values())
    fill_mercari_cost(ws, ws.get_all_values())
    st = _write_status(ws.get_all_values())
    print(f"  書きました: 足した {len(add)}行 / 仕入れ待ち {st['waiting']}件"
          + (f" (いちばん早い発送期限 {st['earliest_ship_by']})" if st["earliest_ship_by"] else ""))
    return 0


LOG = r"C:/dev/iMak/iMakHQ/review_logs/order_purchase_sync.log"

if __name__ == "__main__":
    if sys.stdout is None:                                     # pythonw (予約タスク・窓なし) の時は記録に残す
        sys.stdout = sys.stderr = open(LOG, "a", encoding="utf-8")
        print(f"--- {dt.datetime.now():%Y-%m-%d %H:%M:%S}")
    sys.exit(main(sys.argv[1:]))
