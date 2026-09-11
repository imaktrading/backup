# -*- coding: utf-8 -*-
"""廃盤で公式から消えた UT を **全部** 洗い出して起こす (2026-09-11 新設).

## なぜ要るか

UT の探索 (`uniqlo_ut_discover.py`) は、Wayback に写っていた品番 21,694件を公式 detail で
確かめ、**404 (廃盤) を全部捨てていた**。= 仕入れ対象の「公式で買えない物」を落としていた。
ユーザー指摘「怪獣8号・細田守が取れていない」で判明。

## 判定 — レビューの API は廃盤でも返る

    detail   /jp/api/commerce/v5/ja/products/{pid}/price-groups/00/details   廃盤 → 404
    reviews  /jp/api/commerce/v5/ja/products/{pid}/reviews?limit=1            廃盤でも 200

reviews には **公式のパンくず** (gender / class / category / subcategory) が入っている
(2026-09-11 実測: E440689 細田守 UT → MEN / tops / ut graphic tees)。
= 公式 API だけで「大人の UT か」を速く判定できる。当たった物だけ Wayback で起こす
(`uniqlo_ut_revive.py`。Wayback は1件30秒ほどかかるので、判定で絞るのが肝)。

## 途中保存 (CLAUDE.md「長く走るものは必ず途中保存」)

  - 判定した品番は state に貯める → 再実行は **判定し直さない** (飛ばした件数を出す)
  - 200件ごとに保存。UT 候補は `_ut_gone_candidates.txt` に書き出す

実行:
    python scrapers/uniqlo_ut_gone_sweep.py --limit 50     # 動作確認 (判定だけ)
    python scrapers/uniqlo_ut_gone_sweep.py                # 判定だけ (全件)
    python scrapers/uniqlo_ut_gone_sweep.py --revive       # 判定 + 起こす
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

_CATALOG_ROOT = Path(__file__).resolve().parent.parent
if str(_CATALOG_ROOT) not in sys.path:
    sys.path.insert(0, str(_CATALOG_ROOT))
import api  # noqa: E402
sys.path.insert(0, str(_CATALOG_ROOT / "scrapers"))
import uniqlo_ut_discover as D  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REVIEWS = "https://www.uniqlo.com/jp/api/commerce/v5/ja/products/{pid}/reviews?limit=1"
STATE = Path("C:/dev/iMak_data/catalog/_ut_gone_sweep_state.json")
CAND = Path("C:/dev/iMak_data/catalog/_ut_gone_candidates.txt")
KID = {"KIDS", "BABY"}
SLEEP = 0.25


def classify(pid: str) -> str:
    """'ut' / 'kids' / 'not_ut' / 'none' (reviews も無い) / 'err'."""
    try:
        with urllib.request.urlopen(urllib.request.Request(REVIEWS.format(pid=pid),
                                                           headers=D.UA), timeout=40) as r:
            j = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return "none" if e.code == 404 else "err"
    except Exception:
        return "err"
    finally:
        time.sleep(SLEEP)
    bc = (j.get("result") or {}).get("breadcrumbs") or {}
    if not bc:
        return "none"
    cat = (bc.get("category") or {}).get("name")
    cls = (bc.get("class") or {}).get("name")
    gender = ((bc.get("gender") or {}).get("name") or "").upper()
    if gender in KID:
        return "kids"
    return "ut" if (cat == D.UT_CATEGORY and cls == D.UT_CLASS) else "not_ut"


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"checked": {}}


def save_state(st: dict) -> None:
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATE)
    CAND.write_text("\n".join(sorted(p for p, v in st["checked"].items() if v == "ut")),
                    encoding="ascii")


def run(limit: int | None, workers: int, revive: bool, commit: bool,
        extra: list[str] | None = None) -> None:
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    have = {x[0] for x in db.execute(
        "SELECT product_id FROM products WHERE category IN ('uniqlo_ut','gu')")}
    db.close()
    st = load_state()
    checked = st["checked"]
    pool_pids = D.from_wayback()
    print(f"  Wayback の品番 {len(pool_pids):,}件 / catalog に在る分は飛ばす")
    for f in extra or []:                        # Google 等で拾った品番も同じ判定に通す
        more = D.pids_from_file(f)
        print(f"  {Path(f).name} から {len(more - pool_pids):,}件 足す")
        pool_pids |= more
    todo = [p for p in sorted(pool_pids, key=lambda p: -int(p[1:7]))
            if p not in have and checked.get(p) not in ("ut", "kids", "not_ut", "none")]
    skip = len([p for p in pool_pids if p not in have]) - len(todo)
    print(f"  判定済み {skip:,}件 は飛ばす")
    if limit:
        todo = todo[:limit]
    print(f"=== 廃盤 UT の判定 — 対象 {len(todo):,}件 / 同時 {workers}本 ===", flush=True)
    stat = Counter()
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for i, (pid, v) in enumerate(zip(todo, ex.map(classify, todo)), 1):
            checked[pid] = v
            stat[v] += 1
            if i % 200 == 0:                     # ★途中保存
                save_state(st)
                print(f"    {i:,}/{len(todo):,}  UT {stat['ut']:,} / キッズ {stat['kids']:,} / "
                      f"UT でない {stat['not_ut']:,} / 手がかり無し {stat['none']:,}", flush=True)
    save_state(st)
    n_ut = sum(1 for p, v in checked.items() if v == "ut" and p not in have)
    print("")
    for k, v in stat.most_common():
        print(f"  {k:10s} {v:,}")
    print(f"\n  catalog に無い大人の UT: {n_ut:,}件 → {CAND}")
    if revive:
        import uniqlo_ut_revive as R
        R.run(commit, None, str(CAND), workers=2)


NB_STATE = Path("C:/dev/iMak_data/catalog/_ut_gone_neighbors_state.json")
NB_CAND = Path("C:/dev/iMak_data/catalog/_ut_gone_neighbor_candidates.txt")
WALK_MISS = 6


def run_neighbors(workers: int) -> None:
    """UT の品番の **前後** を歩く。コラボの柄は連番で並ぶ (例 E481118/119/120 が鬼滅)。

    ★判定はレビュー API なので **廃盤の番号も見える** (探索の隣歩きは detail API で、
      廃盤の隣を全部「空振り」にしていた)。キッズも同じコラボの塊なので歩き続ける。
    ★判定済みは叩き直さない (本判定の state と、この歩きの state の両方を見る)。
    """
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    rows = db.execute("SELECT product_id, specs FROM products WHERE category='uniqlo_ut'").fetchall()
    db.close()
    have = {p for p, _ in rows}
    main_checked = load_state()["checked"]
    nb = json.loads(NB_STATE.read_text(encoding="utf-8")) if NB_STATE.exists() else {"checked": {}}
    known = dict(main_checked)
    known.update(nb["checked"])
    member = {"ut", "kids"}                      # 塊の中とみなす判定
    seeds = sorted({int(p[1:7]) for p in have if p.endswith("-000")}
                   | {int(p[1:7]) for p, v in known.items() if v in member})
    print(f"  起点 {len(seeds):,}件 / 判定済み {len(known):,}件 は叩き直さない", flush=True)

    def verdict(pid: str) -> str:
        if pid in have:
            return "ut"
        if pid in known:
            return known[pid]
        v = classify(pid)
        nb["checked"][pid] = v
        known[pid] = v
        return v

    queue, seen, done, found = list(seeds), set(seeds), 0, 0
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        while queue:
            batch, queue = queue[:workers], queue[workers:]
            # 起点ごとに前後を歩く (起点の中は順番、起点どうしは並行)
            def walk(n0: int) -> list[int]:
                hits = []
                for step in (-1, 1):
                    miss, n = 0, n0
                    while miss < WALK_MISS and 100000 <= n + step <= 999999:
                        n += step
                        v = verdict(f"E{n:06d}-000")
                        if v in member:
                            miss = 0
                            if v == "ut" and f"E{n:06d}-000" not in have:
                                hits.append(n)
                        else:
                            miss += 1
                return hits
            for hits in ex.map(walk, batch):
                for n in hits:
                    found += 1
                    if n not in seen:            # 見つけた先からも歩く
                        seen.add(n)
                        queue.append(n)
            done += len(batch)
            if done % 100 < workers:
                NB_STATE.write_text(json.dumps(nb, ensure_ascii=False), encoding="utf-8")
                cand = sorted(p for p, v in nb["checked"].items() if v == "ut" and p not in have)
                NB_CAND.write_text("\n".join(cand), encoding="ascii")
                print(f"    起点 {done:,} 済み / 残り {len(queue):,} / 新しい UT {len(cand):,}", flush=True)
    NB_STATE.write_text(json.dumps(nb, ensure_ascii=False), encoding="utf-8")
    cand = sorted(p for p, v in nb["checked"].items() if v == "ut" and p not in have)
    NB_CAND.write_text("\n".join(cand), encoding="ascii")
    print(f"\n  前後で見つけた大人の UT (catalog に無い): {len(cand):,}件 → {NB_CAND}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--revive", action="store_true", help="判定のあと Wayback で起こす")
    ap.add_argument("--commit", action="store_true", help="--revive の結果を保存する")
    ap.add_argument("--extra", action="append", help="足す品番リスト (Google で拾った分など)")
    ap.add_argument("--neighbors", action="store_true",
                    help="UT の前後の品番を歩く (レビュー API で判定。廃盤も見える)")
    a = ap.parse_args()
    if a.neighbors:
        run_neighbors(a.workers)
    else:
        run(a.limit, a.workers, a.revive, a.commit, a.extra)


if __name__ == "__main__":
    main()
