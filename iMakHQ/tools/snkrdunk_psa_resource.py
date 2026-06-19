#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SNKRDUNK PSA10 再仕入れ可否チェック (card_id ベース)。

「売り切れURLの再訪」ではなく「そのカードを今 SNKRDUNK で(PSA10で)買えるか + 最安」を確認
= 再仕入れ可否ゲートの一チャネル (PSA10)。

技術 (2026-06-09 POC + 2026-05-11 harvest PoC で確定):
  - SNKRDUNK 検索ページは Next.js フルCSR で HTTP 不可。/trading-cards 系の一覧 API は
    keyword/param が効かず純フィード。**正しいのは card_id 引きの per-card API**:
      GET https://snkrdunk.com/en/v1/trading-cards/{card_id}/min-prices-by-conditions
      → {"conditionPrices":[{conditionName:"PSA 10"/"PSA 9"/"A".., minPrice:32800, minPriceFormat}]}
  - condition="PSA 10" の minPrice があれば再仕入れ可 (その価格で買える)。HTTP-only、Selenium不要。
  - card_id の取得は keyword検索ではなく sitemap→card_id 列挙 + 自カードとの突合 (harvest 領域)。
    既存 snkrdunk_scraper.py(iMak_inventory) は個別出品URLの在庫専用で別物。

