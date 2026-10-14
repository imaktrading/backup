#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仕入元が無くなった売れたカードを、メルカリとスニダンで見張り、出たらメールで知らせる (2026-10-13)。

★ユーザー (2026-10-13):「貴方の方で監視できないの？」→「それでやってみようか」。
  バリヤード CLK 013/032 (820209548828) が売れたが、待っている間に唯一の仕入元が売れ、どこにも在庫が無い。
  メルカリの売れた履歴では 3〜5日に1件出るが、出たその日に売れる (取り合い)。出た時にすぐ知らせる。
  **買うのは人** (メルカリはプログラムの購入を禁止・PSA9/まとめ売りの見落とし防止)。メールのリンクから買う。

見張る物は C:/dev/iMak_data/hq/card_watch.json:
  [{"name": 表示名, "until": "YYYY-MM-DD", "queries": [メルカリの検索語],
    "need_all": [全部含む語], "need_any": [どれか含む語], "ng": [含んだら外す語],
    "snkrdunk_id": スニダンのカード番号 or null, "notified": [知らせた出品ID]}]
  期限を過ぎた物・"done": true の物は見ない。

    python card_watch.py            # 1回見る (2分おきの予約 iMakHQ_CardWatch_2min から呼ぶ・2026-10-14 10分→2分)
    python card_watch.py --dry-run  # 見るだけ (メールを送らない・記録しない)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
WATCH = r"C:/dev/iMak_data/hq/card_watch.json"
LOG = r"C:/dev/iMak/iMakHQ/review_logs/card_watch.log"
SEND_MAIL = r"C:/dev/iMak_data/tools/send_mail.py"


def matches(name, w):
    """出品名が見張りの条件に合うか (純関数)。PSA9 等をはっきり書いた物は外す。"""
    n = (name or "").upper()
    if any(x.upper() in n for x in w.get("ng") or []):
        return False
    if re.search(r"PSA\s*[1-9](?!0)", n):
        return False
    if not re.search(r"PSA\s*10", n):
        return False
    if not all(x.upper() in n for x in w.get("need_all") or []):
        return False
    anys = w.get("need_any") or []
    return not anys or any(x.upper() in n for x in anys)


def active(watches, today):
    """期限内で終わっていない見張り (純関数)。"""
    return [w for w in watches if not w.get("done") and (w.get("until") or "9999") >= today.isoformat()]


NG_DEFAULT = ["連番", "セット", "まとめ", "CGC", "BGS", "ARS", "未開封", "オリパ"]


def build_watch(item_id, title, key, ship_by, q, snkrdunk_id):
    """売れた出品 → 見張り1件 (純関数)。q = psa_hoju_fill.build_search_query の戻り (補URLの夜の検索と同じ語)。

    ★2026-10-14 ユーザー「今後のために、修正してよ」(バリヤードは手で見張りを作り、売れて丸1日後に始まった)。
      予備の仕入元 (補) が0本の仕入れ待ちは、order_purchase_sync が取り込んだ時に自動で見張りを始める。
    """
    name_jp = (q or {}).get("name_jp") or ""
    no = (q or {}).get("market_no") or ""
    cn = (q or {}).get("card_no") or ""
    queries = [x for x in dict.fromkeys([(q or {}).get("kw") or "", f"{name_jp} {no} PSA10".strip(),
                                         f"{name_jp} {cn} PSA10".strip()]) if x and name_jp]
    need_any = [x for x in dict.fromkeys([no, cn, cn.replace("-", " ")]) if x]
    return {"name": f"{name_jp or title[:30]} {cn or no} PSA10".strip(), "until": (ship_by or "").replace("/", "-")[:10],
            "ship_by": ship_by or "", "for_item": str(item_id), "key": key or "", "queries": queries,
            "need_all": [], "need_any": need_any, "ng": list(NG_DEFAULT), "snkrdunk_id": snkrdunk_id,
            "notified": [], "auto": True}


