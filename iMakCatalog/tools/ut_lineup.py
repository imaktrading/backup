# -*- coding: utf-8 -*-
"""UT の **全ラインナップ台帳** を1つにする (2026-09-13 新設・ユーザー指示).

ユーザー指摘:「まず、カタログ全ラインナップを決めて、そこに画像やら必要な情報を埋め込む」。
これまでは「探して、取れた物を入れる」だけで、**どの品番が存在するか**の一覧が
3か所 (判定の記録 / ブログ台帳 / Google の検索結果) にばらけていた。

## 台帳に入るもの

品番ごとに:

    status   catalog_full   catalog に在って中身がある (画像・色・素材など)
             catalog_images catalog に在るが画像とコラボ名だけ (data_level=images_only)
             no_material    **UT と確定しているのに** 公式・Wayback・画像サーバーに何も残っていない
             kids / not_ut / unknown    対象外 or 未判定
    sources  どこで見つけたか (公式在庫 / Wayback / 前後の番号 / Google / ブログ / HQ の仕入元URL)
    collab   分かる範囲のコラボ名

## 出すもの

    C:/dev/iMak_data/catalog/ut_lineup.json   台帳 (品番 → 上の内容)
    画面には 状態ごとの件数と、材料が無い品番の一覧 (= 埋めに行く対象)

★これが **分母**。網羅率はこの台帳に対して数える。

実行:
    python tools/ut_lineup.py
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
import api  # noqa: E402
sys.path.insert(0, str(_ROOT / "scrapers"))
import uniqlo_ut_gone_sweep as G  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DATA = Path("C:/dev/iMak_data/catalog")
OUT = DATA / "ut_lineup.json"
PID = re.compile(r"E\d{6}-\d{3}")


def main() -> None:
    src: dict[str, set[str]] = defaultdict(set)
    collab: dict[str, str] = {}

    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    rows = {}
    for pid, s_src, specs in db.execute(
            "SELECT product_id, source, specs FROM products WHERE category='uniqlo_ut'"):
        s = json.loads(specs or "{}")
        rows[pid] = (s_src, s)
        src[pid].add({"uniqlo_official_api": "公式在庫", "uniqlo_official_api_sweep": "公式在庫",
                      "uniqlo_discover": "Wayback/前後の番号",
                      "uniqlo_official_us": "米国の公式", "uniqlo_official_kr": "韓国の公式",
                      "uniqlo_official_tw": "台湾の公式", "uniqlo_official_sg": "シンガポールの公式",
                      "uniqlo_reviews_cdn": "画像だけ"}.get(
                          s_src, "起こした" if s_src.startswith("uniqlo_revive") else s_src))
        if s.get("collab"):
            collab[pid] = s["collab"]
    db.close()

    for f, label in ((DATA / "_uniqlo_blog_pids.txt", "ブログ"),
                     (DATA / "_google_ut_pids_20260911.txt", "Google"),
                     (DATA / "_ut_gone_candidates.txt", "Wayback/廃盤判定"),
                     (DATA / "_ut_gone_neighbor_candidates.txt", "前後の番号"),
                     (DATA / "requests/_uniqlo_gu_supply_urls_dump.csv", "HQ の仕入元URL")):
        if f.exists():
            for p in set(PID.findall(f.read_text(encoding="utf-8", errors="ignore"))):
                src[p].add(label)

    ver = G.recorded()
    out, stat = {}, Counter()
    for pid in sorted(src):
        if pid in rows:
            s = rows[pid][1]
            st = ("catalog_images" if s.get("data_level") == "images_only"
                  else "catalog_overseas" if s.get("region_only")
                  else "catalog_full")
        else:
            v = ver.get(pid)
            st = {"ut": "no_material", "kids": "kids", "not_ut": "not_ut",
                  "none": "not_ut"}.get(v, "unknown")
        stat[st] += 1
        out[pid] = {"status": st, "sources": sorted(src[pid]), "collab": collab.get(pid, "")}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    LABEL = {"catalog_full": "catalog に在る (中身あり)",
             "catalog_overseas": "catalog に在る (海外の公式。日本に無い)",
             "catalog_images": "catalog に在る (画像とコラボ名だけ)",
             "no_material": "UT だが材料が残っていない",
             "kids": "キッズ (対象外)", "not_ut": "UT でない", "unknown": "未判定"}
    print(f"=== UT ラインナップ台帳 — 品番 {len(out):,}件 ===")
    for k, v in stat.most_common():
        print(f"  {LABEL[k]:34s} {v:,}")
    ut_total = stat["catalog_full"] + stat["catalog_images"] + stat["no_material"]
    if ut_total:
        print(f"\n  UT として確定 {ut_total:,}件 中 catalog に在る "
              f"{stat['catalog_full'] + stat['catalog_images']:,}件 "
              f"→ 網羅 {(stat['catalog_full'] + stat['catalog_images']) / ut_total:.0%}")
        print(f"  (中身まである物だけなら {stat['catalog_full'] / ut_total:.0%})")
    print(f"\n  {OUT}")
    # ---- 柄の段: 品番が残っていない物も分母に入れる (Fashion Press / ブログの記事 = その時のラインナップ)
    coll = {}
    gap = DATA / "fashion_press/ut_gap.json"
    if gap.exists():
        for nid, v in json.loads(gap.read_text(encoding="utf-8")).items():
            coll[f"FP{nid}"] = {"source": "Fashion Press", "title": v.get("title", ""),
                                "date": v.get("published", ""), "designs": v.get("article_patterns"),
                                "in_catalog": v.get("catalog_count", 0),
                                "pids": v.get("catalog_pids", [])}
    blog = DATA / "uniqlo_blog_lineup.json"
    if blog.exists():
        for nid, v in json.loads(blog.read_text(encoding="utf-8")).items():
            if v.get("ut"):
                coll[f"BLOG{nid}"] = {"source": "ブログ", "title": v.get("title", ""), "date": "",
                                      "designs": len(v["ut"]), "in_catalog": len(v["in_catalog"]),
                                      "pids": v["in_catalog"]}
    (DATA / "ut_lineup_collabs.json").write_text(
        json.dumps(coll, ensure_ascii=False, indent=1), encoding="utf-8")
    known = [v for v in coll.values() if v["designs"]]
    d_have = sum(min(v["in_catalog"], v["designs"]) for v in known)
    d_want = sum(v["designs"] for v in known)
    print(f"\n=== 柄の段 (品番が無い物も含む) — 記事 {len(coll)}本 ===")
    if d_want:
        print(f"  柄数が分かる {len(known)}本: {d_want}柄 中 catalog {d_have}柄 → 網羅 {d_have / d_want:.0%}")
    zero = [v for v in coll.values() if v["in_catalog"] == 0]
    print(f"  catalog 0件の記事 {len(zero)}本 (= 丸ごと抜けているコラボ)")
    for v in sorted(zero, key=lambda v: v["date"], reverse=True)[:10]:
        print(f"    {v['date'] or '     '}  {v['title'][:44]}")

    miss = [(p, v) for p, v in out.items() if v["status"] == "no_material"]
    print(f"\n[材料が残っていない {len(miss)}件 の出所内訳]")
    c2 = Counter(tuple(v["sources"]) for _, v in miss)
    for k, v in c2.most_common(8):
        print(f"  {v:4d}  {' + '.join(k)}")


if __name__ == "__main__":
    main()
