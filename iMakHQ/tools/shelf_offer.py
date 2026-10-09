#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ウォッチしている人へオファーを送る仕組み (2026-10-05 ユーザー確定・管理表タブ「オファーの仕組み (案)」)。

送るのは **Seller Hub の画面から** (拡張 sellerhub_grab がこの一覧を読んで1件ずつ送る)。
    API (send_offer_to_interested_buyers) はカウンターを受けられない (eBay 仕様「must set false」)。
    ユーザー「カウンターは受けたいね」→「Seller Hub の画面から人が送る 拡張機能を作ってよ」。
    eBay の自動オファーは使わない (広告を外せない・仕入値で赤字を確かめられない)。

送る理由は2つ・仕組みと台帳は1つ (OFFERS_PATH):
    ① 棚②で落とす PSA (shelf_evict が落とす前にここを通す)  ② それ以外 (店全体・`plan` で一覧を作る)

送る条件と値段 (★2026-10-09 ユーザー確定で作り直し。旧: 仕入元2本以上・2番目の仕入元で利益計算・5〜10%):
    - eBay が「今オファーを送れる」とした US の出品 (find_eligible_items。ウォッチ・カート離脱がある) **全部**
      (棚②で落とす前の物もこの中に入る)
    - 仕入元が売り切れでない (商品管理シート D列が空) / バイヤーからのオファーが返事待ちでない / 30日以内に送っていない
    - 値引きは **広告費の分** = US 8% (OFFER_PCT_US)。広告を外して送るので、広告付きで売れた時と利益は同じ (利益計算はしない)
    - 神風のボタン「💌 オファーを送る」で一覧を作り、Edge の拡張が Seller Hub の画面から送る (カウンターを受けるため API では送らない)
    - 送ったオファー中に仕入元が切れても、監視くんの数量0で払えなくなる (2026-10-09 実機で数量0が通ることを確認)

台帳の状態 (status):
    送る待ち   一覧に載せた。拡張が送る前に広告を外す。WAIT_DAYS (2日) 送らなければ後始末
    送った     拡張が送った。期限は96時間 (ebay.com の画面から送ったオファー)
    (結果)     売れた・終了 / 落とす / 広告を戻した / 送らずに終了