def sync_watches(watches, want, waiting_ids, make):
    """見張りの一覧を仕入れ待ちに合わせる (純関数)。戻り: (新しい一覧, 足した件数, 閉じた件数)。

    want = 補0本の仕入れ待ち [{item, title, key, ship_by}] / waiting_ids = 仕入れ待ち全部の itemID。
    - want にあって見張りに無い itemID → make(x) で足す (make が None を返したら足さない)
    - 自動で作った見張り (auto) のうち、仕入れ待ちから外れた (仕入れた・キャンセル) 物 → done
    """
    have = {w.get("for_item") for w in watches if not w.get("done")}
    out, added, closed = list(watches), 0, 0
    for x in want or []:
        if x["item"] in have:
            continue
        w = make(x)
        if w:
            out.append(w)
            have.add(x["item"])
            added += 1
    ws = set(waiting_ids or ())
    for w in out:
        if w.get("auto") and not w.get("done") and w.get("for_item") not in ws:
            w["done"] = True
            closed += 1
    return out, added, closed


def auto_from_orders(want, waiting_ids, log=print):
    """order_purchase_sync から呼ぶ (I/O)。失敗しても取り込みは止めない。0件でも1行出す。"""
    try:
        import mercari_psa_resource as mp
        import psa_hoju_fill as H
        import snkrdunk_psa_resource as S
        cache = H._load_cache()

        def make(x):
            q = H.build_search_query({"title": x.get("title") or "", "key": x.get("key") or "", "itemID": x["item"]}, mp)
            if not q.get("name_jp"):
                return None                                    # カードが分からない = 誤った物を知らせない
            sid = ((cache.get(x["item"]) or {}).get("snkrdunk") or {}).get("card_id")
            if not sid and q.get("card_no"):
                sid = S.resolve_card_id(q["card_no"], variant_hint=q.get("hint"), multi_variant=bool(q.get("multi_variant")))
            return build_watch(x["item"], x.get("title") or "", x.get("key") or "", x.get("ship_by") or "", q, sid)

        try:
            watches = json.load(open(WATCH, encoding="utf-8"))
        except (OSError, ValueError):
            watches = []
        new, added, closed = sync_watches(watches, want, waiting_ids, make)
        if added or closed:
            tmp = WATCH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(new, f, ensure_ascii=False, indent=1)
            os.replace(tmp, WATCH)
        log(f"  👀 見張り: 補0本の仕入れ待ちから足した {added}件 / 仕入れた・キャンセルで閉じた {closed}件 / 補0本 {len(want or [])}件")
        return added, closed
    except Exception as e:                                     # noqa: BLE001
        log(f"  ⚠️要対応 見張りを足せなかった (補0本 {len(want or [])}件): {type(e).__name__}: {e}")
        return 0, 0


def new_hits(found, notified):
    """見つけた出品のうち、まだ知らせていない物 (純関数)。found = [{id, ...}]。"""
    seen = set(notified or [])
    return [f for f in found if f["id"] not in seen]


def search_mercari(w):
    """メルカリの販売中から条件に合う物 (I/O)。"""
    import asyncio
    import logging
    try:
        import certifi
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    except Exception:                                          # noqa: BLE001
        pass
    logging.getLogger().setLevel(logging.ERROR)
    from mercapi import Mercapi
    from mercapi.requests import SearchRequestData
    api, loop = Mercapi(), asyncio.new_event_loop()
    out = {}
    try:
        for q in w.get("queries") or []:
            r = loop.run_until_complete(api.search(q, status=[SearchRequestData.Status.STATUS_ON_SALE]))
            for it in r.items:
                if matches(it.name, w):
                    out[it.id_] = {"id": it.id_, "site": "メルカリ", "price": it.price, "name": it.name,
                                   "url": f"https://jp.mercari.com/item/{it.id_}"}
    finally:
        loop.close()
    return list(out.values())


def search_snkrdunk(w):
    """スニダンの PSA10 の出品 (I/O)。カード番号が無ければ見ない。"""
    cid = w.get("snkrdunk_id")
    if not cid:
        return []
    import snkrdunk_psa_resource as S
    out = []
    for x in S.psa10_listings_for(cid) or []:
        # ★2026-10-14 psa10_listings_for は {price, image, url} しか返さず id が無いので、スニダンは1件も拾えていなかった
        #   (ユーザー「バリヤードがスニダンに出た！」で発覚)。出品の番号は url から取る
        lid = str(x.get("id") or x.get("listing_id") or S._parse_listing_url(x.get("url"))[1] or "")
        if lid:
            out.append({"id": "snkr-" + lid, "site": "スニダン", "price": x.get("price"),
                        "name": w.get("name", ""), "url": S.LISTING_PAGE_TMPL.format(card_id=cid, listing_id=lid)})
    return out


