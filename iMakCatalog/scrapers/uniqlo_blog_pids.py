# -*- coding: utf-8 -*-
"""第三者ブログから UNIQLO の **品番だけ** を集める (2026-09-13 新設・ユーザー提案).

対象: `https://uniqlou-item.blog.jp/` (ユニクロUアイテムリンクまとめ)。
記事に商品ページへのリンクが並んでいて、品番 (`E######-###`) がそのまま載っている。
公式から消えた商品の品番を知る手がかりになる。

★**値は取らない。品番だけ。** 名前・素材・画像などの中身は、これまでどおり公式か Wayback から取る
  (catalog の原則: 値の出所は公式)。ブログは「どの品番が存在したか」を知るためだけに使う。

保存: 記事 HTML は倉庫へ (`_raw/uniqlo_blog/`)。済みは飛ばす。品番の一覧は
`_uniqlo_blog_pids.txt` に書き出す (次の判定 → 起こし に渡す)。

実行:
    python scrapers/uniqlo_blog_pids.py --limit 5
    python scrapers/uniqlo_blog_pids.py
"""
from __future__ import annotations

import argparse
import re
import sys
import time
import urllib.request
from pathlib import Path

_CATALOG_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_CATALOG_ROOT / "scrapers"))
import _raw_store  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SITE = "https://uniqlou-item.blog.jp"
RAW_CAT = "uniqlo_blog"
OUT = Path("C:/dev/iMak_data/catalog/_uniqlo_blog_pids.txt")
UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")}
PID = re.compile(r"E\d{6}-\d{3}")
PACE = 1.0


def get(url: str, tries: int = 3) -> str:
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception:
            time.sleep(5 * (i + 1))
    return ""


def article_urls() -> list[str]:
    """サイトマップから記事URL。無ければトップと分類ページから拾う."""
    urls: set[str] = set()
    idx = get(f"{SITE}/sitemap.xml")
    for sub in re.findall(r"<loc>([^<]+)</loc>", idx):
        if sub.endswith(".xml"):
            for u in re.findall(r"<loc>([^<]+)</loc>", get(sub)):
                if "/archives/" in u and u.endswith(".html"):
                    urls.add(u)
            time.sleep(PACE)
    top = get(SITE + "/")
    for cat in set(re.findall(r'href="(https://uniqlou-item\.blog\.jp/archives/cat_\d+\.html)"', top)):
        h = get(cat)
        urls |= set(re.findall(r'href="(https://uniqlou-item\.blog\.jp/archives/\d+\.html)"', h))
        time.sleep(PACE)
    return sorted(urls)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    urls = article_urls()
    if a.limit:
        urls = urls[:a.limit]
    print(f"=== ブログから品番を集める — 記事 {len(urls)}本 ===", flush=True)
    pids: set[str] = set()
    got = skipped = 0
    for i, u in enumerate(urls, 1):
        key = "post_" + u.rsplit("/", 1)[-1].replace(".html", "")
        if _raw_store.have(RAW_CAT, key):
            import gzip
            h = gzip.open(Path(f"C:/dev/iMak_data/catalog/_raw/{RAW_CAT}/{key}.html.gz"),
                          "rb").read().decode("utf-8", "ignore")
            skipped += 1
        else:
            h = get(u)
            if not h:
                continue
            _raw_store.save(RAW_CAT, key, h, u, ext="html")   # ★取った時点で倉庫へ
            got += 1
            time.sleep(PACE)
        pids |= set(PID.findall(h))
        if i % 25 == 0:
            OUT.write_text("\n".join(sorted(pids)), encoding="ascii")
            print(f"    {i}/{len(urls)} 品番 {len(pids):,}", flush=True)
    OUT.write_text("\n".join(sorted(pids)), encoding="ascii")
    print(f"\n  取った記事 {got} / 倉庫から読んだ {skipped}")
    print(f"  品番 {len(pids):,}件 → {OUT}")


if __name__ == "__main__":
    main()
