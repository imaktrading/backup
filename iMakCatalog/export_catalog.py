"""catalog の内容を人が見やすい CSV に出す (Excel 用 UTF-8 BOM 付き).

各 category ごとに重要 field を列に展開. specs JSON を flatten.

実行:
  python iMakCatalog/export_catalog.py --category montbell --out montbell.csv
  python iMakCatalog/export_catalog.py --category gshock --out gshock.csv
  python iMakCatalog/export_catalog.py --category uniqlo_ut --out ut.csv
  python iMakCatalog/export_catalog.py --all --out-dir C:/dev/iMak_data/catalog/exports/
"""
from __future__ import annotations

import csv
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# sys.path: api を見せる
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import api  # type: ignore


# ============================================================================
# Category 別列定義 (人が見やすい順序)
# ============================================================================
COLUMNS = {
    "montbell": [
        ("product_id",         lambda r, s: r["product_id"]),
        ("name_jp",            lambda r, s: r.get("name_jp") or ""),
        ("name_en",            lambda r, s: r.get("name_en") or ""),
        ("name_en_source",     lambda r, s: r.get("name_en_source") or ""),
        ("source",             lambda r, s: r.get("source") or ""),
        ("type",               lambda r, s: s.get("type", "")),
        ("style",              lambda r, s: s.get("style", "")),
        ("department",         lambda r, s: s.get("department", "")),
        ("outer_shell",        lambda r, s: s.get("outer_shell_material", "")),
        ("lining",             lambda r, s: s.get("lining_material", "")),
        ("insulation",         lambda r, s: s.get("insulation_material", "")),
        ("fabric_type",        lambda r, s: s.get("fabric_type", "")),
        ("features",           lambda r, s: ", ".join(s.get("features", []) or [])),
        ("activity",           lambda r, s: s.get("performance_activity", "")),
        ("weight_g",           lambda r, s: s.get("weight_g", "")),
        ("price_jpy",          lambda r, s: s.get("retail_price_jpy", "")),
        ("country",            lambda r, s: s.get("country_of_origin", "")),
        ("colors",             lambda r, s: ", ".join(c.get("en", "") or c.get("jp", "")
                                                       for c in (s.get("color_variants") or []))),
        ("sizes",              lambda r, s: ", ".join(s.get("size_variants") or [])),
        ("image_count",        lambda r, s: len(s.get("image_urls") or [])),
        ("source_url",         lambda r, s: r.get("source_url") or ""),
        ("description_short",  lambda r, s: (s.get("description_jp") or "")[:80]),
    ],
    "gshock": [
        ("product_id",         lambda r, s: r["product_id"]),
        ("name",               lambda r, s: r.get("name", "")),
        ("name_en",            lambda r, s: r.get("name_en") or ""),
        ("source",             lambda r, s: r.get("source") or ""),
        ("series",             lambda r, s: s.get("series", "")),
        ("display",            lambda r, s: s.get("display", "")),
        ("case_shape",         lambda r, s: s.get("case_shape", "")),
        ("case_size",          lambda r, s: s.get("case_size", "")),
        ("case_thickness",     lambda r, s: s.get("case_thickness", "")),
        ("weight",             lambda r, s: s.get("weight", "")),
        ("water_resistance",   lambda r, s: s.get("water_resistance", "")),
        ("case_material",      lambda r, s: s.get("case_material", "")),
        ("band_material",      lambda r, s: s.get("band_material", "")),
        ("band_strap",         lambda r, s: s.get("band_strap", "")),
        ("crystal",            lambda r, s: s.get("crystal", "")),
        ("movement",           lambda r, s: s.get("movement", "")),
        ("features",           lambda r, s: ", ".join(s.get("features", []) or [])
                                            if isinstance(s.get("features"), list) else (s.get("features") or "")),
        ("year",               lambda r, s: s.get("year", "")),
        ("is_new",             lambda r, s: "Yes" if s.get("is_new") else ""),
        ("is_limited",         lambda r, s: "Yes" if s.get("is_limited") else ""),
        ("price_jpy_msrp",     lambda r, s: s.get("price_jpy_msrp", "")),
        ("official_spec_fetched", lambda r, s: "Yes" if s.get("official_spec_fetched") else ""),
        ("image_count",        lambda r, s: len(r.get("images") or [])),
        ("source_url",         lambda r, s: r.get("source_url") or ""),
    ],
    "uniqlo_ut": [
        ("product_id",         lambda r, s: r["product_id"]),
        ("name_jp",            lambda r, s: r.get("name_jp") or ""),
        ("name_en",            lambda r, s: r.get("name_en") or ""),
        ("l1_id",              lambda r, s: s.get("l1_id", "")),
        ("source",             lambda r, s: r.get("source") or ""),
        ("department",         lambda r, s: s.get("department", "")),
        ("themes",             lambda r, s: ", ".join(s.get("themes", []) or [])),
        ("character_family",   lambda r, s: s.get("character_family", "")),
        ("character",          lambda r, s: s.get("character", "")),
        ("style",              lambda r, s: s.get("style", "")),
        ("pattern",            lambda r, s: s.get("pattern", "")),
        ("brand",              lambda r, s: s.get("brand", "")),
        ("type",               lambda r, s: s.get("type", "")),
        ("ebay_colors",        lambda r, s: ", ".join(s.get("ebay_colors", []) or [])),
        ("ebay_sizes",         lambda r, s: ", ".join(s.get("ebay_sizes", []) or [])),
        ("price_jpy",          lambda r, s: s.get("price_jpy_base", "")),
        ("price_jpy_promo",    lambda r, s: s.get("price_jpy_promo", "")),
        ("country_of_origin",  lambda r, s: s.get("country_of_origin", "")),
        ("material",           lambda r, s: s.get("material", "")),
        ("rating",             lambda r, s: s.get("rating", "")),
        ("image_count",        lambda r, s: len(s.get("image_urls") or [])),
        ("source_url",         lambda r, s: r.get("source_url") or ""),
    ],
}

