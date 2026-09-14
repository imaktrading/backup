#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""売れた → 補充 (2026-08-28 新設)。**作り直さない**。既存の出品を戻すだけ。

ユーザー確定 (2026-08-28):
    「単純に在庫1にして、仕入れ値で価格とポリシーを変えるだけ」

    そのとおりで、中身 (タイトル / Item Specifics / 画像) は元の出品のままでよい。
    新規生成の経路 (タイトル生成・目視・カタログ照合・Claude API) を通す必要がない。
    実害 (2026-08-28): 窓口が Giratina を作り直したところ **値段が $100 で出た**
    (正しくは $120.98)。作り直しは遠回りな上に事故る。

やること:
    Completed (売れて終了) → RelistFixedPriceItem (中身そのまま・新ID)
    Active かつ qty=0      → ReviseFixedPriceItem (同ID)
    どちらも **qty=1 + 新しい仕入値から出した価格 + 送料ポリシー** を一緒に送る。

    eBay 呼出の本体は `ichibankuji_restock.ebay_restock` に既に在る (一番くじで実績)。
    こちらは **価格と送料ポリシーを一緒に送る** 版 (向こうは Quantity だけ)。

対象カテゴリ: PSA / G-Shock / 一番くじ (= 同じ物をもう一度仕入れられるもの)。
    アパレルは入れない (公式在庫が戻れば監視くんが復活させる。2026-08-28 ユーザー確定)。

使い方:
    python sold_restock.py                      # 何をやるかだけ出す (既定 = 送らない)
    python sold_restock.py --write              # 実行
    python sold_restock.py --cost 101051553=8000   # 仕入値を手で渡す (cert or SKU)
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r"C:\dev\iMak\iMakeBayAPI")

import sheet_io as S            # noqa: E402
import sold_restock_worklist as W  # noqa: E402


# ---------------------------------------------------------------- 純関数
def plan_action(status, qty):
    """eBay の状態 → やること (純関数, test 可)。

    判らない状態は **触らない** (fail-closed)。取り違えて出すより出さない方が安い。
    """
    if status == "Completed":
        return "relist"
    if status == "Active":
        return "noop" if (qty or 0) > 0 else "revise"
    return "skip"


def price_for(cost_jpy, category="TCG(PSA10)"):
    """仕入値 → (価格USD, 送料ポリシー名) (I/O 無し)。cost 不明なら (None, None)。

    ★価格も送料も **同じ1回の計算から出す**。片方だけ更新すると採算が狂う。
    """
    if not cost_jpy:
        return None, None
    from pricing_engine import compute_listing_price
    r = compute_listing_price(float(cost_jpy), None, category)
    return r.get("price"), r.get("shipping_profile_name")


def build_item_xml(item_id, price, profile, qty=1):
    """Relist/Revise に載せる <Item> (純関数, test 可)。

    価格/ポリシーが取れなかった時は **その要素を送らない** (元の値が残る)。
    0 や空で上書きすると赤字出品になるため。
    """
    parts = [f"<ItemID>{item_id}</ItemID>", f"<Quantity>{int(qty)}</Quantity>"]
    if price:
        parts.append(f"<StartPrice>{float(price):.2f}</StartPrice>")
    if profile:
        parts.append("<SellerProfiles><SellerShippingProfile>"
                     f"<ShippingProfileName>{profile}</ShippingProfileName>"
                     "</SellerShippingProfile></SellerProfiles>")
    return "<Item>" + "".join(parts) + "</Item>"


# ★2026-09-14 pricing_engine のキーと合わせる (G-SHOCK / 一番くじ は各生成器の PROFIT_CATEGORY と同じ)。
#   "G-shock" / "Ichibankuji" は存在しないキーで、G-SHOCK の売上が1件あるだけで一覧ごと落ちていた。
CATEGORY_FOR_PRICING = {
    "PSA": "TCG(PSA10)",
    "G-Shock": "G-SHOCK",
    "一番くじ": "一番くじ",
}


