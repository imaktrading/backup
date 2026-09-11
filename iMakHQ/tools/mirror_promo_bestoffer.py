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
      (★2026-09-11 ユーザー「押したらやれよ」: パネルのボタンは確認なしで --write を呼ぶ)
    - **既に広告に入っている出品は触らない** (eBaymag が作った 5%/9% のキャンペーンに
      入っている物がある。率を勝手に上書きすると取り合いになる)
    - 既にベストオファーが付いている出品も触らない
    - ★2026-09-11: 出品一覧は **GetSellerList 1回の走査だけ**で取る (サイト/状態/ベストオファー
      が全部入っている)。サイトは `<Site>` で見る (GetSellerList の ViewItemURL は
      ミラーでも ebay.com になる)。**走査で見えた出品しか送らない** = 分からない物は触らない

★2026-09-11 に遅さの原因を実測で潰した (ユーザー「手でやったらすぐなのに」):
    - 押すと「数える」で全部取り → OK → 「実行」で **また全部取り直して**いた (2回)
    - ActiveList の読み方が XML 全体を拾い、**終了済みの出品**まで送っていた (185回 失敗)
    - 状態表の取得が1ページでも欠けると、残りが「付いていない」扱いになり、
      **成功済みに送り直して**いた (累計 1,454回。9/11 の走行は 256件中 163件がこれ)
    - サイズ表記が eBay に通らないミラーは何度送っても落ちる (206回)。1週間は送らない
    - 1件ずつ直列で ~2.8秒/件 → 4本並列

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
import time

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


# GetSellerList の <Site> → サイトの略称。US / Germany 等はここに無い = 対象外。
SITE_BY_NAME = {"UK": "uk", "Australia": "au", "Canada": "ca"}


# ── 純関数 (test 可) ────────────────────────────────────────────────
def parse_seller_list(xml):
    """GetSellerList (Fine) の1ページ → [{item_id, site, best_offer, title}] (純関数)。

    - サイトは `<Site>`。知らない名前は空 (= 触らない)
    - `<ListingStatus>` が Active 以外は入れない (終了済みに送らない)
    - `<BestOfferEnabled>` は付いていない時に省かれる → 無い = 付いていない
    """
    out = []
    for it in re.findall(r"<Item>(.*?)</Item>", xml or "", re.S):
        iid = re.search(r"<ItemID>(\d+)</ItemID>", it)
        st = re.search(r"<ListingStatus>(\w+)</ListingStatus>", it)
        if not iid or not st or st.group(1) != "Active":
            continue
        site = re.search(r"<Site>(\w+)</Site>", it)
        bo = re.search(r"<BestOfferEnabled>(\w+)</BestOfferEnabled>", it)
        ttl = re.search(r"<Title>(.*?)</Title>", it)
        out.append({"item_id": iid.group(1),
                    "site": SITE_BY_NAME.get(site.group(1) if site else "", ""),
                    "best_offer": bool(bo) and bo.group(1).lower() == "true",
                    "title": ttl.group(1) if ttl else ""})
    return out


# 何度送っても同じ理由で落ちる結果 → 何日 送らないか。
#   サイズ表記: eBaymag が値を直すまで通らない (累計 206回)。1週間おきに1回だけ試す
#   20135: そのサイトのカテゴリにベストオファーが無い。eBay は **Warning (=成功扱い) で返す**
#          ので、以前は「成功」と数えて押すたびに送り直していた (9/11 は 409件中 261件がこれ。
#          1件に6回送っていた)。カテゴリの仕様なので 30日おきに1回だけ試す
PERMANENT_NG = (("is not a valid value", 7), ("20135", 30))
BO_UNAVAILABLE = "SKIP: このカテゴリはベストオファー非対応 (20135)"


