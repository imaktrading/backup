#!/usr/bin/env python3
"""set_name_ebay 内部整合監査 (Catalog SSOT) — 2026-06-13 新設 (HQ greenlight).

set_name_ebay の系統的誤り (JP限定ハイクラスパックを英語版 main set 名に誤map 等。
例 S8b VMAXクライマックス→"Brilliant Stars"=英S9=別set) を catalog 内部で検出する。
HQ 照合ツール(出力CSV側) と二重で守る (= dual_gate)。

検査:
  1. era整合      : set_code の era (S/SM/SV/XY/BW…) と set_name_ebay の era接頭
                    ("Sword & Shield—" 等) の不一致を flag (= 別era set名への誤map)。
  2. set_code一貫性: 同一 set_code 内で set_name_ebay が複数値に割れている flag。
  3. source棚卸し  : set_name_ebay_source='(none)' (= 由来不明・未検証) を set_code 単位で
                    集計リスト化 (= S8b級の潜在誤りの母数。件数降順)。

使い方:
  python iMakCatalog/tools/set_name_integrity_audit.py                # pokemon (既定)
  python iMakCatalog/tools/set_name_integrity_audit.py --cat all      # 全カテゴリ
  python iMakCatalog/tools/set_name_integrity_audit.py --out audit.md # md 出力
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import defaultdict

DB_PATH = "C:/dev/iMak_data/catalog/products.sqlite"

_ERAS = ["Scarlet & Violet", "Sword & Shield", "Sun & Moon", "Black & White", "XY"]


def setcode_era(sc: str):
    sc = sc or ""
    if sc.startswith("SV"):
        return "Scarlet & Violet"
    if sc.startswith("SM"):
        return "Sun & Moon"
    if sc.startswith("XY"):
        return "XY"
    if sc.startswith("BW"):
        return "Black & White"
    if re.match(r"^S\d", sc):
        return "Sword & Shield"
    return None  # legacy(DP/L/M…) や promo は era 判定対象外


def ebay_era(name: str):
    name = name or ""
    for era in _ERAS:
        if name.startswith(era + "—") or name.startswith(era + " "):
            return era
    return None


def setcode_of(product_id: str, specs: dict) -> str:
    return specs.get("set_code") or (product_id.split("-")[0] if product_id else "")


def audit(categories):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    q = "SELECT category, product_id, specs FROM products"
    if categories:
        ph = ",".join("?" for _ in categories)
        q += f" WHERE category IN ({ph})"
        rows = conn.execute(q, categories).fetchall()
    else:
        rows = conn.execute(q).fetchall()
    conn.close()

    # set_code -> {set_name_ebay -> count}, set_code -> source set, set_code -> category
    by_code = defaultdict(lambda: defaultdict(int))
    code_src = defaultdict(set)
    code_cat = {}
    none_src = defaultdict(lambda: defaultdict(int))  # source=(none) 棚卸し
    era_mismatch = []  # (set_code, ebay, sc_era, ebay_era, count)

    tmp_era = defaultdict(int)  # (set_code,ebay) count for era check
    for r in rows:
        s = json.loads(r["specs"])
        sc = setcode_of(r["product_id"], s)
        e = s.get("set_name_ebay") or ""
        src = s.get("set_name_ebay_source") or "(none)"
        by_code[sc][e] += 1
        code_src[sc].add(src)
        code_cat[sc] = r["category"]
        if e:
            tmp_era[(sc, e)] += 1
            if src == "(none)":
                none_src[sc][e] += 1

    # 1. era mismatch
    for (sc, e), cnt in tmp_era.items():
        sce, ee = setcode_era(sc), ebay_era(e)
        if sce and ee and sce != ee:
            era_mismatch.append((sc, e, sce, ee, cnt))
    era_mismatch.sort(key=lambda x: -x[4])

    # 2. set_code 一貫性 (set_name_ebay が空でない値が2種以上)
    inconsistent = []
    for sc, d in by_code.items():
        vals = {k: v for k, v in d.items() if k}
        if len(vals) >= 2:
            inconsistent.append((sc, dict(vals)))
    inconsistent.sort(key=lambda x: -sum(x[1].values()))

    # 3. source=(none) 棚卸し (set_code 単位・件数降順)
    none_list = []
    for sc, d in none_src.items():
        total = sum(d.values())
        # 単一値のものだけ (複数値は #2 で別途出る)
        val = max(d.items(), key=lambda kv: kv[1])[0] if d else ""
        none_list.append((sc, val, total, code_cat.get(sc, "")))
    none_list.sort(key=lambda x: -x[2])

    return era_mismatch, inconsistent, none_list


def render(era_mismatch, inconsistent, none_list, categories):
    out = []
    cat_s = ",".join(categories) if categories else "all"
    out.append(f"# set_name_ebay integrity audit (cat={cat_s})\n")
    out.append(f"## 1. era 不一致 (別era set名への誤map疑い) — {len(era_mismatch)} 件\n")
    if not era_mismatch:
        out.append("(なし)\n")
    for sc, e, sce, ee, cnt in era_mismatch:
        out.append(f"- ⚠️ `{sc}` ({sce}) → set_name_ebay=`{e}` ({ee}) × {cnt}件\n")

    out.append(f"\n## 2. set_code 内 set_name_ebay 不統一 — {len(inconsistent)} 件\n")
    if not inconsistent:
        out.append("(なし)\n")
    for sc, vals in inconsistent[:40]:
        out.append(f"- `{sc}`: {vals}\n")

    out.append(
        f"\n## 3. source=(none) 棚卸し (由来不明=未検証, set_code単位) — "
        f"{len(none_list)} set_code / 計 {sum(x[2] for x in none_list)} 件\n"
    )
    out.append("| set_code | set_name_ebay | 件数 | category |\n|---|---|---|---|\n")
    for sc, val, cnt, cat in none_list[:120]:
        out.append(f"| {sc} | {val} | {cnt} | {cat} |\n")
    return "".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cat", default="pokemon_tcg",
                    help="category (pokemon_tcg 既定 / 'all' で全カテゴリ)")
    ap.add_argument("--out", default=None, help="md 出力先 (省略時 stdout)")
    args = ap.parse_args()
    categories = None if args.cat == "all" else [args.cat]

    era_mismatch, inconsistent, none_list = audit(categories)
    report = render(era_mismatch, inconsistent, none_list, categories or [])
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"wrote {args.out}")
        print(f"era不一致={len(era_mismatch)} / 不統一={len(inconsistent)} / "
              f"source=(none) set_code={len(none_list)}")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(report)


if __name__ == "__main__":
    main()