"""
from __future__ import annotations

import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

OFFERS_PATH = r"C:/dev/iMak_data/hq/shelf2_offers.json"
NO_AD_PATH = r"C:/dev/iMak_data/hq/no_ad_items.json"
DISCOUNT_MAX = 10          # 広告費 (V9 の実効プロモ率 10%) の分
MIN_PCT = 5                # eBay の画面のオファーは5%引き以上
OFFER_HOURS = 96           # 画面から送ったオファーの期限 (ebay.com)
WAIT_DAYS = 2              # 一覧に載せて送らないまま この日数で後始末
RESEND_DAYS = 30           # 同じ出品に送るのは30日に1回
MIN_SOURCES = 2
WAITING, SENT = "送る待ち", "送った"
NEG = "https://api.ebay.com/sell/negotiation/v1"
MKT = "https://api.ebay.com/sell/marketing/v1"
MESSAGE = ("Thank you for watching this item! Here is a special price just for you. "
           "This offer is valid for a limited time.")


# ---------------------------------------------------------------- 純関数
def choose_discount(price, costs, profit_at, max_pct=DISCOUNT_MAX, min_sources=MIN_SOURCES, min_pct=MIN_PCT):
    """(値引き%, オファー価格, 計算に使った仕入値, 理由) を返す。送らない時は 値引き%=None。

    profit_at(offer_price, cost) → 円の利益 (広告なし)。
    """
    costs = sorted(c for c in costs if c)
    if len(costs) < min_sources:
        return None, None, None, f"今買える仕入元が{len(costs)}本 (2本以上で送る)"
    basis = costs[1]                                  # 2番目に安い仕入元
    for pct in range(max_pct, min_pct - 1, -1):
        offer = round(price * (100 - pct) / 100, 2)
        if profit_at(offer, basis) >= 0:
            return pct, offer, basis, ""
    return None, None, basis, f"{min_pct}%引きでも赤字 (2番目に安い仕入元で計算)"


def floor_price(price, basis, profit_at):
    """カウンターを受けてよい一番低い値段 (2番目に安い仕入元で利益0)。$0.5 刻みで上から探す (純関数)。"""
    lo = None
    p = round(price, 2)
    while p > 0 and profit_at(p, basis) >= 0:
        lo = p
        p = round(p - 0.5, 2)
    return lo


def offer_state(entry, now):
    """台帳の1件 → waiting / waiting_over / offering / expired / done / None (台帳に無い)。"""
    if not entry:
        return None
    if entry.get("status") not in (None, WAITING, SENT):
        return "done"
    try:
        if entry.get("status") == WAITING:
            t = datetime.datetime.fromisoformat(entry["planned"])
            return "waiting" if now < t + datetime.timedelta(days=WAIT_DAYS) else "waiting_over"
        exp = datetime.datetime.fromisoformat(entry["expires"])
    except (KeyError, ValueError, TypeError):
        return "expired"
    return "offering" if now < exp else "expired"


def recently_sent(entry, now, days=RESEND_DAYS):
    """30日以内に送った (= もう送らない)。"""
    try:
        return now - datetime.datetime.fromisoformat(entry.get("sent") or "") < datetime.timedelta(days=days)
    except (ValueError, TypeError):
        return False


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


# ---------------------------------------------------------------- I/O
def _headers():
    import ads_add_new_listings as A
    return {"Authorization": f"Bearer {A._token()}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
            "Content-Type": "application/json", "Accept": "application/json"}


def eligible_ids(h):
    """eBay が今オファーを送れるとした itemID。取れなければ None (= 一覧に載せない)。"""
    import requests
    out, url = set(), f"{NEG}/find_eligible_items?limit=200"
    try:
        while url:
            r = requests.get(url, headers=h, timeout=60)
            if r.status_code != 200:
                return None
            d = r.json()
            out |= {str(x.get("listingId")) for x in d.get("eligibleItems") or []}
            url = d.get("next")
    except Exception:                                          # noqa: BLE001
        return None
    return out


def buyable_costs(urls):
    """仕入元 + 補 の URL → 今買える物の値段 (円) の一覧。読めない物は数えない。"""
    import mercari_psa_resource as mp
    import snkrdunk_psa_resource as sp
    import psa_sold_cheapest as PC
    out, snkr = [], {}
    for u in urls:
        if not u:
            continue
        try:
            if "mercari" in u:
                d = mp.api_detail(u)
                if d and d.get("buyable") and d.get("price"):
                    out.append(int(d["price"]))
            elif "snkrdunk" in u:
                ok, pr, _img = PC.snkr_listing_now(sp, u, snkr)
                if ok and pr:
                    out.append(int(pr))
        except Exception:                                      # noqa: BLE001
            continue
    return out


def remove_ad(h, iid):
    """US の RUNNING キャンペーン全部からその出品の広告を外す (ミラーの10%は別キャンペーン・触らない)。"""
    import requests
    try:
        camps = requests.get(f"{MKT}/ad_campaign", headers=h,
                             params={"campaign_status": "RUNNING", "limit": 200},
                             timeout=60).json().get("campaigns", [])
    except Exception:                                          # noqa: BLE001
        return False
    ok = True
    for c in camps:
        if c.get("marketplaceId") != "EBAY_US":
            continue
        try:
            r = requests.post(f"{MKT}/ad_campaign/{c['campaignId']}/bulk_delete_ads_by_listing_id",
                              headers=h, data=json.dumps({"requests": [{"listingId": iid}]}), timeout=60)
            if r.status_code not in (200, 207):
                ok = False
                continue
            for res in r.json().get("responses") or []:
                if res.get("statusCode") not in (200, 204, 404) and \
                        not any("not found" in (e.get("message") or "").lower()
                                or e.get("errorId") in (35045, 35048) for e in res.get("errors") or []):
                    ok = False
        except Exception:                                      # noqa: BLE001
            ok = False
    return ok


def restore_ads(iids, log=print):
    """US の広告 (8%) を付け直す。戻り: 付け直せた itemID の集合。"""
    if not iids:
        return set()
    import ads_add_new_listings as A
    for iid in iids:
        remove_no_ad(iid)
    try:
        res = dict(A.create_ads(A._token(), [(iid, iid) for iid in iids]))
    except Exception as e:                                     # noqa: BLE001
        log(f"  ⚠ 広告を付け直せず ({type(e).__name__}) → 次回もう一度")
        for iid in iids:
            add_no_ad(iid)
        return set()
    ok = set()
    for iid in iids:
        r = res.get(iid, "")
        if r == "OK" or "already" in r.lower() or "exist" in r.lower():
            ok.add(iid)
        else:
            add_no_ad(iid)
            log(f"  ⚠ {iid} 広告を付け直せず ({r}) → 次回もう一度")
    return ok


def add_no_ad(iid, path=None):
    path = path or NO_AD_PATH
    d = load_json(path, {"iids": []})
    if iid not in d.get("iids", []):
        d.setdefault("iids", []).append(iid)
        save_json(path, d)


def no_ad_ids(path=None):
    return set(load_json(path or NO_AD_PATH, {"iids": []}).get("iids") or [])


def remove_no_ad(iid, path=None):
    path = path or NO_AD_PATH
    d = load_json(path, {"iids": []})
    if iid in (d.get("iids") or []):
        d["iids"] = [x for x in d["iids"] if x != iid]
        save_json(path, d)


WON, FULL = "オファーで成約", "定価で売れた"


def match_sales(ledger, sales_rows, item_col=1, date_col=4, price_col=6):
    """送ったオファーが売れたかを販売実績の行で決める (純関数)。台帳に outcome を書き、書いた件数を返す。

    ★2026-10-09 ユーザー「送ったオファーで成約になったものは、後でわかるの？効果測定という意味ね」。
      送った日〜期限の日に、その itemID の注文があり、売値がオファーの値段以下なら「オファーで成約」、高ければ「定価で売れた」。
      ミラー (別の itemID) の注文は数えない (オファーは US に送る)。
    """
    sold = {}
    for r in sales_rows or []:
        iid = (r[item_col] if len(r) > item_col else "").strip()
        if not iid:
            continue
        try:
            day = datetime.datetime.strptime((r[date_col] or "").strip(), "%Y/%m/%d").date()
            price = float(str(r[price_col]).replace(",", "").replace("$", ""))
        except (ValueError, IndexError):
            continue
        sold.setdefault(iid, []).append((day, price))
    n = 0
    for iid, e in ledger.items():
        if not e.get("sent") or e.get("outcome"):
            continue
        try:
            a = datetime.datetime.fromisoformat(e["sent"]).date()
            b = datetime.datetime.fromisoformat(e.get("expires") or e["sent"]).date()
        except (ValueError, TypeError):
            continue
        hit = [(d, p) for d, p in sold.get(iid, []) if a <= d <= b]
        if not hit:
            continue
        d, p = min(hit)
        offer = float(e.get("offer") or 0)
        e.update(outcome=WON if offer and p <= offer + 0.5 else FULL, sold_price=p, sold_day=d.isoformat())
        e["status"] = e["outcome"]
        n += 1
    return n


def offer_stats(ledger):
    """送った件数・オファーで成約・売上 (純関数)。神風に出す。"""
    sent = [e for e in ledger.values() if e.get("sent")]
    won = [e for e in sent if e.get("outcome") == WON]
    return {"sent": len(sent), "won": len(won), "won_usd": round(sum(float(e.get("sold_price") or 0) for e in won), 2),
            "full": sum(1 for e in sent if e.get("outcome") == FULL)}


def _read_sales():
    """販売実績の全行 (I/O)。読めなければ None。"""
    try:
        import order_purchase_sync as OPS
        import sheet_io as S
        ws = S._open(OPS.SALES_SHEET_ID).get_worksheet_by_id(OPS.SALES_GID)
        return S._read_with_quota_retry(ws.get_all_values)[1:]
    except Exception:                                          # noqa: BLE001
        return None


def settle(ledger, drop_ids, live_ids, write=False, log=print, now=None):
    """期限が来た物の後始末 (write=False は数えるだけ)。台帳の status を埋めて返す。

    送った → 期限切れ:  出品が無い = 売れた・終了 / 落とす候補 = 落とす / それ以外 = 広告を戻した
    送る待ち → 2日:     落とす候補 = 落とす / それ以外 = (広告を外していれば戻して) 送らずに終了
    """
    now = now or datetime.datetime.now()
    sales = _read_sales() if write else None                   # 試し (write=False) では販売実績を読まない
    if sales is not None:
        won = match_sales(ledger, sales)
        st_ = offer_stats(ledger)
        log(f"  📈 オファーの効果: 送った {st_['sent']}件 / オファーで成約 {st_['won']}件 (${st_['won_usd']:,.2f}) "
            f"/ 定価で売れた {st_['full']}件 (今回わかった {won}件)")
    back = []
    for iid, e in ledger.items():
        if e.get("outcome"):
            # 売れた出品も、補充されて出し直る時のために、期限が来たら外した広告を戻す (状態は成約のまま)
            try:
                over = now >= datetime.datetime.fromisoformat(e.get("expires") or "")
            except ValueError:
                over = True
            if over and e.get("ad_removed") and not e.get("ad_back"):
                back.append(iid)
            continue
        st = offer_state(e, now)
        if st not in ("expired", "waiting_over"):
            continue
        if live_ids is not None and iid not in live_ids:
            e["status"] = "売れた・終了"
        elif iid in drop_ids:
            e["status"] = "落とす"
        elif st == "waiting_over" and not e.get("ad_removed"):
            e["status"] = "送らずに終了"
        else:
            back.append(iid)
    if back:
        if not write:
            log(f"  💌 期限が来て落とさない {len(back)}件 → 押した時に US の広告を8%で付け直します")
        else:
            ok = restore_ads(back, log=log)
            for iid in ok:
                e = ledger[iid]
                if e.get("outcome"):
                    e["ad_back"] = now.isoformat(timespec="seconds")
                    continue
                e["status"] = "広告を戻した" if offer_state(e, now) == "expired" else "送らずに終了"
            if ok:
                log(f"  💌 期限が来て落とさない {len(ok)}件 の US 広告を8%で付け直しました")
    if write:
        save_json(OFFERS_PATH, ledger)
    return ledger


EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
SEND_URL = "https://www.ebay.com/sh/lst/active?offers=sendNewOffers&source=filterbar&action=search#shg-offers"
SEND_STAMP = r"C:/dev/iMak_data/hq/offers_send_requested.txt"
SEND_WINDOW_MIN = 15       # ★2026-10-09 ボタンを押してからこの分数の間だけ、拡張に一覧を渡す
SEND_BATCH = 10           # ★2026-10-09 ボタン1回で送る件数
OFFER_PCT_US = 8           # ★2026-10-09 ユーザー確定: 値引きは広告費の分 (US 8%・ミラーは 10%・ミラーはまだ送らない)


def pick_rows(rows, el, sheet, active_offer_ids, sold_col=3):
    """送る出品を選ぶ (純関数)。戻り: [(row, 理由 or "")] — 理由が空なら送る。

    ★2026-10-09 ユーザー確定「オファーが送れるものには全部送る」:
      - eBay が送れるとした出品 (el) / 商品管理シートにある / 仕入元が売り切れでない (D列が空 = 監視くんの判定)
      - バイヤーからのオファーが返事待ちの出品には送らない
      - 値引きは広告費の分なので利益計算はしない (広告付きで売れた時と同じ利益。「プロモぶんだから赤にはならない」)
    """
    out = []
    for r in rows:
        iid = str(r.get("item_id"))
        if iid not in el:
            continue
        row = sheet.get(iid)
        if not row:
            out.append((r, "商品管理シートに無い"))
        elif (row[sold_col].strip() if len(row) > sold_col else ""):
            out.append((r, "仕入元が売り切れ"))
        elif iid in active_offer_ids:
            out.append((r, "バイヤーからのオファーが返事待ち"))
        else:
            out.append((r, ""))
    return out


def active_offer_ids():
    """バイヤーからのオファーが返事待ちの itemID (I/O・GetBestOffers Active)。取れなければ None。"""
    try:
        import re as _re
        sys.path.insert(0, r"C:\dev\iMak\iMakeBayAPI")
        import fix_de_speedpak_shipping as fx
        import offer_calc as O
        fx.refresh()
        tok = fx.token()
        by = {}
        for n in range(1, 20):
            t = fx.post("GetBestOffers", "<BestOfferStatus>Active</BestOfferStatus>"
                        f"<Pagination><EntriesPerPage>100</EntriesPerPage><PageNumber>{n}</PageNumber></Pagination>"
                        "<DetailLevel>ReturnAll</DetailLevel>", tok, site="0")
            before = len(by)
            O.parse_best_offers(t, by)
            if len(by) == before:
                break
        return set(by)
    except Exception:                                          # noqa: BLE001
        return None


def count_sendable(now=None):
    """今ボタンを押したら送れる件数 (神風の「新規に出せる PSA」の横に出す・2026-10-09 ユーザー)。台帳は書かない (I/O)。

    戻り: {"n": 件数} / 読めなければ {"n": None, "error": 理由}。
    """
    import csv
    import glob
    now = now or datetime.datetime.now()
    try:
        ledger = load_json(OFFERS_PATH, {})
        fun = sorted(glob.glob(os.path.join(HERE, "..", "funnel_output", "funnel_*.csv")))
        rows = []
        if fun:
            with open(fun[-1], encoding="utf-8-sig", newline="") as f:
                rows = [r for r in csv.DictReader(f) if (r.get("site") or "") == "US"]
        rows = [r for r in rows if str(r.get("item_id")) not in ledger
                or (offer_state(ledger[str(r.get("item_id"))], now) == "done"
                    and not recently_sent(ledger[str(r.get("item_id"))], now))]
        el = eligible_ids(_headers())
        act = active_offer_ids()
        if el is None or act is None:
            return {"n": None, "error": "eBay の一覧が読めない"}
        import psa_hoju_fill as H
        sheet = {H._cell(x, H.B): x for x in H._read_high()[1:] if H._cell(x, H.B)}
        sales = _read_sales()
        if sales is not None and match_sales(ledger, sales):
            save_json(OFFERS_PATH, ledger)
        return {"n": sum(1 for _r, why in pick_rows(rows, el, sheet, act) if not why), **offer_stats(ledger)}
    except Exception as e:                                     # noqa: BLE001
        return {"n": None, "error": f"{type(e).__name__}: {e}"[:200]}


def plan_items(rows, ledger, now=None, log=print, reason="店全体", limit=None):
    """出品 [{item_id, price, watch, title}] → 送る待ちの台帳行を足す (I/O: eBay・シート)。戻り: 足した itemID の集合。"""
    now = now or datetime.datetime.now()
    rows = [r for r in rows if str(r.get("item_id")) not in ledger
            or (offer_state(ledger[str(r.get("item_id"))], now) == "done"
                and not recently_sent(ledger[str(r.get("item_id"))], now))]
    if not rows:
        return set()
    try:
        h = _headers()
    except Exception as e:                                     # noqa: BLE001
        log(f"  ⚠ eBay の鍵を読めずオファーの一覧を作れません ({type(e).__name__})")
        return set()
    el = eligible_ids(h)
    if el is None:
        log("  ⚠ オファーを送れる出品の一覧が取れない → 一覧に載せません")
        return set()
    act = active_offer_ids()
    if act is None:
        log("  ⚠ 返事待ちのオファーが読めない → 一覧に載せません (二重に値引きしないため)")
        return set()
    import psa_hoju_fill as H
    sheet = {H._cell(x, H.B): x for x in H._read_high()[1:] if H._cell(x, H.B)}
    added = set()
    # ★2026-10-09 ユーザー「一気処理だと時間かかるよね？1回10件とかにしない？」: limit 件まで。
    #   ウォッチの多い順 (買いそうな人が多い物から) → 値段の高い順
    def _num(v):
        try:
            return float(str(v or 0).replace(",", "") or 0)
        except ValueError:
            return 0.0
    picked = sorted(pick_rows(rows, el, sheet, act), key=lambda x: (bool(x[1]), -_num(x[0].get("watch")), -_num(x[0].get("price"))))
    for r, why in picked:
        if limit is not None and len(added) >= limit and not why:
            continue
        iid = str(r.get("item_id"))
        title = (r.get("title") or "")[:40]
        if why:
            log(f"     ✗ {iid} 載せない ({why}) {title}")
            continue
        price = float(str(r.get("price") or 0).replace(",", "") or 0)
        offer = round(price * (100 - OFFER_PCT_US) / 100, 2)
        ledger[iid] = {"status": WAITING, "planned": now.isoformat(timespec="seconds"), "reason": reason,
                       "price": price, "pct": OFFER_PCT_US, "offer": offer, "floor": None,
                       "title": r.get("title") or ""}
        added.add(iid)
        log(f"     💌 一覧に載せた ({reason}): {iid} ${price:.2f} → {OFFER_PCT_US}%引き ${offer:.2f} {title}")
    return added


def offer_before_drop(picked, is_psa, send=False, now=None, log=print, live_ids=None):
    """棚② の落とす候補 [(tier, row)] → 落とす物だけ返す。オファーの一覧に載る / 送った物は落とさない。

    send=False (試し) は台帳を書かず、載せる予定を出すだけ。
    """
    now = now or datetime.datetime.now()
    ledger = load_json(OFFERS_PATH, {})
    drop_ids = {str(r.get("item_id")) for _t, r in picked}
    settle(ledger, drop_ids, live_ids, write=send, log=log, now=now)
    keep, hold = [], []
    for t, r in picked:
        iid = str(r.get("item_id") or "")
        if offer_state(ledger.get(iid), now) in ("waiting", "offering"):
            hold.append(iid)
            continue
        keep.append((t, r))
    if hold:
        log(f"  💌 オファーの一覧に載っている / 送った {len(hold)}件 は期限まで落としません")
    cands = [r for t, r in keep if is_psa(r) and float(str(r.get("watch") or 0).replace(",", "") or 0) > 0]
    new = plan_items(cands, ledger if send else dict(ledger), now=now, log=log, reason="棚②") if cands else set()
    if send:
        save_json(OFFERS_PATH, ledger)
        if new:
            log(f"  💌 落とす前のオファー: {len(new)}件を送る一覧に載せました (Seller Hub で拡張が送ります・2日送らなければ落とします)")
    elif new:
        log(f"  💌 落とす前のオファー (試し): {len(new)}件を送る一覧に載せる予定 — --end の時に載せ、落としません")
    return [(t, r) for t, r in keep if str(r.get("item_id")) not in new]


# ---------------------------------------------------------------- 拡張・神風から呼ぶ
def send_requested(now=None, path=None):
    """ボタンを押してから SEND_WINDOW_MIN 分以内か (I/O)。

    ★2026-10-10 ユーザー「勝手にオファーを送る動いてなかった？」: 前の晩の Seller Hub のタブが Edge の起動で
      #shg-offers 付きのまま復元され、拡張が残りの一覧を送った (06:56 に1件)。押した直後だけ渡す。
    """
    now = now or datetime.datetime.now()
    try:
        with open(path or SEND_STAMP, encoding="utf-8") as f:
            t = datetime.datetime.fromisoformat(f.read().strip())
    except (OSError, ValueError):
        return False
    return now - t <= datetime.timedelta(minutes=SEND_WINDOW_MIN)


def waiting_list(now=None):
    """送る待ちの一覧 (拡張が読む)。"""
    now = now or datetime.datetime.now()
    ledger = load_json(OFFERS_PATH, {})
    return [dict(e, item_id=iid) for iid, e in ledger.items() if offer_state(e, now) == "waiting"]


def prepare(iid):
    """拡張が送る直前に呼ぶ: US の広告を外す。外せなければ送らない。"""
    ledger = load_json(OFFERS_PATH, {})
    e = ledger.get(iid)
    if not e or e.get("status") != WAITING:
        return {"ok": False, "error": "送る待ちに無い出品"}
    if not remove_ad(_headers(), iid):
        return {"ok": False, "error": "広告を外せなかった"}
    add_no_ad(iid)
    e["ad_removed"] = datetime.datetime.now().isoformat(timespec="seconds")
    save_json(OFFERS_PATH, ledger)
    return {"ok": True, "pct": e.get("pct")}


def mark_sent(iid, pct=None):
    """拡張が送れた時に呼ぶ: 台帳を「送った」にして期限 (96時間) を入れる。"""
    ledger = load_json(OFFERS_PATH, {})
    e = ledger.get(iid)
    if not e:
        return {"ok": False, "error": "台帳に無い出品"}
    now = datetime.datetime.now()
    e.update(status=SENT, sent=now.isoformat(timespec="seconds"),
             expires=(now + datetime.timedelta(hours=OFFER_HOURS)).isoformat(timespec="seconds"))
    if pct is not None:
        e["pct_sent"] = pct
    save_json(OFFERS_PATH, ledger)
    return {"ok": True}


def build_store_plan(log=print, limit=None):
    """店全体: eBay が送れるとした PSA 出品を一覧に載せる (神風のボタン)。期限の後始末もする。"""
    import csv
    import glob
    ledger = load_json(OFFERS_PATH, {})
    fun = sorted(glob.glob(os.path.join(HERE, "..", "funnel_output", "funnel_*.csv")))
    rows = []
    if fun:
        with open(fun[-1], encoding="utf-8-sig", newline="") as f:
            rows = [r for r in csv.DictReader(f) if (r.get("site") or "") == "US"]
    live = {str(r.get("item_id")) for r in rows}
    try:
        import shelf_evict as SE
        drops = set(load_json(SE.LAST_PSA_DROPS, {}).get("iids") or [])
    except Exception:                                          # noqa: BLE001
        drops = set()
    settle(ledger, drops, live or None, write=True, log=log)
    plan_items(rows, ledger, log=log, reason="店全体", limit=limit)
    save_json(OFFERS_PATH, ledger)
    w = waiting_list()
    log(f"💌 送る一覧: {len(w)}件")
    return w


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                          # noqa: BLE001
        pass
    if len(sys.argv) > 1 and sys.argv[1] == "plan":
        build_store_plan()
    elif len(sys.argv) > 1 and sys.argv[1] == "send":
        # ★2026-10-09 ユーザー「突然送られると他業務の邪魔になるから、ボタン化して」: 神風のボタンから。
        #   一覧を作り (期限の後始末も)、あれば Seller Hub の送る画面を Edge で開く → 拡張が送ってタブを閉じる
        w = build_store_plan(limit=SEND_BATCH)
        if w:
            import subprocess
            import time as _t
            with open(SEND_STAMP, "w", encoding="utf-8") as f:            # 押した時刻 (拡張はこの15分だけ送る)
                f.write(datetime.datetime.now().isoformat(timespec="seconds"))
            subprocess.Popen([EDGE, SEND_URL])
            print(f"💌 Seller Hub を Edge で開きました: {len(w)}件を拡張が送ります", flush=True)
            # ★2026-10-09 ユーザー「送ってる最中なのに、ログは終わりましたになるね」: 送り終わるまで待って結果を出す
            ids = {e["item_id"] for e in w}
            last, still_since = None, _t.time()
            while True:
                _t.sleep(10)
                led = load_json(OFFERS_PATH, {})
                left = [i for i in ids if (led.get(i) or {}).get("status") == WAITING]
                sent = [i for i in ids if (led.get(i) or {}).get("status") == SENT]
                if left != last:
                    print(f"   … 送った {len(sent)}件 / 残り {len(left)}件", flush=True)
                    last, still_since = left, _t.time()
                if not left or _t.time() - still_since > 180:          # 全部送れた / 3分動かない = 拡張が止まった
                    break
            print(f"💌 終わり: 送った {len(sent)}件 / 送れなかった {len(left)}件"
                  + (" (送れなかった分は2日後に広告を戻して終わり・次に押せばまた候補に出る)" if left else ""))
        else:
            print("💌 送る物はありません")
    else:
        for e in waiting_list():
            print(f"{e['item_id']} {e.get('reason')} {e.get('pct')}%引き ${e.get('offer')} 下限 ${e.get('floor')} {e.get('title', '')[:40]}")