def parse_item_status(xml):
    """GetItem の応答 → (ListingStatus, 残り在庫, 出品サイト) (純関数, test 可)。

    ★2026-09-14 実機で確認: GetItem に QuantityAvailable は無く、Quantity は **出品時の総数**。
      売れて在庫0の出品も Quantity=1 / QuantitySold=1 で返る。Quantity だけ見ると
      「在庫1 = 触らない」になり、数量を戻す処理が一度も動かない。残り = Quantity − QuantitySold。
    ★出品サイトは ShipToLocations の直後の <Site>。その前の <Site> は出品者・落札者のもので、
      オーストラリアのミラーでも先頭は "US" になる。
    """
    x = xml or ""
    st = re.search(r"<ListingStatus>(.*?)</ListingStatus>", x)
    qa = re.search(r"<QuantityAvailable>(\d+)</QuantityAvailable>", x)
    q = re.search(r"<Quantity>(\d+)</Quantity>", x)
    qs = re.search(r"<QuantitySold>(\d+)</QuantitySold>", x)
    if qa:
        avail = int(qa.group(1))
    elif q:
        avail = max(0, int(q.group(1)) - (int(qs.group(1)) if qs else 0))
    else:
        avail = -1
    m = re.search(r"</ShipToLocations>\s*<Site>(.*?)</Site>", x)
    sites = re.findall(r"<Site>(.*?)</Site>", x)
    site = m.group(1) if m else (sites[-1] if sites else "?")
    return (st.group(1) if st else "?"), avail, site


COL_SOLD = 3        # D 売り切れ (監視くんが仕入元の売切を書く)
COL_CHECKED = 14    # O 売り切れチェック時間 (監視くんの巡回時刻)
COST_FRESH_DAYS = 2


def row_cost_is_current(row, now=None, max_age_days=COST_FRESH_DAYS, after=None):
    """台帳の仕入値 (N = M − K) を「今の仕入値」として使ってよいか (純関数, test 可)。

    ★2026-09-14 監視くんは巡回のたびに M (現在価格) を **仕入元と補URLのうち生きている最安** で
      書き直す (M-min, inventory commit 8d89664)。巡回が新しく、仕入元が売切でなければ
      N はその時点の仕入値。これを一律「売れた時の古い値」扱いにしていたため、
      補充が毎回「古い仕入値なので止めます」で止まっていた。
    """
    import datetime as _dt
    if len(row) > COL_SOLD and (row[COL_SOLD] or "").strip():
        return False
    raw = (row[COL_CHECKED] or "").strip() if len(row) > COL_CHECKED else ""
    try:
        t = _dt.datetime.strptime(raw, "%Y/%m/%d %H:%M:%S")
    except ValueError:
        return False
    now = now or _dt.datetime.now()
    if after and t.date() < after:
        # ★2026-09-14 発送より前の巡回は、その注文のために買った仕入元をまだ「在庫あり」と見ている
        #   ことがある。買った後の巡回 (= 発送日以降) の値だけを今の仕入値にする。
        return False
    return _dt.timedelta(0) <= now - t <= _dt.timedelta(days=max_age_days)


def _order_date(s):
    """'Sep-08-26' → date。読めなければ None (純関数)。"""
    import datetime as _dt
    try:
        return _dt.datetime.strptime((s or "").strip(), "%b-%d-%y").date()
    except ValueError:
        return None


def shipped_after_by_row(want, sheets):
    """台帳の行ごとに、いちばん新しい発送日 {(シート, 行番号): date} (I/O 無し)。"""
    out = {}
    for o, _cat in want:
        d = _order_date(o.get("Shipped On Date"))
        if not d:
            continue
        label, n, row = W.find_row(sheets, (o.get("Custom Label") or "").strip(),
                                   (o.get("Item Number") or "").strip())
        if row is not None and (out.get((label, n)) is None or d > out[(label, n)]):
            out[(label, n)] = d
    return out


def _api_day(iso):
    """'2026-09-08T07:26:00.000Z' → 'Sep-08-26' (注文レポートと同じ形)。空は '' (純関数)。"""
    import datetime as _dt
    try:
        return _dt.datetime.strptime((iso or "")[:10], "%Y-%m-%d").strftime("%b-%d-%y")
    except ValueError:
        return ""


