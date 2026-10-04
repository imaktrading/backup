#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""棚② で落とす前に、ウォッチしている人へオファーを1回送る (2026-10-05 ユーザー確定)。

流れ (棚②のボタン = shelf_evict --end の中で動く):
    1. 落とす候補 (PSA) のうち、eBay が「今オファーを送れる」とした出品だけが対象
       (find_eligible_items。ウォッチ・カート離脱の人がいる出品。10/4 実測: 落とす31件中3件)
    2. 仕入元 + 補 のうち **今買える物が2本以上** ある時だけ送る (API で確かめる)。
       1本だと、受けてもらう前に切れたら仕入れられない
    3. 値段は **広告費の10%分を引く** (ユーザー「プロモ費が10%だから、その分割引けばいいか」)。
       **2番目に安い仕入元** で利益を計算し、赤字になるなら値引きを浅くする。1%でも赤字なら送らない
       (一番安い仕入元が先に売り切れても赤字にならない。一番高い物で計算すると 40件中24件しか
        10%引きで送れず「それだと、オファーする意味なくね？」→ 2番目で 35件)
    4. 送る前にその出品の **広告を外す** (広告を付けたまま10%引くと利益が1/3になる・offer_calc で実測)
    5. 送った物は台帳 (OFFERS_PATH) に残し、期限まで落とさない。期限が切れて売れていなければ、
       次に棚②を押した時に落とす。同じ出品に送るのは1回だけ
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
OFFER_DAYS = 2
MIN_SOURCES = 2
NEG = "https://api.ebay.com/sell/negotiation/v1"
MKT = "https://api.ebay.com/sell/marketing/v1"
MESSAGE = ("Thank you for watching this item! Here is a special price just for you. "
           "This offer is valid for a limited time.")


# ---------------------------------------------------------------- 純関数
def choose_discount(price, costs, profit_at, max_pct=DISCOUNT_MAX, min_sources=MIN_SOURCES):
    """(値引き%, オファー価格, 計算に使った仕入値, 理由) を返す。送らない時は 値引き%=None。

    profit_at(offer_price, cost) → 円の利益 (広告なし)。
    """
    costs = sorted(c for c in costs if c)
    if len(costs) < min_sources:
        return None, None, None, f"今買える仕入元が{len(costs)}本 (2本以上で送る)"
    basis = costs[1]                                  # 2番目に安い仕入元
    for pct in range(max_pct, 0, -1):
        offer = round(price * (100 - pct) / 100, 2)
        if profit_at(offer, basis) >= 0:
            return pct, offer, basis, ""
    return None, None, basis, "値引きすると赤字 (2番目に安い仕入元で計算)"


def offer_state(entry, now):
    """台帳の1件 → "offering" (期限前・落とさない) / "expired" (落としてよい) / None (未送信)。"""
    if not entry:
        return None
    try:
        exp = datetime.datetime.fromisoformat(entry["expires"])
    except (KeyError, ValueError, TypeError):
        return "expired"
    return "offering" if now < exp else "expired"


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
    """eBay が今オファーを送れるとした itemID。取れなければ None (= 送らない・落とす前の動きは今までどおり)。"""
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
    """US の RUNNING キャンペーン全部からその出品の広告を外す。外せた / 元から無い = True。"""
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


def send_offer(h, iid, offer_price):
    """ウォッチしている人へオファーを送る。戻り (成功, 理由)。"""
    import requests
    body = {"allowCounterOffer": False, "message": MESSAGE,
            "offerDuration": {"unit": "DAY", "value": OFFER_DAYS},
            "offeredItems": [{"listingId": iid, "quantity": 1,
                              "price": {"currency": "USD", "value": f"{offer_price:.2f}"}}]}
    try:
        r = requests.post(f"{NEG}/send_offer_to_interested_buyers", headers=h,
                          data=json.dumps(body), timeout=60)
    except Exception as e:                                     # noqa: BLE001
        return False, type(e).__name__
    if r.status_code in (200, 201):
        return True, ""
    return False, f"HTTP {r.status_code}: {r.text[:160]}"


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


def settle_expired(ledger, picked_ids, live_ids, send=False, log=print):
    """期限が切れたオファーの後始末 (I/O)。台帳の status を埋めて返す。

    - 出品がもう無い (売れた / 終わった) → status "売れた・終了" (オファーで売れたかは注文で数える)
    - まだ落とす候補 → "落とす" (呼び手が落とす)
    - 落とす候補から外れた → 広告 (8%) を付け直して "広告を戻した" (外したまま放置しない)
    status が付いた物は二度と処理しない。
    """
    todo = [(iid, e) for iid, e in ledger.items()
            if not e.get("status") and offer_state(e, datetime.datetime.now()) == "expired"]
    back = []
    for iid, e in todo:
        if live_ids is not None and iid not in live_ids:
            e["status"] = "売れた・終了"
        elif iid in picked_ids:
            e["status"] = "落とす"
        else:
            back.append(iid)
    if back:
        if not send:
            log(f"  💌 期限が切れて落とす候補から外れた {len(back)}件 → 押した時に広告を付け直します")
        else:
            try:
                import ads_add_new_listings as A
                for iid in back:
                    remove_no_ad(iid)
                res = dict(A.create_ads(A._token(), [(iid, iid) for iid in back]))
                for iid in back:
                    r = res.get(iid, "")
                    if r == "OK" or "already" in r.lower() or "exist" in r.lower():
                        ledger[iid]["status"] = "広告を戻した"
                    else:
                        add_no_ad(iid)
                        log(f"  ⚠ {iid} 広告を付け直せず ({r}) → 次回もう一度")
                log(f"  💌 期限切れ・落とさない {len(back)}件 の広告を付け直しました")
            except Exception as e:                             # noqa: BLE001
                log(f"  ⚠ 広告を付け直せず ({type(e).__name__}) → 次回もう一度")
    if send and todo:
        save_json(OFFERS_PATH, ledger)
    return ledger


