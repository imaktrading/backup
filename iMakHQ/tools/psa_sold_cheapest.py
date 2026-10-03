#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""売れた PSA10 の仕入れ先を、買う直前に探し直して目視画面に並べる (2026-10-03)。

★ユーザー (2026-10-03):「PSA10 だけど、売れたら仕入元URLと補URLに加えて、改めてメルカリとスニダンで
  最安値を調べて購入しているんだけど、この部分を精度高く作れないかな」
  決めたこと: 出す場所 = 目視画面 / 調べる時 = ボタンを押した時 /
              メルカリは条件外 (評価100未満・送料別・版未確認) も **印を付けて** 出す (最終判断は手で)。

やること (仕入れ待ち = 販売実績の 仕入済チェック無し × 未発送 の PSA 注文ごと):
  1. 商品管理シートの行 (itemID で引く) から KEY・鑑定番号・仕入元 (A列)・補URL1〜5 を読む
  2. 仕入元・補URL が **今** 買えるか・今の値段を API で確かめる (メルカリ / スニダン)
  3. 補URL探しと同じ検索 (KEY から番号と版を決める) で、メルカリとスニダンを探し直す
     - メルカリは条件で落とさず、詳細を API で読んで 評価数・送料・版の確かさを印にする
     - 買えない物 (売り切れ・オークション) は新しい候補からは外す。仕入元・補URL は「売り切れ」と出す
  4. 自分の出品の画像 (売った現物) とカタログの画像を左に、候補を安い順に並べた HTML を開く

eBay にもシートにも書かない (読むだけ)。

    python psa_sold_cheapest.py              # 仕入れ待ちの PSA 全部
    python psa_sold_cheapest.py --item 1234  # この itemID だけ (仕入れ待ちでなくても)