def order_rows_from_api(order, shipped_iso=""):
    """Fulfillment API の注文1件 → 注文レポートと同じキーの行 list (純関数, test 可)。

    ★2026-09-14 夜間は注文 API から取る。注文レポートは人が週1で落とすので、それだけだと
      補充が最大1週間遅れる。返金・キャンセルは Total Price 0、未払いは Paid On Date 空にして、
      order_pending の判定をレポートと同じにする。
    """
    pay = (order.get("orderPaymentStatus") or "").upper()
    cancelled = ((order.get("cancelStatus") or {}).get("cancelState") or "") == "CANCELED"
    paid = ""
    if pay in ("PAID", "PARTIALLY_REFUNDED", "FULLY_REFUNDED"):
        pays = (order.get("paymentSummary") or {}).get("payments") or []
        paid = _api_day(pays[0].get("paymentDate") if pays else order.get("creationDate"))
    total = (order.get("pricingSummary") or {}).get("total") or {}
    total_s = "0" if (pay == "FULLY_REFUNDED" or cancelled) else str(total.get("value") or "")
    out = []
    for li in order.get("lineItems") or []:
        out.append({
            "Item Number": str(li.get("legacyItemId") or ""),
            "Custom Label": li.get("sku") or "",
            "Item Title": li.get("title") or "",
            "Quantity": str(li.get("quantity") or ""),
            "Sale Date": _api_day(order.get("creationDate")),
            "Paid On Date": paid,
            "Shipped On Date": _api_day(shipped_iso),
            "Total Price": total_s,
        })
    return out


def orders_from_api(days=90):
    """注文 API → 注文レポートと同じ形の行 (I/O)。発送日は fulfillmentHrefs を読む。取れなければ例外。"""
    import datetime as _dt
    import requests
    import ads_add_new_listings as _A
    tok = _A._token()
    h = {"Authorization": f"Bearer {tok}", "Accept": "application/json"}
    end = _dt.datetime.utcnow()
    params = {"filter": f"creationdate:[{end - _dt.timedelta(days=days):%Y-%m-%dT%H:%M:%S.000Z}.."
                        f"{end:%Y-%m-%dT%H:%M:%S.000Z}]", "limit": "200"}
    url, rows = "https://api.ebay.com/sell/fulfillment/v1/order", []
    while url:
        r = requests.get(url, headers=h, params=params, timeout=60)
        params = None
        r.raise_for_status()
        d = r.json()
        for o in d.get("orders") or []:
            shipped = ""
            for href in o.get("fulfillmentHrefs") or []:
                f = requests.get(href, headers=h, timeout=60)
                if f.ok:
                    shipped = max(shipped, f.json().get("shippedDate") or "")
            rows += order_rows_from_api(o, shipped)
        url = d.get("next")
    return rows


def order_shipped(order):
    """注文レポートの1行が発送済みか (純関数, test 可)。"""
    return bool((order.get("Shipped On Date") or "").strip())


def order_pending(order):
    """まだ仕入れ・発送が終わっていない注文か (純関数, test 可)。

    ★2026-09-14 支払い済みで未発送 = その注文のための仕入れが終わっていないことがある。ここで数量を戻すと、
      同じ仕入元を2人に売ることになる (実例: カビゴン 9/12 の注文が未発送のまま在庫0)。
      未払い (Paid On Date 空 = 8/23 G-SHOCK) と全額返金 (Total Price 0 = 7/24 G-SHOCK) は
      仕入れが発生しないので止めない。
    """
    if order_shipped(order):
        return False
    if not (order.get("Paid On Date") or "").strip():
        return False
    import re as _re
    total = _re.sub(r"[^0-9.]", "", order.get("Total Price") or "")
    try:
        if total and float(total) == 0:
            return False
    except ValueError:
        pass
    return True


def pending_rows(want, sheets):
    """未発送の注文がある台帳の行 {(シート, 行番号)} (I/O 無し)。同じ出品が2回売れて片方だけ未発送でも止める。"""
    out = set()
    for o, _cat in want:
        if not order_pending(o):
            continue
        label, n, row = W.find_row(sheets, (o.get("Custom Label") or "").strip(),
                                   (o.get("Item Number") or "").strip())
        if row is not None:
            out.add((label, n))
    return out


