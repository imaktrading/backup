#!/usr/bin/env python3
"""GU のグラフィックT を「公式の検索に出ない物」まで拾う — 2026-09-15

## なぜ
`gu_graphic_tee.py` は `products?q=グラフィックT` (今の在庫 84件) からしか品番を得ていない。
2026-09-15 実測: catalog の GU 品番の前後を ±15 当たっただけで、
  - **今も公式で買えるのに catalog に無い** グラフィックT (ジョジョの奇妙な冒険2/4、PAC-MAN、UNDERCOVER …)
  - **公式から消えた** グラフィックT (details は nok だが、レビュー API は分類を返す。画像サーバーにも残る)
が出た。9/13 の依頼で ONE PIECE × GU (2024) が丸ごと抜けていたのも同じ理由。UT で使った掘り方を GU に広げる。

## 取り方
    候補     = catalog の GU 品番 + Wayback に保存された GU 商品ページの品番 + 見つけた品番の前後
    判定     = レビュー API のパンくず (limit=1)。category=graphict / class=tops / キッズ・ベビー以外
    生きている = details が ok  → `gu_graphic_tee.py --ids` で取り込む (値はすべて公式)
    消えた     = details が nok → 画像サーバーの画像を総当たり → 画像だけの行 (出品しない印)
                  名前は Wayback の保存ページに商品 JSON があればその名前。無ければ「GU <品番> (商品名不明)」

## 途中保存
    判定は `_raw/gu/_gu_verdicts.jsonl` に1件ずつ追記 (再実行は済んだ品番を飛ばす)
    画像だけの行は1件ずつ保存 / 取り込みは gu_graphic_tee.py 側が途中保存

実行:
    python scrapers/gu_graphic_discover.py --limit 200          # 判定だけ (書かない)
    python scrapers/gu_graphic_discover.py --commit
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scrapers")]
import api  # noqa: E402
import _raw_store  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CATEGORY = "gu"
BASE = "https://www.gu-global.com/jp/api/commerce/v5/ja/products/{pid}"
REVIEWS = BASE + "/reviews?limit=1"
DETAILS = BASE + "/price-groups/00/details"
PDP = "https://www.gu-global.com/jp/ja/products/{pid}/00"
RAW = _raw_store.RAW_ROOT / CATEGORY
VERDICTS = RAW / "_gu_verdicts.jsonl"
WAYBACK_PIDS = RAW / "_wayback_pids.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"}
IMG_BASES = ("https://image.uniqlo.com/GU/ST3/AsianCommon/imagesgoods/{l1}/",
             "https://image.uniqlo.com/GU/ST3/jp/imagesgoods/{l1}/")
IMG_PRE = ("goods", "jpgoods")
KIDS = {"KIDS", "BABY", "GIRLS", "BOYS"}
# 見つけた品番 (と catalog の品番) の前後をこの幅だけ歩く。
# ★8 では足りなかった (2026-09-15): GU は品番がパンツ・靴下等と入り混じっていて、
#   E357167 / E361243 (公式から消えたグラフィックT) が catalog の品番から 8 より離れていて1回目で漏れた
WALK = 20


def _json(url: str) -> dict:
    for attempt in range(3):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25).read())
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return {"status": "nok", "http": e.code}
            time.sleep(2 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError):
            time.sleep(2 * (attempt + 1))
    return {"status": "error"}


def classify(pid: str) -> dict:
    r = _json(REVIEWS.format(pid=pid))
    bc = ((r.get("result") or {}).get("breadcrumbs") or {})
    v = {"pid": pid,
         "gender": ((bc.get("gender") or {}).get("name") or "").upper(),
         "category": (bc.get("category") or {}).get("name") or "",
         "class": (bc.get("class") or {}).get("name") or "",
         "at": datetime.now().isoformat(timespec="seconds")}
    if r.get("status") == "error":
        v["error"] = True
    return v


def is_target(v: dict) -> bool:
    return v.get("category") == "graphict" and v.get("class") == "tops" and v.get("gender") not in KIDS


def load_verdicts() -> dict[str, dict]:
    if not VERDICTS.exists():
        return {}
    out = {}
    for ln in VERDICTS.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            v = json.loads(ln)
            if not v.get("error"):
                out[v["pid"]] = v
    return out


def record(v: dict) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    with VERDICTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(v, ensure_ascii=False) + "\n")


def _head_ok(url: str) -> bool:
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers=UA, method="HEAD"),
                                      timeout=15).status == 200
    except Exception:
        return False


def images_of(pid: str) -> list[str]:
    """画像サーバーを総当たり (並行)。色ごと・サブ番号ごとに最初に当たった1つ."""
    l1 = pid[1:7]
    main = [[b.format(l1=l1) + f"item/{p}_{c:02d}_{l1}_3x4.jpg" for b in IMG_BASES for p in IMG_PRE]
            for c in range(100)]
    subs = [[b.format(l1=l1) + f"sub/{p}_{l1}_sub{n}_3x4.jpg" for b in IMG_BASES for p in IMG_PRE]
            for n in range(1, 40)]
    urls = [u for g in main + subs for u in g]
    with cf.ThreadPoolExecutor(max_workers=32) as ex:
        ok = dict(zip(urls, ex.map(_head_ok, urls)))
    return [next(u for u in g if ok[u]) + "?impolicy=quality" for g in main + subs if any(ok[u] for u in g)]


def wayback_name(pid: str) -> str:
    """Wayback の保存ページに商品 JSON があれば公式の商品名."""
    try:
        cdx = json.loads(urllib.request.urlopen(urllib.request.Request(
            f"https://web.archive.org/cdx/search/cdx?url=gu-global.com/jp/ja/products/{pid}*"
            "&output=json&fl=timestamp,original&filter=statuscode:200&limit=-3", headers=UA),
            timeout=90).read() or b"[]")
    except Exception:
        return ""
    import uniqlo_ut_revive as R
    for ts, orig in sorted(cdx[1:], reverse=True):
        try:
            h = urllib.request.urlopen(urllib.request.Request(
                f"https://web.archive.org/web/{ts}id_/{orig}", headers=UA), timeout=90).read().decode("utf-8", "ignore")
        except Exception:
            continue
        d = R._pdp_product(h, pid)
        if d and d.get("name"):
            _raw_store.save(CATEGORY, f"revive_{pid}", h, orig)
            return d["name"]
    return ""


def catalog_pids(db) -> set[str]:
    return {r[0] for r in db.execute("SELECT product_id FROM products WHERE category=?", (CATEGORY,))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--limit", type=int, help="判定する品番の上限 (動作確認)")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()

    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    have = catalog_pids(db)
    verdicts = load_verdicts()
    seeds = set(have)
    if WAYBACK_PIDS.exists():
        seeds |= set(json.loads(WAYBACK_PIDS.read_text(encoding="utf-8")))
    # ★判定済みの当たりと catalog の品番からも前後を歩く (再実行で WALK を広げた時に効かせるため)
    for p in {q for q, v in verdicts.items() if is_target(v)} | have:
        n = int(p[1:7])
        seeds |= {f"E{k:06d}-000" for k in range(n - WALK, n + WALK + 1)}
    queue = sorted(p for p in seeds if p not in verdicts)
    print(f"  候補 {len(seeds)}件 / 判定済み {len(seeds) - len(queue)}件 は飛ばす", flush=True)

    stat = Counter()
    probed = 0

    def run_batch(pids: list[str]) -> list[dict]:
        with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
            return list(ex.map(classify, pids))

    # 1) 候補を判定。当たった品番の前後を歩く
    while queue and (not a.limit or probed < a.limit):
        batch = queue[:60]
        queue = queue[60:]
        for v in run_batch(batch):
            probed += 1
            record(v)
            if v.get("error"):
                stat["判定できず (後で再実行)"] += 1
                continue
            verdicts[v["pid"]] = v
            if is_target(v):
                n = int(v["pid"][1:7])
                for k in range(n - WALK, n + WALK + 1):
                    p = f"E{k:06d}-000"
                    if p not in verdicts and p not in queue:
                        queue.append(p)
        if probed % 600 < 60:
            hits = sum(1 for v in verdicts.values() if is_target(v))
            print(f"  判定 {probed}件 / グラフィックT {hits}件 / 残り候補 {len(queue)}件", flush=True)

    targets = sorted(p for p, v in verdicts.items() if is_target(v) and p not in have)
    print(f"  catalog に無い大人のグラフィックT: {len(targets)}件", flush=True)

    # 2) 生きている / 消えた に分ける
    alive, gone = [], []
    for p in targets:
        d = _json(DETAILS.format(pid=p))
        (alive if d.get("status") == "ok" else gone).append(p)
    stat["生きている (公式から取り込む)"] = len(alive)
    stat["公式から消えた"] = len(gone)
    print(f"  生きている {len(alive)}件 / 消えた {len(gone)}件", flush=True)

    # 3) 生きている → gu_graphic_tee.py (値はすべて公式)
    if alive:
        for i in range(0, len(alive), 40):
            cmd = [sys.executable, str(ROOT / "scrapers" / "gu_graphic_tee.py"),
                   "--ids", ",".join(alive[i:i + 40])] + (["--commit"] if a.commit else [])
            out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
            print("\n".join(out.stdout.strip().splitlines()[-3:]), flush=True)

    # 4) 消えた → 画像だけの行
    now = datetime.now().isoformat(timespec="seconds")
    for p in gone:
        imgs = images_of(p)
        if not imgs:
            stat["消えた・画像も無い"] += 1
            continue
        name = wayback_name(p)
        stat["画像だけの行" + (" (名前は Wayback)" if name else "")] += 1
        print(f"    + {p}  画像 {len(imgs):2d}枚  {name[:40]}", flush=True)
        if not a.commit:
            continue
        with sqlite3.connect(str(api._DB_PATH), timeout=120) as chk:
            if chk.execute("SELECT 1 FROM products WHERE category=? AND product_id=?", (CATEGORY, p)).fetchone():
                stat["その間に行が入った (触らない)"] += 1
                continue
        v = verdicts[p]
        api.upsert(category=CATEGORY, product_id=p, name=name or f"GU {p} (商品名不明)",
                   name_jp=name or "", set_name=None, set_name_official=None, card_set_id=None,
                   language="ja",
                   specs={"brand": "GU", "gender": v.get("gender"), "data_level": "images_only",
                          "not_for_listing": True,
                          "not_for_listing_reason": "公式から消えた商品。画像だけで色・サイズ・素材が無い",
                          "image_urls": imgs, "official_gone_at": now,
                          "revived_from": "reviews+cdn" + ("+wayback_name" if name else ""),
                          "revived_at": now},
                   images=imgs, source="gu_reviews_cdn", source_url=PDP.format(pid=p))

    for k, v in stat.most_common():
        print(f"  {k}: {v}")
    print("commit" if a.commit else "dry-run (書き込みなし)", flush=True)


if __name__ == "__main__":
    main()
