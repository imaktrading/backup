#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PSA10 再仕入れ可否ゲート (2チャネル統合: メルカリ ＆ SNKRDUNK)。

RESTOCK∩PSA10 の各カードについて、メルカリ と SNKRDUNK の両方で「今PSA10が買えるか+最安」を
確認し束ねる。どちらか一方でも在庫あり → 再仕入れ可。両方なし → 再仕入れ不能(End候補)。

設計メモ: oos_demand_harvest_design.md §7/§7c
チャネル:
  - メルカリ: mercari_psa_resource.fetch_mercari_cheapest (キーワード検索, Selenium)
  - SNKRDUNK: snkrdunk_psa_resource.check_by_keyword (HTTP-only, 全シリーズ, Selenium不要)
              productNumber→id を /en/v1/search?type=trading-card で HTTP 解決 → min-prices で PSA10。
              旧 harvest Selenium(CSR描画フレで0件多発)は廃止。HTTP化で安定+全シリーズ+誤End救済。

combine() は純関数 (I/O無し) で test 可能。HTTP shape({available,psa10_price_jpy,card_url})と
harvest shape({psa10_count,psa10_details}) の両対応。出力は「PSA再仕入れ」タブ。
"""
from __future__ import annotations

import os
import re
import sys

# SNKRDUNK 突合用 card 番号 (ワンピース OP/ST/EB/P 系。SNKRDUNK name の [CARD] と突合)。
# Pokemon は title が日本語で番号を持たない → canonical KEY から導出 (_key_card_number)。
CARD_NUM_RE = re.compile(r"\b((?:OP|ST|EB)\d{2}-\d{3}|P-\d{2,3})\b", re.IGNORECASE)


def _card_number(title):
    m = CARD_NUM_RE.search(title or "")
    return m.group(1).upper() if m else None


def _key_card_number(key):
    """canonical KEY (catalog product_id) → SNKRDUNK 検索/突合用 card番号 (変種suffix除去)。

    Pokemon 等 title に番号が出ない場合の供給源。KEY='SV-P-291'→'SV-P-291' /
    'OP11-106_p2'→'OP11-106'。url-key(item:/shops:)・数字を含まない値は None (fail-closed)。
    SNKRDUNK 側は _norm_cardnum で set-code+番号を区切り非依存に突合 (SV系は一致、S系prefix差は
    no-match=Mercariのみ=安全)。
    """
    if not key or str(key).startswith(("item:", "shops:")):
        return None
    base = str(key).split("_")[0].strip().upper()
    return base if re.search(r"\d", base) else None


def _resource_card_number(title, key):
    """SNKRDUNK 突合用 card番号: title 由来(OP/ST/EB/P)優先、無ければ canonical KEY 由来。"""
    return _card_number(title) or _key_card_number(key)


def _min_price(prices):
    vals = [p for p in prices if isinstance(p, int) and p > 0]
    return min(vals) if vals else None


def combine(mercari, snkrdunk, mercari_cands=None, max_aux=5):
    """2チャネル結果を束ねる純関数。

    Args:
        mercari: (price_jpy:int, url:str, name:str) or None  (メルカリ最安)
        snkrdunk: {"available":bool,"psa10_price_jpy":int,"psa10_listings":[{price,url}]} (HTTP shape)
                  or {"psa10_count":int,"psa10_details":[...]} (harvest shape) or None
        mercari_cands: [(price:int,url:str,name:str),...] メルカリ正変種の価格昇順候補 (補URL用)
        max_aux: 補URL に載せる代替候補の最大数 (両ch混合の最安 max_aux 件)
    Returns:
        {resourceable, channels, cheapest_jpy, cheapest_channel, cheapest_url,
         mercari_jpy, mercari_url, snkrdunk_jpy, snkrdunk_count, snkrdunk_urls, aux_urls}
        aux_urls = メルカリ＆SNKRDUNK 混合の最安 max_aux 件を **高い順** ([0]=高 … [-1]=最安)。
    """
    channels = []
    cand = []  # (channel, price, url)

    m_price = mercari[0] if (mercari and isinstance(mercari[0], int) and mercari[0] > 0) else None
    if m_price:
        channels.append("mercari")
        cand.append(("mercari", m_price, mercari[1] if len(mercari) > 1 else ""))

    s_count = 0
    s_price = None
    snkrdunk_urls = []          # 補URL一覧 (全PSA10出品、価格付)
    if isinstance(snkrdunk, dict):
        if "available" in snkrdunk:
            # HTTP shape (snkrdunk_psa_resource.check_by_keyword): 在庫+最安+PSA10出品一覧(補URL候補)
            if snkrdunk.get("available"):
                s_price = snkrdunk.get("psa10_price_jpy")
                # psa10_listings = 価格昇順の全PSA10出品 → 補URL列(最安の代替候補)。
                listings = snkrdunk.get("psa10_listings") or []
                snkrdunk_urls = [{"price": d.get("price"), "url": d.get("url", "")}
                                 for d in listings if d.get("url")]
                if not snkrdunk_urls:                 # 後方互換 (psa10_listings 無→card_url 1件)
                    url = snkrdunk.get("card_url", "")
                    snkrdunk_urls = [{"price": s_price, "url": url}] if url else []
                s_count = len(snkrdunk_urls) or 1
        else:
            # harvest shape (find_psa10_urls_for_card): 個別補URL一覧 (psa10_count/psa10_details)
            s_count = int(snkrdunk.get("psa10_count") or 0)
            details = snkrdunk.get("psa10_details") or []
            snkrdunk_urls = sorted(
                [{"price": d.get("price"), "url": d.get("url", "")}
                 for d in details if isinstance(d, dict) and d.get("url")],
                key=lambda x: (x["price"] is None, x["price"] or 0),
            )
            if not snkrdunk_urls and snkrdunk.get("psa10_urls"):
                snkrdunk_urls = [{"price": None, "url": u} for u in snkrdunk["psa10_urls"]]
            s_price = _min_price([d.get("price") for d in details if isinstance(d, dict)])
        if s_count > 0:
            channels.append("snkrdunk")
            s_url = snkrdunk_urls[0]["url"] if snkrdunk_urls else ""
            cand.append(("snkrdunk", s_price if s_price else 10**12, s_url))

    cheapest = None
    priced_cand = [c for c in cand if isinstance(c[1], int) and 0 < c[1] < 10**12]
    if priced_cand:
        cheapest = min(priced_cand, key=lambda x: x[1])

    # --- 補URL: メルカリ＆SNKRDUNK 混合の最安 max_aux 件を 高い順 ([0]=高 … [-1]=最安) ---
    # 「補」= 最安が売切/状態相違時の代替候補。両ch横断で安い順に拾い、列には高い順で並べる。
    pool = []
    for c in (mercari_cands or []):
        if c and isinstance(c[0], int) and c[0] > 0 and len(c) > 1 and c[1]:
            pool.append({"price": c[0], "url": c[1], "channel": "mercari"})
    for u in snkrdunk_urls:
        if u.get("url") and isinstance(u.get("price"), int) and u["price"] > 0:
            pool.append({"price": u["price"], "url": u["url"], "channel": "snkrdunk"})
    pool.sort(key=lambda x: x["price"])           # 安い順
    aux_urls = list(reversed(pool[:max_aux]))      # 最安 max_aux 件 → 高い順

    return {
        "resourceable": len(channels) > 0,
        "channels": channels,
        "cheapest_jpy": cheapest[1] if cheapest else None,
        "cheapest_channel": cheapest[0] if cheapest else (channels[0] if channels else None),
        "cheapest_url": cheapest[2] if cheapest else "",
        "mercari_jpy": m_price,
        "mercari_url": (mercari[1] if (mercari and len(mercari) > 1) else "") if m_price else "",
        "snkrdunk_jpy": s_price,
        "snkrdunk_count": s_count,
        "snkrdunk_urls": snkrdunk_urls,   # SNKRDUNK の PSA10出品一覧 (価格昇順)
        "aux_urls": aux_urls,             # 補URL: 両ch混合の最安 max_aux 件 (高い順)
    }


def dedupe_rows(rows, idfn):
    """同一eBay出品の重複行を除去(順序保持)。idfn(row)=itemID。itemID無は url|title で代替キー。

    funnel/CSV 由来で同じ listing が複数行になることがある(2026-06-17 実機: 81行中10重複)。
    同じ現物を2回探索/2回目視するのは無駄なので入口で1本化する。純関数(test可)。
    """
    seen, out = set(), []
    for r in rows:
        iid = idfn(r)
        k = iid or ((r.get("ebay_url", "") or "") + "|" + (r.get("title", "") or ""))
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def _load_restock_psa10():
    """funnel RESTOCK∩PSA10 を mercari_psa_resource 経由で取得 (rows: title/ebay_price/...)."""
    import csv
    import glob
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import mercari_psa_resource as mp
    files = [p for p in glob.glob(os.path.join(mp.DESK, "03_PSA再仕入れ候補_*.csv"))
             if "_メルカリ判定" not in os.path.basename(p)]
    src = max(files, key=os.path.getmtime) if files else mp.build_input_from_funnel()
    if not src:
        return [], mp
    rows = list(csv.DictReader(open(src, encoding="utf-8-sig")))
    deduped = dedupe_rows(rows, lambda r: mp._ebay_item_id(r.get("ebay_url", "") or ""))
    if len(deduped) != len(rows):
        print(f"  重複除去: {len(rows)}→{len(deduped)}行 (同一eBay出品の重複)")
    return deduped, mp


def _run_mismatch_pdca(rejected, confirmed_idx, idx_row, targets, cert_map, mp):
    """確認ゲートの不一致(OFF)を PDCA で回す: read台帳→reconcile→write→原因別ルーティング→トレンド。

    Check止まりにしない(pdca_spiral_up_expectation): 前回比 新規/再発/再燃/解決 を出し、
    catalog誤は Catalog修正依頼書を自動生成、cert誤/出品誤は台帳に振り分けて再掲。失敗は警告のみ。
    """
    import datetime
    today = datetime.date.today().isoformat()
    recs = []
    for rj in rejected:
        i = rj.get("idx")
        r = idx_row.get(i, {})
        t = targets[i] if isinstance(i, int) and i < len(targets) else {}
        iid = mp._ebay_item_id(r.get("ebay_url", "") or "")
        recs.append({"itemID": iid, "cert": cert_map.get(iid, ""), "key": r.get("key", ""),
                     "card_no": t.get("card_no", ""), "title": t.get("title", ""),
                     "reason": rj.get("reason"), "psa_image": t.get("psa_image", ""),
                     "catalog_image": t.get("ref_image", ""), "ebay_url": r.get("ebay_url", "")})
    confirmed_iids = {mp._ebay_item_id(idx_row[i].get("ebay_url", "") or "")
                      for i in confirmed_idx if i in idx_row}
    confirmed_iids.discard("")
    try:
        import psa_mismatch_pdca as pdca
        from sheet_io import read_tab, write_rows_to_tab
        prev = pdca.ledger_from_rows(read_tab("PSA不一致台帳"))
        ledger, st = pdca.reconcile(prev, recs, confirmed_iids, today)
        write_rows_to_tab("PSA不一致台帳", pdca.to_tab_rows(ledger))
        print(f"📒 不一致PDCA: 新規{st['new']} 再発{st['recurring']} 再燃{st['reopened']} "
              f"解決{st['resolved']} / 未対処計{st['open']}")
        if st["by_route"]:
            print("   原因内訳: " + " ".join(
                f"{pdca.ROUTE_LABEL.get(k, k)}={v}" for k, v in st["by_route"].items()))
        buckets = pdca.route_buckets(ledger)
        cat = buckets.get("catalog") or []
        if cat:
            reqdir = r"C:/dev/iMak_data/catalog/requests"
            os.makedirs(reqdir, exist_ok=True)
            p = os.path.join(reqdir, f"{today}_psa_mismatch_catalog.md")
            with open(p, "w", encoding="utf-8") as f:
                f.write(pdca.build_catalog_request_md(cat, today))
            print(f"   → Catalog修正依頼書: {p} ({len(cat)}件)")
        for k in ("cert", "listing"):
            n = len(buckets.get(k) or [])
            if n:
                print(f"   → {pdca.ROUTE_LABEL[k]}: 未対処{n}件 (台帳「PSA不一致台帳」参照)")
    except Exception as e:
        print(f"⚠ 不一致PDCA skip ({type(e).__name__}: {e})")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    limit = None
    for a in sys.argv[1:]:
        if a.startswith("--limit="):
            limit = int(a.split("=", 1)[1])

    rows, mp = _load_restock_psa10()
    if not rows:
        sys.exit("RESTOCK∩PSA10 がありません (先にファネル分析)。")
    if limit:
        rows = rows[:limit]
    print(f"対象 PSA10: {len(rows)}枚 (2チャネル: メルカリ＆SNKRDUNK)")

    # --- Step6 P1: canonical KEY を血統に通す (itemID で商品管理シートに join) ---
    # 各行に r["key"] = canonical product_id (固有変種) を付与。bare番号でなく KEY で正確な変種を同定する土台。
    # 取得失敗/未マッチ時は r["key"] 無し → 後段は従来の bare番号 fallback (fail-soft)。
    keyed = 0
    itemid_row = {}
    cert_map = {}
    try:
        from sheet_io import product_index
        keymap, itemid_row, cert_map = product_index()
        for r in rows:
            iid = mp._ebay_item_id(r.get("ebay_url", "") or "")
            k = keymap.get(iid) if iid else None
            if k:
                r["key"] = k
                keyed += 1
        print(f"  canonical KEY 付与: {keyed}/{len(rows)}枚 (商品管理シート itemID join)")
    except Exception as e:
        print(f"  ⚠ canonical KEY map 取得失敗 ({type(e).__name__}: {e}) — bare番号で続行")

    # --- pre-search 目視確認ゲート (2026-06-17) ---
    # 「探す前に、仕入れたい正カードが正しいか」を catalog 正カード画像で目視確認 → 確定分だけ探索。
    # 番号一致では弾けない変種取り違え(CHR/VMAX・JP/Asia)や KEY未解決(正画像なし)を、探索に時間を
    # 使う前に人手で確定する。--no-confirm で skip(全件探索, 非対話/test用)。
    if "--no-confirm" in sys.argv:
        print("  (--no-confirm) 確認ゲートskip、全件探索")
    else:
        import psa_resource_confirm as prc
        targets = []
        for i, r in enumerate(rows):
            meta = mp.card_meta_for_key(r.get("key")) if r.get("key") else None
            cat_img = (meta or {}).get("image", "")
            iid = mp._ebay_item_id(r.get("ebay_url", "") or "")
            cert = cert_map.get(iid) if iid else None
            psa_img = prc.psa_image_for_cert(cert)   # 現物=出品に使ったPSA画像 (cert→psa_cache)
            targets.append({
                "idx": i,
                "title": (r.get("title") or "")[:90],
                "card_no": _resource_card_number(r.get("title", "") or "", r.get("key")) or "",
                "psa_image": psa_img,          # ① 現物 (出品PSA)
                "ref_image": cat_img,          # ② 解決先 (catalog 正カード)
                "ref_label": (meta or {}).get("hint", "") or (r.get("set_no") or ""),
                "ebay_url": r.get("ebay_url", ""),
                "no_image": not psa_img,       # 現物が引けない行は赤枠で要注意
            })
        print(f"▶ 目視確認ゲート: {len(targets)}件をブラウザ表示。①現物=②catalog の一致を確認...")
        res = prc.confirm_targets(targets)
        if res is None:
            sys.exit("確認がタイムアウト/未確定。探索せず終了(再実行してください)。")
        confirmed_idx, rejected = res["confirmed"], res["rejected"]
        idx_row = {i: r for i, r in enumerate(rows)}    # filter前に idx→row 固定
        # PDCA: 不一致(OFF)を台帳に蓄積 → 原因別振り分け → 再発/解決トレンド
        _run_mismatch_pdca(rejected, confirmed_idx, idx_row, targets, cert_map, mp)
        if not confirmed_idx:
            sys.exit("確定0件(全件不一致)。探索せず終了。台帳「PSA不一致台帳」で原因対処を。")
        sel = set(confirmed_idx)
        rows = [r for i, r in enumerate(rows) if i in sel]
        print(f"  ✅ 確定 {len(rows)}/{len(targets)}件 → これだけ Mercari/SNKRDUNK 探索")

    # --- メルカリ (一括 Selenium, name_jp検索 + 画像検索フォールバック) ---
    print("▶ メルカリ最安取得中 (name_jp検索+画像検索フォールバック)...")
    mercari_res = {}
    try:
        cards = [{**mp.build_card_query(r.get("title", ""), r.get("set_no", ""), r.get("key")),
                  "ebay_item_id": mp._ebay_item_id(r.get("ebay_url", ""))} for r in rows]
        mercari_res = mp.fetch_mercari_cheapest(cards)
    except Exception as e:
        print(f"  ⚠ メルカリ skip ({type(e).__name__}: {e}) — SNKRDUNKのみで判定")

    # --- SNKRDUNK (HTTP-only, 全シリーズ, Selenium不要) ---
    # productNumber→id を /en/v1/search?type=trading-card で HTTP 解決→ min-prices で PSA10。
    # 旧: harvest Selenium(CSR描画フレで0件多発)を廃止。HTTP化で安定+全シリーズ。
    print("▶ SNKRDUNK PSA10 取得中 (HTTP, 全シリーズ)...")
    import snkrdunk_psa_resource as sp
    snkr_res = {}
    for i, r in enumerate(rows):
        cn = _resource_card_number(r.get("title", "") or "", r.get("key"))
        if not cn:
            snkr_res[i] = None
            print(f"  [{i+1}/{len(rows)}] (card番号抽出不可) skip", flush=True)
            continue
        # Step6 P3: canonical KEY → catalog の set+name を variant_hint に。同番号の複数 print を正選択。
        vhint = None
        k = r.get("key")
        if k:
            meta = mp.card_meta_for_key(k)
            if meta:
                vhint = meta.get("hint")  # set + get_info(入手元set) + variant_type + rarity + name_jp + key
        res = sp.check_by_keyword(cn, variant_hint=vhint)
        snkr_res[i] = res
        if res.get("_error") == "card_not_found":
            print(f"  [{i+1}/{len(rows)}] {cn}: SNKRDUNK未登録", flush=True)
        elif res.get("available"):
            print(f"  [{i+1}/{len(rows)}] {cn}: PSA10 ¥{res.get('psa10_price_jpy')}", flush=True)
        else:
            print(f"  [{i+1}/{len(rows)}] {cn}: PSA10在庫なし", flush=True)

    # --- 統合 + 出力 ---
    MAX_AUX = 5  # 補URL列数 (AC-AG 相当)
    aux_cols = [f"補URL{k+1}" for k in range(MAX_AUX)]
    out_rows = [["set_no", "title", "再仕入れ可否", "チャネル", "最安¥", "最安チャネル",
                 "mercari¥", "mercari_URL", "snkrdunk¥", "snkrdunk件数",
                 *aux_cols, "ebay_url"]]
    import psa_resource_html as prh
    html_items = []      # 目視ビューア用 (正カード + 仕入候補 + 補)
    go = 0
    aux_writeback = {}   # {商品管理シート行番号: [補URL,...]} (itemID join できた行のみ)
    for i, r in enumerate(rows):
        mr = mercari_res.get(i) or {}
        c = combine(mr.get("best"), snkr_res.get(i),
                    mercari_cands=mr.get("cands"), max_aux=MAX_AUX)
        if c["resourceable"]:
            go += 1
        # 補URL: メルカリ＆SNKRDUNK 混合の最安 MAX_AUX 件を 高い順 (URLのみ、価格は各¥列に既出)。
        aux = [u["url"] for u in c["aux_urls"] if u.get("url")]
        # 商品管理シートの 補URL列(AC-AG)へ書戻し用に収集 (itemID で行特定)
        iid = mp._ebay_item_id(r.get("ebay_url", "") or "")
        rn = itemid_row.get(iid) if iid else None
        if rn and aux:
            aux_writeback[rn] = aux
        aux += [""] * (MAX_AUX - len(aux))
        # 目視ビューア item: 仕入候補(main)+ SNKRDUNK候補(=補) を正カードと並べる。
        # resourceable のみ画像取得(End候補は画像不要)。Mercari=CDN構成 / SNKRDUNK=og:image。
        if c["resourceable"]:
            _meta = mp.card_meta_for_key(r.get("key")) if r.get("key") else None
            _cands = []
            if c.get("mercari_url"):
                _cands.append({"channel": "mercari", "url": c["mercari_url"], "price": c.get("mercari_jpy"),
                               "is_main": c.get("cheapest_url") == c["mercari_url"],
                               "image": prh.candidate_image("mercari", c["mercari_url"])})
            for d in (c.get("snkrdunk_urls") or [])[:MAX_AUX]:
                _u = d.get("url")
                if not _u:
                    continue
                _cands.append({"channel": "snkrdunk", "url": _u, "price": d.get("price"),
                               "is_main": c.get("cheapest_url") == _u,
                               "image": prh.candidate_image("snkrdunk", _u)})
            html_items.append({"title": (r.get("title") or "")[:80],
                               "ref_image": (_meta or {}).get("image", ""),
                               "ref_label": (_meta or {}).get("hint", "") or (r.get("set_no") or ""),
                               "ng": False, "candidates": _cands})
        out_rows.append([
            r.get("set_no") or mp.search_keyword(r.get("title", ""), "").replace("PSA10 ", ""),
            (r.get("title") or "")[:60],
            "再仕入れ可◎" if c["resourceable"] else "不能✕(End候補)",
            "/".join(c["channels"]) or "-",
            c["cheapest_jpy"] or "", c["cheapest_channel"] or "",
            c["mercari_jpy"] or "", c["mercari_url"],
            c["snkrdunk_jpy"] or "", c["snkrdunk_count"],
            *aux, r.get("ebay_url", ""),
        ])
    print(f"\n再仕入れ可: {go}/{len(rows)}  不能(End候補): {len(rows)-go}")

    # 探索後の最終確認ビューア (確定カードの 仕入候補 + 補 を正カードと並べる)。
    # ※「正しいカードを探すか」は探索前の確認ゲート(prc.confirm_targets)で済。ここは結果の最終目視。
    try:
        OUT_DIR = mp.DESK  # デスクトップに出力(ユーザーがすぐ開ける)
        os.makedirs(OUT_DIR, exist_ok=True)
        _hp = os.path.join(OUT_DIR, "psa_resource_review.html")
        prh.build_html(html_items, _hp)
        print(f"🖼️ 目視ビューア: {_hp} ({len(html_items)}件)")
        try:
            os.startfile(_hp)
        except Exception:
            import webbrowser
            webbrowser.open("file:///" + _hp.replace("\\", "/"))
    except Exception as e:
        print(f"⚠ 目視HTML生成失敗: {type(e).__name__}: {e}")

    try:
        from sheet_io import write_rows_to_tab, MAINT_URL
        write_rows_to_tab("PSA再仕入れ", out_rows)
        print(f"📊 「PSA再仕入れ」タブ更新: {len(out_rows)-1}件 → {MAINT_URL}")
    except Exception as e:
        print(f"⚠ スプシ更新失敗: {type(e).__name__}: {e}")

    # 商品管理シートの 補URL列(AC-AG)へ SNKRDUNK PSA10 直リンクを書戻し
    if aux_writeback:
        try:
            from sheet_io import write_aux_urls
            n = write_aux_urls(aux_writeback)
            print(f"🔗 商品管理シート 補URL(AC-AG) 書戻し: {n}行")
        except Exception as e:
            print(f"⚠ 補URL書戻し失敗: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
