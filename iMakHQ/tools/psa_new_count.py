#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新規に出品できる PSA の枚数を数える (神風「今日やること」の状態の1行に出す・2026-10-05)。

ユーザー「HIGH を読んで、新規出品出来るカード枚数 (補に回っていない、売り切れじゃない等) を
今日やることの下に、注文仕入れ待ち0件みたいに表示できる？」

数え方は PSA 新規出品 (iMakTCG/psa_to_csv.py の load_targets_from_sheet_psa) と同じ条件:
    I列 (鑑定番号) あり / B列 (itemID) 空 / A列 (仕入元URL) あり / R列 = TCG
    出品中の鑑定番号・KEY と重ならない / 仕入元URL が出品中の行の仕入元・補URL に使われていない
    D列 (売り切れ) 空 / K列 (出品見合せ) 空 / 仕入値 (N→M→F) がある
psa_to_csv は触らない決まり (新規生成器) なので、同じ条件をここに持つ。ずれたら test が赤になる。
eBay は叩かない (出品中の鑑定番号は live 一覧の控えを読むだけ)。
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def count_rows(rows2d, listed_cert, listed_keys, taken_urls, already_listed, norm_url, pick_cost, key_col=34,
               ok_certs=None):
    """シートの行 → 内訳 (純関数)。n が出品できる行 (現物) の数。ok_certs (list) を渡すと、通った行の鑑定番号を足す。"""
    out = {"n": 0, "listed": 0, "taken": 0, "sold": 0, "no_go": 0, "nocost": 0}
    for row in rows2d[1:]:
        g = lambda i: (row[i] if len(row) > i else "").strip()     # noqa: E731
        url, item_id, sold, cert, no_go, cat = g(0), g(1), g(3), g(8), g(10), g(17)
        if not cert or item_id or not url or cat != "TCG":
            continue
        if already_listed(cert, g(key_col), listed_cert, listed_keys):
            out["listed"] += 1
            continue
        if norm_url(url) in taken_urls:
            out["taken"] += 1
            continue
        if sold:
            out["sold"] += 1
            continue
        if no_go:
            out["no_go"] += 1
            continue
        r = [""] * 14
        r[5], r[12], r[13] = g(5), g(12), g(13)
        if not pick_cost(r):
            out["nocost"] += 1
            continue
        out["n"] += 1
        if ok_certs is not None:
            ok_certs.append(cert)
    return out


def card_of(entry):
    """PSA の記録1件 → カードの見分け (ブランド・番号・名前・版)。分からなければ None (純関数)。"""
    k = tuple(str((entry or {}).get(x) or "").strip().upper() for x in ("Brand", "CardNumber", "Subject", "Variety"))
    return k if any(k[:3]) else None


def count_cards(ok_certs, listed_certs, psa_cache):
    """出せる行 → {"cards": 新しく出せるカードの種類, "dup_listed": 別の鑑定番号で出品中のカード, "unknown": カードが分からない行}。

    ★2026-10-15 ユーザー「意味不明な数字を出すな」: 「新規に出せる PSA 194枚」は **行 (現物) の数**で、
      同じカードの2枚目 (出品時に補URLに回る) や、別の鑑定番号で既に出品中のカードまで数えていた
      (実測: 194行 → カードが分かる181行 = 156種類 → うち出品中31 → 新しく出せる 125種類 / 分からない13行)。
    """
    listed = {card_of(psa_cache.get(str(c))) for c in listed_certs} - {None}
    cards, unknown = set(), 0
    for c in ok_certs:
        k = card_of(psa_cache.get(str(c)))
        if k is None:
            unknown += 1
        else:
            cards.add(k)
    new = {k for k in cards if k not in listed}
    return {"cards": len(new), "dup_listed": len(cards) - len(new), "unknown": unknown}


def count_workload():
    try:
        import sheet_io as S
        import dup_guard as D
        sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "iMakeBayAPI")))
        from listing_common import pick_cost_jpy
        rows = S._product_ws().get_all_values()
        listed = S.listed_certs(rows) | S.live_listed_certs()
        ok = []
        out = count_rows(rows, listed, S.listed_key_forms(rows),
                         D.live_supply_urls(rows), S.already_listed_reason, D.norm_url, pick_cost_jpy,
                         key_col=S.PRODUCT_COL_KEY, ok_certs=ok)
        try:
            import psa_resource_confirm as prc
            out.update(count_cards(ok, listed, prc._load_psa_cache() or {}))
        except Exception as e:                                 # noqa: BLE001 種類が出せなければ行の数だけ (画面に「行」と出す)
            out["cards_error"] = f"{type(e).__name__}"[:40]
        return out
    except Exception as e:                                     # noqa: BLE001
        return {"n": None, "error": f"{type(e).__name__}: {e}"[:80]}


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                          # noqa: BLE001
        pass
    print(count_workload())
