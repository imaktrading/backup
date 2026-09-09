# -*- coding: utf-8 -*-
"""UT の「出品に要る値」を公式から取り切って catalog に焼く (2026-09-09 新設).

## なぜ要るか

**廃盤になると公式から全部消える。** 2026-09-09 実測:

    現行品 E485482  detail API 200 / 画像13枚 / 素材 / 原産国 / 透け感  すべて取れる
    廃盤品 E475823  detail API 404 / 商品ページ 404                  何も取れない

画像URLだけは CDN に生き残る (2021年の E420005 が今も 200) が、**URLを知る手段が消える**。
実寸表に至っては復元手段が無い。だから **現役のうちに取り切って catalog に持つ**。

取り込み当時 (2026-05) は「商品名・色・サイズ記号・価格・正面画像1枚」しか取っていなかった。
出品くんは毎回 公式を叩き直して 素材・原産国・透け感・実寸を集めている
(skill `apparel-tee-listing`)。廃盤になった時点でそれができなくなる。

## 取るもの (公式 detail API 1回で全部)

    images.main / sub / features / chip   全画像 (実測 13枚)
    composition                           素材 (Material)
    countriesOfOrigin                     原産国 (Country of Origin)
    designDetail                          透け感 / トップスフィット (Fit)
    longDescription / shortDescription    キャラ判定に使う説明文
    careInstruction / washingInformation  洗濯表示
    sizeChartUrl                          実寸表の場所 (本体は別途 Selenium。403 で直読み不可)

★実寸表 (身丈/肩幅/身幅/裄丈) は **この scraper では取らない**。
  `.../size/<l1id>_size.html` は bot に 403 を返すため、PDP のモーダルを開くしかない。
  `scrapers/uniqlo_ut_sizechart.py` (Selenium) が担当する。

## 生データをそのまま残す

取った JSON と 商品ページ HTML を `_raw/uniqlo_ut/` に置く (`scrapers/_raw_store.py`)。
**次に別の項目が要ると分かった時、取り直しが要らない。** 廃盤になったら二度と取れないので、
「今 使う項目」だけ抜いて捨てるのは危ない。

## 途中保存 (CLAUDE.md「長く走るものは必ず途中保存」)

  - 20件ごとに commit する
  - 再実行時は **DB を見て** 済んだ行 (`specs.enriched_at` あり) を飛ばす
  - 飛ばした件数を出す
  - 廃盤 (404) は `specs.official_gone_at` を残し、次回も再挑戦しない

実行:
    python scrapers/uniqlo_ut_enrich.py            # 何件対象か見る
    python scrapers/uniqlo_ut_enrich.py --commit
    python scrapers/uniqlo_ut_enrich.py --commit --include-kids
"""
from __future__ import annotations

import argparse
import json
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

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CATEGORY = "uniqlo_ut"
DETAIL = ("https://www.uniqlo.com/jp/api/commerce/v5/ja/products/{pid}"
          "/price-groups/00/details?includeModelSize=true&httpFailure=true")
PDP = "https://www.uniqlo.com/jp/ja/products/{pid}/00"
UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"),
      "Accept-Language": "ja,en;q=0.8"}
SLEEP = 0.4
SAVE_EVERY = 20
# ★キッズ・ベビーは扱わない (2026-09-09 ユーザー確定)
KID_GENDERS = {"KIDS", "BABY"}


def _get(url: str) -> str:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read().decode("utf-8", "ignore")


def fetch(pid: str) -> dict | None:
    """公式 detail。廃盤は 404 が飛ぶ。**生データはそのまま倉庫に置く**."""
    raw = _get(DETAIL.format(pid=pid))
    _raw_store.save(CATEGORY, f"detail_{pid}", raw, DETAIL.format(pid=pid), ext="json")
    return json.loads(raw).get("result") or {}


def archive_pdp(pid: str) -> None:
    """商品ページ HTML も残す (API に出ない文言が要ることがある)。失敗は無視."""
    if _raw_store.have(CATEGORY, f"pdp_{pid}"):
        return
    try:
        _raw_store.save(CATEGORY, f"pdp_{pid}", _get(PDP.format(pid=pid)),
                        PDP.format(pid=pid), ext="html")
    except Exception:
        pass