def recently_failed_for_good(log_lines, now=None):
    """進捗ログ → **最後の結果**が PERMANENT_NG で、まだ待つ日数内の itemID の集合 (純関数)。"""
    import datetime
    now = now or datetime.datetime.now()
    last = {}
    for ln in log_lines:
        try:
            r = json.loads(ln)
            last[r["item_id"]] = (r["ts"], r.get("result") or "")
        except (ValueError, KeyError, TypeError):
            continue
    out = set()
    for iid, (ts, res) in last.items():
        try:
            t = datetime.datetime.fromisoformat(ts)
        except ValueError:
            continue
        if any(k in res and (now - t).days < d for k, d in PERMANENT_NG):
            out.add(iid)
    return out


def plan(items, advertised, only="", bo_state=None):
    """やることを決める (純関数)。戻り: {site: {promo, bo, ad_exists, bo_exists}}。

    既に広告に入っている物・既にベストオファーが付いている物は **触らない**。
    """
    out = {k: {"promo": [], "bo": [], "ad_exists": 0, "bo_exists": 0} for k in SITES}
    # ★2026-08-21: ActiveList は同じ出品を複数ページに返すことがある (実測 6,837 対
    #   GetSellerList 4,898)。重複を残したまま bulk API に渡すと
    #   `errorId 35018 There are duplicate listing` で **チャンク丸ごと 400** になり、
    #   1件も追加されない。3サイトとも きっかり 200件 残っていたのはこれが原因。
    seen_ids = set()
    uniq = []
    for it in items:
        if it["item_id"] in seen_ids:
            continue
        seen_ids.add(it["item_id"])
        uniq.append(it)
    items = uniq
    for it in items:
        s = it["site"]
        if not s or (only and s != only):
            continue
        if it["item_id"] in advertised:
            out[s]["ad_exists"] += 1
        else:
            out[s]["promo"].append(it["item_id"])
        # ★状態表があればそれを真とする (ActiveList は BestOfferEnabled を返さない)。
        #   表に無い = 分からない → 付ける側に倒す (付け直しは無害、付け漏れは機会損失)
        has_bo = it["best_offer"]
        if bo_state is not None:
            has_bo = bo_state.get(it["item_id"], False)
        if has_bo:
            out[s]["bo_exists"] += 1
        else:
            out[s]["bo"].append(it["item_id"])
    return out


# ── eBay とのやり取り ───────────────────────────────────────────────
def _mk_headers(tok, marketplace):
    return {"Authorization": "Bearer " + tok, "X-EBAY-C-MARKETPLACE-ID": marketplace,
            "Content-Type": "application/json"}


def fetch_listings(fx, trading, page_tries=3):
    """出品中を GetSellerList (Fine) で全部取る → (items, 取れなかったページ番号の list)。

    ★2026-08-21: ActiveList は BestOfferEnabled を返さないので GetSellerList を使う。
    ★2026-09-11: 以前は ActiveList (一覧) と GetSellerList (状態) の2本を取っていた。
      状態の側は Failure のページで **黙って打ち切り**、残りの出品が「付いていない」扱いに
      なって成功済みに送り直していた。今は1本だけ取り、
      - Failure / 空のページは その場で page_tries 回 取り直す
      - それでも取れないページは **送らない** (見えていない出品は触らない) で、件数を報告する
    EndTimeFrom = 今 → 終了済みは最初から入らない。GTC は30日で更新されるので窓は1つで足りる
    (eBay の上限は 121日)。
    """
    import datetime
    from concurrent.futures import ThreadPoolExecutor
    now = datetime.datetime.utcnow()
    lo = now.strftime("%Y-%m-%dT%H:%M:%S")
    hi = (now + datetime.timedelta(days=119)).strftime("%Y-%m-%dT%H:%M:%S")

    def get_page(page):
        inner = ("<GranularityLevel>Fine</GranularityLevel>"
                 "<EndTimeFrom>%sZ</EndTimeFrom><EndTimeTo>%sZ</EndTimeTo>"
                 "<Pagination><EntriesPerPage>200</EntriesPerPage>"
                 "<PageNumber>%d</PageNumber></Pagination>" % (lo, hi, page))
        for _ in range(page_tries):
            tok = trading.get()
            xml = fx.post("GetSellerList", inner, tok, site="0") or ""
            if "<Ack>Failure</Ack>" not in xml and "<ItemArray>" in xml:
                return xml
            if _is_token_error(xml):
                trading.force(stale=tok)
            time.sleep(2)
        return ""

    first = get_page(1)
    m = re.search(r"<TotalNumberOfPages>(\d+)</TotalNumberOfPages>", first)
    if not m:
        raise RuntimeError("出品一覧の1ページ目が取れません (件数が分からないので中止)")
    pages = int(m.group(1))
    # ★2026-09-11: 1ページ ~7秒 × 19ページ = 2分強が待ちの大半。2ページ目以降は並べて取る
    #   (呼出回数は同じ)。並び順は元のページ順に戻す。
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        rest = list(ex.map(get_page, range(2, pages + 1)))
    items, missing = [], []
    for page, xml in zip(range(1, pages + 1), [first] + rest):
        if xml:
            items.extend(parse_seller_list(xml))
        else:
            missing.append(page)
    return items, missing


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


