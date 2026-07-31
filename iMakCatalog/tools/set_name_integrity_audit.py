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
  4. name整合      : name_en ≠ specs.character_name (両方非空) を flag
                    (= romaji name_en 修正時の character_name 同期漏れ等。eBay C:Character は
                    character_name 由来のため不整合=誤出品。2026-06-13 HQ依頼で追加)。

使い方:
  python iMakCatalog/tools/set_name_integrity_audit.py                # pokemon (既定)
  python iMakCatalog/tools/set_name_integrity_audit.py --cat all      # 全カテゴリ
  python iMakCatalog/tools/set_name_integrity_audit.py --out audit.md # md 出力
"""
import argparse
import datetime as _dt
import json
import re
import sqlite3
import sys
from collections import defaultdict

DB_PATH = "C:/dev/iMak_data/catalog/products.sqlite"

# 完走マーカー (途中で死んだ = マーカーが出ない = ログ検知できる).
# prune_daily.log と同型の「=== ... ===」規約に合わせる (2026-07-31 daily cron 化).
_START_MARK = "=== set_name integrity audit START"
_END_MARK = "=== set_name integrity audit COMPLETE"

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
    q = "SELECT category, product_id, name_en, specs FROM products"
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
    name_desync = []  # (product_id, name_en, character_name)

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
        # 4. name_en ↔ character_name 整合 (両方非空で不一致)
        #    接頭辞一致 ("Pikachu V" vs "Pikachu" の V/VMAX/ex 接尾差) は正当として除外し、
        #    真の名前相違 (romaji 同期漏れ等) のみ flag。
        cn = s.get("character_name")
        ne = r["name_en"]
        if ne and cn and ne != cn \
                and not ne.startswith(cn) and not cn.startswith(ne):
            name_desync.append((r["product_id"], ne, cn))

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
    name_desync.sort(key=lambda x: x[0])

    return era_mismatch, inconsistent, none_list, name_desync


def render(era_mismatch, inconsistent, none_list, name_desync, categories):
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

    out.append(
        f"\n## 4. name_en ≠ character_name (eBay C:Character 不整合) — "
        f"{len(name_desync)} 件\n"
    )
    if not name_desync:
        out.append("(なし)\n")
    for pid, ne, cn in name_desync[:60]:
        out.append(f"- `{pid}`: name_en=`{ne}` ≠ character_name=`{cn}`\n")
    return "".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cat", default="pokemon_tcg",
                    help="category (pokemon_tcg 既定 / 'all' で全カテゴリ)")
    ap.add_argument("--out", default=None, help="md 出力先 (省略時 stdout)")
    args = ap.parse_args()
    categories = None if args.cat == "all" else [args.cat]

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    cat_s = ",".join(categories) if categories else "all"
    ts = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{_START_MARK} {ts} (cat={cat_s}) ===")

    era_mismatch, inconsistent, none_list, name_desync = audit(categories)
    report = render(era_mismatch, inconsistent, none_list, name_desync, categories or [])
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"wrote {args.out}")
    else:
        print(report)

    # ── base→_pN name 誤伝播の継続検出 (2026-08-01 name-guard, WARN のみ・自動修正なし) ──
    #   name_jp≠base なのに name_en/character_name が base と一致する _pN = 別カードに別キャラ名。
    #   これが >0 は name_guard.propagate_name_fields を通さない別経路の再混入。
    import os as _os
    sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    from name_guard import find_variant_name_violations, find_facet_n1_candidates  # noqa: E402
    _conn = sqlite3.connect(str(DB_PATH))
    _cats = categories or ["pokemon_tcg", "one_piece_tcg", "gundam_tcg",
                           "dragonball_scg", "yugioh_tcg"]
    name_viol = []
    for _cat in _cats:
        name_viol += find_variant_name_violations(_conn, _cat)
    if name_viol:
        print(f"\n⚠️ [name-guard] base→_pN 名前誤伝播 {len(name_viol)} 件 (WARN, 自動修正なし):")
        for v in name_viol[:20]:
            print(f"    {v['product_id']}: name_jp={v['name_jp']!r} ≠ base={v['base_name_jp']!r} "
                  f"だが name_en/char が base と一致 (name_en={v['name_en']!r})")

    # set_name_ebay N:1 誤マップ候補 (WARN のみ・自動修正なし。allowlist=facet_n1_allowlist.yaml)
    facet_n1 = []
    for _cat in _cats:
        facet_n1 += [{**x, "category": _cat} for x in find_facet_n1_candidates(_conn, _cat)]
    _conn.close()
    if facet_n1:
        print(f"\n⚠️ [facet-N:1] allowlist 外の N:1 誤マップ候補 {len(facet_n1)} facet "
              f"(WARN・自動修正なし・一括null禁止。per-facet で窓口 GO 要):")
        for x in facet_n1[:30]:
            print(f"    {x['set_name_ebay']!r} <- stranger {list(x['strangers'].items())[:4]}")

    # 完走マーカー (末尾に必ず出す。ログの grep でこれが無ければ途中死亡).
    print(
        f"{_END_MARK}: era={len(era_mismatch)} inconsistent={len(inconsistent)} "
        f"none_src={len(none_list)} name_desync={len(name_desync)} "
        f"name_propagate_viol={len(name_viol)} facet_n1_candidates={len(facet_n1)} ==="
    )


if __name__ == "__main__":
    main()
