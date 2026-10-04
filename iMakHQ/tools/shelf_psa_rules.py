#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""棚② PSA の「落とす / 補優先 / 残す」を決める表 (2026-10-04 ユーザー確定)。

表の正本は管理表 (17H4ETRh…) のタブ「棚②の新ルール案 (HQ)」、図は
https://claude.ai/artifact/9EoqTWrpe6iKEBbeVVLTHW 。番号 (①③⑦⑧⑩⑪⑫⑭ / 0b / 11b / M0〜M4) は表の行と同じ。

対象: PSA (カテゴリ TCG)・在庫あり・売れたことが無い・出品30日超 (shelf_evict の ② に入った物)。

    1. 表 (補の有無 × 日数 × 値下げ済み × ウォッチ × 閲覧 × 前の90日比) で 取下げ / 補優先 / 残す
    2. 取下げになった物に **市場の門** をかける
         M0 出品90日以上               → 取下げ (ケツ。市場の門をかけない)
         M1/M2 同じ日本語版 PSA10 が今9件以下 → 残す (うちしか出していない・競争が少ない)
         M3 10件以上・うちが相場の1.2倍超  → 取下げ (値段で勝てない)
         M4 10件以上・相場と同じくらい以下 → 残す (見られ方の問題)
       市場の数が取れない時は **残す** (判断できない物を落とさない)

★2026-10-04 ユーザー「落としだして増えている、オファーの数とかかなり増えている」= 落とすのは効いている。
  残す側に倒すのは90日まで。90日を過ぎたら市場に関係なく落とす (「ケツは決めないとね」「90日でいいんじゃない？」)。
★「多い」の境目10件はユーザー確定 (10/4 試算: 真ん中12件)。数えるのは Japanese/JP と書いてあり、
  うちに無い印 (マスターボール・リバース・漫画・別イラスト・英語等) の付かない物だけ。
  数えすぎると「多い」と出て落とす側に寄るので、迷う物は数えない。
★決めた結果は1件ずつ台帳 (DECISIONS_PATH) に残す。市場の門で残した物が後で売れたか、
  落とした物が当たっていたかを1〜2か月後に数えるため (ユーザー「やってみよう」の前提)。
