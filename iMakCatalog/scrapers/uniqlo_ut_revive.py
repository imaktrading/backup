# -*- coding: utf-8 -*-
"""倉庫に写っている **廃盤の UT 商品** を catalog に起こす (2026-09-10 新設).

## なぜ要るか

コラボ特設ページ (現行 + Wayback) を保管したら、そこに **catalog に無い商品番号**が
大量に写っていた。2026-09-10 実測: 保管60本を見ただけで 商品番号124件のうち **93件が未収録**。
廃盤で公式 API から消えた商品が、当時のページには載っている。

## どこから取るか

    1. 公式 API がまだ生きていれば **それが最優先** (現行と同じ値が全部取れる)
    2. 死んでいれば **Wayback の商品ページ** に当時の JSON が埋まっている
         composition / designDetail / longDescription / name … 現行と同じ形
    3. 画像は **品番から総当たり**。CDN は生きている
         (2026-09-10 実測: 2021年の E420005 も、廃盤の E456407 も 200 が返る)

## 取れないもの (廃盤では諦める)

    原産国    商品ページに項目が無い (現行 API だけが持つ)
    実寸表    サイズ表ページは Wayback に在るが **中身が空** (JS で描く作りで器だけ)

= だから現役のうちに取るのが本筋 (`tools/uniqlo_monthly.py`)。ここは取りこぼしの救済。

## 途中保存 (CLAUDE.md「長く走るものは必ず途中保存」)

  - 1商品ごとに保存 / 再実行は DB を見て済みを飛ばす (飛ばした件数を出す)
  - 取った生データは `_raw/uniqlo_ut/` に置く (`revive_<pid>`)

実行:
    python scrapers/uniqlo_ut_revive.py --limit 5
    python scrapers/uniqlo_ut_revive.py --commit
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import gzip
import json
import os
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
import uniqlo_ut_enrich as E  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CATEGORY = "uniqlo_ut"
RAW = Path("C:/dev/iMak_data/catalog/_raw/uniqlo_ut")
PDP = "https://www.uniqlo.com/jp/ja/products/{pid}/00"
CDX = ("http://web.archive.org/cdx/search/cdx?url=uniqlo.com/jp/ja/products/{pid}*"
       "&output=json&fl=original,timestamp&filter=statuscode:200&collapse=urlkey&limit=3")
SNAP = "https://web.archive.org/web/{ts}id_/{url}"
UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")}
SLEEP = 1.5
_PID = re.compile(r"E\d{6}-\d{3}")
# 商品名に UT / グラフィックT が入るものだけ入れる (関連商品を弾く)
_IS_UT = re.compile(r"UT|UT[/（(・]|グラフィックT")
# 画像の置き場は2通り (日本向け / アジア共通) x 2通りの綴り
_IMG_BASES = ("https://image.uniqlo.com/UQ/ST3/jp/imagesgoods/{l1}/",
              "https://image.uniqlo.com/UQ/ST3/AsianCommon/imagesgoods/{l1}/")
_IMG_PRE = ("jpgoods", "goods")
COLORS = ("00", "01", "02", "03", "04", "05", "06", "08", "09", "10", "11", "12",
          "13", "14", "15", "16", "18", "19", "20", "21", "22", "24", "26", "27",
          "30", "31", "32", "34", "35", "36", "37", "38", "39", "50", "51", "52",
          "53", "54", "56", "57", "58", "59", "60", "61", "62", "63", "64", "65",
          "66", "67", "68", "69", "70", "71", "72")


def _get(url: str, timeout: int = 60, tries: int = 3) -> str:
    """★Wayback は時々 詰まる/切れる (2026-09-11 実測: 同じ品番が1回目は取れず2回目は取れた)。
    404 以外は間を空けて粘る."""
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                        timeout=timeout) as r:
                return r.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            if e.code == 404 or i == tries - 1:
                raise
        except Exception:
            if i == tries - 1:
                raise
        time.sleep(8 * (i + 1))
    raise RuntimeError("unreachable")


def _head_ok(url: str) -> bool:
    try:
        r = urllib.request.urlopen(
            urllib.request.Request(url, headers=UA, method="HEAD"), timeout=15)
        return r.status == 200
    except Exception:
        return False


def unknown_pids(db) -> list[str]:
    """倉庫のページに写っていて、catalog に無い商品番号."""
    have = {x[0] for x in db.execute(
        "SELECT product_id FROM products WHERE category IN ('uniqlo_ut','gu')")}
    seen: set[str] = set()
    for f in os.listdir(RAW):
        if not f.startswith(("wb_", "spl_", "cat_", "collab_")):
            continue
        try:
            with gzip.open(RAW / f, "rb") as fh:
                seen |= set(_PID.findall(fh.read().decode("utf-8", "ignore")))
        except Exception:
            continue
    return sorted(seen - have)


def images_of(pid: str) -> list[str]:
    """品番から画像URLを総当たりで見つける (CDN は生きている)."""
    l1 = pid[1:7]
    out: list[str] = []
    for col in COLORS:                       # メイン (色ごと)
        for base in _IMG_BASES:
            for pre in _IMG_PRE:
                u = base.format(l1=l1) + f"item/{pre}_{col}_{l1}_3x4.jpg"
                if _head_ok(u):
                    out.append(u + E.BIG)
                    break
            else:
                continue
            break
    miss = 0
    for n in range(1, 30):                   # サブ (連番。飛ぶことがあるので少し粘る)
        found = False
        for base in _IMG_BASES:
            for pre in _IMG_PRE:
                u = base.format(l1=l1) + f"sub/{pre}_{l1}_sub{n}_3x4.jpg"
                if _head_ok(u):
                    out.append(u + E.BIG)
                    found = True
                    break
            if found:
                break
        miss = 0 if found else miss + 1
        if miss >= 8:
            break
    return out


def _pdp_product(h: str, pid: str) -> dict | None:
    """Wayback の商品ページに埋まっている product JSON を取り出す."""
    i = h.find('"pdpEntity"')
    if i < 0:
        return None
    j = h.find('"product":', i)
    if j < 0 or j - i > 400:
        return None
    try:
        p, _ = json.JSONDecoder().raw_decode(h[j + len('"product":'):])
    except Exception:
        return None
    return p if isinstance(p, dict) else None


def is_ut(d: dict) -> bool:
    """UT か。パンくずが在れば **公式の分類** (category=ut graphic tees かつ class=tops)。
    無ければ名前で見る (古い取り方で取った値)."""
    bc = d.get("breadcrumbs") or {}
    if bc:
        return ((bc.get("category") or {}).get("name") == "ut graphic tees"
                and (bc.get("class") or {}).get("name") == "tops")
    return bool(_IS_UT.search(d.get("name") or ""))


def from_wayback(pid: str) -> tuple[dict | None, str]:
    """Wayback の商品ページから 当時の値を取る."""
    try:
        rows = json.loads(_get(CDX.format(pid=pid)))[1:]
    except Exception:
        return None, ""
    for original, ts in [(r[0], r[1]) for r in rows]:
        try:
            h = _get(SNAP.format(ts=ts, url=original), timeout=90)
        except Exception:
            continue
        # ★ページには公式 detail と同じ形の JSON が丸ごと埋まっている
        #   (`"pdpEntity":{"E472114-000-00":{..."product":{...}}}`)。これを読むのが正。
        #   以前は `"name":"..."` を正規表現で拾っていて、**最初に出てくる空の name** を
        #   掴んでいた (2026-09-11 実測: 怪獣8号 UT 4件を「UT ではない」と捨てた)
        p = _pdp_product(h, pid)
        if p and (p.get("composition") or p.get("longDescription") or p.get("name")):
            p["_snapshot"] = ts
            return p, h
        d: dict = {}
        for key in ("name", "composition", "designDetail",
                    "longDescription", "shortDescription", "careInstruction"):
            m = re.search(rf'"{key}":"((?:[^"\\]|\\.)*)"', h)
            if m:
                try:
                    d[key] = json.loads('"' + m.group(1) + '"')
                except Exception:
                    d[key] = m.group(1)
        if d.get("composition") or d.get("longDescription"):
            d["_snapshot"] = ts
            return d, h
    return None, ""


def _fetch_one(pid: str) -> tuple[str, dict | None, str, str, list[str], str]:
    """1品番を 公式 → Wayback の順で取る (並行で呼ぶ。DB には触らない)."""
    src, d, raw, err = "", None, "", ""
    try:                                      # 1. 公式がまだ生きていないか
        live = E.fetch(pid)
        if live:
            d, src = live, "official"
    except urllib.error.HTTPError:
        pass
    except Exception as e:
        err = type(e).__name__
    if d is None:                             # 2. Wayback
        d, raw = from_wayback(pid)
        if d:
            src = f"wayback_{d.get('_snapshot', '')}"
    imgs: list[str] = []
    if d is not None and is_ut(d):
        # ★Wayback のページの JSON にも公式と同じ images が在る。在ればそれを使う
        #   (総当たりの images_of は 1枚しか当たらないことがある)
        imgs = E.all_images(d.get("images") or {}) if d.get("images") else images_of(pid)
    time.sleep(SLEEP)
    return pid, d, src, raw, imgs, err


def run(commit: bool, limit: int | None, pids_file: str | None = None,
        workers: int = 4) -> None:
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    db.row_factory = sqlite3.Row
    have = {x[0] for x in db.execute(
        "SELECT product_id FROM products WHERE category IN ('uniqlo_ut','gu')")}
    if pids_file:
        # ★渡されたリスト **だけ** を救済する (2026-09-11)。以前は倉庫の未収録分も
        #   全部混ぜていて、4件を確かめるつもりが 10分以上回り続けた。
        import uniqlo_ut_discover as D
        listed = D.pids_from_file(pids_file)
        pids = sorted(listed - have)
        print(f"  リストの品番 {len(listed)}件 / catalog に在る {len(listed) - len(pids)}件 は飛ばす")
    else:
        pids = unknown_pids(db)
        print(f"  倉庫に写っていて catalog に無い商品番号: {len(pids)}件")
    if limit:
        pids = pids[:limit]
    print(f"=== 廃盤品の救済 ({'APPLY' if commit else 'DRY-RUN'}) — 対象 {len(pids)}件 "
          f"/ 同時 {workers}本 ===", flush=True)

    now = datetime.now().isoformat(timespec="seconds")
    stat, n = Counter(), 0
    # ★取りに行くのは並行、**保存は1本** (sqlite を複数から書かない)
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        results = pool.map(_fetch_one, pids)
        for pid, d, src, raw, imgs, err in results:
            _save_one(db, pid, d, src, raw, imgs, err, now, commit, stat)
            n += stat.pop("_saved", 0)
    db.close()
    print("")
    for k, v in stat.most_common():
        print(f"  {k:24s} {v}")
    print("")
    print(f"{'適用' if commit else '(dry-run — --commit で適用)'} {n}件")


def _save_one(db, pid, d, src, raw, imgs, err, now, commit, stat) -> None:
    if err:
        stat[err] += 1
    if d is None:
        stat["値が取れない"] += 1
        return
    if raw:
        _raw_store.save(CATEGORY, f"revive_{pid}", raw, PDP.format(pid=pid), ext="html")
    # ★UT 以外は入れない (2026-09-10)。コラボページの HTML には関連商品が混ざるので、
    #   そのまま入れるとリネンシャツやレギンスまで `uniqlo_ut` に入る。
    if not is_ut(d):
        stat["UT ではない"] += 1
        return
    # ★性別を必ず入れる (2026-09-10)。入れないと キッズが「大人」として扱われ、
    #   実寸表の Selenium が 1件15秒かけて叩きに行く (実際に11件やった)。
    #   detail API の genderName は **小文字** (`kids` / `men`) なので大文字にそろえる。
    gender = (d.get("genderName") or "").strip().upper()
    specs = {
        "gender": gender,
        "department": U._gender_to_dept(gender),
        "composition": d.get("composition") or "",
        "design_detail": d.get("designDetail") or "",
        "long_description": d.get("longDescription") or "",
        "short_description": d.get("shortDescription") or "",
        "care_instruction": d.get("careInstruction") or "",
        "image_urls": imgs,
        "revived_at": now, "revived_from": src,
        "official_gone_at": None if src == "official" else now,
    }
    if src == "official":
        specs["countries_of_origin"] = [x.get("code") for x in
                                        (d.get("countriesOfOrigin") or []) if x.get("code")]
        specs["enriched_at"] = now
    stat[f"取れた ({src.split('_')[0]})"] += 1
    stat["画像あり"] += bool(imgs)
    print(f"    + {pid}  画像 {len(imgs):2d}枚  {src:18s} "
          f"{(d.get('name') or '')[:34]}", flush=True)
    if commit:
        try:                               # ★1件の失敗で走行を落とさない
            api.upsert(category=CATEGORY, product_id=pid,
                       name=d.get("name") or "", name_jp=d.get("name") or "",
                       set_name=None, set_name_official=None, card_set_id=None,
                       language="ja", specs=specs, images=imgs,
                       source=f"uniqlo_revive_{src}", source_url=PDP.format(pid=pid))
            stat["_saved"] += 1
        except Exception as e:
            stat[f"保存できない ({type(e).__name__})"] += 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--pids-file", help="外部から貰った品番リスト (CSV/1行1品番)。"
                    "このリストだけを 公式→Wayback の順で救済する")
    ap.add_argument("--workers", type=int, default=4, help="同時に取りに行く本数")
    a = ap.parse_args()
    run(a.commit, a.limit, a.pids_file, a.workers)


if __name__ == "__main__":
    main()