ADS_CHUNK = 200      # bulk API の1回あたり上限。超えた分は黙って捨てられる
AD_EXISTS = "SKIP: 既に広告あり"


def add_ads(tok, site_key, item_ids):
    """10% で そのサイトのキャンペーンに追加 → [(itemID, 結果)]。

    ★2026-08-21: 全件を1回の POST に詰めていたため、上限を超えた分が**応答にも現れず
      黙って落ちて**いた (3サイトとも きっかり 200件だけ残っていたのが症状)。
      chunk に割り、**送った数と返ってきた数が合わない時は明示的に NG にする**。
    """
    _d, _s, mk, camp = SITES[site_key]
    out = []
    for k in range(0, len(item_ids), ADS_CHUNK):
        chunk = item_ids[k:k + ADS_CHUNK]
        body = {"requests": [{"listingId": i, "bidPercentage": BID} for i in chunk]}
        r = requests.post(API + "/ad_campaign/%s/bulk_create_ads_by_listing_id" % camp,
                          headers=_mk_headers(tok, mk), data=json.dumps(body), timeout=120)
        if r.status_code not in (200, 201, 207):
            out += [(i, "HTTP %d: %s" % (r.status_code, r.text[:110])) for i in chunk]
            continue
        seen = set()
        for res in r.json().get("responses", []):
            i = str(res.get("listingId"))
            seen.add(i)
            errs = "; ".join(e.get("message", "") for e in (res.get("errors") or []))
            if res.get("statusCode") in (200, 201):
                out.append((i, "OK"))
            elif "already exists" in errs:
                # ★2026-09-11: RUNNING 以外のキャンペーンに入っている広告は fetch_advertised に
                #   見えず、毎回送って「既にある」で落ちていた (6件)。触らない側に数える
                out.append((i, AD_EXISTS))
            else:
                out.append((i, "NG %s: %s" % (res.get("statusCode"), errs[:90])))
        # 応答が返ってこなかった分を「成功」に数えない (silent drop を作らない)
        for i in chunk:
            if i not in seen:
                out.append((i, "NG: 応答に含まれず (上限で落ちた可能性)"))
    return out


TOKEN_MAX_AGE_SEC = 40 * 60      # 実測で ~2h 有効。余裕を持って 40分で取り直す
PROGRESS_LOG = r"C:\dev\iMak_data\hq\mirror_bestoffer_progress.jsonl"


