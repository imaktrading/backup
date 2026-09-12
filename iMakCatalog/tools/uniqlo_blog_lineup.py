# -*- coding: utf-8 -*-
"""ブログの記事ごとの品番を「ラインナップ台帳」にする (2026-09-13).

`scrapers/uniqlo_blog_pids.py` が倉庫に置いた記事 HTML (`_raw/uniqlo_blog/`) を読み、
**記事 = その時の商品の並び** として台帳にする。ユーザー指示:
「リンク切れもあるけど、残っているものや、ラインナップ把握に使える」。

出す物: `C:/dev/iMak_data/catalog/uniqlo_blog_lineup.json`
    {記事ID: {title, url, pids[], ut[], in_catalog[], missing[]}}

★値は取らない。**どの品番が存在したか**だけ。UT かどうかは公式のレビューAPI判定
  (`_ut_gone_verdicts.jsonl`) を見る。中身が公式にも Wayback にも残っていない品番は、
  catalog の行にはならないが「その時これが出ていた」という記録として残る (= 網羅率の分母)。

実行:
    python tools/uniqlo_blog_lineup.py
"""
from __future__ import annotations

import gzip
import json
import re
import sqlite3
import sys
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

RAW = Path("C:/dev/iMak_data/catalog/_raw/uniqlo_blog")
OUT = Path("C:/dev/iMak_data/catalog/uniqlo_blog_lineup.json")
PID = re.compile(r"E\d{6}-\d{3}")


def main() -> None:
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    have = {x[0] for x in db.execute(
        "SELECT product_id FROM products WHERE category IN ('uniqlo_ut','gu')")}
    db.close()
    ver = G.recorded()
    out, n_ut, n_have = {}, 0, 0
    for f in sorted(RAW.glob("post_*.html.gz")):
        h = gzip.open(f, "rb").read().decode("utf-8", "ignore")
        title = (re.findall(r"<title>(.*?)</title>", h) or [""])[0].split(" : ")[0]
        pids = sorted(set(PID.findall(h)))
        ut = [p for p in pids if p in have or ver.get(p) == "ut"]
        miss = [p for p in ut if p not in have]
        nid = f.name[len("post_"):-len(".html.gz")]
        out[nid] = {"title": title, "url": f"https://uniqlou-item.blog.jp/archives/{nid}.html",
                    "pids": pids, "ut": ut, "in_catalog": [p for p in ut if p in have],
                    "missing": miss}
        n_ut += len(ut)
        n_have += len(out[nid]["in_catalog"])
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  記事 {len(out)}本 / 品番 {sum(len(v['pids']) for v in out.values()):,}")
    print(f"  UT の品番 {n_ut} / catalog に在る {n_have} → 網羅 {n_have / n_ut:.0%}" if n_ut else "")
    print(f"  {OUT}")
    print("\n[UT が多い記事]")
    for nid, v in sorted(out.items(), key=lambda x: -len(x[1]["ut"]))[:12]:
        if v["ut"]:
            print(f"  UT {len(v['ut']):3d} (catalog {len(v['in_catalog']):3d})  {v['title'][:46]}")


if __name__ == "__main__":
    main()