def restock_target(state, row, sold_item_id, item_col=S.PRODUCT_COL_ITEMID):
    """数量を戻す相手の itemID (純関数, test 可)。

    台帳の出品が在庫0 → **台帳の出品** (US の親)。ミラーで売れても注文の番号はミラーなので、
    注文の番号を使うとミラーを触ってしまう (820041751397 = AU で売れた実例)。
    台帳が空 (売れて閉じた) → 注文の番号。
    """
    if state == "在庫0":
        return (row[item_col] or "").strip()
    return sold_item_id


def parse_cost_args(argv):
    """--cost KEY=VALUE を dict に (純関数, test 可)。"""
    out = {}
    for i, a in enumerate(argv):
        if a == "--cost" and i + 1 < len(argv) and "=" in argv[i + 1]:
            k, v = argv[i + 1].split("=", 1)
            try:
                out[k.strip()] = float(v)
            except ValueError:
                pass
    return out


def ebay_status(fx, U, item_id, tok):
    """GetItem → (ListingStatus, 残り在庫, 出品サイト)。取れなければ ('?', -1, '?') = 触らない。"""
    try:
        r = fx.post("GetItem", f"<ItemID>{item_id}</ItemID><DetailLevel>ReturnAll</DetailLevel>",
                    tok, U.SITE_US)
    except Exception:                                              # noqa: BLE001
        return "?", -1, "?"
    return parse_item_status(r)
    st = re.search(r"<ListingStatus>(.*?)</ListingStatus>", r or "")
    q = re.search(r"<QuantityAvailable>(\d+)</QuantityAvailable>", r or "") or         re.search(r"<Quantity>(\d+)</Quantity>", r or "")
    return (st.group(1) if st else "?"), (int(q.group(1)) if q else -1)


# ---------------------------------------------------------------- I/O
def fresh_cost_map(rows2d):
    """「PSA再仕入れ」タブ → {card番号: 最安¥} (純関数, test 可)。

    ★台帳(商品管理シート)の仕入値は **売れた時の値** で、今 買える値ではない。
      実測 (2026-08-28): Giratina は台帳¥15,380 に対し実勢¥8,000、Eevee は
      ¥26,500 に対し ¥8,400。古い方で戻すと **売れない値段** で並ぶ。
      🃏 PSA再仕入れ照合 が出した「最安¥」を正とする。
    """
    if not rows2d:
        return {}
    hdr = rows2d[0]

    def _i(name):
        for i, h in enumerate(hdr):
            if name in (h or ""):
                return i
        return None

    ci, pi = _i("set_no"), _i("最安")
    if ci is None or pi is None:
        return {}
    out = {}
    for r in rows2d[1:]:
        k = (r[ci] or "").strip() if len(r) > ci else ""
        v = re.sub(r"[^0-9]", "", (r[pi] or "")) if len(r) > pi else ""
        if k and v:
            out[k] = float(v)
    return out


def card_no_of(order):
    """「PSA再仕入れ」タブと突き合わせる card番号 (純関数, test 可)。

    タブの set_no は `016/054` `196/SV-P` の形。出品タイトルの `#016/054` から取る。
    """
    m = re.search(r"#([A-Za-z0-9-]+/[A-Za-z0-9-]+)", (order.get("Item Title") or "") if order else "")
    return m.group(1) if m else ""


def live_keys(sheets, live_ids, key_col=S.PRODUCT_COL_KEY,
              item_col=S.PRODUCT_COL_ITEMID):
    """**同じカードが既に live** な KEY の集合 (純関数, test 可)。

    ★2026-08-30: 補充は「その行の B列が空か」だけで未補充と判断していたため、
      **別の行に同じカードの生きた出品があっても もう1本出してしまった**。
      実害: Giratina (pokemon_tcg:SM10a-016) が 820057636763 と 820045155453 の2本 live。

      出品くん本体は同じカードの二重出品を3段で止めている
      (抽出時の「同KEYが出品済の2枚目を除外」/ 重複くん excluder / dup_guard)。
      補充は eBay を直接叩くのでそのどれも通らない。**ここで同じ判定をする**。

    ★2026-09-14: live_ids に出品一覧 (dict) を渡すと **在庫1以上の出品だけ** を数える。
      在庫0 の出品まで「出品中」にすると、在庫0 の自分自身に当たって補充できない。
    """
    if isinstance(live_ids, dict):
        live_ids = {k for k, v in live_ids.items() if int((v or {}).get("avail") or 0) > 0}
    out = set()
    for _label, rows in sheets:
        for r in rows[1:]:
            b = (r[item_col] or "").strip() if len(r) > item_col else ""
            k = (r[key_col] or "").strip() if len(r) > key_col else ""
            if b and k and b in live_ids:
                out.add(k)
    return out