"""
from __future__ import annotations

import argparse
import html as _html
import json
import os
import re
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r"C:\dev\iMak\iMakeBayAPI")

OUT = Path(r"C:\dev\iMak_data\hq\psa_sold_cheapest.html")
# 画面に出したメルカリの候補 {注文番号: {"at": 日付, "ids": [m…]}}。注文の取り込み (order_purchase_sync) が
# 購入履歴と結ぶ時の候補に足す (2026-10-04 ユーザー OK: この画面から買った物も自動で結ぶ)
SHOWN = Path(r"C:\dev\iMak_data\hq\psa_sold_shown_candidates.json")
SHOWN_KEEP_DAYS = 60
MIN_REVIEWS = 100                 # 補URL と同じ基準 (個人の評価数)
MAX_MERCARI = 10
MAX_SNKR = 6


# ---------------------------------------------------------------- 純関数
def is_psa_order_row(r, c_title, c_cat):
    """販売実績の行が PSA の注文か (純関数)。カテゴリ TCG かつ タイトルに PSA。"""
    t = (r[c_title] if len(r) > c_title else "") or ""
    cat = (r[c_cat] if len(r) > c_cat else "") or ""
    return "PSA" in t.upper() and cat in ("TCG", "")


def norm_url(u):
    return (u or "").strip().split("?", 1)[0].split("#", 1)[0].rstrip("/").lower()


def marks_of(c, min_reviews=MIN_REVIEWS):
    """候補の印 (純関数)。空 = 補URL と同じ条件を満たす。

    c: {channel, buyable, ship, reviews, shops, version}
    """
    m = []
    if c.get("buyable") is False:
        return ["売り切れ"]
    if c.get("buyable") is None:
        m.append("在庫を確かめられず")
    if c.get("channel") == "mercari":
        ship = c.get("ship") or ""
        if not ship:
            m.append("送料?")
        elif ship != "送料込み":
            m.append(ship)                         # 着払い / 送料別
        if not c.get("shops"):
            rv = c.get("reviews")
            if rv is None:
                m.append("評価?")
            elif rv < min_reviews:
                m.append(f"評価{rv}件")
    v = c.get("version") or ""
    if v in ("版未確認", "番号未確認"):
        m.append(v)
    return m


def version_label(number_ok, set_ok):
    """出品名に番号が書いてあるか / 弾の言葉 (KEY の版) が書いてあるか → 印 (純関数)。"""
    if not number_ok:
        return "番号未確認"
    return "" if set_ok else "版未確認"


def sort_candidates(cands):
    """買える物を先に、安い順。売り切れは最後 (純関数)。"""
    def k(c):
        sold = c.get("buyable") is False
        p = c.get("price")
        return (sold, 0 if isinstance(p, int) else 1, p if isinstance(p, int) else 0)
    return sorted(cands, key=k)


def merge_candidates(existing, found):
    """仕入元・補URL と、探し直しで見つけた物を URL で1本にまとめる (純関数)。

    同じ URL は既存側 (仕入元 / 補N) の名前を残し、探し直しで分かった値段・印を足す。
    """
    out, idx = [], {}
    for c in existing:
        idx[norm_url(c["url"])] = len(out)
        out.append(dict(c))
    for c in found:
        k = norm_url(c["url"])
        if k in idx:
            e = out[idx[k]]
            for f in ("price", "image", "name"):
                if not e.get(f) and c.get(f):
                    e[f] = c[f]
            continue
        idx[k] = len(out)
        out.append(dict(c))
    return out


def shown_ids(cands):
    """画面に出したメルカリ候補の id (売り切れは除く) (純関数)。"""
    out = []
    for c in cands:
        m = re.search(r"jp\.mercari\.com/item/(m\d+)", c.get("url") or "")
        if m and c.get("buyable") is not False and m.group(1) not in out:
            out.append(m.group(1))
    return out


def merge_shown(store, order, ids, today, keep_days=SHOWN_KEEP_DAYS):
    """記録に足す (前に出した id も残す)。keep_days より古い注文は消す (純関数)。"""
    import datetime as _dt
    out = {}
    for k, v in (store or {}).items():
        try:
            if (today - _dt.date.fromisoformat(v.get("at", ""))).days <= keep_days:
                out[k] = v
        except ValueError:
            continue
    if order and ids:
        old = (out.get(order) or {}).get("ids") or []
        out[order] = {"at": today.isoformat(), "ids": old + [x for x in ids if x not in old]}
    return out


def load_shown(path=SHOWN):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_shown(store, path=SHOWN):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _e(v):
    return _html.escape("" if v is None else str(v))


def build_html(orders):
    """orders: [{order, item_id, title, ship_by, sold_usd, cost_jpy, ref_images, key, note, cands}] → HTML。"""
    from viewer_zoom import ZOOM_CSS, ZOOM_JS, ZOOM_OVERLAY, zoom_button
    rows = []
    for o in orders:
        ref = (o.get("ref_images") or [""])[0]
        refs = "".join(f"<a href='{_e(u)}' target='_blank'><img class='ref' src='{_e(u)}' alt=''></a>"
                       for u in (o.get("ref_images") or []) if u)
        cards = []
        cheapest = None
        for c in o["cands"]:
            mk = marks_of(c)
            ok = not mk
            if ok and cheapest is None and isinstance(c.get("price"), int):
                cheapest = c
            badge = ("<span class='ok'>条件OK</span>" if ok else
                     "".join(f"<span class='ng'>{_e(x)}</span>" for x in mk))
            price = f"¥{c['price']:,}" if isinstance(c.get("price"), int) else "¥?"
            img = c.get("image") or ""
            cls = "cand sold" if c.get("buyable") is False else "cand"
            cards.append(
                f"<div class='{cls}'><div class='src'>{_e(c['src'])}</div>"
                + (f"<a href='{_e(c['url'])}' target='_blank'><img src='{_e(img)}' alt=''></a>" if img
                   else f"<a class='noimg' href='{_e(c['url'])}' target='_blank'>画像なし</a>")
                + f"<div class='pr'>{price} {zoom_button(img, ref)}</div>"
                f"<div class='bd'>{badge}</div>"
                f"<div class='nm'>{_e((c.get('name') or '')[:60])}</div>"
                f"<a class='go' href='{_e(c['url'])}' target='_blank'>開く ↗</a></div>")
        best = (f"最安 (条件OK): <b>¥{cheapest['price']:,}</b> {_e(cheapest['src'])}"
                if cheapest else "<b class='warn'>条件OKの候補なし — 印の付いた物から選ぶか手で探す</b>")
        cost = f"出品時の仕入値 ¥{o['cost_jpy']:,}" if isinstance(o.get("cost_jpy"), int) else ""
        rows.append(
            f"<section><h2>{_e(o['title'])}</h2>"
            f"<div class='meta'>注文 {_e(o['order'])} / itemID {_e(o['item_id'])} / 発送期限 {_e(o.get('ship_by'))}"
            f" / 売値 {_e(o.get('sold_usd'))} / {cost} / KEY {_e(o.get('key'))}</div>"
            + (f"<div class='note'>{_e(o['note'])}</div>" if o.get("note") else "")
            + f"<div class='best'>{best}</div>"
            f"<div class='wrap'><div class='refs'><div class='src'>① 売った現物 / カタログ</div>{refs}</div>"
            f"<div class='cands'>{''.join(cards) or '<p>候補なし</p>'}</div></div></section>")
    css = """
