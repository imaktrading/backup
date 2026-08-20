#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mirror_promo_bestoffer.py — UK/AU/CA のミラー出品に 広告10% と ベストオファー を付ける。

人が3サイトの画面を回って手でやっていた作業の自動化 (2026-08-21 ユーザー依頼)。

前提 (2026-08-21 実機確認):
    - UK/AU/CA の出品は **US本体の eBaymag ミラー**。1ページ248件の内訳は
      ebay.com 170 / com.au 27 / ca 26 / co.uk 25
    - eBaymag の「Promoted Listings 広告費率の同期」は **US と同率にする**機能で、
      10% にはできない。ユーザーが 2026-08-21 に OFF にしたので、率はこちらで入れる
    - ベストオファーは eBaymag に機能が無い。`ReviseFixedPriceItem` で付ける

安全側の作り:
    - 既定は **一覧を出すだけ**。`--write` を付けた時だけ eBay に書く
    - **既に広告に入っている出品は触らない** (eBaymag が作った 5%/9% のキャンペーンに
      入っている物がある。率を勝手に上書きすると取り合いになる)
    - 既にベストオファーが付いている出品も触らない
    - サイトの判定は **ViewItemURL のドメイン**。Site 要素は ActiveList では返らない

使い方:
    python mirror_promo_bestoffer.py              # 対象を数えるだけ
    python mirror_promo_bestoffer.py --write      # 実際に付ける
    python mirror_promo_bestoffer.py --only uk    # サイトを絞る
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r"C:\dev\iMak\iMakeBayAPI")

API = "https://api.ebay.com/sell/marketing/v1"
BID = "10.0"

# サイト → (ドメイン, Trading API の SiteID, Marketing の marketplace, 10%キャンペーン)
# キャンペーンIDは 2026-08-21 に RUNNING を実機で見て「率10.0」の物を選んだ。
# eBaymag が作る `Ebaymag-...` は 5%/9% が混在しているので使わない。
SITES = {
    "uk": ("ebay.co.uk", "3", "EBAY_GB", "160824676010"),
    "au": ("ebay.com.au", "15", "EBAY_AU", "160824732010"),
    "ca": ("ebay.ca", "2", "EBAY_CA", "164860042010"),
}


# ── 純関数 (test 可) ────────────────────────────────────────────────
def site_of(view_item_url):
    """ViewItemURL → サイトの略称。分からなければ空 (推測しない)。"""
    m = re.search(r"https?://(?:www\.)?([^/]+)", view_item_url or "")
    host = m.group(1).lower() if m else ""
    for key, (dom, _s, _m, _c) in SITES.items():
        if host == dom or host.endswith("." + dom):
            return key
    return ""


def parse_active(xml):
    """ActiveList の XML → [{item_id, site, best_offer, title}] (純関数)。"""
    out = []
    for it in re.findall(r"<Item>(.*?)</Item>", xml or "", re.S):
        iid = re.search(r"<ItemID>(\d+)</ItemID>", it)
        url = re.search(r"<ViewItemURL>(.*?)</ViewItemURL>", it)
        bo = re.search(r"<BestOfferEnabled>(\w+)</BestOfferEnabled>", it)
        ttl = re.search(r"<Title>(.*?)</Title>", it)
        if not iid:
            continue
        out.append({"item_id": iid.group(1),
                    "site": site_of(url.group(1) if url else ""),
                    "best_offer": (bo.group(1).lower() == "true") if bo else False,
                    "title": ttl.group(1) if ttl else ""})
    return out


def plan(items, advertised, only=""):
    """やることを決める (純関数)。戻り: {site: {promo, bo, ad_exists, bo_exists}}。

    既に広告に入っている物・既にベストオファーが付いている物は **触らない**。
    """
    out = {k: {"promo": [], "bo": [], "ad_exists": 0, "bo_exists": 0} for k in SITES}
    for it in items:
        s = it["site"]
        if not s or (only and s != only):
            continue
        if it["item_id"] in advertised:
            out[s]["ad_exists"] += 1
        else:
            out[s]["promo"].append(it["item_id"])
        if it["best_offer"]:
            out[s]["bo_exists"] += 1
        else:
            out[s]["bo"].append(it["item_id"])
    return out


# ── eBay とのやり取り ───────────────────────────────────────────────
def _mk_headers(tok, marketplace):
    return {"Authorization": "Bearer " + tok, "X-EBAY-C-MARKETPLACE-ID": marketplace,
            "Content-Type": "application/json"}


def fetch_active(fx, tok):
    """出品中を全ページ取る。取り切れなければ **例外**。

    途中で切れたのを「全部」と思うと、未処理を「対応済」と誤認する
    (failclosed_must_skip_not_destructive と同じ理由)。
    """
    items, page = [], 1
    while page <= 40:
        inner = ("<ActiveList><Include>true</Include><Pagination>"
                 "<EntriesPerPage>200</EntriesPerPage>"
                 "<PageNumber>%d</PageNumber></Pagination></ActiveList>"
                 "<DetailLevel>ReturnAll</DetailLevel>" % page)
        xml = fx.post("GetMyeBaySelling", inner, tok, site="0")
        if "<Ack>Failure</Ack>" in (xml or ""):
            raise RuntimeError("ActiveList の取得に失敗 (%d ページ目)" % page)
        got = parse_active(xml)
        if not got:
            break
        items.extend(got)
        page += 1
    return items


