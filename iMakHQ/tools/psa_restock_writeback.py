# -*- coding: utf-8 -*-
"""PSA再仕入れ RESTOCK — スプシ書戻し(状態同期・送信後verify)。

設計: 2026-06-17_psa_restock_pipeline_design.md Phase3。RESTOCK確定 → Revise CSV → 手動UL の後、
**実eBay状態(qty)を verify** してからスプシを更新する(state_sync_safety: fail-OPEN禁止)。

- qty>=1 → RESTOCK実反映 = 実行済 → 「RESTOCK確定」status更新 + 「再仕入れ待ち」台帳を復活/解決
- qty==0 → まだ未アップロード/未反映 = 入稿待ち(silentに済扱いしない=要対応に残す)
- qty None → 取得不能 = 不明(fail-closed: 済にしない)

classify_restock は純関数(test可)。I/O(GetItem qty / スプシ)は reconcile_and_write。
"""

ST_DONE = "実行済(qty復活)"
ST_PENDING = "入稿待ち(qty=0)"
ST_UNKNOWN = "状態不明(要確認)"


def classify_restock(confirmed_items, qty_map):
    """RESTOCK確定 items を実eBay qty で分類(純関数)。

    Args:
        confirmed_items: [{"itemID":..}, ...]  (RESTOCK確定リスト)
        qty_map: {itemID: available_qty(int) or None}
    Returns:
        {"done":[itemID...], "pending":[itemID...], "unknown":[itemID...], "status":{itemID: 状態文字}}
    """
    done, pending, unknown, status = [], [], [], {}
    for it in confirmed_items:
        iid = (it.get("itemID") or "").strip()
        if not iid:
            continue
        q = qty_map.get(iid)
        if q is None:
            unknown.append(iid)
            status[iid] = ST_UNKNOWN
        elif q >= 1:
            done.append(iid)
            status[iid] = ST_DONE
        else:
            pending.append(iid)
            status[iid] = ST_PENDING
    return {"done": done, "pending": pending, "unknown": unknown, "status": status}


def reconcile_and_write(today):
    """「RESTOCK確定」タブを読み、各 itemID の実eBay qty を verify → スプシ書戻し(I/O)。

    - RESTOCK確定タブ: 各行に「RESTOCK状態 / 確認日」を付す(末尾2列を上書き)。
    - 再仕入れ待ち台帳: 実行済(qty>=1)の itemID は「復活可」へ(= 供給戻り→復活確認済)。
    戻り: stats dict。失敗は例外送出(呼出側で握る)。
    """
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                     "..", "..", "iMakeBayAPI")))
    from sheet_io import read_tab, write_rows_to_tab
    from ebay_getitem_images import fetch_listing_qty
    import psa_restock_wait as prw

    rows = read_tab("RESTOCK確定")
    if not rows or len(rows) < 2:
        return {"total": 0, "done": 0, "pending": 0, "unknown": 0}
    header = rows[0]
    iid_i = header.index("itemID") if "itemID" in header else 0
    body = [r for r in rows[1:] if any(r)]
    items = [{"itemID": (r[iid_i] if iid_i < len(r) else "")} for r in body]
    qty_map = {it["itemID"]: fetch_listing_qty(it["itemID"]) for it in items if it["itemID"]}
    cls = classify_restock(items, qty_map)

    # RESTOCK確定タブに状態列を付与(既存末尾に「RESTOCK状態」「状態確認日」を上書き)
    if "RESTOCK状態" not in header:
        header = header + ["RESTOCK状態", "状態確認日"]
    si = header.index("RESTOCK状態")
    out = [header]
    for r, it in zip(body, items):
        r = list(r) + [""] * (len(header) - len(r))
        r[si] = cls["status"].get(it["itemID"], ST_UNKNOWN)
        r[si + 1] = today
        out.append(r)
    write_rows_to_tab("RESTOCK確定", out)

    # 再仕入れ待ち台帳: 実行済(qty>=1=供給戻り確認)を「復活可」に反映
    done_ids = set(cls["done"])
    if done_ids:
        wled = prw.ledger_from_rows(read_tab("再仕入れ待ち"))
        wled2, _ = prw.reconcile(wled, [], done_ids, today)
        write_rows_to_tab("再仕入れ待ち", prw.to_tab_rows(wled2))

    return {"total": len(items), "done": len(cls["done"]),
            "pending": len(cls["pending"]), "unknown": len(cls["unknown"])}