class TradingToken:
    """Trading API のトークンを **時間が経ったら自分で取り直す** 係。

    ★2026-08-21 の実害: 3,504件を1件ずつ ReviseFixedPriceItem で送ると2時間を超え、
      最初に取ったトークンが途中で失効して **1,717件が丸ごと失敗**した
      (`IAF token supplied is expired`)。取り直す作りになっていなかった。
      長時間ループで最初のトークンを持ち回すのは、必ずこの形で壊れる。
    """

    def __init__(self, fx):
        import threading
        self.fx = fx
        self.value = fx.token()
        self.at = time.time()
        self.refreshed = 0
        self._lock = threading.Lock()      # ★2026-09-11: 並列で送るので取り直しは1本ずつ

    def get(self):
        if time.time() - self.at >= TOKEN_MAX_AGE_SEC:
            self.force()
        return self.value

    def force(self, stale=None):
        """取り直す。stale を渡すと、**その値のままの時だけ**取り直す
        (並列の4本が同時に失効を掴んでも、取り直しは1回で済む)。"""
        with self._lock:
            if stale is not None and self.value != stale:
                return
            self.fx.refresh()
            self.value = self.fx.token()
            self.at = time.time()
            self.refreshed += 1
            print("    (トークンを取り直しました %d回目)" % self.refreshed, flush=True)


import threading                                 # noqa: E402
_LOG_LOCK = threading.Lock()


def _log_progress(site_key, item_id, res):
    """1件ごとに追記する。**途中で落ちても どこまで済んだか残す**ため。"""
    try:
        os.makedirs(os.path.dirname(PROGRESS_LOG), exist_ok=True)
        with _LOG_LOCK, open(PROGRESS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                "site": site_key, "item_id": item_id,
                                "result": res}, ensure_ascii=False) + chr(10))
    except OSError:
        pass                                     # 記録できなくても本処理は続ける


def _read_progress_lines():
    try:
        with open(PROGRESS_LOG, encoding="utf-8") as f:
            return f.readlines()
    except OSError:
        return []


def _is_token_error(res):
    """失効・認証エラーか (純関数)。文言が変わっても拾えるよう緩めに見る。"""
    low = (res or "").lower()
    return ("token" in low and ("expire" in low or "invalid" in low or "auth" in low))         or "iaf token" in low


