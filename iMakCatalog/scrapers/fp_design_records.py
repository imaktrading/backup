# -*- coding: utf-8 -*-
"""公式から消えたコラボを **「柄」単位** で catalog に持つ (2026-09-13 新設・ユーザー指示).

ユーザー指摘:「品番だけど、バイヤーは品番では探さない。内部の KEY みたいな感じでしょ?」

そのとおりで、品番 (`E######-###`) は内部の KEY。買い手は **作品名・柄**で探す。
だから catalog の単位を品番だけにすると、**品番が残っていない = 何も無い**ことになる。
実際いま、品番だけあって中身が無い行が 487件あり、目視にも出品にも使えない。

一方 Fashion Press には、公式から消えたコラボでも **写真 + 説明文 (「メンズ Tシャツ 1,990円」)
+ コラボ名 + 発売日** が残っている。これは **メルカリの商品を見分けるのに使える**。

## 何を入れるか

記事の写真1枚 = 1柄として、次を持つ行を作る:

    product_id  FP<記事ID>-<連番>        (公式の品番ではない。印として FP で始める)
    name        コラボ名 (記事の「」の中) + 説明文
    specs.data_level   = "fp_design"    ★公式値ではない。**出品の項目には使わない**
    specs.source_site  = "fashion_press"
    specs.image_urls   = 倉庫の写真 (file:// でなく元 URL。倉庫のパスは images_local)
    specs.collab / release_date / price_text / article_url

★これは **目視で当てるため**の記録。`data_level=fp_design` の行は出品に出さない
  (出品くんは `region_only` と同じ扱いで落とせる)。

実行:
    python scrapers/fp_design_records.py --limit 3
    python scrapers/fp_design_records.py --commit
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

_CATALOG_ROOT = Path(__file__).resolve().parent.parent
if str(_CATALOG_ROOT) not in sys.path:
    sys.path.insert(0, str(_CATALOG_ROOT))
import api  # noqa: E402
sys.path.insert(0, str(_CATALOG_ROOT / "scrapers"))
import fashion_press_uniqlo as F  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CATEGORY = "uniqlo_ut"
GAP = Path("C:/dev/iMak_data/catalog/fashion_press/ut_gap.json")
# キッズ / ベビー だけの写真は入れない (対象外)
KID = re.compile(r"キッズ|ベビー|BABY|KIDS|100cm|110cm|120cm|130cm|140cm|150cm|160cm")
# 服でない物 (トートバッグ等) も入れない
NOT_TEE = re.compile(r"バッグ|タオル|ノート|ステッカー|キャップ|マスコット|チャーム|ぬいぐるみ|"
                     r"アートブック|マメザラ|ハンカチ|バンダナ|ポーチ|ストール|グローブ")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--limit", type=int, help="記事の数を絞る (動作確認用)")
    ap.add_argument("--only-missing", action="store_true", default=True,
                    help="catalog に品番で入っていないコラボの記事だけ (既定)")
    a = ap.parse_args()

    arts = json.loads(F.OUT.read_text(encoding="utf-8"))["articles"]
    gap = json.loads(GAP.read_text(encoding="utf-8")) if GAP.exists() else {}
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    have = {x[0] for x in db.execute("SELECT product_id FROM products WHERE category=?", (CATEGORY,))}
    db.close()

    targets = []
    for nid, a_ in arts.items():
        if not F.is_ut_article(a_.get("title") or "", a_.get("detail_text") or ""):
            continue
        g = gap.get(nid) or {}
        if a.only_missing and g.get("catalog_count"):
            continue                      # 品番で入っているコラボは対象外
        targets.append((nid, a_, g))
    targets.sort(key=lambda x: x[1].get("published") or "", reverse=True)
    if a.limit:
        targets = targets[:a.limit]
    print(f"=== 柄の記録 ({'APPLY' if a.commit else 'DRY-RUN'}) — 記事 {len(targets)}本 ===",
          flush=True)

    now = datetime.now().isoformat(timespec="seconds")
    stat, n = Counter(), 0
    for nid, art, g in targets:
        caps = {v.get("img"): v.get("caption", "")
                for v in (art.get("photo_captions") or {}).values() if v.get("img")}
        figs = list(art.get("figures") or [])
        seen = {f["url"] for f in figs}
        for u in (art.get("photos") or []):
            if u not in seen:
                figs.append({"url": u, "caption": caps.get(u, "")})
                seen.add(u)
        collab = ((art.get("names") if isinstance(art.get("names"), list) else None)
                  or (g.get("names") or [""]))[0]
        det = art.get("detail") or {}
        local = art.get("images_local") or {}
        made = 0
        for i, f in enumerate(figs, 1):
            cap = (f.get("caption") or caps.get(f["url"], "")).strip()
            if KID.search(cap) or NOT_TEE.search(cap):
                stat["キッズ / 服でない (入れない)"] += 1
                continue
            if not cap and i > 12:            # 説明文の無い写真は多すぎる時だけ落とす
                stat["説明文なし (入れない)"] += 1
                continue
            pid = f"FP{nid}-{i:02d}"
            if pid in have:
                stat["既に在る"] += 1
                continue
            name = f"{collab or art.get('title','')[:24]} {cap}".strip()[:110]
            specs = {
                "data_level": "fp_design", "source_site": "fashion_press",
                "collab": collab, "release_date": det.get("発売日") or det.get("発売時期") or "",
                "price_text": cap, "article_url": art.get("url"),
                "article_title": art.get("title"), "published": art.get("published"),
                "image_urls": [f["url"]], "image_local": local.get(f["url"], ""),
                "brand": "Uniqlo", "category_line": "UT",
                "not_for_listing": True,      # ★公式値ではない。出品の項目には使わない
                "recorded_at": now,
            }
            made += 1
            n += 1
            if a.commit:
                api.upsert(category=CATEGORY, product_id=pid, name=name, name_jp=name,
                           set_name=None, set_name_official=None, card_set_id=None,
                           language="ja", specs=specs, images=[f["url"]],
                           source="fashion_press_design", source_url=art.get("url"))
        if made:
            stat["柄を作った"] += made
            print(f"    + {art.get('published','')[:10]} {made:2d}柄  {art.get('title','')[:40]}",
                  flush=True)
    print("")
    for k, v in stat.most_common():
        print(f"  {k:28s} {v:,}")
    print(f"\n{'適用' if a.commit else '(dry-run — --commit で適用)'} {n:,}柄")


if __name__ == "__main__":
    main()
