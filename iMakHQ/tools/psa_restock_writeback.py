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


def first_supply_url(joined):
    """確認済仕入URL(" | " 連結)から先頭(最安=主供給先)を取り出す。純関数。"""
    for u in (joined or "").split(" | "):
        u = u.strip()
        if u:
            return u
    return ""


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


def pending_rows_from_confirmed(rows):
    """RESTOCK確定の2d行 → (まだ実行済でない件数, 実行済件数) (純関数)。

    「押したら何件 verify しに行くか」= 実行済でない行。空欄 (まだ一度も見ていない) も含む。
    """
    if not rows or len(rows) < 2:
        return 0, 0
    h = rows[0]
    si = h.index("RESTOCK状態") if "RESTOCK状態" in h else None
    ii = h.index("itemID") if "itemID" in h else 0
    todo = done = 0
    for r in rows[1:]:
        if not any(r) or not (r[ii] if ii < len(r) else "").strip():
            continue
        st = (r[si] if si is not None and si < len(r) else "") or ""
        if ST_DONE in st:
            done += 1
        else:
            todo += 1
    return todo, done


def count_workload(rows=None):
    """押したら『何件の実状態を確かめに行くか』を数える (パネルのヒント用・2026-09-01).

    ★数えるだけの段では eBay を1回も叩かない (qty の確認は押してから)。
      材料は「RESTOCK確定」タブだけ。
    """
    try:
        if rows is None:
            import os as _os
            import sys as _sys
            _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
            _sys.path.insert(0, _os.path.normpath(_os.path.join(
                _os.path.dirname(_os.path.abspath(__file__)), "..", "..", "iMakeBayAPI")))
            from sheet_io import read_tab
            rows = read_tab("RESTOCK確定")
        todo, done = pending_rows_from_confirmed(rows)
        return {"actionable": todo, "done": done, "total": todo + done}
    except Exception as e:                                     # noqa: BLE001
        return {"error": "%s: %s" % (type(e).__name__, e)}


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
    from sheet_io import read_tab, write_rows_to_tab, product_index, restock_reactivate_master
    from ebay_getitem_images import fetch_listing_qty
    import psa_restock_wait as prw

    rows = read_tab("RESTOCK確定")
    if not rows or len(rows) < 2:
        return {"total": 0, "done": 0, "pending": 0, "unknown": 0, "master_synced": 0}
    header = rows[0]
    iid_i = header.index("itemID") if "itemID" in header else 0
    url_i = header.index("確認済仕入URL") if "確認済仕入URL" in header else None
    cost_i = header.index("最安¥") if "最安¥" in header else None
    body = [r for r in rows[1:] if any(r)]
    items = [{"itemID": (r[iid_i] if iid_i < len(r) else "")} for r in body]
    qty_map = {it["itemID"]: fetch_listing_qty(it["itemID"]) for it in items if it["itemID"]}
    cls = classify_restock(items, qty_map)

    # 復活分(qty>=1)の商品管理シート master 同期: A列(供給URL)更新 + D列(売り切れ)クリア
    # + N列(仕入れ価格=新コスト最安¥)。Revise出品価格は新コスト基準のV8なので master コストも揃える。
    # 在庫監視が「売り切れ」を見て復活出品を取り下げ直すのを防ぐ(state_sync_safety)。
    done_set = set(cls["done"])
    master_synced = 0
    if done_set:
        try:
            itemid_to_url = {}
            itemid_to_cost = {}
            for r, it in zip(body, items):
                iid = it["itemID"]
                if iid not in done_set:
                    continue
                if url_i is not None and url_i < len(r):
                    u = first_supply_url(r[url_i])
                    if u:
                        itemid_to_url[iid] = u
                if cost_i is not None and cost_i < len(r) and r[cost_i].strip():
                    itemid_to_cost[iid] = r[cost_i]
            _km, itemid_row, _cm = product_index()
            itemid_to_row = {iid: itemid_row.get(iid) for iid in done_set if itemid_row.get(iid)}
            master_synced = restock_reactivate_master(itemid_to_row, itemid_to_url, itemid_to_cost)
        except Exception as e:
            print(f"⚠ master(A/D列)同期skip: {type(e).__name__}: {e}")

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
            "pending": len(cls["pending"]), "unknown": len(cls["unknown"]),
            "master_synced": master_synced}


def main():
    import sys
    import datetime
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    today = datetime.date.today().isoformat()
    st = reconcile_and_write(today)
    print(f"🔄 RESTOCK状態同期: 計{st['total']} / 実行済{st['done']} / "
          f"入稿待ち{st['pending']} / 不明{st['unknown']}")
    print(f"   🔗 master同期(復活分): A列(供給URL)+D列(売り切れ解除)+N列(仕入れ価格=新コスト) = {st.get('master_synced', 0)}行")
    # 実行済化を PSA再仕入れ funnel の出品状態列にも反映(フロー内自動更新)。
    try:
        from restock_funnel_status import update_funnel_listing_status
        _t = update_funnel_listing_status()
        print(f"   📍 PSA再仕入れ 出品状態列 同期: {_t}")
    except Exception as _e:
        print(f"   ⚠ 出品状態列 同期skip: {type(_e).__name__}: {_e}")
    if st["pending"] or st["unknown"]:
        print("   ⚠ 入稿待ち/不明あり=要対応(silentに済化しない。反映後に再実行で解消)")


if __name__ == "__main__":
    main()