"""
from __future__ import annotations

import csv
import datetime
import glob
import json
import os
import re
import statistics
import sys

CAP_AGE = 90            # これ以上は市場に関係なく落とす (M0)
MID_AGE = 60
MARKET_MANY = 10        # 同じ日本語版 PSA10 がこれ以上出ていれば「多い」
PRICE_HIGH = 1.2        # 相場のこれ倍を超えたら「高い」
VIEW_SEEN = 6           # 過去90日の閲覧がこれ以上なら「見られた」

TRAFFIC_GLOBS = (r"C:/dev/iMak_data/seller_hub/reports/**/eBay-ListingsTrafficReport-*.csv",
                 r"C:/Users/imax2/Downloads/eBay-ListingsTrafficReport-*.csv")
DECISIONS_PATH = r"C:/dev/iMak_data/hq/shelf2_decisions.jsonl"
HOJU_PRIORITY_PATH = r"C:/dev/iMak_data/hq/shelf2_hoju_priority.json"

DROP, HOJU, KEEP = "取下げ", "補優先", "残す"

# 前の90日と比べる表示の4項目 (検索/検索以外 × 広告/広告以外) の列
_CHANGE_COLS = ("% Change in Top 20 search spot impressions from promoted listings",
                "% Change in Top 20 search spot impressions",
                "% Change in non-search promoted listings impressions",
                "% Change in non-search organic impressions")


def _num(v):
    v = str(v or "").replace("%", "").replace(",", "").replace('="', "").replace('"', "").strip()
    try:
        return float(v)
    except ValueError:
        return None


def parse_traffic(lines):
    """トラフィックレポートの行 → {itemID: (閲覧, [4項目の増減%])} (純関数)。"""
    hi = next((i for i, l in enumerate(lines) if l.startswith("Listing title")), None)
    if hi is None:
        return {}
    rd = csv.reader(lines[hi:])
    h = next(rd)
    try:
        ii, vi = h.index("eBay item ID"), h.index("Total page views")
        ci = [h.index(c) for c in _CHANGE_COLS]
    except ValueError:
        return {}
    out = {}
    for r in rd:
        if len(r) <= max([ii, vi] + ci):
            continue
        iid = str(r[ii]).replace('="', "").replace('"', "").strip()
        if iid:
            out[iid] = (_num(r[vi]) or 0.0, [_num(r[c]) for c in ci])
    return out


def load_traffic(globs=TRAFFIC_GLOBS):
    """一番新しいトラフィックレポート (I/O)。無ければ ({}, "")。"""
    files = []
    for g in globs:
        files += glob.glob(g, recursive=True)
    if not files:
        return {}, ""
    f = max(files, key=os.path.getmtime)
    try:
        with open(f, encoding="utf-8-sig") as fh:
            return parse_traffic(fh.read().splitlines()), f
    except OSError:
        return {}, ""


def grown(ch):
    """4項目とも前の90日より増えた (0%以上)。"""
    return bool(ch) and all(c is not None and c >= 0 for c in ch)


def buried(ch):
    """4項目のうち半分を超える項目が半分以下 (-50%以下) に減った。"""
    return bool(ch) and sum(1 for c in ch if c is not None and c <= -50) > len(ch) / 2


def table_verdict(age, has_aux, down, watch, views, ch):
    """表の判定 (純関数)。戻り (取下げ/補優先/残す, 表の番号)。

    views=None = 閲覧が分からない (レポートに無い)。「見られていない」が要る行では落とさない。
    """
    if age >= CAP_AGE and grown(ch):
        return KEEP, "0b 伸びている"
    if age >= CAP_AGE and buried(ch):
        return DROP, "11b 埋もれた"
    if has_aux:
        if age < MID_AGE:
            if down and not watch:
                return DROP, "①③ 値下げ済・ウォッチ無"
            return HOJU, "②④⑤⑥ 補優先"
        if age < CAP_AGE:
            if not watch:
                return DROP, ("⑦⑧ 値下げ済・ウォッチ無" if down else "⑩ 補優先でも下げられない")
            return HOJU, ("⑨ 補優先" if down else "⑩b 補優先")
        return DROP, "⑪ 90日"
    if age < MID_AGE:
        if views is None:
            return KEEP, "⑫? 閲覧不明"
        if views < VIEW_SEEN:
            return DROP, "⑫ 補無・見られない"
        return HOJU, "⑬ 補無・補を探す"
    return DROP, "⑭ 補無・60日"


_JP = re.compile(r"JAPANESE|\bJAP\b|\bJP\b|\bJPN\b|JAPAN|日本")
_EXTRA = ("MASTER BALL", "POKE BALL", "POKEBALL", "REVERSE", "MANGA", "ALT ART", "ALTERNATE ART",
          "PARALLEL", " EN ", "ENGLISH", "CHINESE", "KOREAN", "SIGNED", "STAMP", "PRERELEASE")
_PSA10 = re.compile(r"PSA\s?10")


def same_listing(ours, theirs, num):
    """市場の出品が うちと同じ商品 (日本語版・同じ刷りの PSA10) か (純関数)。迷えば False。"""
    o, t = " " + (ours or "").upper() + " ", " " + (theirs or "").upper() + " "
    if not num or num.upper() not in t or not _PSA10.search(t) or not _JP.search(t):
        return False
    if not all((w in o) or (w not in t) for w in _EXTRA):
        return False
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import market_ledger as ML
        return ML.same_product(ours, theirs)
    except Exception:                                          # noqa: BLE001
        return True


def card_query(title):
    """うちのタイトル → (検索語, カード番号)。番号が無ければ ("", "")。"""
    m = re.search(r"#(\S+)", title or "")
    if not m:
        return "", ""
    num = m.group(1)
    rest = (title or "").split(m.group(0), 1)[1].split()
    return " ".join(x for x in ("PSA 10", num, rest[0] if rest else "") if x), num


def market_stats(title, item_id, items):
    """検索結果 → (同じ物の数, 出品中の値段の真ん中) (純関数)。"""
    _q, num = card_query(title)
    def _legacy(i):                          # "v1|358...|0" → "358..." (うち自身を数えない)
        parts = str(i.get("legacyItemId") or i.get("itemId") or "").split("|")
        return parts[1] if len(parts) > 1 else parts[0]
    same = [i for i in items or [] if _legacy(i) != str(item_id)
            and same_listing(title, i.get("title"), num)]
    prices = []
    for i in same:
        try:
            prices.append(float(i["price"]["value"]))
        except (KeyError, TypeError, ValueError):
            pass
    return len(same), (statistics.median(prices) if prices else None)


def market_verdict(age, price, stat):
    """市場の門 (純関数)。stat=None (取れない) は残す。戻り (取下げ/残す, 番号)。"""
    if age >= CAP_AGE:
        return DROP, "M0 90日・ケツ"
    if stat is None:
        return KEEP, "M? 市場の数が取れない"
    n, med = stat
    if n == 0:
        return KEEP, "M1 市場に無い"
    if n < MARKET_MANY:
        return KEEP, "M2 市場に少ない"
    if med and price > med * PRICE_HIGH:
        return DROP, "M3 多い・うちが高い"
    return KEEP, "M4 多い・値段は負けていない"


class Market:
    """eBay の検索 API で市場の出品を引く (I/O)。トークンが取れなければ全部 None (= 残す)。"""

    def __init__(self):
        self.tok, self.err = None, ""
        try:
            sys.path.insert(0, os.path.normpath(os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "..", "..", "iMakeBayAPI")))
            import check_csv_core as C
            k = C.load_ebay_keys()
            self.tok = C.get_oauth_token(k["AppID"], k["AppSecret"])
        except Exception as e:                                 # noqa: BLE001
            self.err = f"{type(e).__name__}"

    def stat(self, title, item_id):
        q, _num = card_query(title)
        if not self.tok or not q:
            return None
        import requests
        try:
            r = requests.get("https://api.ebay.com/buy/browse/v1/item_summary/search",
                             headers={"Authorization": f"Bearer {self.tok}",
                                      "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"},
                             params={"q": q, "limit": 100}, timeout=30)
            if r.status_code != 200:
                return None
            return market_stats(title, item_id, r.json().get("itemSummaries") or [])
        except Exception:                                      # noqa: BLE001
            return None


def judge(row, has_aux, down, traffic, market=None):
    """1件の判定 (market 以外は純関数)。戻り dict (verdict, code, 材料)。"""
    f = lambda v: float(str(v or 0).replace(",", "") or 0)        # noqa: E731
    iid = str(row.get("item_id") or "")
    age, price, watch = f(row.get("age_days")), f(row.get("price")), f(row.get("watch")) > 0
    tv = traffic.get(iid)
    views, ch = (tv[0], tv[1]) if tv else (None, None)
    v, code = table_verdict(age, has_aux, down, watch, views, ch)
    out = {"item_id": iid, "title": row.get("title") or "", "age": int(age), "price": price,
           "aux": has_aux, "down": down, "watch": watch, "views": views, "table": code,
           "verdict": v, "code": code, "market": None}
    if v == DROP and code != "11b 埋もれた":
        st = None if (market is None or age >= CAP_AGE) else market.stat(out["title"], iid)
        out["market"] = st
        out["verdict"], out["code"] = market_verdict(age, price, st)
        if out["verdict"] == KEEP and market is None:
            out["code"] = "M? 市場を見ていない"
    return out


def log_decisions(decisions, path=DECISIONS_PATH, now=None):
    """判定を台帳に足す (I/O)。書けなくても止めない。"""
    at = (now or datetime.datetime.now()).isoformat(timespec="seconds")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            for d in decisions:
                fh.write(json.dumps(dict(d, at=at), ensure_ascii=False) + "\n")
    except OSError:
        pass


def write_hoju_priority(decisions, path=HOJU_PRIORITY_PATH, now=None):
    """補優先の itemID を補URL③・夜の検索が先に回す一覧に書く (I/O)。"""
    ids = [d["item_id"] for d in decisions if d.get("verdict") == HOJU]
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"at": (now or datetime.datetime.now()).isoformat(timespec="seconds"),
                       "iids": ids}, fh, ensure_ascii=False)
    except OSError:
        pass
    return ids


def load_hoju_priority(path=HOJU_PRIORITY_PATH):
    try:
        with open(path, encoding="utf-8") as fh:
            return [str(x).strip() for x in (json.load(fh).get("iids") or []) if str(x).strip()]
    except (OSError, ValueError, AttributeError):
        return []
