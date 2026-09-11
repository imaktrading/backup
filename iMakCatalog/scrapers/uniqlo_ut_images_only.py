# -*- coding: utf-8 -*-
"""中身が残っていない廃盤 UT を「取れる情報だけ」で catalog に入れる (2026-09-11).

## なぜ要るか

廃盤 UT の判定 (`uniqlo_ut_gone_sweep.py`) で「大人の UT」と確定した品番のうち、
公式 detail も Wayback の保存も中身が無いものがある (2026-09-11 実測: 611件中 440件。
2020年頃より前の商品で、当時のページは表示後に中身を読み込む作りのため保存が殻)。

ユーザー指示「取れる情報」「取れたものは漏らさず保存しろ」。取れるのは次の2つ:

    reviews API   公式のパンくず (性別 / コラボ名) / 評価 / レビュー (買ったサイズ・体型)
    画像サーバー   image.uniqlo.com は廃盤でも生きている。色コードごとのメイン画像 + サブ画像

## 何を入れるか

- `name` は **公式のコラボ名の表示** (パンくず subcategory の locale、例「怪獣８号（UT）」)。
  商品名は残っていないので作らない。`specs.name_is_collab_label = true`
- `specs.data_level = "images_only"` — 素材・実寸表・色名が無い。**出品側はこの印の行を
  そのまま出さない** (目視で商品を特定する用)
- 色は画像のファイル名の色コード (`goods_09_...` の 09) だけ持つ (`color_codes`)。色名は推測しない
- 取った reviews の生 JSON は倉庫へ (`reviews_<pid>.json`)

## 途中保存

1件ごとに DB へ。catalog に在る品番は飛ばす (再実行は残りだけ)。

実行:
    python scrapers/uniqlo_ut_images_only.py --pids-file <候補> --limit 3   # 動作確認
    python scrapers/uniqlo_ut_images_only.py --pids-file <候補> --commit
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path

_CATALOG_ROOT = Path(__file__).resolve().parent.parent
if str(_CATALOG_ROOT) not in sys.path:
    sys.path.insert(0, str(_CATALOG_ROOT))
import api  # noqa: E402
sys.path.insert(0, str(_CATALOG_ROOT / "scrapers"))
import _raw_store  # noqa: E402
import uniqlo_ut as U  # noqa: E402
import uniqlo_ut_discover as D  # noqa: E402
import uniqlo_ut_revive as R  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CATEGORY = "uniqlo_ut"
# ★limit は 1。50 にするとパンくずが空で返る (2026-09-11 実測)
REVIEWS = "https://www.uniqlo.com/jp/api/commerce/v5/ja/products/{pid}/reviews?limit=1"
KID = {"KIDS", "BABY"}


def fetch(pid: str) -> tuple[str, dict | None, list[str]]:
    """(品番, reviews の result, 画像URL)。生 JSON は **取った側で** 倉庫へ."""
    try:
        with urllib.request.urlopen(urllib.request.Request(REVIEWS.format(pid=pid),
                                                           headers=D.UA), timeout=40) as r:
            raw = r.read().decode("utf-8", "ignore")
        _raw_store.save(CATEGORY, f"reviews_{pid}", raw, REVIEWS.format(pid=pid), ext="json")
        res = json.loads(raw).get("result") or {}
    except Exception:
        return pid, None, []
    bc = res.get("breadcrumbs") or {}
    adult_ut = ((bc.get("category") or {}).get("name") == D.UT_CATEGORY
                and (bc.get("class") or {}).get("name") == D.UT_CLASS
                and ((bc.get("gender") or {}).get("name") or "").upper() not in KID)
    # 画像の総当たりは重い (1件で数百回)。大人の UT の時だけ
    return pid, res, (R.images_of(pid) if adult_ut else [])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pids-file", action="append", required=True)
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()

    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    have = {x[0] for x in db.execute(
        "SELECT product_id FROM products WHERE category IN ('uniqlo_ut','gu')")}
    db.close()
    pids: set[str] = set()
    for f in a.pids_file:
        pids |= D.pids_from_file(f)
    todo = sorted(pids - have)
    print(f"  候補 {len(pids):,}件 / catalog に在る {len(pids) - len(todo):,}件 は飛ばす")
    if a.limit:
        todo = todo[:a.limit]
    print(f"=== 画像とコラボ名だけで入れる ({'APPLY' if a.commit else 'DRY-RUN'}) — "
          f"対象 {len(todo):,}件 / 同時 {a.workers}本 ===", flush=True)
    now = datetime.now().isoformat(timespec="seconds")
    stat = Counter()
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        for pid, res, imgs in ex.map(fetch, todo):
            if res is None:
                stat["reviews が取れない"] += 1
                continue
            bc = res.get("breadcrumbs") or {}
            cat = (bc.get("category") or {}).get("name")
            cls = (bc.get("class") or {}).get("name")
            gender = ((bc.get("gender") or {}).get("name") or "").upper()
            if cat != D.UT_CATEGORY or cls != D.UT_CLASS:
                stat["UT ではない"] += 1
                continue
            if gender in KID:
                stat["キッズ (対象外)"] += 1
                continue
            if not imgs:
                stat["画像も無い"] += 1
                continue
            collab = ((bc.get("subcategory") or {}).get("locale") or "").strip()
            if collab in ("その他", "others"):
                collab = ""                    # 「その他」は名前にならない
            label = collab or f"UT {pid} (商品名不明)"
            codes = sorted({m.group(1) for u in imgs
                            for m in [re.search(r"goods_(\d{2})_\d{6}", u)] if m})
            rating = res.get("rating") or {}
            sizes = Counter(x.get("purchasedSize") for x in (res.get("reviews") or [])
                            if x.get("purchasedSize"))
            specs = {
                "gender": "UNISEX" if gender in ("UNISEX", "男女兼用") else gender,
                "department": U._gender_to_dept(gender),
                "collab": collab, "name_is_collab_label": True,
                "data_level": "images_only",
                "image_urls": imgs, "color_codes": codes,
                "rating": rating.get("average"), "review_count": rating.get("count"),
                "review_purchased_sizes": dict(sizes),
                "official_gone_at": now, "revived_at": now, "revived_from": "reviews+cdn",
                "brand": "Uniqlo", "category_line": "UT",
            }
            stat["入れた"] += 1
            print(f"    + {pid}  画像 {len(imgs):2d}枚  色 {','.join(codes):12s} {collab[:30]}",
                  flush=True)
            if a.commit:
                # ★保存の直前にもう一度見る。その間に中身のある行 (公式 / Wayback) が入って
                #   いたら、画像だけの行で上書きしない
                with sqlite3.connect(str(api._DB_PATH), timeout=120) as chk:
                    if chk.execute("SELECT 1 FROM products WHERE category=? AND product_id=?",
                                   (CATEGORY, pid)).fetchone():
                        stat["その間に中身のある行が入った (触らない)"] += 1
                        continue
                try:
                    api.upsert(category=CATEGORY, product_id=pid, name=label,
                               name_jp=label, set_name=None, set_name_official=None,
                               card_set_id=None, language="ja", specs=specs, images=imgs,
                               source="uniqlo_reviews_cdn",
                               source_url=R.PDP.format(pid=pid))
                except Exception as e:
                    stat[f"保存できない ({type(e).__name__})"] += 1
    print("")
    for k, v in stat.most_common():
        print(f"  {k:24s} {v:,}")
    print(f"\n{'適用' if a.commit else '(dry-run — --commit で適用)'} {stat['入れた']:,}件")


if __name__ == "__main__":
    main()
