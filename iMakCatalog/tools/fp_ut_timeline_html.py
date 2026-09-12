# -*- coding: utf-8 -*-
"""Fashion Press の UT 記事を **年表の HTML** で見られるようにする (2026-09-11 新設).

## なぜ要るか

公式から消えた昔の UT コラボは、catalog (公式) には入らない。
「いつ・何のコラボが・どんな柄で・いくらで出たか」は Fashion Press の記事にしか残っていない。
ユーザーはこれを手で集めていた (`OneDrive/デスクトップ/ebay/出品関係/UNIQLO UT/` に
年月＋コラボ名のフォルダ 35個、出典メモの多くが Fashion Press)。

## 何が見えるか

    年ごとの見出し / 語句検索
    1記事 = 公開日・発売日・タイトル (記事へのリンク)・アイテム例 (柄の数と価格)
            本文の写真と説明文 (「メンズ Tシャツ 1,990円 ※背面」)、写真を押すと原寸
    手元フォルダに同じ記事の出典メモがあれば「手元にあり」の印

元データ: `scrapers/fashion_press_uniqlo.py` が作る `fashion_press/uniqlo_articles.json`

実行:
    python tools/fp_ut_timeline_html.py
    python tools/fp_ut_timeline_html.py --open
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import webbrowser
from collections import defaultdict
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scrapers"))
import fashion_press_uniqlo as F  # noqa: E402  (UT の記事かの判定は1か所)

SRC =Path("C:/dev/iMak_data/catalog/fashion_press/uniqlo_articles.json")
OUT = Path("C:/dev/iMak_data/catalog/fp_ut_timeline.html")
GAP = Path("C:/dev/iMak_data/catalog/fashion_press/ut_gap.json")   # tools/fp_ut_gap.py
USER_DIR = Path("C:/Users/imax2/OneDrive/デスクトップ/ebay/出品関係/UNIQLO UT")


def user_folders() -> dict[str, str]:
    """手元フォルダの出典メモ (`httpswww.fashion-press.netnews40320.txt`) → {記事ID: フォルダ名}."""
    out: dict[str, str] = {}
    if not USER_DIR.exists():
        return out
    for f in USER_DIR.rglob("*.txt"):
        m = re.search(r"fashion-press\.netnews(\d+)", f.name)
        if m:
            out[m.group(1)] = f.parent.name
    return out


def _thumb(url: str) -> str:
    return re.sub(r"/img/news/(\d+)/", r"/img/news/\1/w300_", url, count=1)


def build() -> tuple[str, int]:
    data = json.loads(SRC.read_text(encoding="utf-8"))["articles"]
    arts = sorted((a for a in data.values()
                   if F.is_ut_article(a.get("title") or "", a.get("detail_text") or "")),
                  key=lambda a: a.get("published") or "", reverse=True)
    mine = user_folders()
    gap = json.loads(GAP.read_text(encoding="utf-8")) if GAP.exists() else {}
    by_year: dict[str, list] = defaultdict(list)
    for a in arts:
        by_year[(a.get("published") or "????")[:4]].append(a)

    e = html.escape
    parts = []
    for year in sorted(by_year, reverse=True):
        parts.append(f'<h2 id="y{year}">{year}年 <small>{len(by_year[year])}件</small></h2>')
        for a in by_year[year]:
            d = a.get("detail") or {}
            items = d.get("アイテム例") or d.get("価格") or ""
            # 写真1枚ごとの説明文 (`fashion_press_gallery.py` が取ったもの)。
            # 本文の写真より数が多く、古い記事でも「メンズ Tシャツ 1,990円」まで分かる
            caps = {v.get("img"): v.get("caption", "")
                    for v in (a.get("photo_captions") or {}).values() if v.get("img")}
            figs = a.get("figures") or []
            seen = {f["url"] for f in figs}
            for u in (a.get("photos") or []):
                if u not in seen:
                    figs.append({"url": u, "caption": caps.get(u, "")})
                    seen.add(u)
            for f in figs:                     # 本文側に説明文が無ければ写真ページの物を使う
                if not f.get("caption"):
                    f["caption"] = caps.get(f["url"], "")
            local = a.get("images_local") or {}

            def src(u: str) -> str:
                # ★倉庫に在れば倉庫の写真を使う (Fashion Press が消しても見える)
                return Path(local[u]).as_uri() if u in local else u
            imgs = "".join(
                f'<a href="{e(src(f["url"]))}" target="_blank"><figure>'
                f'<img loading="lazy" src="{e(src(f["url"]) if f["url"] in local else _thumb(f["url"]))}" alt="">'
                f'<figcaption>{e(f.get("caption") or "")}</figcaption></figure></a>'
                for f in figs)
            badge = (f'<span class="mine">手元にあり: {e(mine[a["id"]])}</span>'
                     if a["id"] in mine else "")
            g = gap.get(a["id"]) or {}
            n_cat, want = g.get("catalog_count", 0), g.get("article_patterns")
            if n_cat == 0:
                badge += '<span class="none">カタログ 0件 (写真のみ)</span>'
            else:
                badge += (f'<span class="cat">カタログ {n_cat}件'
                          f'{f" / 記事 {want}柄" if want else ""}</span>')
            search = e(" ".join([a.get("title", ""), a.get("detail_text", ""),
                                 " ".join(f.get("caption", "") for f in figs)]).lower())
            parts.append(f"""