def _cost_from_row(row):
    """台帳の行 → 仕入値¥ (既存の pick_cost をそのまま借りる)。"""
    try:
        from listing_common import pick_cost_jpy
        return pick_cost_jpy(row)
    except Exception:                                              # noqa: BLE001
        for col in (S.PRODUCT_COL_COST, S.PRODUCT_COL_COST_M):
            v = (row[col] or "").strip() if len(row) > col else ""
            n = re.sub(r"[^\d.]", "", v)
            if n:
                return float(n)
    return None


def count_workload():
    """押したら何件・何が起きるか (2026-08-31・ラベル/ヒント用)。

    ★eBay の per-item 状態確認 (ebay_status) はしない。live キャッシュ
      (itemid_writeback_audit、2時間以内なら再取得しない) があればそれで判定し、
      無ければ「要確認」として **actionable には数えない** (cull_end / shelf_evict と
      同じ理由: 表示のために API 枠を使わない。2026-08-24 に表示目的の取得で
      取下げが5時間止まった実害がある)。

    戻り: {report: 注文レポートが在るか, actionable: 今すぐ送れる件数
           (live キャッシュで Active&qty=0 と確認できた分), unknown: キャッシュに無く
           判定できない件数 (Completed=要 relist の可能性。押せば分かる), done: 既に補充済,
           error: 読めなかった理由}"""
    out = {"report": False, "actionable": 0, "unknown": 0, "done": 0,
           "blocked": 0, "error": ""}
    try:
        src = W._find_desk_report()
        if not src:
            out["error"] = "注文レポートがありません (reports フォルダに ebay-all-orders-report-*.csv)"
            return out
        out["report"] = True
        pairs = [(o, W.category_of(o.get("Item Title") or "")) for o in W.read_orders(src)]
        want = [(o, c) for o, c in pairs if c]
        if not want:
            return out
        sheets = W._sheets()
        cache_raw = {}
        try:
            import json as _json
            import itemid_writeback_audit as _A
            if _A.CACHE.exists():
                cache_raw = _json.loads(_A.CACHE.read_text(encoding="utf-8"))
        except Exception:                                          # noqa: BLE001
            cache_raw = {}
        already = live_keys(sheets, cache_raw) if cache_raw else set()
        pending = pending_rows(want, sheets)
        seen = set()
        for o, cat in want:
            sku = (o.get("Custom Label") or "").strip()
            iid = (o.get("Item Number") or "").strip()
            label, n, row = W.find_row(sheets, sku, iid)
            if row is None:
                continue
            state, _aux = W.classify(row, live=cache_raw or None)
            if state == "補充済":
                out["done"] += 1
                continue
            if state == "出品なし":
                out["unknown"] += 1
                continue
            target = restock_target(state, row, iid)
            if target in seen:          # 同じ出品が2回売れた (注文は2行) → 1回だけ
                continue
            seen.add(target)
            if (label, n) in pending:   # 未発送の注文がある = まだ仕入れ中
                out["blocked"] = out.get("blocked", 0) + 1
                continue
            _key = (row[S.PRODUCT_COL_KEY] or "").strip() if len(row) > S.PRODUCT_COL_KEY else ""
            if _key and _key in already:
                continue
            # ★2026-09-04: 仕入値が取れない行は **押しても止まる** (本体が
            #   「仕入値が取れないので止めます」で skip)。青にすると押しても減らない。
            #   本体と同じ _cost_from_row を通す (二重実装しない)。cost_override や
            #   当日の調査結果で埋まる可能性は残るので、0 にせず blocked として出す。
            _has_cost = bool(_cost_from_row(row)) and row_cost_is_current(row)
            info = cache_raw.get(target)
            if info is None:
                out["unknown"] += 1
            elif int(info.get("avail") or 0) == 0:
                if _has_cost:
                    out["actionable"] += 1
                else:
                    out["blocked"] = out.get("blocked", 0) + 1
            # avail > 0 = 既に在庫あり (noop)。候補にも数えない。
    except Exception as e:                                          # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"[:60]
    return out


