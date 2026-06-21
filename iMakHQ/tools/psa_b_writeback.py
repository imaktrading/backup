# -*- coding: utf-8 -*-
"""PSA新規出品の itemID を商品管理シート B列 に書き戻す(出品後の状態同期)。

背景: 2026-05 統合Hight移行で psa_to_csv の出品後書戻しが撤廃され、以後「新規出品の B列 itemID
手入力運用」になったが追いつかず、出品済カードが出品プール(B列空)に残留 → 毎回 Selenium が
既出品を再scrape → dedup除外 = 歩留まり激減(10件→1〜2件)の主因(2026-06-21 究明)。

このツールは FileExchange の Add結果レポート(CustomLabel + ItemID)を読み、CustomLabel から
master 行を一意特定して B列(itemID)を書く。出品済が pool から抜け、Selenium が fresh だけ回す。

CustomLabel 形式(psa_to_csv / fork が付与):
  - "PSA10-<cert>"        → 商品管理シート I列(cert#)一致で特定
  - "m<mercari-item-id>"  → A列(供給URL)末尾の item-id 一致で特定

設計原則(出品の正確性・state_sync_safety):
  - fail-closed: 一意特定できない / 形式不明 / B列が既に別IDで埋まってる → **書かない**(報告のみ)。
    誤った itemID↔カード紐付けは inventory/RESTOCK の誤動作源なので、確証なき書込はしない。
  - 既定 dry-run。--execute で実書込。

match_* は純関数(test可)。I/O(レポート読み・スプシ書き)は reconcile_b_column。
"""
import os
import re
import sys


def mercari_id_from_url(url):
    """供給URL から mercari item-id(m...) を取り出す。純関数。mercari でなければ ''。

    例: 'https://jp.mercari.com/item/m81209020913' → 'm81209020913'
        ' ... | https://...' 連結は先頭を見る。
    """
    head = (url or "").split(" | ")[0].strip()
    m = re.search(r"/(m\d+)\b", head)
    if m:
        return m.group(1)
    # 末尾が m<digits> だけのケースも拾う
    m2 = re.search(r"\b(m\d+)\s*$", head)
    return m2.group(1) if m2 else ""


def match_label_to_cert_or_mid(custom_label):
    """CustomLabel → ('cert', <cert#>) | ('mid', <m...>) | (None, '')。純関数。

    PSA10-<cert> → cert一致用 / m<digits> → mercari-id一致用 / それ以外 → 不明(fail-closed)。
    """
    cl = (custom_label or "").strip()
    if cl.upper().startswith("PSA10-"):
        cert = cl[len("PSA10-"):].strip()
        return ("cert", cert) if cert.isdigit() else (None, "")
    if re.fullmatch(r"m\d+", cl):
        return ("mid", cl)
    return (None, "")


def plan_writeback(add_pairs, cert_to_row, mid_to_row, current_b):
    """書戻し計画を返す(純関数, network無し)。

    Args:
      add_pairs: [(custom_label, item_id), ...]  (Add結果レポート由来, ItemID有のみ)
      cert_to_row: {cert#: 1-indexed行}          (master I列)
      mid_to_row:  {m<id>: 1-indexed行}          (master A列の供給URL由来)
      current_b:   {1-indexed行: 既存B列値}
    Returns:
      [{label,item_id,key,row,current,status}, ...]
      status: 'WRITE'(空→書込) | 'SKIP_SAME'(既に同ID) | 'CONFLICT'(別IDで埋まり=書かない)
              | 'NO_MATCH'(行特定不可) | 'BAD_LABEL'(形式不明)
    """
    plan = []
    for label, iid in add_pairs:
        kind, key = match_label_to_cert_or_mid(label)
        if kind is None:
            plan.append({"label": label, "item_id": iid, "key": "", "row": "",
                         "current": "", "status": "BAD_LABEL"})
            continue
        row = (cert_to_row if kind == "cert" else mid_to_row).get(key)
        if not row:
            plan.append({"label": label, "item_id": iid, "key": f"{kind}:{key}", "row": "",
                         "current": "", "status": "NO_MATCH"})
            continue
        cur = (current_b.get(row) or "").strip()
        if not cur:
            status = "WRITE"
        elif cur == iid:
            status = "SKIP_SAME"
        else:
            status = "CONFLICT"      # 既に別 itemID。誤上書き防止で書かない(fail-closed)。
        plan.append({"label": label, "item_id": iid, "key": f"{kind}:{key}", "row": row,
                     "current": cur, "status": status})
    return plan