def enable_best_offer(fx, tok, site_key, item_id):
    """その出品にベストオファーを付ける。**そのサイトの SiteID で呼ぶ**。"""
    _d, sid, _m, _c = SITES[site_key]
    inner = ("<ErrorLanguage>en_US</ErrorLanguage><WarningLevel>High</WarningLevel>"
             "<Item><ItemID>%s</ItemID><BestOfferDetails>"
             "<BestOfferEnabled>true</BestOfferEnabled></BestOfferDetails></Item>" % item_id)
    xml = fx.post("ReviseFixedPriceItem", inner, tok, site=sid)
    ack = re.search(r"<Ack>(\w+)</Ack>", xml or "")
    # ★2026-09-11: カテゴリがベストオファー非対応だと eBay は **Warning 20135** で返し、
    #   付かない。Warning を一律「OK」にしていたので、付いていない物を成功と数えていた。
    if re.search(r"<ErrorCode>20135</ErrorCode>", xml or ""):
        return BO_UNAVAILABLE
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
    t0 = time.time()
    fx.refresh()
    trading = TradingToken(fx)
    sell_tok = ADS._token()

    items, missing = fetch_listings(fx, trading)
    print("出品中 %d件 を確認 (%.0f秒)" % (len(items), time.time() - t0), flush=True)
    if missing:
        print("⚠️ 取れなかったページ %d枚 (%s) — そこに載っている出品は今回 送りません"
              % (len(missing), ",".join(map(str, missing))))
    advertised = fetch_advertised(sell_tok)
    print("すでに広告に入っている出品 %d件 (サイト横断・eBaymag 分を含む)" % len(advertised),
          flush=True)

    todo = plan(items, advertised, a.only)
    skip = recently_failed_for_good(_read_progress_lines())
    for key in SITES:
        d = todo[key]
        d["skipped"] = [i for i in d["bo"] if i in skip]
        d["bo"] = [i for i in d["bo"] if i not in skip]
        if a.limit:
            d["promo"], d["bo"] = d["promo"][:a.limit], d["bo"][:a.limit]
        print("\n=== %s (%s)" % (key.upper(), SITES[key][0]))
        print("  広告10%%を付ける: %d件 / 既に広告あり(触らない): %d件"
              % (len(d["promo"]), d["ad_exists"]))
        print("  ベストオファーを付ける: %d件 / 既にあり(触らない): %d件"
              % (len(d["bo"]), d["bo_exists"]))
        if d["skipped"]:
            print("  (付けられない/サイズ表記で落ちる %d件は送らない)" % len(d["skipped"]))

    if not a.write:
        print("\n→ 実際に付けるには --write")
        return 0

    ng = 0
    for key in SITES:
        d = todo[key]
        if d["promo"]:
            res_ads = add_ads(sell_tok, key, d["promo"])
            for i, res in res_ads:
                if res not in ("OK", AD_EXISTS):
                    ng += 1
                    print("  ⚠️ %s 広告 %s: %s" % (key, i, res))
            print("  ✅ %s 広告10%%: %d件 付けた (既にあった %d件)"
                  % (key.upper(), sum(1 for _i, r in res_ads if r == "OK"),
                     sum(1 for _i, r in res_ads if r == AD_EXISTS)), flush=True)
    jobs = [(key, i) for key in SITES for i in todo[key]["bo"]]
    ok_by, ng_bo, na = send_best_offers(fx, trading, jobs)
    ng += ng_bo
    for key in SITES:
        if todo[key]["bo"]:
            print("  ✅ %s ベストオファー: %d件中 %d件 成功"
                  % (key.upper(), len(todo[key]["bo"]), ok_by.get(key, 0)), flush=True)
    if na:
        print("  (カテゴリがベストオファー非対応で付けられない %d件 — 30日は送りません)" % na)
    print("\n所要 %.0f秒" % (time.time() - t0))
    print(("失敗 %d件" % ng) if ng else "全件 成功")
    return 1 if ng else 0


WORKERS = 4      # ★2026-09-11: 1件 ~2.8秒の待ちが大半なので並べる。呼出回数は変わらない


def send_best_offers(fx, trading, jobs, workers=WORKERS, send=None):
    """[(site_key, itemID)] にベストオファーを付ける → ({site: 成功数}, 失敗数, 付けられない数)。

    send は test 用 (既定は enable_best_offer)。1件ごとに進捗ログへ書く。
    「付けられない」(カテゴリ非対応) は失敗に数えない (こちらで直せる物ではない)。
    """
    from concurrent.futures import ThreadPoolExecutor
    send = send or enable_best_offer
    ok_by, lock, state = {}, threading.Lock(), {"n": 0, "ng": 0, "na": 0}

    def _send(tok, key, i):
        try:
            return send(fx, tok, key, i)
        except Exception as e:                             # noqa: BLE001
            return "NG: %s: %s" % (type(e).__name__, str(e)[:80])   # 1件の例外で全体を止めない

    def one(job):
        key, i = job
        tok = trading.get()
        res = _send(tok, key, i)
        if _is_token_error(res):
            # 失効を掴んだら **その場で取り直して1回だけやり直す** (次の周回に送らない)
            trading.force(stale=tok)
            res = _send(trading.get(), key, i)
        _log_progress(key, i, res)
        with lock:
            state["n"] += 1
            if res == "OK":
                ok_by[key] = ok_by.get(key, 0) + 1
            elif res == BO_UNAVAILABLE:
                state["na"] += 1
            else:
                state["ng"] += 1
                print("  ⚠️ %s ベストオファー %s: %s" % (key, i, res), flush=True)
            if state["n"] % 100 == 0:
                print("    ベストオファー %d/%d 済" % (state["n"], len(jobs)), flush=True)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        list(ex.map(one, jobs))
    return ok_by, state["ng"], state["na"]


if __name__ == "__main__":
    raise SystemExit(main())
