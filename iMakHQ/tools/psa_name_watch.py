#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""psa_name_watch — PSA のラベルと カタログの英名 を突き合わせる (2026-08-24)。

## なぜ要るか
カタログの英名が「別人の名前」や「直訳」になっている事故が 8/23-24 で3件出た:

    ジニア        -> Zinnia            (Zinnia は ヒガナ。**出品されてしまった**)
    ポケモンごっこ  -> Imitation Pokémon (公式は Poké Kid。**出品されてしまった**)
    オルティガ     -> Arven             (Arven は ペパー。入稿前に止まった)

カタログ側の「英名が割れている」検出では **半分しか捕まらない**。3行とも同じ誤りなら
中で矛盾しないので気づけない (カナリィ=Canary がまさにそれ)。カタログからの回答:

> 「日本語名の直訳が英名になっている」型は、カタログの中だけでは検出できません。
>  外の正解と突き合わせるしかありません。
>  → **そちらの突合が、この型に対する唯一の検出面です。** 定期的に回してください。
>  (こちらから live の cert 一覧は見えないので、この面はそちらにしか作れません)
>  — catalog/requests/2026-08-23_hq_translated_names_pokekid_canari_response.md

出品くんは PSA のラベル (= 外の正解) と cert↔KEY の対応を持っている唯一の担当なので、
ここに置く。入稿前の1本 (csv_auditor.psa_identity_findings) は **今から出す分**しか見ない。
こちらは **出品済を含む全行**を見る。

## 使い方
    python psa_name_watch.py                 # 全行を突合して食い違いを出す
    python psa_name_watch.py --json out.json # 依頼書に貼る形で書き出す
    python psa_name_watch.py --live-only     # 出品中の行だけ
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                              # noqa: BLE001
    pass

CATALOG_DB = r"C:/dev/iMak_data/catalog/products.sqlite"
SHEET_CATEGORY = "TCG"
COL_ITEMID, COL_TITLE_JP, COL_CERT = 1, 2, 8


def catalog_names(db_path=CATALOG_DB):
    """{(category, product_id): (日本語名, 英名, character_name)}。"""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    out = {}
    for r in con.execute("SELECT category,product_id,name,name_en,specs FROM products"):
        try:
            specs = json.loads(r["specs"] or "{}")
        except Exception:                                      # noqa: BLE001
            specs = {}
        out[(r["category"], r["product_id"])] = (
            r["name"] or "", r["name_en"] or "", specs.get("character_name") or "")
    con.close()
    return out


def rows_to_check(vals, key_col):
    """シート → [(cert, KEY, 出品中か)]。KEY と cert が揃った TCG 行だけ。"""
    out = []
    cat_col = vals[0].index("カテゴリ") if "カテゴリ" in vals[0] else 17

    def g(row, i):
        return (row[i] or "").strip() if i < len(row) else ""

    for row in vals[1:]:
        if g(row, cat_col) != SHEET_CATEGORY:
            continue
        key, cert = g(row, key_col), g(row, COL_CERT)
        if ":" not in key or not cert:
            continue
        out.append((cert, key, bool(g(row, COL_ITEMID))))
    return out


def mismatches(rows, names, psa_meta_fn, findings_fn):
    """名前が1語もかすらない行を返す (純関数・test 可)。

    照合そのものは csv_auditor と **同じ関数**を使う (2か所に真理表を作らない)。
    """
    out = []
    checked = 0
    for cert, key, is_live in rows:
        cat, _, pid = key.partition(":")
        rec = names.get((cat, pid))
        meta = psa_meta_fn(cert)
        if not rec or not meta:
            continue
        checked += 1
        jp, en, ch = rec
        hdrs = ["*Title", "C:Game", "C:Card Name", "C:Character"]
        row = ["", "", en, ch]
        for _sev, msg in findings_fn(hdrs, row, meta):
            if "名前が一致しない" in msg:
                out.append({"cert": cert, "key": key, "live": is_live,
                            "catalog_jp": jp, "catalog_en": en,
                            "psa_subject": (meta.get("Subject") or "").strip(),
                            "psa_brand": (meta.get("Brand") or "").strip()})
    return out, checked


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="", help="結果をこのパスに書き出す")
    ap.add_argument("--live-only", action="store_true", help="出品中の行だけ見る")
    a = ap.parse_args()

    import csv_auditor as A
    import sheet_io

    vals = sheet_io._product_ws().get_all_values()
    key_col = vals[0].index("KEY")
    rows = rows_to_check(vals, key_col)
    if a.live_only:
        rows = [r for r in rows if r[2]]

    bad, checked = mismatches(rows, catalog_names(), A._psa_meta, A.psa_identity_findings)

    print(f"=== PSAラベル ↔ カタログ英名 の突合 ===")
    print(f"  突合できた行: {checked} / 名前が1語もかすらない: {len(bad)}件 "
          f"(うち出品中 {sum(1 for b in bad if b['live'])}件)")
    seen = set()
    for b in bad:
        if b["key"] in seen:
            continue
        seen.add(b["key"])
        mark = "live " if b["live"] else "未出品"
        print(f"  {mark} {b['key']:26} カタログ={b['catalog_jp']}/{b['catalog_en']!r}")
        print(f"         PSA={b['psa_subject']!r}  cert={b['cert']}")
    if not bad:
        print("  ✅ 食い違いはありません")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"checked": checked, "mismatches": bad}, f,
                      ensure_ascii=False, indent=2)
        print(f"  📝 書き出し: {a.json}")
    # 見つかったら 1 (= 走行の締めで拾える)。0件が正常。
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