<article data-s="{search}">
  <div class="meta">公開 {e((a.get('published') or '')[:10])}
    {('/ 発売 ' + e(d.get('発売日') or d.get('発売時期') or '')) if (d.get('発売日') or d.get('発売時期')) else ''}
    {badge}</div>
  <h3><a href="{e(a['url'])}" target="_blank">{e(a.get('title', ''))}</a></h3>
  {f'<pre>{e(items)}</pre>' if items else ''}
  <div class="figs">{imgs}</div>
</article>""")
    years = " ".join(f'<a href="#y{y}">{y}</a>' for y in sorted(by_year, reverse=True))
    page = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>UT コラボ年表 (Fashion Press)</title>
<style>
body{{font:14px/1.5 system-ui,sans-serif;margin:0;padding:0 16px 40px;background:#fafafa;color:#222}}
header{{position:sticky;top:0;background:#fafafa;padding:10px 0;border-bottom:1px solid #ddd;z-index:1}}
header input{{width:min(420px,100%);padding:6px 8px;font-size:15px}}
header nav a{{margin-right:8px}}
h2{{margin:28px 0 8px;border-left:5px solid #c00;padding-left:8px}}
h2 small{{color:#888;font-weight:normal}}
article{{background:#fff;border:1px solid #e3e3e3;border-radius:6px;padding:10px 12px;margin:10px 0}}
article h3{{margin:4px 0;font-size:15px}}
.meta{{color:#666;font-size:12px}}
.mine{{background:#e8f4ea;color:#185a2a;border-radius:3px;padding:1px 6px;margin-left:6px}}
.cat{{background:#e8eef8;color:#1d3f73;border-radius:3px;padding:1px 6px;margin-left:6px}}
.none{{background:#fbeaea;color:#8a1c1c;border-radius:3px;padding:1px 6px;margin-left:6px}}
pre{{white-space:pre-wrap;font:12px/1.5 system-ui,sans-serif;background:#f6f6f6;padding:6px;margin:6px 0}}
.figs{{display:flex;flex-wrap:wrap;gap:6px}}
.figs a{{text-decoration:none;color:#444}}
figure{{margin:0;width:120px}}
figure img{{width:120px;height:150px;object-fit:cover;background:#eee;display:block}}
figcaption{{font-size:11px;line-height:1.3}}
</style></head><body>
<header><b>UT コラボ年表</b> — Fashion Press の記事 {len(arts)}件
 (手元フォルダと同じ記事 {sum(1 for a in arts if a['id'] in mine)}件)<br>
<input id="q" placeholder="語句で絞る (例: 鬼滅 / ジャンプ / 1,990円)"> <nav>{years}</nav></header>
{''.join(parts)}
<script>
const q=document.getElementById('q');
q.addEventListener('input',()=>{{const v=q.value.trim().toLowerCase();
document.querySelectorAll('article').forEach(a=>{{a.hidden=v&&!a.dataset.s.includes(v)}});}});
</script></body></html>"""
    return page, len(arts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--open", action="store_true")
    a = ap.parse_args()
    page, n = build()
    OUT.write_text(page, encoding="utf-8")
    print(f"  UT の記事 {n}件")
    print(f"  {OUT}  ({OUT.stat().st_size / 1e6:.1f} MB)")
    if a.open:
        webbrowser.open(OUT.as_uri())


if __name__ == "__main__":
    main()
