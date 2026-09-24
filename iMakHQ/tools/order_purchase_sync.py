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
       V 仕入済 (チェック欄・手で付ける) / W 仕入日 (チェックを見て自動) / X 仕入先URL (商品管理シートから)
       Y 発送期限 (eBay) / Z 注文の状態 (未発送 / 発送済 / キャンセル / 返金。eBay から毎回更新)
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
C_TRACK, C_CAT = 13, 17
C_DONE, C_DONE_AT, C_URL, C_SHIPBY, C_STATE = 21, 22, 23, 24, 25     # V W X Y Z
HEAD = ["仕入済", "仕入日", "仕入先URL", "発送期限", "注文の状態"]

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


def price_usd(order, li):
    """その行の商品価格 (USD)。USD 以外は 支払額の換算率で直す。出せなければ ''。"""
    cost = li.get("lineItemCost") or {}
    try:
        v = float(cost.get("value"))
    except (TypeError, ValueError):
        return ""
    if (cost.get("currency") or "USD") == "USD":
        return round(v, 2)
    due = (order.get("paymentSummary") or {}).get("totalDueSeller") or {}
    try:
        if due.get("currency") == "USD" and due.get("convertedFromCurrency") == cost.get("currency"):
            return round(v * float(due["value"]) / float(due["convertedFromValue"]), 2)
    except (TypeError, ValueError, ZeroDivisionError, KeyError):
        pass
    return ""


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


def new_rows(orders, existing, next_no, url_of=lambda sku, iid: "", start=START_DATE):
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
            r[C_DATE], r[C_COUNTRY], r[C_PRICE] = day.strftime("%Y/%m/%d"), country_of(o), price_usd(o, li)
            r[C_CAT] = category_of(title)
            r[C_DONE] = order_state(o) == "発送済"             # 送ってある = 仕入れ済み
            r[C_URL] = url_of(li.get("sku") or "", iid)
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


def _ws():
    import gspread
    from google.oauth2.service_account import Credentials
    import sheet_io as S
    gc = gspread.authorize(Credentials.from_service_account_file(
        S.CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"]))
    return gc.open_by_key(SALES_SHEET_ID).get_worksheet_by_id(SALES_GID)


def _url_lookup():
    """(sku, itemId) → 商品管理シートの仕入元 (A列)。読めなければ常に ''。"""
    try:
        import sold_restock_worklist as W
        sheets = W._sheets()
    except Exception as e:                                     # noqa: BLE001
        print(f"  (商品管理シートを読めませんでした: {e} — 仕入先URL は空で足します)")
        return lambda sku, iid: ""

    def f(sku, iid):
        _l, _n, row = W.find_row(sheets, (sku or "").strip(), (iid or "").strip())
        u = ((row[0] if row else "") or "").strip()
        return u if u.startswith("http") else ""
    return f


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
    add = new_rows(orders, set(existing), (max(nos) if nos else 0) + 1, _url_lookup())

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
              f"{r[C_TITLE][:50]} {'(仕入先あり)' if r[C_URL] else '(仕入先なし)'}")
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
