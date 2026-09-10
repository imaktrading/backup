# -*- coding: utf-8 -*-
"""公式の検索に出てこない UT を **外から** 見つける (2026-09-10 新設).

## なぜ要るか — 公式の検索は「今買えるもの」しか返さない

2026-09-10 ユーザー指摘。`E481120-000` (鬼滅の刃 UT) が catalog に無かった。
実測すると、これまでの取り込み口が全部 **今の在庫しか見ていなかった**:

    products?q=UT                       266件   ← これまでの唯一の入口
    products?q=鬼滅の刃                   0件   ← コラボ名では引けない
    products?path=1072,1750,1771        127件   (MEN の UT カテゴリ)
    sitemap                             商品ページを1件も載せていない

なのに **商品ページと detail API は生きている** (`E481120-000` は 200 が返る)。
= 番号さえ分かれば全部取れる。**番号を知る手段が無かっただけ。**

ユーザー指示:「google でキーワード入れて、ユニクロドメインなら、取りに行かないと」

## 番号の見つけ方 (3つ。安くて当たる順に走る)

    1. 検索      コラボ名で site:uniqlo.com を引き、商品URLの品番を拾う
                 (2026-09-10 実測: 「ユニクロ 鬼滅の刃 UT」で E481118/119/120 が出た)
    2. 隣の番号   コラボの商品は **連番で並ぶ**。既知の品番の前後を歩く
                 (実測: E481118/119/120 が鬼滅、E481121/124/125 がパウ・パトロール)
    3. Wayback   CDX に商品URLが **21,694件**。公式の266件と桁が違う

## UT かどうかの判定 — 名前ではなく **公式のパンくず**

    breadcrumbs.category.name == "ut graphic tees"

名前に "UT" が入るキッズ商品 (`パウ・パトロール UT`) はパンくずが `tops` になる。
名前で見ると入ってしまう (2026-09-10 実測)。**公式の分類をそのまま使う。**
キッズ・ベビーは対象外 (2026-09-09 ユーザー確定)。

## 途中保存 (CLAUDE.md「長く走るものは必ず途中保存」)

  - 叩いた品番は state に貯める → 再実行は **叩き直さない** (飛ばした件数を出す)
  - 見つかった商品は 1件ごとに DB へ保存。生 JSON は `_raw/uniqlo_ut/` に置く
  - 途中で落ちても、次の実行が続きから走る

★検索は **既定では走らせない**。2026-09-10 実測で 80語ほど投げたところで 403 が続いた
  (鍵無しの検索は連投を許さない)。番号は Wayback と 隣の番号で取れるので、そちらを既定にする。
  使う時は `--search`。5回続けて弾かれたら自分で打ち切る。

実行:
    python scrapers/uniqlo_ut_discover.py --limit 20           # 動作確認 (dry-run)
    python scrapers/uniqlo_ut_discover.py --commit             # Wayback + 隣の番号
    python scrapers/uniqlo_ut_discover.py --search --commit    # 検索も足す
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
import urllib.parse
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
import uniqlo_ut_enrich as E  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CATEGORY = "uniqlo_ut"
STATE = Path("C:/dev/iMak_data/catalog/_ut_discover_state.json")
PDP = "https://www.uniqlo.com/jp/ja/products/{pid}/00"
SEARCH = "https://html.duckduckgo.com/html/?q={q}"
CDX = ("http://web.archive.org/cdx/search/cdx?url=uniqlo.com/jp/ja/products*"
       "&output=json&fl=original&filter=statuscode:200&collapse=urlkey&limit=200000")
UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")}
_PID = re.compile(r"(?:/products/|products%2F)(E\d{6}-\d{3})")
# ★UT の判定は公式のパンくず。名前で見ると キッズの「〜 UT」が入る
UT_CATEGORY = "ut graphic tees"
KID = {"KIDS", "BABY"}
SLEEP_API = 0.25          # 公式 API (並行して叩くので短め)
SLEEP_SEARCH = 8.0        # 検索エンジン (連投すると閉める)
WALK_MISS = 6             # 隣を歩く時、何回続けて空振りしたら止めるか


# ---------------------------------------------------------------- 下ごしらえ
def _get(url: str, timeout: int = 40, tries: int = 3) -> str:
    for i in range(tries):
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and i < tries - 1:
                time.sleep(15 * (i + 1))
                continue
            raise
    raise RuntimeError("unreachable")


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"probed": [], "queried": [], "cand": []}


def save_state(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"probed": sorted(st["probed"]),
                                 "queried": sorted(st["queried"]),
                                 "cand": sorted(st.get("cand") or [])},
                                ensure_ascii=False), encoding="utf-8")


def keywords(db) -> list[str]:
    """検索に投げる語。**catalog が既に知っているコラボ名**から作る (推測しない)."""
    ks: set[str] = set()
    for (sp,) in db.execute("SELECT specs FROM products WHERE category='uniqlo_ut'"):
        s = json.loads(sp or "{}")
        for v in (s.get("collab"), s.get("character_family"),
                  s.get("collab_official_name")):
            if v and len(str(v)) >= 2:
                ks.add(str(v))
    # 名前の頭 (「鬼滅の刃 UT」の「鬼滅の刃」) も拾う。コラボ名が specs に無い行のため
    for (nm,) in db.execute("SELECT name FROM products WHERE category='uniqlo_ut'"):
        head = re.split(r"\s*UT[\s/（(]|\s+UT$", nm or "")[0].strip()
        if 2 <= len(head) <= 24:
            ks.add(head)
    # キッズ・ベビーの品揃えは対象外なので、その語では引かない
    return sorted(k for k in ks
                  if not k.upper().startswith(("KIDS", "GIRLS", "BOYS", "BABY")))


# ---------------------------------------------------------------- 番号を探す
def from_search(words: list[str], st: dict, pace: float = SLEEP_SEARCH) -> set[str]:
    """コラボ名で site:uniqlo.com を引き、商品URLの品番を拾う."""
    found: set[str] = set()
    todo = [w for w in words if w not in st["queried"]]
    print(f"  検索: 語 {len(words)}個 / 済み {len(words) - len(todo)}個 は飛ばす")
    ng = 0
    for i, w in enumerate(todo, 1):
        q = urllib.parse.quote(f"ユニクロ {w} UT site:uniqlo.com")
        try:
            hits = set(_PID.findall(_get(SEARCH.format(q=q), timeout=60)))
            ng = 0
        except Exception as e:
            ng += 1
            print(f"    ! {w[:20]:22s} {getattr(e, 'code', type(e).__name__)}", flush=True)
            # ★検索エンジンは連投すると閉める (2026-09-10 実測: 80語ほどで 403 が続いた)。
            #   続けて弾かれ始めたら **やめる**。番号は Wayback と 隣の番号で取れる
            if ng >= 5:
                print("    検索が弾かれ続けるので打ち切る "
                      "(Wayback と 隣の番号で拾う)", flush=True)
                break
            time.sleep(pace * 4)
            continue
        new = hits - found
        found |= hits
        st["cand"] = sorted(set(st.get("cand") or []) | hits)
        st["queried"].append(w)
        if new:
            print(f"    {i:4d}/{len(todo)} {w[:22]:24s} 品番 {len(new):2d}件", flush=True)
        if i % 20 == 0:
            save_state(st)
        time.sleep(pace)
    save_state(st)
    return found


def from_neighbors(seeds: set[str], known: set[str], st: dict, on_found) -> set[str]:
    """既知の品番の **前後を歩く**。コラボの商品は連番で並ぶ.

    ★見つけた品番も **その場で新しい起点にする** (塊の端から端まで拾い切るため)。
      2026-09-10 実測: E481118 だけを起点にして E481119 / E481120 に届いた
      (= ユーザーが手で見つけた3件を、番号だけで辿れる)。
    """
    probed = set(st["probed"])
    found: set[str] = set()
    queue = sorted({int(p[1:7]) for p in seeds if re.fullmatch(r"E\d{6}-\d{3}", p)})
    seen_seed = set(queue)
    print(f"  隣の番号: 起点 {len(queue)}件 から前後に歩く")
    done = 0
    while queue:
        n0 = queue.pop(0)
        done += 1
        for step in (-1, 1):
            miss, n = 0, n0
            while miss < WALK_MISS:
                n += step
                pid = f"E{n:06d}-000"
                if pid in known or pid in probed:
                    miss = 0                      # 既に知っている = まだ塊の中
                    continue
                probed.add(pid)
                d = detail(pid)
                if d is None:
                    miss += 1
                else:
                    miss = 0
                    found.add(pid)
                    on_found(pid, d)
                    if n not in seen_seed:        # 見つけた先からも歩く
                        seen_seed.add(n)
                        queue.append(n)
                time.sleep(SLEEP_API)
        if done % 25 == 0:
            st["probed"] = list(probed)
            save_state(st)
            print(f"    起点 {done}件 完了 / 残り {len(queue)}件 / "
                  f"見つけた {len(found)}件", flush=True)
    st["probed"] = list(probed)
    save_state(st)
    return found


def pids_from_file(path: str) -> set[str]:
    """外部から貰った品番リストを読む (2026-09-10)。

    HQ 発行の仕入元URL dump (`FLG,item_id,title,supply_url,ebay_url` の CSV) や
    1行1品番のテキストをそのまま渡せる。**uniqlo.com の行だけ**から品番を拾う
    (同じ CSV に gu-global.com の行が混ざっていても、この scraper (uniqlo_ut) には
    取り込まない — GU は `gu_graphic_tee.py` の担当)。
    """
    out: set[str] = set()
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    for line in text.splitlines():
        if "uniqlo.com" in line:
            out |= set(_PID.findall(line))
        else:
            m = re.fullmatch(r"\s*(E\d{6}-\d{3})\s*", line)
            if m:
                out.add(m.group(1))
    return out


def from_wayback() -> set[str]:
    """Wayback の商品URLから品番を集める (2026-09-10 実測 21,694件)."""
    rows = json.loads(_get(CDX, timeout=240))[1:]
    pids: set[str] = set()
    for row in rows:
        pids |= set(_PID.findall(row[0]))
    print(f"  Wayback: URL {len(rows):,}件 -> 品番 {len(pids):,}件")
    return pids


# ---------------------------------------------------------------- 中身を確かめる
_DETAIL_CACHE: dict[str, dict | None] = {}


def detail(pid: str) -> dict | None:
    """公式 detail。**UT でなければ None** (パンくずで判定)。廃番は 404."""
    if pid in _DETAIL_CACHE:
        return _DETAIL_CACHE[pid]
    try:
        raw = _get(E.DETAIL.format(pid=pid), timeout=40, tries=2)
    except Exception:
        _DETAIL_CACHE[pid] = None
        return None
    try:
        r = json.loads(raw).get("result") or {}
    except Exception:
        _DETAIL_CACHE[pid] = None
        return None
    cat = ((r.get("breadcrumbs") or {}).get("category") or {}).get("name") or ""
    if cat != UT_CATEGORY:
        _DETAIL_CACHE[pid] = None
        return None
    if (r.get("genderName") or "").strip().upper() in KID:
        _DETAIL_CACHE[pid] = None
        return None
    _raw_store.save(CATEGORY, f"detail_{pid}", raw, E.DETAIL.format(pid=pid), ext="json")
    _DETAIL_CACHE[pid] = r
    return r


def _polite(fn):
    """並行で叩く時も、1本あたり必ず間を空ける (公式に負担をかけない)."""
    def inner(pid: str):
        try:
            return fn(pid)
        finally:
            time.sleep(SLEEP_API)
    return inner


def store(db, pid: str, d: dict, now: str) -> None:
    """見つけた UT を catalog に入れる (現行の取り込みと同じ形)."""
    imgs = E.all_images(d.get("images") or {})
    gender = (d.get("genderName") or "").strip().upper()
    specs = {
        "gender": gender, "department": U._gender_to_dept(gender),
        "composition": d.get("composition") or "",
        "design_detail": d.get("designDetail") or "",
        "long_description": d.get("longDescription") or "",
        "short_description": d.get("shortDescription") or "",
        "care_instruction": d.get("careInstruction") or "",
        "size_chart_url": d.get("sizeChartUrl") or "",
        "countries_of_origin": [x.get("code") for x in (d.get("countriesOfOrigin") or [])
                                if x.get("code")],
        "image_urls": imgs, "enriched_at": now, "discovered_at": now,
        "l1_id": (d.get("l1Ids") or [None])[0],
        "collab": (((d.get("breadcrumbs") or {}).get("subcategory") or {}).get("locale") or ""),
    }
    api.upsert(category=CATEGORY, product_id=pid,
               name=d.get("name") or "", name_jp=d.get("name") or "",
               set_name=None, set_name_official=None, card_set_id=None,
               language="ja", specs=specs, images=imgs,
               source="uniqlo_discover", source_url=PDP.format(pid=pid))


# ---------------------------------------------------------------- 本体
def run(args) -> None:
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    db.row_factory = sqlite3.Row
    known = {x[0] for x in db.execute(
        "SELECT product_id FROM products WHERE category IN ('uniqlo_ut','gu')")}
    st = load_state()
    print(f"  catalog が持っている品番 {len(known):,}件 / "
          f"叩いたことがある {len(st['probed']):,}件")

    now = datetime.now().isoformat(timespec="seconds")
    stat, saved = Counter(), []

    def keep(pid: str, d: dict) -> None:
        """見つけた1件を **その場で** 保存する (途中で落ちても残す)."""
        stat["見つけた"] += 1
        print(f"    + {pid}  画像 {len(E.all_images(d.get('images') or {})):2d}枚  "
              f"{(d.get('genderName') or ''):7s} {(d.get('name') or '')[:34]}", flush=True)
        if not args.commit:
            return
        try:
            store(db, pid, d, now)
            saved.append(pid)
            known.add(pid)
        except Exception as e:              # ★1件の失敗で走行を落とさない
            stat[f"保存できない ({type(e).__name__})"] += 1

    # ---- 1) 検索 / Wayback で集めた品番を確かめる
    cand: set[str] = set(st.get("cand") or [])   # 前回までに見つけた分
    if args.search:
        kw = keywords(db)
        cand |= from_search(kw[:args.kw_limit] if args.kw_limit else kw, st)
    if args.wayback:
        cand |= from_wayback()
    if args.pids_file:
        cand |= pids_from_file(args.pids_file)

    probed = set(st["probed"])
    todo = [c for c in cand if c not in known and c not in probed]
    skip = len([c for c in cand if c not in known]) - len(todo)
    # ★新しい番号から見る。UT は **E42xxxx〜E49xxxx に固まっている**
    #   (2026-09-10 実測: 既知1,592件が全部 E4 台)。古い番号は最後に回す
    todo.sort(key=lambda p: -int(p[1:7]))
    print(f"\n  候補 {len(cand):,}件 / 確かめるのは {len(todo):,}件 "
          f"(catalog に在る分と 叩き済み {skip:,}件 は飛ばす)")
    if args.limit:
        todo = todo[:args.limit]
    print(f"=== UT を探す ({'APPLY' if args.commit else 'DRY-RUN'}) — "
          f"対象 {len(todo):,}件 / 同時 {args.workers}本 ===", flush=True)

    # ★取りに行くのは並行、**保存は1本**にする (sqlite を複数から書かない)
    with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for i, (pid, d) in enumerate(
                zip(todo, pool.map(_polite(detail), todo, chunksize=1)), 1):
            probed.add(pid)
            if d is None:
                stat["UT ではない / 消えている"] += 1
            else:
                keep(pid, d)
            if i % 200 == 0:                # ★途中保存
                st["probed"] = list(probed)
                save_state(st)
                print(f"    {i:,}/{len(todo):,} 済み / "
                      f"見つけた {stat['見つけた']:,}件", flush=True)
    st["probed"] = list(probed)
    save_state(st)

    # ---- 2) 隣の番号を歩く (見つけた分も起点にする)
    if args.neighbors:
        from_neighbors(known, known, st, keep)

    db.close()
    print("")
    for k, v in stat.most_common():
        print(f"  {k:28s} {v:,}")
    print("")
    print(f"{'適用' if args.commit else '(dry-run — --commit で適用)'} {len(saved)}件")
    if saved:
        print("  ★このあと sizechart を回すと 実寸表まで入る "
              "(tools/uniqlo_monthly.py)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--search", action="store_true", help="コラボ名で検索して拾う")
    ap.add_argument("--neighbors", action="store_true", help="既知の品番の前後を歩く")
    ap.add_argument("--wayback", action="store_true", help="Wayback の商品URLから拾う")
    ap.add_argument("--pids-file", help="外部から貰った品番リスト (CSV/1行1品番)。"
                    "uniqlo.com の行だけ拾う")
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--limit", type=int, help="確かめる品番の数を絞る (動作確認用)")
    ap.add_argument("--kw-limit", type=int, help="投げる検索語の数を絞る (動作確認用)")
    ap.add_argument("--workers", type=int, default=5,
                    help="公式 API を同時に叩く本数 (既定5。保存は1本のまま)")
    a = ap.parse_args()
    if not (a.search or a.neighbors or a.wayback or a.pids_file):
        # ★既定は Wayback + 隣の番号。検索は弾かれるので明示した時だけ
        a.wayback = a.neighbors = True
    run(a)


if __name__ == "__main__":
    main()