入力: SNKRDUNK の trading-card card_id (CLI 引数 or import して check_resource)。
出力: {available, psa10_price_jpy, conditions} or {"_error":...} (fail-closed)。
"""
from __future__ import annotations

import re
import sys

import requests

API_TMPL = "https://snkrdunk.com/en/v1/trading-cards/{card_id}/min-prices-by-conditions"
SEARCH_URL = "https://snkrdunk.com/en/v1/search"      # productNumber→id 解決 (type=trading-card)
# 出品一覧API (condition別の実出品が取れる)。displayShortConditionTitle で 'PSA10' を判別。
# (2026-06-09 CDPで apparelesページのXHRから特定。/v1/ で /en/ 不要)。
LISTINGS_TMPL = "https://snkrdunk.com/v1/apparels/{card_id}/used?perPage=100&page=1&sizeId=0&isSaleOnly=true"
# 補URL: PSA10最安"出品"に直リンク (apparelesカードページは全condition混在で生カードが目立ち
# 「PSA10じゃない」と見える問題への対処。2026-06-09 ユーザー指摘)。listing_id 付きで PSA10 を直接開く。
LISTING_PAGE_TMPL = "https://snkrdunk.com/apparels/{card_id}/used/{listing_id}"
# フォールバック用カードページ (全PSA10出品が並ぶ日本語ページ)。snkrdunk はトレカも内部 "apparels"
# パスで扱う。実機確認: /apparels/{id}=JP表示 / /trading-cards/{id}=空404 / /en/trading-cards/{id}=英語。
CARD_PAGE_TMPL = "https://snkrdunk.com/apparels/{card_id}"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://snkrdunk.com/en/",
}
_TIMEOUT_SEC = 15
PSA10 = "PSA 10"


def parse_min_prices(data, condition=PSA10):
    """min-prices-by-conditions JSON → 指定 condition の最安を抽出。純関数(test可)。

    Returns: {available, psa10_price_jpy, conditions}
      available: 指定condition が在庫一覧に在り minPrice>0
    """
    rows = data.get("conditionPrices", []) if isinstance(data, dict) else []
    conds = {}
    for r in rows:
        name = (r.get("conditionName") or "").strip()
        if name:
            conds[name] = r.get("minPrice")
    price = conds.get(condition)
    try:
        price = int(price) if price is not None else None
    except (TypeError, ValueError):
        price = None
    return {
        "available": price is not None and price > 0,
        "psa10_price_jpy": price,
        "conditions": conds,
    }


def _hint_tokens(variant_hint):
    """variant_hint(canonical変種の set/name 文字列 or list) → 照合トークン list。

    kanji / katakana / set-code を**分離抽出**(混在連結を防ぐ=「神速」を単独トークンに)。
    set-code は [A-Z]{2,}+数字 (P1 等の suffix 雑音を除外)。short/単字は採らない(部分一致誤爆回避)。
    """
    if not variant_hint:
        return []
    parts = variant_hint if isinstance(variant_hint, (list, tuple)) else [variant_hint]
    toks = []

    def _add(t):
        if t and len(t) >= 2 and t not in toks:
            toks.append(t)
    for p in parts:
        s = (p or "").upper().replace(" ", "")
        for m in re.findall(r"[A-Z]{2,}-?\d{1,3}", s):   # set code: OP-11 / EB04 / PRB-02
            _add(m.replace("-", ""))
        for m in re.findall(r"[A-Z]{3,}", s):             # Latin set語 (EGGHEAD / CRISIS 等)
            _add(m)
        for m in re.findall(r"[一-龥]{2,}", s):           # 漢字ラン (神速 等)
            _add(m)
        for m in re.findall(r"[ァ-ヴー]{2,}", s):          # カタカナラン (ゼウス 等、ー含む)
            _add(m)
    return toks


def _print_signal(variant_hint):
    """canonical変種の print種別を返す: 'SPC'(SP/特別) / 'P'(パラレル/alt art) / ''(通常)。

    hint(card_meta_for_key の list)に variant_type='alt_art' / rarity='SPカード' 等が入る。
    同一set内の 通常 vs パラレル vs SP を marketplace の print マーカーと突合する基準。
    """
    parts = variant_hint if isinstance(variant_hint, (list, tuple)) else [variant_hint]
    s = " ".join(str(p) for p in parts if p).upper()
    if "SPカード".upper() in s or "SPC" in s or "スーパーパラレル".upper() in s:
        return "SPC"
    if "ALT_ART" in s or "PARALLEL" in s or "パラレル".upper() in s or "*" in s:
        return "P"               # rarity の * (Dragon Ball の L*/SR*/R* 等=パラレル)も検出
    return ""


def _item_print(name):
    """marketplace 商品名から print種別を判定: 'SPC' / 'P' / ''(通常)。

    SNKRDUNK rarity-print コード(例 'R-P'/'SR-P'/'R-SPC')や 'パラレル'/'SP' 表記を検出。
    """
    n = (name or "").upper()
    m = re.search(r"\b[A-Z]{1,3}-(SPC|SP|SEC|PR|P)\b", n)
    if m:
        return "SPC" if m.group(1) in ("SPC", "SP", "SEC") else "P"
    # Dragon Ball 等の rarity-asterisk(例 'L*'/'SR*'/'R*' [SB02-033])= パラレル。base(*無)と区別。
    if re.search(r"[A-Z]{1,3}\*", n):
        return "P"
    if "パラレル" in (name or "") or "PARALLEL" in n:
        return "P"
    if "スーパーパラレル" in (name or "") or "SPカード" in (name or ""):
        return "SPC"
    return ""


def _norm_cardnum(s):
    """card番号を比較用に正規化: 英数字のみ・大文字・'/'以降(総数)除去。

    'SV-P-291'→'SVP291' / 'SV2a 201/165'→'SV2A201' / 'OP11-106'→'OP11106'。
    set-code+番号を区切り(空白/ハイフン)非依存で id-strict 突合するための正規形。
    """
    s = (s or "").upper().split("/")[0]
    return re.sub(r"[^A-Z0-9]", "", s)


def _bracket_matches(name_upper, cn_norm):
    """name 内の `[...番号...]` を正規化して cn_norm と完全一致するか (Pokemon 等 productNumber 空 対応)。

    Pokemon は productNumber が空で番号が name の `[SV-P 291]` `[SV2a 201/165]` に埋まる。
    区切り差(空白/ハイフン)・総数(/165)を吸収しつつ **set-code+番号の完全一致のみ**採用
    (部分一致を許さない=誤マッチ防止。'S8a'≠'SV8a' は弾く=fail-closed)。
    """
    if not cn_norm:
        return False
    for m in re.findall(r"\[([^\]]+)\]", name_upper or ""):
        if _norm_cardnum(m) == cn_norm:
            return True
    return False


def _match_item(data, card_number, variant_hint=None):
    """search レスポンスから card_number に一致する trading-card の item dict を返す
    (純関数・id-strict)。id だけ欲しい時は parse_search_for_card、画像も要る時は item.thumbnailUrl。

    SNKRDUNK は鑑定カードを streetwears/sneakers バケツに入れる。name 中の `[CARD_NUMBER]`
    か productNumber 完全一致で突合。Pokemon は productNumber が空+番号が name の
    `[SV-P 291]`/`[SV2a 201/165]` に埋まるため、正規化(set-code+番号の完全一致)でも突合。
    Step6 P3: **同番号に複数 print** がある時(変種非決定性)、variant_hint(canonical変種の
    set/name トークン)で正しい product を選ぶ。決め手が無い複数一致は None (fail-closed=誤variant買わない)。
    一致が無ければ None (fail-closed)。
    """
    if not isinstance(data, dict):
        return None
    cn = (card_number or "").upper().strip()
    if not cn:
        return None
    cn_norm = _norm_cardnum(cn)
    items = []
    for bucket in ("streetwears", "sneakers", "tradingCards"):
        v = data.get(bucket)
        if isinstance(v, list):
            items.extend(v)
    matches = []
    for it in items:
        if not isinstance(it, dict):
            continue
        pn = (it.get("productNumber") or "").upper().strip()
        name = (it.get("name") or "").upper()
        # 英語版 [EN] は除外。日本語PSA再仕入れなので EN版は別カード(=JP と同番号で曖昧化し、
        # JP「L」と EN「L」が両残り→fail-closed→card_not_found を招く。例 SB02-033 が毎回候補なしの真因)。
        if "[EN]" in name.replace(" ", ""):
            continue
        if pn == cn or f"[{cn}]" in name.replace(" ", "") or _bracket_matches(name, cn_norm):
            matches.append(it)
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]                      # 単一一致 = 確定
    # 複数 print (変種非決定性): ①set トークンで絞る → ②同setで残れば print種別で tie-break
    toks = _hint_tokens(variant_hint)
    if not toks:
        return None                            # hint無で複数 = 曖昧 → fail-closed
    scored = [(sum(1 for t in toks if t in (it.get("name") or "").upper().replace(" ", "").replace("-", "")), it)
              for it in matches]
    top_score = max(s for s, _ in scored)
    if top_score <= 0:
        return None                            # set 決め手無 → fail-closed
    topgroup = [it for s, it in scored if s == top_score]
    if len(topgroup) == 1:
        return topgroup[0]                     # set で一意
    # 同 set 内に複数 print → print種別(parallel/special/通常)で tie-break
    target = _print_signal(variant_hint)
    matched = [it for it in topgroup if _item_print(it.get("name", "")) == target]
    if len(matched) == 1:
        return matched[0]
    return None                                # print でも一意化できず → fail-closed


def parse_search_for_card(data, card_number, variant_hint=None):
    """search レスポンス → card_number 一致の trading-card id (純関数・id-strict)。後方互換 wrapper。"""
    it = _match_item(data, card_number, variant_hint=variant_hint)
    return it.get("id") if isinstance(it, dict) else None


def resolve_card_id(card_number, timeout=_TIMEOUT_SEC, variant_hint=None, _meta=None):
    """productNumber(例 OP11-106) → SNKRDUNK trading-card id を HTTP 解決。Selenium不要・全シリーズ。

    Step6 P3: variant_hint(canonical変種の set/name) を渡すと、同番号の複数 print から正しい
    product を選ぶ(決め手無→fail-closed)。hint無は従来どおり(単一一致のみ確定)。
    _meta(dict) を渡すと _meta["thumbnail"] に商品画像URL(search の thumbnailUrl)を入れる
    = RESTOCK確証で実カード画像を出すため(listing ページの og:image はサイト既定ロゴで不可)。
    """
    if not card_number or not str(card_number).strip():
        return None
    try:
        r = requests.get(SEARCH_URL, headers=HEADERS, timeout=timeout,
                         params={"keyword": card_number, "type": "trading-card",
                                 "page": 1, "perPage": 20})
    except Exception:
        return None
    if r.status_code != 200:
        return None
    try:
        it = _match_item(r.json(), card_number, variant_hint=variant_hint)
    except Exception:
        return None
    if not isinstance(it, dict):
        return None
    if _meta is not None:
        _meta["thumbnail"] = it.get("thumbnailUrl") or ""
    return it.get("id")


def parse_psa10_listings(data, short_cond="PSA10"):
    """used listings JSON → PSA10 かつ販売中の [{listing_id, price}] を価格昇順で返す純関数。

    displayShortConditionTitle が 'PSA10' の出品のみ採用 (生カードB/A等を除外)。
    isDisplaySold=True は除外。これで「PSA10じゃない」混入を根絶 (2026-06-09 ユーザー指摘)。
    """
    items = data.get("apparelUsedItems", []) if isinstance(data, dict) else []
    want = short_cond.upper().replace(" ", "")
    out = []
    for it in items:
        if not isinstance(it, dict) or it.get("isDisplaySold"):
            continue
        cond = (it.get("displayShortConditionTitle") or "").upper().replace(" ", "")
        if cond != want:
            continue
        try:
            price = int(it.get("price"))
        except (TypeError, ValueError):
            continue
        lid = it.get("id")
        if price > 0 and lid:
            # primaryPhoto = 出品者の実スラブ写真(その出品個別)= RESTOCK確証で照合すべき実物画像。
            img = ((it.get("primaryPhoto") or {}).get("imageUrl") or "")
            out.append({"listing_id": lid, "price": price, "image": img})
    out.sort(key=lambda x: x["price"])
    return out


def fetch_psa10_listings(card_id, timeout=_TIMEOUT_SEC):
    """card_id の PSA10販売中出品を価格昇順で返す。API失敗時は None (= min-prices へフォールバック)。"""
    if not card_id or not str(card_id).strip():
        return None
    try:
        r = requests.get(LISTINGS_TMPL.format(card_id=str(card_id).strip()),
                         headers=HEADERS, timeout=timeout)
        if r.status_code != 200:
            return None
        return parse_psa10_listings(r.json())
    except Exception:
        return None


def check_by_keyword(card_number, condition=PSA10, timeout=_TIMEOUT_SEC, variant_hint=None):
    """productNumber から HTTP-only で PSA10 再仕入れ可否を判定。

    出品一覧API(displayShortConditionTitle='PSA10')で実PSA10出品の最安を取り、補URLは
    その PSA10最安"出品"に直リンク (混在カードページでなく直接PSA10)。出品API不調時のみ
    min-prices へフォールバック (補URL=カードページ)。
    Step6 P3: variant_hint(canonical変種の set/name) で同番号の複数 print を正しく選ぶ。
    Returns: {available, psa10_price_jpy, conditions, card_id, card_url} or {"_error":...}
    """
    _meta = {}                                       # resolve_card_id が thumbnail(実カード画像)を入れる
    cid = resolve_card_id(card_number, timeout=timeout, variant_hint=variant_hint, _meta=_meta)
    if cid is None:
        return {"_error": "card_not_found", "available": False, "psa10_price_jpy": None}
    card_image = _meta.get("thumbnail", "")          # RESTOCK確証で出す実カード画像(全PSA10出品で共通)
    listings = fetch_psa10_listings(cid, timeout=timeout)
    if listings is not None:                         # 出品API成功 = これを正とする
        if listings:
            # 価格昇順の全PSA10出品を補URL候補に (最安が売切/状態相違時の代替=補URLの存在意義)。
            # 各出品に listing_id 直リンク。最安以外も返すことで補URL列が機能する。
            psa10_listings = [
                {"price": x["price"], "image": x.get("image", ""),
                 "url": LISTING_PAGE_TMPL.format(card_id=cid, listing_id=x["listing_id"])}
                for x in listings
            ]
            return {"available": True, "psa10_price_jpy": psa10_listings[0]["price"],
                    "conditions": {}, "card_id": cid, "card_image": card_image,
                    "card_url": psa10_listings[0]["url"],
                    "psa10_listings": psa10_listings}
        return {"available": False, "psa10_price_jpy": None, "conditions": {},
                "card_id": cid, "card_image": card_image,
                "card_url": CARD_PAGE_TMPL.format(card_id=cid),
                "psa10_listings": []}
    # 出品API不調 → min-prices フォールバック
    res = check_resource(cid, condition=condition, timeout=timeout)
    if "_error" not in res:
        res["card_id"] = cid
        res["card_image"] = card_image
        res["card_url"] = CARD_PAGE_TMPL.format(card_id=cid)
    return res


def check_resource(card_id, condition=PSA10, timeout=_TIMEOUT_SEC):
    """card_id の condition別最安を取得 → 再仕入れ可否。通信/HTTP/JSON 失敗は {"_error":...}。"""
    if not card_id or not str(card_id).strip():
        return {"_error": "empty_card_id"}
    url = API_TMPL.format(card_id=str(card_id).strip())
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
    except Exception as e:
        return {"_error": f"http_error:{type(e).__name__}"}
    if r.status_code == 404:
        return {"_error": "http_404"}  # card_id 不在
    if r.status_code != 200:
        return {"_error": f"http_{r.status_code}"}
    try:
        data = r.json()
    except Exception:
        return {"_error": "json_parse"}
    return parse_min_prices(data, condition=condition)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if len(sys.argv) < 2:
        print("usage: snkrdunk_psa_resource.py <card_id> [<card_id> ...]")
        sys.exit(2)
    for cid in sys.argv[1:]:
        res = check_resource(cid)
        if "_error" in res:
            print(f"card {cid}: [!] {res['_error']}")
            continue
        flag = "再仕入れ可 ◎" if res["available"] else "PSA10在庫なし ✕"
        print(f"card {cid}: {flag}  PSA10最安=¥{res['psa10_price_jpy']}  全condition={res['conditions']}")


if __name__ == "__main__":
    main()