# 汎用 (登録済の他カテゴリ用): 主要 field のみ
GENERIC_COLUMNS = [
    ("product_id",     lambda r, s: r["product_id"]),
    ("name",           lambda r, s: r.get("name", "")),
    ("name_jp",        lambda r, s: r.get("name_jp") or ""),
    ("name_en",        lambda r, s: r.get("name_en") or ""),
    ("source",         lambda r, s: r.get("source") or ""),
    ("set_name",       lambda r, s: r.get("set_name") or ""),
    ("specs_summary",  lambda r, s: ", ".join(f"{k}={v}" for k, v in list(s.items())[:8] if not isinstance(v, (list, dict)))),
    ("image_count",    lambda r, s: len(r.get("images") or [])),
    ("source_url",     lambda r, s: r.get("source_url") or ""),
    ("updated_at",     lambda r, s: r.get("updated_at") or ""),
]


def export_category(category: str, out_path: str) -> int:
    """指定 category の全 record を CSV 出力 (UTF-8 BOM 付き、Excel 対応)."""
    cols = COLUMNS.get(category, GENERIC_COLUMNS)
    conn = sqlite3.connect(str(api._DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM products WHERE category = ? ORDER BY product_id",
        (category,),
    )
    rows = cur.fetchall()
    conn.close()

    out_path = str(out_path)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        # header
        w.writerow([col_name for col_name, _ in cols])
        # rows
        for r in rows:
            r_dict = dict(r)
            try:
                specs = json.loads(r_dict.get("specs") or "{}")
            except Exception:
                specs = {}
            r_dict["images"] = json.loads(r_dict.get("images") or "[]") \
                if r_dict.get("images") else []
            row_vals = []
            for col_name, getter in cols:
                try:
                    v = getter(r_dict, specs)
                except Exception:
                    v = ""
                # 改行や tab を空白に置換 (CSV/Excel 安全)
                if isinstance(v, str):
                    v = v.replace("\n", " ").replace("\r", " ").replace("\t", " ")
                row_vals.append(v)
            w.writerow(row_vals)
    print(f"  → {len(rows)} rows → {out_path}")
    return len(rows)


def export_all(out_dir: str, ts: str = None) -> dict:
    """登録されている全 category を個別 CSV で出力."""
    if ts is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    conn = sqlite3.connect(str(api._DB_PATH))
    cats = [r[0] for r in conn.execute(
        "SELECT DISTINCT category FROM products ORDER BY category"
    ).fetchall()]
    conn.close()

    os.makedirs(out_dir, exist_ok=True)
    counts: dict = {}
    for cat in cats:
        out = os.path.join(out_dir, f"{cat}_{ts}.csv")
        counts[cat] = export_category(cat, out)
    return counts


def _cli():
    args = sys.argv[1:]
    if not args:
        print("Usage:")
        print("  python iMakCatalog/export_catalog.py --category montbell --out montbell.csv")
        print("  python iMakCatalog/export_catalog.py --category gshock --out gshock.csv")
        print("  python iMakCatalog/export_catalog.py --category uniqlo_ut --out ut.csv")
        print("  python iMakCatalog/export_catalog.py --all --out-dir C:/dev/iMak_data/catalog/exports/")
        sys.exit(1)
    if args[0] == "--all":
        out_dir = "C:/dev/iMak_data/catalog/exports/"
        if "--out-dir" in args:
            out_dir = args[args.index("--out-dir") + 1]
        result = export_all(out_dir)
        print(f"\n=== 完了 ===")
        for cat, n in result.items():
            print(f"  {cat}: {n} rows")
    elif args[0] == "--category":
        cat = args[1]
        out = "out.csv"
        if "--out" in args:
            out = args[args.index("--out") + 1]
        export_category(cat, out)
    else:
        print(f"⚠️ 不明: {args}")
        sys.exit(1)


if __name__ == "__main__":
    _cli()