def all_images(images: dict) -> list[str]:
    """images の4種 (main / sub / features / chip) を1本の並びにする。

    公式の並び順を保つ (main -> sub -> features -> chip)。出品の1枚目は main。
    """
    out: list[str] = []

    def add(u):
        if u and u not in out:
            out.append(u)

    for _k, v in sorted((images.get("main") or {}).items()):
        add(v.get("image") if isinstance(v, dict) else v)
    for v in images.get("sub") or []:
        add(v.get("image") if isinstance(v, dict) else v)
    for v in images.get("features") or []:
        add(v.get("imageUrl") if isinstance(v, dict) else v)
    for _k, v in sorted((images.get("chip") or {}).items()):
        add(v if isinstance(v, str) else (v or {}).get("image"))
    return out


def feature_texts(images: dict) -> list[dict]:
    return [{"image": v.get("imageUrl"), "text": v.get("text")}
            for v in (images.get("features") or []) if isinstance(v, dict)]


def targets(db, include_kids: bool) -> list[sqlite3.Row]:
    rows = db.execute(
        "SELECT id, product_id, name, images, specs FROM products WHERE category=?",
        (CATEGORY,)).fetchall()
    out, skipped, kids = [], 0, 0
    for r in rows:
        s = json.loads(r["specs"] or "{}")
        if not include_kids and str(s.get("gender") or "").upper() in KID_GENDERS:
            kids += 1
            continue
        if s.get("enriched_at") or s.get("official_gone_at"):
            skipped += 1
            continue
        out.append(r)
    print(f"  済み {skipped}行 は飛ばす / キッズ・ベビー {kids}行 は対象外")
    return out


def run(commit: bool, include_kids: bool, limit: int | None) -> None:
    db = sqlite3.connect(str(api._DB_PATH))
    db.row_factory = sqlite3.Row
    rows = targets(db, include_kids)
    if limit:
        rows = rows[:limit]
    print(f"=== UT 仕上げ ({'APPLY' if commit else 'DRY-RUN'}) — 対象 {len(rows)}行 ===")

    now = datetime.now().isoformat(timespec="seconds")
    stat, done, gone = Counter(), 0, 0
    for i, r in enumerate(rows, 1):
        pid = r["product_id"]
        try:
            d = fetch(pid)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                gone += 1
                stat["廃盤 (公式から消えた)"] += 1
                if commit:
                    s = json.loads(r["specs"] or "{}")
                    s["official_gone_at"] = now
                    db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                               (json.dumps(s, ensure_ascii=False), now, r["id"]))
                time.sleep(SLEEP)
                continue
            stat[f"HTTP {e.code}"] += 1
            time.sleep(SLEEP)
            continue
        except Exception as e:
            stat[type(e).__name__] += 1
            time.sleep(SLEEP)
            continue

        s = json.loads(r["specs"] or "{}")
        imgs = all_images(d.get("images") or {})
        if imgs:
            stat["画像を入れた"] += 1
        for key, src in (("composition", "composition"),
                         ("design_detail", "designDetail"),
                         ("long_description", "longDescription"),
                         ("short_description", "shortDescription"),
                         ("care_instruction", "careInstruction"),
                         ("washing_information", "washingInformation"),
                         ("size_chart_url", "sizeChartUrl"),
                         ("product_type_official", "productType")):
            v = d.get(src)
            if v not in (None, "", [], {}):
                if not s.get(key):
                    stat[key] += 1
                s[key] = v
        coo = [x.get("code") for x in (d.get("countriesOfOrigin") or []) if x.get("code")]
        if coo:
            if not s.get("countries_of_origin"):
                stat["countries_of_origin"] += 1
            s["countries_of_origin"] = coo
        ft = feature_texts(d.get("images") or {})
        if ft:
            s["feature_texts"] = ft
        s["image_urls"] = imgs or s.get("image_urls") or []
        s["enriched_at"] = now
        archive_pdp(pid)                      # 生の商品ページも残す

        if commit:
            db.execute("UPDATE products SET images=?, specs=?, updated_at=? WHERE id=?",
                       (json.dumps(imgs or json.loads(r["images"] or "[]"), ensure_ascii=False),
                        json.dumps(s, ensure_ascii=False), now, r["id"]))
            done += 1
            if done % SAVE_EVERY == 0:          # ★途中保存
                db.commit()
                print(f"    ... {done}行 保存 ({i}/{len(rows)})")
        time.sleep(SLEEP)

    if commit:
        db.commit()
    db.close()
    print("")
    for k, v in stat.most_common():
        print(f"  {k:28s} {v}")
    print("")
    print(f"{'適用' if commit else '(dry-run — --commit で適用)'} "
          f"{done}行 / 廃盤 {gone}行")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--include-kids", action="store_true", help="キッズ・ベビーも取る")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    run(a.commit, a.include_kids, a.limit)


if __name__ == "__main__":
    main()