def offer_before_drop(picked, is_psa, send=False, now=None, log=print, live_ids=None):
    """落とす候補 [(tier, row)] → 落とす物だけ返す。オファーを送った / オファー中の物は外す。

    send=False (試し) は eBay に何も書かず、送る予定を出すだけ。
    """
    now = now or datetime.datetime.now()
    ledger = load_json(OFFERS_PATH, {})
    settle_expired(ledger, {str(r.get("item_id")) for _t, r in picked}, live_ids, send=send, log=log)
    keep, offering, expired, plan = [], [], [], []
    for t, r in picked:
        iid = str(r.get("item_id") or "")
        st = offer_state(ledger.get(iid), now)
        if st == "offering":
            offering.append(iid)
            continue
        if st == "expired" and (ledger.get(iid) or {}).get("status") == "落とす":
            expired.append(iid)
        keep.append((t, r))
    if offering:
        log(f"  💌 オファー中 {len(offering)}件 は期限まで落としません")
    if expired:
        log(f"  💌 オファーの期限が切れて売れなかった {len(expired)}件 を落とします")
    cands = [(t, r) for t, r in keep if is_psa(r) and str(r.get("item_id")) not in ledger
             and float(str(r.get("watch") or 0).replace(",", "") or 0) > 0]
    if not cands:
        return keep
    try:
        h = _headers()
    except Exception as e:                                     # noqa: BLE001
        log(f"  ⚠ eBay の鍵を読めずオファーは送りません ({type(e).__name__}) → 今までどおり落とします")
        return keep
    el = eligible_ids(h)
    if el is None:
        log("  ⚠ オファーを送れる出品の一覧が取れない → 今までどおり落とします")
        return keep
    cands = [(t, r) for t, r in cands if str(r.get("item_id")) in el]
    if not cands:
        log("  💌 落とす候補に、eBay がオファーを送らせてくれる出品はありません")
        return keep
    import psa_hoju_fill as H
    import offer_calc as O
    rows = {H._cell(x, H.B): x for x in H._read_high()[1:] if H._cell(x, H.B)}
    p = O.fetch()
    ck = next(k for k in p["cats"] if "TCG" in k)
    sent = set()
    for t, r in cands:
        iid = str(r.get("item_id"))
        price = float(str(r.get("price") or 0).replace(",", "") or 0)
        row = rows.get(iid)
        urls = ([H._cell(row, 0)] + [H._cell(row, H.AUX0 + k) for k in range(H.AUXN)]) if row else []
        costs = buyable_costs(urls)
        pct, offer, basis, why = choose_discount(
            price, costs,
            lambda op, c: O.calc_py(p, "US計算", ck, "US", op, c, promo_on=False, listed=price))
        title = (r.get("title") or "")[:40]
        if pct is None:
            log(f"     ✗ {iid} 送らない ({why}) {title}")
            continue
        plan.append(iid)
        line = f"{iid} ${price:.2f} → ${offer:.2f} ({pct}%引き・仕入 ¥{basis:,} で計算) {title}"
        if not send:
            log(f"     → 送る予定: {line}")
            continue
        if not remove_ad(h, iid):
            log(f"     ✗ {iid} 広告を外せず送らない (落とします) {title}")
            continue
        add_no_ad(iid)
        ok, err = send_offer(h, iid, offer)
        if not ok:
            log(f"     ✗ {iid} オファーを送れず ({err}) → 落とします")
            continue
        ledger[iid] = {"sent": now.isoformat(timespec="seconds"),
                       "expires": (now + datetime.timedelta(days=OFFER_DAYS, hours=1)).isoformat(timespec="seconds"),
                       "price": price, "offer": offer, "pct": pct, "cost_basis": basis,
                       "costs": costs, "title": r.get("title") or ""}
        save_json(OFFERS_PATH, ledger)
        sent.add(iid)
        log(f"     💌 送った: {line}")
    if send:
        log(f"  💌 落とす前のオファー: 送った {len(sent)}件 (台帳 {OFFERS_PATH})")
        return [(t, r) for t, r in keep if str(r.get("item_id")) not in sent]
    log(f"  💌 落とす前のオファー (試し): 送る予定 {len(plan)}件 — --end の時に送り、期限まで落としません")
    return [(t, r) for t, r in keep if str(r.get("item_id")) not in set(plan)]