NTFY_TOPIC = r"C:/dev/iMak_data/credentials/ntfy_topic.txt"


def push(w, hits):
    """スマホに通知 (ntfy・I/O)。送れたら True。

    ★2026-10-13 ユーザー「メールは来たけど、gmail が大量に届くから、通知も 251578件」→ 見張り専用の通知アプリ。
      通知を押すと1件目の出品が開く。合言葉 (topic) は credentials に置く (知られると他人も送れる・読める)。
    """
    import requests
    try:
        topic = open(NTFY_TOPIC, encoding="utf-8").read().strip()
    except OSError:
        return False
    h0 = hits[0]
    body = "\n".join(f"{h['site']} ¥{h['price']:,} {h['name'][:40]}" if isinstance(h.get("price"), int)
                     else f"{h['site']} {h['name'][:40]}" for h in hits)
    r = requests.post(f"https://ntfy.sh/{topic}", data=body.encode("utf-8"), timeout=30,
                      headers={"Title": f"仕入元が出た: {w['name'][:40]}".encode("utf-8"),
                               "Priority": "high", "Click": h0["url"], "Tags": "rotating_light"})
    return r.ok


def mail(w, hits):
    """見つけた物をメールで送る (I/O)。送れたら True。"""
    lines = [f"{h['site']} ¥{h['price']:,} {h['name'][:60]}\n{h['url']}" if isinstance(h.get("price"), int)
             else f"{h['site']} {h['name'][:60]}\n{h['url']}" for h in hits]
    body = (f"見張っているカード「{w['name']}」が出ました。PSA9・まとめ売りでないか写真を見てから買ってください。\n"
            f"発送期限: {w.get('ship_by', '')}\n\n" + "\n\n".join(lines))
    r = subprocess.run([sys.executable, SEND_MAIL, "--subject", f"🚨 仕入元が出た: {w['name']} ({len(hits)}件)",
                        "--body", body], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=120)
    return r.returncode == 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    now = dt.datetime.now()
    try:
        watches = json.load(open(WATCH, encoding="utf-8"))
    except (OSError, ValueError):
        watches = []
    act = active(watches, now.date())
    msgs = []
    for w in act:
        found, errs, per = [], [], []
        for fn, site in ((search_mercari, "メルカリ"), (search_snkrdunk, "スニダン")):
            try:
                got = fn(w)
                found += got
                per.append(f"{site} {len(got)}")
            except Exception as e:                             # noqa: BLE001
                errs.append(f"{fn.__name__}: {type(e).__name__}")
                per.append(f"{site} 読めず")
        hits = new_hits(found, w.get("notified"))
        sent = ""
        if hits and not a.dry_run:
            try:
                p = push(w, hits)
            except Exception:                                  # noqa: BLE001
                p = False
            m = mail(w, hits)
            if p or m:
                w.setdefault("notified", []).extend(h["id"] for h in hits)
                sent = f"通知 {'○' if p else '×'} / メール {'○' if m else '×'}"
            else:
                sent = "⚠ 通知もメールも送れず (次の回にまた送る)"
        # ★2026-10-14 サイト別に出す (スニダンが常に0件だったのに、合計しか出さず気づけなかった)
        msgs.append(f"{w['name']}: 販売中 {len(found)}件 ({' / '.join(per)}) / 新しく見つけた {len(hits)}件 {sent}"
                    + (f" / 読めず {', '.join(errs)}" if errs else ""))
    if not a.dry_run and act:
        tmp = WATCH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(watches, f, ensure_ascii=False, indent=1)
        os.replace(tmp, WATCH)
    # ★走行ログで「動いた」が分かる1行 (0件でも出す)
    line = f"{now:%Y-%m-%d %H:%M} 👀 見張り {len(act)}件 / " + (" | ".join(msgs) or "見張る物なし")
    print(line)
    if not a.dry_run:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                          # noqa: BLE001
        pass
    sys.exit(main())
