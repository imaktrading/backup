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
# Pokemon等は番号フォーマット差で未対応(fail-closed→Mercariのみ)、拡張余地。
CARD_NUM_RE = re.compile(r"\b((?:OP|ST|EB)\d{2}-\d{3}|P-\d{2,3})\b", re.IGNORECASE)


def _card_number(title):
    m = CARD_NUM_RE.search(title or "")
    return m.group(1).upper() if m else None


def _min_price(prices):
    vals = [p for p in prices if isinstance(p, int) and p > 0]
    return min(vals) if vals else None


def combine(mercari, snkrdunk):
    """2チャネル結果を束ねる純関数。

    Args:
        mercari: (price_jpy:int, url:str, name:str) or None  (mercari_psa_resource の戻り)
        snkrdunk: {"psa10_count":int, "psa10_details":[{"price":int,"url":str},...],
                   "search_failed":bool} or None  (harvest find_psa10_urls_for_card の戻り)
    Returns:
        {resourceable, channels, cheapest_jpy, cheapest_channel, cheapest_url,
         mercari_jpy, snkrdunk_jpy, snkrdunk_count}
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
            # HTTP shape (snkrdunk_psa_resource.check_by_keyword): 在庫+最安+カードページURL
            if snkrdunk.get("available"):
                s_price = snkrdunk.get("psa10_price_jpy")
                s_count = 1
                url = snkrdunk.get("card_url", "")
                snkrdunk_urls = [{"price": s_price, "url": url}] if url else []
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
        "snkrdunk_urls": snkrdunk_urls,   # 補URL一覧 (全PSA10出品、価格昇順)
    }


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
    return list(csv.DictReader(open(src, encoding="utf-8-sig"))), mp


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

    # --- メルカリ (一括 Selenium) ---
    print("▶ メルカリ最安取得中...")
    mercari_res = {}
    try:
        kws = [(mp.search_keyword(r.get("title", ""), r.get("set_no", "")),) for r in rows]
        mercari_res = mp.fetch_mercari_cheapest(kws)
    except Exception as e:
        print(f"  ⚠ メルカリ skip ({type(e).__name__}: {e}) — SNKRDUNKのみで判定")

    # --- SNKRDUNK (HTTP-only, 全シリーズ, Selenium不要) ---
    # productNumber→id を /en/v1/search?type=trading-card で HTTP 解決→ min-prices で PSA10。
    # 旧: harvest Selenium(CSR描画フレで0件多発)を廃止。HTTP化で安定+全シリーズ。
    print("▶ SNKRDUNK PSA10 取得中 (HTTP, 全シリーズ)...")
    import snkrdunk_psa_resource as sp
    snkr_res = {}
    for i, r in enumerate(rows):
        cn = _card_number(r.get("title", "") or "")
        if not cn:
            snkr_res[i] = None
            print(f"  [{i+1}/{len(rows)}] (card番号抽出不可) skip", flush=True)
            continue
        res = sp.check_by_keyword(cn)
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
    go = 0
    for i, r in enumerate(rows):
        c = combine(mercari_res.get(i), snkr_res.get(i))
        if c["resourceable"]:
            go += 1
        # SNKRDUNK 補URL: URLのみ(クリック可)。価格は snkrdunk¥ 列に既出。最大5件
        aux = [u["url"] for u in c["snkrdunk_urls"][:MAX_AUX] if u.get("url")]
        aux += [""] * (MAX_AUX - len(aux))
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

    try:
        from sheet_io import write_rows_to_tab, MAINT_URL
        write_rows_to_tab("PSA再仕入れ", out_rows)
        print(f"📊 「PSA再仕入れ」タブ更新: {len(out_rows)-1}件 → {MAINT_URL}")
    except Exception as e:
        print(f"⚠ スプシ更新失敗: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