def reconcile_b_column(report_paths, execute=False, verify=True):
    """Add結果レポート群 → master の B列 itemID を書戻し(I/O)。戻り: stats dict。

    verify=True(既定): 空B列に書く前に eBay で itemID の生存を確認し、未解決(qty=None=stale/無効)
    は 'DEAD' として弾く。古い応答CSVを誤って食わせても死IDで上書きしない安全弁(2026-06-21 実証)。
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                     "..", "..", "iMakeBayAPI")))
    from sheet_io import _product_ws, PRODUCT_COL_ITEMID, PRODUCT_COL_CERT
    from relist_writeback import parse_add_report   # CustomLabel+ItemID 抽出を再利用(DRY)

    add_pairs = []
    for p in report_paths:
        pairs = parse_add_report(p)
        add_pairs.extend(pairs)
        print(f"📂 Add結果: {os.path.basename(p)} → {len(pairs)} 行(ItemID有)")
    if not add_pairs:
        print("ItemID 入りの Add 行が無い。終了。")
        return {"total": 0, "write": 0, "skip_same": 0, "conflict": 0, "no_match": 0, "bad_label": 0}

    vals = _product_ws().get_all_values()
    cert_to_row, mid_to_row, current_b = {}, {}, {}
    for i, r in enumerate(vals):
        if i == 0:
            continue
        row = i + 1
        cert = (r[PRODUCT_COL_CERT].strip() if len(r) > PRODUCT_COL_CERT else "")
        if cert:
            cert_to_row.setdefault(cert, row)
        mid = mercari_id_from_url(r[0] if r else "")
        if mid:
            mid_to_row.setdefault(mid, row)
        current_b[row] = (r[PRODUCT_COL_ITEMID] if len(r) > PRODUCT_COL_ITEMID else "")

    plan = plan_writeback(add_pairs, cert_to_row, mid_to_row, current_b)

    # 生存検証: 空B列に書く候補(WRITE)の itemID が eBay で解決するか確認。
    # qty=None(未解決=stale/無効ID)は 'DEAD' に降格 → 書かない(死IDで空B列を汚さない)。
    # qty>=0(0=売切/終了 も valid listing)は書く。
    if verify:
        write_cands = [p for p in plan if p["status"] == "WRITE"]
        if write_cands:
            from ebay_getitem_images import fetch_listing_qty
            print(f"🔎 生存検証中(eBay)… {len(write_cands)}件")
            for p in write_cands:
                try:
                    q = fetch_listing_qty(p["item_id"])
                except Exception:
                    q = None
                if q is None:
                    p["status"] = "DEAD"      # 未解決=stale → 書かない

    from collections import Counter
    cnt = Counter(p["status"] for p in plan)

    print(f"\n計画: WRITE {cnt['WRITE']} / SKIP_SAME {cnt['SKIP_SAME']} / CONFLICT {cnt['CONFLICT']} / "
          f"NO_MATCH {cnt['NO_MATCH']} / BAD_LABEL {cnt['BAD_LABEL']} / DEAD {cnt['DEAD']}")
    for p in plan:
        if p["status"] in ("CONFLICT", "NO_MATCH", "BAD_LABEL", "DEAD"):
            print(f"  ⚠ {p['status']:9} label={p['label']:16} key={p['key']:14} "
                  f"row={p['row'] or '-'} 既存B={p['current'] or '-'} (→書かない)")

    writes = [p for p in plan if p["status"] == "WRITE"]

    if not execute:
        print("\n[DRY-RUN] 書込なし。--execute で B列 反映。")
        return {"total": len(plan), "write": cnt["WRITE"], "skip_same": cnt["SKIP_SAME"],
                "conflict": cnt["CONFLICT"], "no_match": cnt["NO_MATCH"], "bad_label": cnt["BAD_LABEL"],
                "dead": cnt["DEAD"], "executed": False}

    if writes:
        ws = _product_ws()
        col = chr(65 + PRODUCT_COL_ITEMID)   # 1 → B
        reqs = [{"range": f"{col}{p['row']}", "values": [[p["item_id"]]]} for p in writes]
        ws.batch_update(reqs, value_input_option="RAW")
        for p in writes:
            print(f"  ✍ row{p['row']} B列 ← {p['item_id']} ({p['key']})")
    print(f"\n✅ B列書込 {len(writes)} 行。出品済が出品プールから外れます。")
    return {"total": len(plan), "write": cnt["WRITE"], "skip_same": cnt["SKIP_SAME"],
            "conflict": cnt["CONFLICT"], "no_match": cnt["NO_MATCH"], "bad_label": cnt["BAD_LABEL"],
            "dead": cnt["DEAD"], "executed": True}


def main():
    import argparse
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="PSA新規出品の itemID を商品管理シート B列 に書戻し")
    ap.add_argument("reports", nargs="+", help="FileExchange Add結果レポート CSV(複数可)")
    ap.add_argument("--execute", action="store_true", help="実書込(既定は dry-run)")
    ap.add_argument("--no-verify", action="store_true", help="eBay生存検証を省く(既定は検証ON)")
    a = ap.parse_args()
    st = reconcile_b_column(a.reports, execute=a.execute, verify=not a.no_verify)
    if st.get("conflict") or st.get("no_match") or st.get("bad_label") or st.get("dead"):
        print("   ⚠ 未反映あり(CONFLICT/NO_MATCH/BAD_LABEL/DEAD)= fail-closed で書かなかった分。要確認。")


if __name__ == "__main__":
    main()