:root{--bg:#f6f7f9;--fg:#222;--card:#fff;--line:#ddd}
body{font-family:'Yu Gothic UI',Meiryo,sans-serif;background:var(--bg);color:var(--fg);margin:0;padding:16px}
h1{font-size:20px}section{background:var(--card);border:1px solid var(--line);border-radius:8px;
padding:12px;margin:0 0 18px}h2{font-size:16px;margin:0 0 4px}.meta{font-size:12px;color:#666}
.note{color:#b50;font-size:13px;margin-top:4px}.best{margin:8px 0;font-size:15px}.warn{color:#c00}
.wrap{display:flex;gap:12px;align-items:flex-start}.refs{flex:0 0 190px}.ref{width:180px;display:block;margin-bottom:6px}
.cands{display:flex;flex-wrap:wrap;gap:10px}.cand{width:170px;border:1px solid var(--line);border-radius:6px;padding:6px;font-size:12px}
.cand img{width:156px;height:200px;object-fit:contain;background:#eee}.cand.sold{opacity:.45}
.src{font-weight:bold;font-size:12px;margin-bottom:4px}.pr{font-size:16px;font-weight:bold;margin:4px 0}
.ok{background:#0a7;color:#fff;border-radius:3px;padding:0 5px}.ng{background:#e85;color:#fff;border-radius:3px;
padding:0 5px;margin-right:3px;display:inline-block;margin-bottom:2px}.nm{color:#555;height:3em;overflow:hidden}
.noimg{display:flex;width:156px;height:200px;align-items:center;justify-content:center;background:#eee}
.go{display:inline-block;margin-top:4px}
"""
    return ("<!doctype html><html lang='ja'><head><meta charset='utf-8'><title>PSA 売れた分の仕入れ先</title>"
            f"<style>{css}{ZOOM_CSS}</style></head><body>"
            f"<h1>PSA10 売れた分の仕入れ先 ({len(orders)}件)</h1>"
            "<p style='font-size:13px'>左が売った現物。候補は買える物を安い順に。"
            "<span class='ok'>条件OK</span> = 補URL と同じ条件 (版確認済・送料込み・評価100以上 or Shops)。"
            "オレンジの印は条件外 (買う前に中身を確かめる)。</p>"
            + "".join(rows) + ZOOM_OVERLAY + f"<script>{ZOOM_JS}</script></body></html>")


# ---------------------------------------------------------------- I/O
def _mercari_now(mp, url):
    """メルカリの URL → (buyable, price, name, image, ship, reviews, shops)。読めなければ buyable=None。"""
    d = mp.api_detail(url)
    shops = mp._is_shops_url(url)
    if d is None:
        return dict(buyable=None, price=None, name="", image="", ship="", reviews=None, shops=shops)
    return dict(buyable=d["buyable"], price=d.get("price"), name=d.get("name", ""),
                image=d.get("image", ""), ship=d.get("ship", ""), reviews=d.get("reviews"), shops=shops)


def snkr_listing_now(sp, url, cache):
    """スニダンの出品 URL → (生きているか True/False/None, 値段, 写真)。cache は card_id ごとの一覧。"""
    card_id, lid = sp._parse_listing_url(url)
    if not card_id or not lid:
        return None, None, ""
    if card_id not in cache:
        try:
            cache[card_id] = sp.fetch_psa10_listings(card_id)
        except Exception:                                      # noqa: BLE001
            cache[card_id] = None
    ls = cache[card_id]
    if ls is None:
        return None, None, ""
    for x in ls:
        if str(x.get("listing_id")) == str(lid):
            p = x.get("price")
            return True, (p if isinstance(p, int) and p > 0 else None), x.get("image") or ""
    return False, None, ""


def existing_candidates(mp, sp, urls):
    """仕入元・補URL の今 → 候補 [{src, channel, url, price, buyable, ...}]。"""
    out = []
    _snkr_cache = {}
    for label, u in urls:
        if "mercari.com" in u:
            c = {"src": label, "channel": "mercari", "url": u, "version": ""}
            c.update(_mercari_now(mp, u))
        elif "snkrdunk.com" in u:
            # ★2026-10-04: 出品ページの og:image はスニダン共通のロゴだった (補URL の画像が全部ロゴ)。
            #   出品一覧の API に、その出品の写真 (primaryPhoto) と値段がある → 1回で生死・値段・写真を取る
            live, price, img = snkr_listing_now(sp, u, _snkr_cache)
            c = {"src": label, "channel": "snkrdunk", "url": u, "version": "", "buyable": live,
                 "price": price, "name": "", "image": img}
        else:
            c = {"src": label, "channel": "other", "url": u, "version": "", "buyable": None,
                 "price": None, "name": "", "image": ""}
        out.append(c)
    return out


def search_candidates(mp, sp, hoju, target):
    """補URL探しと同じ検索で、メルカリとスニダンを探し直す → (候補, メモ)。"""
    q = hoju.build_search_query(target, mp)
    if not q.get("card_no"):
        return [], "タイトルと KEY から番号が取れず、探し直せませんでした (仕入元・補URL だけ出しています)"
    notes = []
    found = []
    try:
        res = mp.fetch_mercari_cheapest([{**q, "ebay_item_id": target["itemID"]}], freeship_min_reviews=None)
        m = res.get(0)
    except Exception as e:                                     # noqa: BLE001
        m = None
        notes.append(f"メルカリを探せませんでした ({type(e).__name__})")
    if isinstance(m, dict) and not m.get("_error"):
        kind = q.get("mirror")
        groups = ("all_cands", "variant_cands", "loose_cands")
        seen = set()
        for k in groups:
            for t in (m.get(k) or []):
                if not (isinstance(t, (list, tuple)) and len(t) > 2):
                    continue
                if kind and mp.mirror_title_conflicts(kind, t[2]):
                    continue                               # ミラーの版が違う
                if norm_url(t[1]) in seen:
                    continue
                seen.add(norm_url(t[1]))
                # 印は検索の枠ではなく **出品名そのもの** で決める (2026-10-03 実測: 画像検索に切り替わった回は
                #   番号も弾も書いてある出品まで「番号未確認」の枠に入っていた)
                found.append({"src": "メルカリ", "channel": "mercari", "url": t[1], "price": t[0],
                              "name": t[2], "version": version_label(
                                  mp._name_matches_card(t[2], q["card_no"], q.get("market_no")),
                                  mp.kw_variant_confident(t[2], q.get("hint")))})
        found = sorted(found, key=lambda c: c["price"] if isinstance(c["price"], int) else 10**9)[:MAX_MERCARI]
        for c in found:                                    # 詳細を API で読んで印を付ける
            now = _mercari_now(mp, c["url"])
            p = c["price"]
            c.update(now)
            if not isinstance(c.get("price"), int):
                c["price"] = p
        found = [c for c in found if c.get("buyable") is not False]
    elif isinstance(m, dict):
        notes.append(f"メルカリを探せませんでした ({m.get('_error')})")
    try:
        s = sp.check_by_keyword(q["card_no"], variant_hint=q.get("hint"),
                                multi_variant=q.get("multi_variant"))
    except Exception as e:                                     # noqa: BLE001
        s = {"_error": type(e).__name__}
    if s.get("available"):
        for d in (s.get("psa10_listings") or [])[:MAX_SNKR]:
            found.append({"src": "スニダン", "channel": "snkrdunk", "url": d["url"], "price": d.get("price"),
                          "name": s.get("card_name", ""), "image": d.get("image") or s.get("card_image", ""),
                          "buyable": True, "version": ""})
    elif s.get("_error") and s.get("_error") != "card_not_found":
        notes.append(f"スニダンを探せませんでした ({s.get('_error')})")
    return found, " / ".join(notes)


def key_from_title(title):
    """KEY が空の時、カタログの唯一の口 (catalog_lookup) でタイトルから引く。決められなければ ''。"""
    try:
        import sqlite3
        import catalog_lookup as CL
        with sqlite3.connect(CL.DB) as conn:
            no = CL.card_no(title)
            row = CL.lookup(CL.candidates(no, title), conn, title) if no else None
        return row[0] if row else ""
    except Exception:                                          # noqa: BLE001
        return ""


def load_waiting_orders(item_filter=None):
    """販売実績の 仕入れ待ち PSA 注文 → [{order, item_id, title, ship_by, sold_usd}]。"""
    import order_purchase_sync as ops
    rows = ops._ws().get_all_values()
    out = []
    if item_filter:
        pick = [(n, r) for n, r in enumerate(rows[1:], 2)
                if len(r) > ops.C_ITEM and r[ops.C_ITEM].strip() == item_filter]
    else:
        pick = [(n, r) for n, r in ops.waiting(rows) if is_psa_order_row(r, ops.C_TITLE, ops.C_CAT)]
    # ★売れた後は商品管理シートの itemID 欄が空になる (実測 2026-10-03: ミュウ 002/028 の行は B 空・A に仕入元)。
    #   itemID だけでは引けないので、eBay の注文から SKU (= 鑑定番号) を取って引く (order_purchase_sync と同じ)。
    try:
        by_id = {ops.norm_order(o.get("orderId")): o for o in ops.fetch_orders()}
    except Exception as e:                                     # noqa: BLE001
        print(f"  (eBay の注文を読めませんでした: {type(e).__name__} — itemID だけで引きます)")
        by_id = {}
    for _n, r in pick:
        r = r + [""] * (ops.C_STATE + 1 - len(r))
        o = by_id.get(ops.norm_order(r[ops.C_ORDER])) or {}
        iid = r[ops.C_ITEM].strip()
        skus = [li.get("sku") or "" for li in (o.get("lineItems") or [])
                if not iid or str(li.get("legacyItemId") or "") in ("", iid)]
        out.append({"order": r[ops.C_ORDER], "item_id": iid, "title": r[ops.C_TITLE],
                    "ship_by": r[ops.C_SHIPBY], "sold_usd": r[ops.C_PRICE],
                    "sku": next((x for x in skus if x), "")})
    if item_filter and not out:
        out.append({"order": "", "item_id": item_filter, "title": "", "ship_by": "", "sold_usd": "", "sku": ""})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--item", help="この itemID だけ")
    ap.add_argument("--no-open", action="store_true")
    a = ap.parse_args(argv)

    import mercari_psa_resource as mp
    import psa_hoju_fill as hoju
    import psa_resource_confirm as prc
    import sheet_io as S
    import snkrdunk_psa_resource as sp
    import sold_restock_worklist as W

    orders = load_waiting_orders(a.item)
    print(f"仕入れ待ちの PSA: {len(orders)}件")
    if not orders:
        print("✅ 仕入れ待ちの PSA はありません")
        return 0
    sheets = W._sheets()
    aux = S.PRODUCT_COL_AUX_START
    done = []
    for i, o in enumerate(orders, 1):
        _l, _n, row = W.find_row(sheets, o.get("sku", ""), o["item_id"])
        note = ""
        key = cert = ""
        urls = []
        cost = None
        if row:
            row = row + [""] * (S.PRODUCT_COL_KEY + 1 - len(row))
            key, cert = row[S.PRODUCT_COL_KEY].strip(), row[S.PRODUCT_COL_CERT].strip()
            if row[0].strip():
                urls.append(("仕入元", row[0].strip()))
            for k in range(S.PRODUCT_AUX_MAX):
                u = row[aux + k].strip() if len(row) > aux + k else ""
                if u.startswith("http"):
                    urls.append((f"補{k + 1}", u))
            try:
                cost = int(re.sub(r"[^\d]", "", row[S.PRODUCT_COL_COST]) or 0) or None
            except (ValueError, IndexError):
                cost = None
            if not o["title"]:
                o["title"] = row[2]
        else:
            note = "商品管理シートに行が見つかりません (タイトルだけで探しています)"
        if not key:
            key = key_from_title(o["title"])
            if key:
                print(f"   (KEY が空 → タイトルからカタログで {key})", flush=True)
        print(f"[{i}/{len(orders)}] {o['item_id']} {o['title'][:50]} (仕入元・補 {len(urls)}本)", flush=True)
        ex = existing_candidates(mp, sp, urls)
        target = {"itemID": o["item_id"], "title": o["title"], "key": key, "cert": cert}
        found, n2 = search_candidates(mp, sp, hoju, target)
        note = " / ".join(x for x in (note, n2) if x)
        cands = sort_candidates(merge_candidates(ex, found))
        refs = []
        try:
            refs.append(prc.ebay_listing_image(o["item_id"]))
        except Exception:                                      # noqa: BLE001
            pass
        if key:
            try:
                meta = mp.card_meta_for_key(key) or {}
                refs.append(meta.get("image") or "")
            except Exception:                                  # noqa: BLE001
                pass
        ok = [c for c in cands if not marks_of(c) and isinstance(c.get("price"), int)]
        print(f"   → 候補 {len(cands)}件 / 条件OK {len(ok)}件"
              + (f" / 最安 ¥{ok[0]['price']:,} ({ok[0]['src']})" if ok else ""), flush=True)
        done.append({**o, "key": key, "cost_jpy": cost, "note": note, "cands": cands,
                     "ref_images": [u for u in refs if u]})
    import datetime as _dt
    import order_purchase_sync as ops
    store = load_shown()
    for d in done:
        store = merge_shown(store, ops.norm_order(d.get("order")), shown_ids(d["cands"]), _dt.date.today())
    save_shown(store)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build_html(done), encoding="utf-8")
    print(f"✅ 目視画面: {OUT}")
    if not a.no_open:
        webbrowser.open(OUT.as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
