#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""再仕入れで確定した仕入元を捨てない (2026-10-10)。

★ユーザー指摘「目視して在庫を戻すに何回も出てきて、都度10枚程度確定しているのに」
  (McDonald's Pikachu 820161951186)。実測: RESTOCK確定 144行のうち 115行が2本以上確定していたが、
  ③ は先頭1本だけを A列に書き、残り **694本を捨てていた**。補URL にも入らないので、
  その1本が売り切れると ① に戻り、また探して目視していた。

  1. 補URLに書く: 確定した残りの URL を補URL (AC-AG) の空きに入れる (目視を通った物なので
     「目視なしの自動書込は止める」の対象外)。他の出品が使っている URL は入れない。
  2. 次に切り替える: 先頭の仕入元が売り切れた時、確定した他の URL が **今買えると確かめられた** なら
     ① に戻さず、その URL を先頭にして ② で戻す。確かめられない物は使わない。

    python restock_aux.py            # 既に確定している分の残りを補URLへ (走行ログに件数)
    python restock_aux.py --dry-run
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import sheet_io  # noqa: E402

A, B, D = 0, 1, 3
AUX0, AUXN = sheet_io.PRODUCT_COL_AUX_START, sheet_io.PRODUCT_AUX_MAX
SEP = " | "


def _cell(r, i):
    return ((r[i] if i < len(r) else "") or "").strip()


def _norm(u):
    return (u or "").strip().split("?", 1)[0].rstrip("/")


def split_urls(joined):
    return [u.strip() for u in (joined or "").split("|") if u.strip()]


def owner_map(product_vals):
    """{正規化URL: [itemID]} 生きている出品 (B あり・D 空) の A と補 (純関数)。"""
    out = {}
    for r in (product_vals or [])[1:]:
        iid = _cell(r, B)
        if not iid or _cell(r, D):
            continue
        for u in [_cell(r, A)] + [_cell(r, AUX0 + k) for k in range(AUXN)]:
            if u:
                out.setdefault(_norm(u), set()).add(iid)
    return out


def plan_aux(confirmed_rows, product_vals, owners, dead=frozenset()):
    """RESTOCK確定の行 → ({シートの行番号: 補5本}, {行番号: itemID}, 足した本数, 他出品で外した本数)。純関数。

    - 終了済の行・補充保留の行は触らない
    - 足すのは「A列と既存の補に無い・他の出品が使っていない・売り切れと分かっていない」確定URL
    - 既存の補は消さない。空いている枠に、確定した順 (安い順) に入れる
    """
    if not confirmed_rows or len(confirmed_rows) < 2:
        return {}, {}, 0, 0
    h = confirmed_rows[0]
    ii = h.index("itemID") if "itemID" in h else 0
    cu = h.index("確認済仕入URL") if "確認済仕入URL" in h else None
    si = h.index("RESTOCK状態") if "RESTOCK状態" in h else None
    if cu is None:
        return {}, {}, 0, 0
    row_of = {}
    for n, r in enumerate(product_vals[1:], start=2):
        iid = _cell(r, B)
        if iid:
            row_of.setdefault(iid, []).append(n)
    plan, expect, added, owned = {}, {}, 0, 0
    for r in confirmed_rows[1:]:
        iid = _cell(r, ii)
        st = _cell(r, si) if si is not None else ""
        rows = row_of.get(iid) or []
        if not iid or "終了済" in st or len(rows) != 1:
            continue
        row = rows[0]
        pr = product_vals[row - 1]
        if sheet_io.is_restock_hold(pr):
            continue
        existing = [_cell(pr, AUX0 + k) for k in range(AUXN)]
        have = {_norm(_cell(pr, A))} | {_norm(u) for u in existing if u}
        new = []
        # 先頭は A列に入る物 (② で戻す時に書く) なので補には入れない
        for u in split_urls(_cell(r, cu))[1:]:
            n = _norm(u)
            if n in have or n in dead:
                continue
            if [o for o in owners.get(n, ()) if o != iid]:
                owned += 1
                continue
            have.add(n)
            new.append(u)
        if not new:
            continue
        full = list(existing)
        for k in range(AUXN):
            if not full[k] and new:
                full[k] = new.pop(0)
                added += 1
        if full != existing:
            plan[row] = full
            expect[row] = iid
    return plan, expect, added, owned


def rotate_dead_first(confirmed_rows, sold_out_supply, alive):
    """先頭の仕入元が売り切れた行で、確定した他の URL が今買えるなら先頭を差し替える (純関数)。

    alive: {正規化URL: True/False/None} — True と確かめた物だけ使う。
    戻り: (新しい行, 差し替えた itemID, 外す itemID [他に買える物が無い])
    """
    if not confirmed_rows or len(confirmed_rows) < 2 or not sold_out_supply:
        return confirmed_rows, [], []
    h = confirmed_rows[0]
    ii = h.index("itemID") if "itemID" in h else 0
    si = h.index("RESTOCK状態") if "RESTOCK状態" in h else None
    cu = h.index("確認済仕入URL") if "確認済仕入URL" in h else None
    out, rotated, dropped = [h], [], []
    for r in confirmed_rows[1:]:
        iid = _cell(r, ii)
        st = _cell(r, si) if si is not None else ""
        urls = split_urls(_cell(r, cu)) if cu is not None else []
        dead = sold_out_supply.get(iid)
        if (iid and dead and urls and "実行済" not in st and "終了済" not in st
                and _norm(urls[0]) == _norm(dead)):
            rest = [u for u in urls[1:] if alive.get(_norm(u)) is True]
            if rest:
                r = list(r) + [""] * (len(h) - len(r))
                r[cu] = SEP.join(rest)
                if si is not None:
                    r[si] = ""
                out.append(r)
                rotated.append(iid)
            else:
                dropped.append(iid)
            continue
        out.append(r)
    return out, rotated, dropped


def check_alive(urls):
    """URL → {正規化URL: True/False/None}。メルカリ = API / スニダン = 出品一覧。確かめられない物は None (I/O)。"""
    res = {}
    merc = [u for u in urls if "mercari.com" in u]
    if merc:
        try:
            import mercari_psa_resource as _mp
            ok, _t, _unk = _mp.api_stock_check(merc)
            for u, v in ok.items():
                res[_norm(u)] = v
        except Exception as e:                                 # noqa: BLE001
            print(f"  ⚠ メルカリの在庫を確かめられません ({type(e).__name__}) — その URL は使いません")
    for u in [u for u in urls if "snkrdunk.com" in u]:
        try:
            import snkrdunk_psa_resource as _sp
            live, _p = _sp.listing_live_price(u)
            res[_norm(u)] = live
        except Exception:                                      # noqa: BLE001
            res[_norm(u)] = None
    return res


def write_aux(plan, expect, dry_run=False):
    """補URLを書く (I/O)。戻り: 書いた行数。"""
    if not plan or dry_run:
        return 0
    return sheet_io.write_aux_urls(plan, expect_iid=expect)


def fill_from_confirmed(dry_run=False, confirmed_rows=None, product_vals=None):
    """RESTOCK確定の残りの URL を補URLへ (I/O)。走行ログに必ず1行出す。"""
    from sheet_io import read_tab, _product_ws
    try:
        confirmed_rows = confirmed_rows if confirmed_rows is not None else read_tab("RESTOCK確定")
        product_vals = product_vals if product_vals is not None else _product_ws().get_all_values()
        owners = owner_map(product_vals)
        plan, expect, added, owned = plan_aux(confirmed_rows, product_vals, owners)
        all_new = sorted({u for row in plan.values() for u in row if u})
        alive = check_alive(all_new) if all_new else {}
        dead = {n for n, v in alive.items() if v is False}
        if dead:
            plan, expect, added, owned = plan_aux(confirmed_rows, product_vals, owners, dead)
        n = write_aux(plan, expect, dry_run)
    except Exception as e:                                     # noqa: BLE001
        print(f"⚠️要対応 確定した仕入元を補URLへ: 失敗 {type(e).__name__}: {e}")
        return 0
    print(f"🔗 確定した仕入元を補URLへ: {n}行 / {added}本 (確定 {max(len(confirmed_rows) - 1, 0)}行のうち・"
          f"売り切れで外した {len(dead)}本・他の出品が使用中で外した {owned}本)"
          + (" [試しに数えただけ]" if dry_run else ""))
    return n


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    fill_from_confirmed(dry_run="--dry-run" in argv)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                          # noqa: BLE001
        pass
    sys.exit(main())
