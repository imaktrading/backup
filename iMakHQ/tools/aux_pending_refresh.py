#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""補URL の目視待ちの棚卸し (毎朝・KAGOYA の仕事の一部)。

★2026-10-03 ユーザー「最新の検索に無い (値段が取れていません) ってのがあるけど、おかしくない？」
  → 「そんなの夜のうちにやっとかないと」。
  目視待ち 1,440本のうち 670本が値段なしだった (10/2 に積んだ分だけで169本)。
  積む時に値段を残す作りはあるが、値段の出どころが「補URL 探索の記録」だけで、
  2枚目の自動追記 (重複で弾いた仕入元) は探索で見つけた物ではないので最初から値段が無い。
  人の目に出す前に、今の値段と売り切れを確かめておく:
    - 売り切れ (確かに消えている) → 目視待ちから外す (外した記録は aux_pending_removed.jsonl)
    - 売っている → 今の値段を書く
    - 確かめられない (通信の失敗など) → 触らない (消さない側に倒す)

  メルカリは API (mercapi・Chrome なし)、スニダンは出品一覧の API (同じカードは1回で済ませる)。
"""
from __future__ import annotations

import datetime
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import aux_pending  # noqa: E402

REMOVED_LOG = os.path.join(HERE, "..", "review_logs", "aux_pending_removed.jsonl")


# ---------------------------------------------------------------------------
# 純関数
# ---------------------------------------------------------------------------
def urls_to_check(rows):
    """確かめる URL (重複なし・itemID のある行だけ。itemID の無い行は画面に出ないので見ない)。"""
    out = []
    for r in rows or []:
        if (r.get("itemID") or "").strip() and (r.get("url") or "").strip():
            out.append(r["url"].strip())
    return list(dict.fromkeys(out))


def plan(rows, results, today=None):
    """results = {url: {"live": True|False|None, "price": int|None}} を目視待ちに当てる。

    返り値 (残す行, 外した行)。live=False の行だけ外す。live=True は値段を書き、確かめた日を付ける。
    live=None・結果が無い行は触らない。
    """
    today = today or datetime.date.today().isoformat()
    keep, removed = [], []
    for r in rows or []:
        res = (results or {}).get((r.get("url") or "").strip())
        if not res or res.get("live") is None:
            keep.append(r)
            continue
        if res["live"] is False:
            removed.append(dict(r, removed=today, why="売り切れ・消えている"))
            continue
        r = dict(r, checked=today)
        if isinstance(res.get("price"), (int, float)) and res["price"] > 0:
            r["price"] = int(res["price"])
        keep.append(r)
    return keep, removed


# ---------------------------------------------------------------------------
# 確かめる (I/O)
# ---------------------------------------------------------------------------
def check_urls(urls, sleep=0.5, log=print):
    """{url: {"live", "price"}}。確かめられなかった URL は入れない。"""
    out = {}
    merc = [u for u in urls if "mercari.com" in u]
    snkr = [u for u in urls if "snkrdunk.com" in u]
    out.update(_check_mercari(merc, sleep, log))
    out.update(_check_snkrdunk(snkr, sleep, log))
    return out


def _check_mercari(urls, sleep, log):
    out = {}
    if not urls:
        return out
    import asyncio
    try:
        try:
            import certifi
            os.environ.setdefault("SSL_CERT_FILE", certifi.where())
        except Exception:                                      # noqa: BLE001
            pass
        import logging as _lg
        _lg.getLogger().setLevel(_lg.ERROR)
        from mercapi import Mercapi
        api, loop = Mercapi(), asyncio.new_event_loop()
    except Exception as e:                                     # noqa: BLE001
        log(f"  ⚠ メルカリ API が使えない ({type(e).__name__}) — メルカリ分は今回見ない")
        return out
    try:
        for k, u in enumerate(urls, 1):
            m_item = re.search(r"jp\.mercari\.com/item/(m\w+)", u)
            m_shop = re.search(r"jp\.mercari\.com/shops/product/(\w+)", u)
            try:
                if m_item:
                    d = loop.run_until_complete(api.item(m_item.group(1)))
                    if d is None:
                        out[u] = {"live": False, "price": None}
                    else:
                        live = (str(getattr(d, "status", "") or "").lower() in ("on_sale", "item_status_on_sale")
                                and getattr(d, "auction_info", None) is None)
                        out[u] = {"live": live, "price": getattr(d, "price", None)}
                elif m_shop:
                    p = loop.run_until_complete(api.product(m_shop.group(1)))
                    if p is None:
                        out[u] = {"live": False, "price": None}
                    else:
                        pd = getattr(p, "product_detail", None)
                        qty = sum(int(getattr(v, "quantity", 0) or 0) for v in (getattr(pd, "variants", None) or []))
                        try:
                            price = int(getattr(p, "price", "") or 0) or None
                        except (TypeError, ValueError):
                            price = None
                        out[u] = {"live": qty > 0, "price": price}
            except Exception:                                  # noqa: BLE001  判らない = 触らない
                pass
            if sleep:
                time.sleep(sleep)
            if k % 100 == 0:
                log(f"  メルカリ {k}/{len(urls)}")
    finally:
        try:
            loop.close()
        except Exception:                                      # noqa: BLE001
            pass
    return out


def _check_snkrdunk(urls, sleep, log):
    """同じカードの出品は1回の一覧で済ませる。"""
    out = {}
    if not urls:
        return out
    import snkrdunk_psa_resource as sp
    by_card = {}
    for u in urls:
        cid, lid = sp._parse_listing_url(u)
        if cid and lid:
            by_card.setdefault(cid, []).append((u, lid))
    for k, (cid, items) in enumerate(by_card.items(), 1):
        try:
            ls = sp.fetch_psa10_listings(cid)
        except Exception:                                      # noqa: BLE001
            ls = None
        if ls is not None:                                     # None = API 失敗 → 触らない
            for u, lid in items:
                live, price = sp._live_price_from_listings(lid, ls)
                out[u] = {"live": live, "price": price}
        if sleep:
            time.sleep(sleep)
        if k % 100 == 0:
            log(f"  スニダン {k}/{len(by_card)}カード")
    return out


# ---------------------------------------------------------------------------
# 当てる (家で)
# ---------------------------------------------------------------------------
def apply_results(results, path=None, log=print):
    """目視待ちに結果を当てて書き直す。返り値 (外した本数, 値段を書いた本数)。

    書き直す直前に読み直す (ほかの処理が積んだ分を消さない)。
    """
    p = path or aux_pending.PATH
    rows = aux_pending.load(p)
    keep, removed = plan(rows, results)
    before ={(r.get("itemID"), r.get("url")): r.get("price") for r in rows}
    priced = sum(1 for r in keep if r.get("checked") and before.get((r.get("itemID"), r.get("url"))) != r.get("price"))
    if not removed and not priced and not any(r.get("checked") for r in keep):
        return 0, 0
    tmp = p + ".refresh_tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in keep:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, p)
    if removed:
        with open(REMOVED_LOG, "a", encoding="utf-8") as f:
            for r in removed:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    log(f"  🧾 目視待ちの棚卸し: 売り切れで外した {len(removed)}本 / 値段を書いた {priced}本 / 残り {len(keep)}本")
    return len(removed), priced


def main():
    """手で回す時 (家)。--dry は確かめるだけで書かない。"""
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    rows = aux_pending.load()
    urls = urls_to_check(rows)
    lim = None
    for a in sys.argv[1:]:
        if a.startswith("--limit="):
            lim = int(a.split("=", 1)[1])
    if lim:
        urls = urls[:lim]
    print(f"目視待ち {len(rows)}本 / 確かめる URL {len(urls)}本")
    res = check_urls(urls)
    sold = sum(1 for v in res.values() if v["live"] is False)
    print(f"確かめられた {len(res)}本 (売り切れ {sold} / 販売中 {len(res) - sold})")
    if "--dry" in sys.argv:
        return 0
    apply_results(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