def fetch_advertised(tok):
    """RUNNING キャンペーン全部の ad を {listingId: 率} に畳む (サイト横断)。"""
    out = {}
    for _k, (_d, _s, mk, _c) in SITES.items():
        H = _mk_headers(tok, mk)
        camps = requests.get(API + "/ad_campaign", headers=H,
                             params={"campaign_status": "RUNNING", "limit": 200},
                             timeout=60).json().get("campaigns", [])
        for c in camps:
            if c.get("marketplaceId") != mk:
                continue
            for page in range(20):
                r = requests.get(API + "/ad_campaign/%s/ad" % c["campaignId"], headers=H,
                                 params={"limit": 500, "offset": page * 500}, timeout=60)
                if r.status_code != 200:
                    break
                ads = r.json().get("ads", [])
                for ad in ads:
                    if ad.get("listingId"):
                        out[str(ad["listingId"])] = str(ad.get("bidPercentage"))
                if len(ads) < 500:
                    break
    return out


def add_ads(tok, site_key, item_ids):
    """10% で そのサイトのキャンペーンに追加 → [(itemID, 結果)]。"""
    _d, _s, mk, camp = SITES[site_key]
    body = {"requests": [{"listingId": i, "bidPercentage": BID} for i in item_ids]}
    r = requests.post(API + "/ad_campaign/%s/bulk_create_ads_by_listing_id" % camp,
                      headers=_mk_headers(tok, mk), data=json.dumps(body), timeout=120)
    if r.status_code not in (200, 201, 207):
        return [(i, "HTTP %d: %s" % (r.status_code, r.text[:110])) for i in item_ids]
    out = []
    for res in r.json().get("responses", []):
        i = str(res.get("listingId"))
        if res.get("statusCode") in (200, 201):
            out.append((i, "OK"))
        else:
            errs = "; ".join(e.get("message", "") for e in (res.get("errors") or []))
            out.append((i, "NG %s: %s" % (res.get("statusCode"), errs[:90])))
    return out


def enable_best_offer(fx, tok, site_key, item_id):
    """その出品にベストオファーを付ける。**そのサイトの SiteID で呼ぶ**。"""
    _d, sid, _m, _c = SITES[site_key]
    inner = ("<ErrorLanguage>en_US</ErrorLanguage><WarningLevel>High</WarningLevel>"
             "<Item><ItemID>%s</ItemID><BestOfferDetails>"
             "<BestOfferEnabled>true</BestOfferEnabled></BestOfferDetails></Item>" % item_id)
    xml = fx.post("ReviseFixedPriceItem", inner, tok, site=sid)
    ack = re.search(r"<Ack>(\w+)</Ack>", xml or "")
    if ack and ack.group(1) in ("Success", "Warning"):
        return "OK"
    msgs = re.findall(r"<LongMessage>(.*?)</LongMessage>", xml or "")
    return "NG: " + (msgs[0][:110] if msgs else "応答不明")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="実際に付ける (既定は一覧だけ)")
    ap.add_argument("--only", default="", choices=[""] + list(SITES), help="サイトを絞る")
    ap.add_argument("--limit", type=int, default=0, help="各サイトこの件数まで (TEST用)")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                          # noqa: BLE001
        pass

    import ads_add_new_listings as ADS
    import fix_de_speedpak_shipping as fx
    fx.refresh()
    trading_tok = fx.token()
    sell_tok = ADS._token()

    items = fetch_active(fx, trading_tok)
    print("出品中 %d件 を確認" % len(items))
    advertised = fetch_advertised(sell_tok)
    print("すでに広告に入っている出品 %d件 (サイト横断・eBaymag 分を含む)" % len(advertised))

    todo = plan(items, advertised, a.only)
    for key in SITES:
        d = todo[key]
        if a.limit:
            d["promo"], d["bo"] = d["promo"][:a.limit], d["bo"][:a.limit]
        print("\n=== %s (%s)" % (key.upper(), SITES[key][0]))
        print("  広告10%%を付ける: %d件 / 既に広告あり(触らない): %d件"
              % (len(d["promo"]), d["ad_exists"]))
        print("  ベストオファーを付ける: %d件 / 既にあり(触らない): %d件"
              % (len(d["bo"]), d["bo_exists"]))

    if not a.write:
        print("\n→ 実際に付けるには --write")
        return 0

    ng = 0
    for key in SITES:
        d = todo[key]
        if d["promo"]:
            for i, res in add_ads(sell_tok, key, d["promo"]):
                if res != "OK":
                    ng += 1
                    print("  ⚠️ %s 広告 %s: %s" % (key, i, res))
            print("  ✅ %s 広告10%%: %d件 送信" % (key.upper(), len(d["promo"])))
        for i in d["bo"]:
            res = enable_best_offer(fx, trading_tok, key, i)
            if res != "OK":
                ng += 1
                print("  ⚠️ %s ベストオファー %s: %s" % (key, i, res))
        if d["bo"]:
            print("  ✅ %s ベストオファー: %d件 送信" % (key.upper(), len(d["bo"])))
    print(("\n失敗 %d件" % ng) if ng else "\n全件 成功")
    return 1 if ng else 0


if __name__ == "__main__":
    raise SystemExit(main())