def main():
    argv = sys.argv[1:]
    write = "--write" in argv
    allow_stale = "--allow-stale-cost" in argv
    cost_override = parse_cost_args(argv)
    paths = [a for a in argv if not a.startswith("--") and "=" not in a]
    max_send = next((int(a.split("=", 1)[1]) for a in argv if a.startswith("--max=")), 10)
    if "--orders-api" in argv:
        try:
            orders = orders_from_api()
        except Exception as e:                                     # noqa: BLE001
            print(f"⚠️要対応: 注文 API を読めませんでした ({type(e).__name__}: {e}) → 何もしません")
            return 1
        print(f"対象: 注文 API (90日 {len(orders)}行) / {'本番' if write else 'まだ送りません (--write で実行)'}"
              f" / 1回の上限 {max_send}件")
    else:
        src = paths[0] if paths else W._find_desk_report()
        if not src or not os.path.isfile(src):
            print("注文レポートが見つかりません (reports フォルダに ebay-all-orders-report-*.csv)")
            return 2
        print(f"対象: {os.path.basename(src)} / {'本番' if write else 'まだ送りません (--write で実行)'}")
        orders = W.read_orders(src)

    pairs = [(o, W.category_of(o.get("Item Title") or "")) for o in orders]
    want = [(o, c) for o, c in pairs if c]
    if not want:
        print("補充対象カテゴリ (PSA / G-Shock / 一番くじ) の売上はありません")
        return 0

    sheets = W._sheets()
    try:
        fresh = fresh_cost_map(S.read_tab("PSA再仕入れ"))
    except Exception:                                              # noqa: BLE001
        fresh = {}
    print(f"今の仕入値 (🃏 PSA再仕入れ照合 の最安¥): {len(fresh)}件")
    # ★同じカードが既に live なら補充しない (本体と同じ判定)
    _live = {}
    try:
        import json as _json
        import itemid_writeback_audit as _A
        _live = _json.loads(_A.CACHE.read_text(encoding="utf-8"))
        already = live_keys(sheets, _live)
    except Exception:                                              # noqa: BLE001
        _live = {}
        already = set()
        print("  ⚠ live 一覧を読めず、同じカードの二重出品チェックを飛ばします")
    print(f"  既に live なカード: {len(already)}種類")
    # ★eBay の口は **今日の出品で実績のある** fix_de_speedpak_shipping を使う
    #   (ichibankuji_restock._sell_token は別 worktree のトークン path を見ていて動かない)
    import ebay_upload_csv as U
    import fix_de_speedpak_shipping as fx
    fx.refresh()
    tok = fx.token()

    done = skipped = acted = 0
    seen = set()
    pending = pending_rows(want, sheets)
    shipped_after = shipped_after_by_row(want, sheets)
    relisted = failed = 0
    for o, cat in want:
        sku = (o.get("Custom Label") or "").strip()
        iid = (o.get("Item Number") or "").strip()
        title = (o.get("Item Title") or "")[:56]
        label, n, row = W.find_row(sheets, sku, iid)
        if row is None:
            print(f"  ⏭ [{cat}] 台帳に行が無い: {title}")
            skipped += 1
            continue
        state, _aux = W.classify(row, live=_live or None)
        if state == "補充済":
            done += 1
            continue
        if state == "出品なし":
            print(f"  ⏭ [{cat}] 台帳の出品 {row[S.PRODUCT_COL_ITEMID].strip()} が出品一覧に無い → 触らない: {title}")
            skipped += 1
            continue
        target = restock_target(state, row, iid)
        if target in seen:
            continue
        seen.add(target)
        if (label, n) in pending:
            print(f"  ⏭ [{cat}] 未発送の注文がある (仕入れが済んでから戻す): {title}")
            skipped += 1
            continue
        _key = (row[S.PRODUCT_COL_KEY] or "").strip() if len(row) > S.PRODUCT_COL_KEY else ""
        if _key and _key in already:
            print(f"  ⏭ [{cat}] 同じカードが既に出品中 ({_key}) → 補充しない: {title}")
            skipped += 1
            continue

        cost = cost_override.get(sku) or cost_override.get(
            re.sub(r"\D", "", row[S.PRODUCT_COL_CERT] or "") if len(row) > S.PRODUCT_COL_CERT else "")
        stale = False
        if not cost:
            cost = fresh.get(card_no_of(o))
        if not cost:
            cost = _cost_from_row(row)
            stale = bool(cost) and not row_cost_is_current(row, after=shipped_after.get((label, n)))
        price, profile = price_for(cost, CATEGORY_FOR_PRICING.get(cat, "TCG(PSA10)"))
        # ★2026-09-04: 仕入値の上限 (global.yaml cost_sanity) はここにも効かせる。
        #   売れた物をもう一度出すのも「仕入れる」こと。新規と同じ基準にする。
        try:
            from pricing_engine import cost_sanity as _cs
            _ng = _cs(int(float(cost))) if cost else None
        except Exception:                                          # noqa: BLE001
            _ng = None

        status, qty, site = ebay_status(fx, U, target, tok)
        act = plan_action(status, qty)
        head = f"  [{cat}] row{n} {target} {title}"
        if site != "US":
            # eBaymag のミラーは触らない (親の US を戻せば付いてくる)。サイト不明も触らない
            print(f"{head}\n     → 出品サイトが {site} (US 以外) → 触らない")
            skipped += 1
            continue
        if act in ("noop", "skip"):
            print(f"{head}\n     → {act} (eBay状態={status} qty={qty}) 触らない")
            skipped += 1
            continue
        if _ng:
            print(head + chr(10) + "     → " + _ng + " → 補充しない")
            skipped += 1
            continue
        if not price:
            # ★仕入値が無いまま戻すと **元の値段のまま** 出てしまう。fail-closed で止める。
            print(f"{head}\n     → 仕入値が取れないので止めます (--cost で渡してください)")
            skipped += 1
            continue

        src_mark = " ⚠️古い仕入値 (監視くんの巡回が古い/仕入元が売切)" if stale else " 監視くんの今の最安"
        print(f"{head}")
        print(f"     → {act} / qty=1 / ${price} / {profile} "
              f"(仕入¥{int(cost):,}{src_mark})")
        if stale and write and not allow_stale:
            # 古い仕入値のまま戻すと「売れない値段」で並ぶ。既定では送らない。
            print("     → 止めました。今の仕入値を --cost で渡すか、"
                  "🃏 PSA再仕入れ照合 を先に走らせてください (--allow-stale-cost で強行)")
            skipped += 1
            continue
        if not write:
            acted += 1
            continue
        if acted >= max_send:
            # 急増ガード: 1回に送る数を絞る。残りは次の回 (データ不具合での一括送信を防ぐ)
            print(f"     → 1回の上限 {max_send}件に達したので、次の回に回します")
            skipped += 1
            continue
        call = "RelistFixedPriceItem" if act == "relist" else "ReviseFixedPriceItem"
        resp = fx.post(call, build_item_xml(target, price, profile), tok, U.SITE_US)
        ack, new_id, err = U.parse_ack(resp)
        if ack not in ("Success", "Warning"):
            print(f"     ❌ 失敗: {err[:120]}")
            continue
        new_id = new_id or target
        # 送った後に読み直して、在庫1になったかを確かめる (送れた ≠ 戻った)
        v_status, v_qty, _v_site = ebay_status(fx, U, new_id, tok)
        if v_status == "Active" and v_qty >= 1:
            print(f"     ✅ {call} → ItemID {new_id} (読み直し: 在庫{v_qty})")
        else:
            print(f"     ⚠️要対応: {call} は通ったが読み直すと 状態={v_status} 在庫={v_qty} (ItemID {new_id})")
            failed += 1
        if act == "relist":
            relisted += 1
        acted += 1

    print(f"\n補充済で何もしない {done} / 対象 {acted} / 見送り {skipped}"
          + (f" / ⚠️要対応 {failed}" if failed else ""))
    if acted and not write:
        print("→ 実行するには --write")
    if write and relisted:
        # 出し直すと番号が変わる。台帳の B列を合わせないと、監視くんが新しい出品を見られない
        import subprocess
        print("→ 出し直した分の itemID をスプシに反映します")
        subprocess.run([sys.executable, "-u", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                           "itemid_writeback_audit.py"), "--apply", "--no-cache"])
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
