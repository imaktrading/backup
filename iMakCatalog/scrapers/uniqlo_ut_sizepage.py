#!/usr/bin/env python3
"""公式から消えた UT の実寸表を、公式の「サイズページ」から取る — 2026-09-14

依頼: requests/2026-09-13_ut_size_chart_for_gone_products.md (出品くん)

## なぜ
`uniqlo_ut_sizechart.py` は商品ページのモーダルを開いて取る (Selenium)。
**商品ページが 404 になると開けない** ので、消えた商品の実寸は取れないと思っていた。

ところが details の `sizeChartUrl` は **商品と別の静的ページ**:

    https://www.uniqlo.com/jp/ja/size/<品番6桁>_size.html

実測 (2026-09-14):
    - 商品が 404 でも、このページは生きていることがある (E463102 / E463101 は 200、表あり)
    - 403 のページは何度叩いても 403 (一時的な拒否ではない)
    - Wayback にこのページが 4,987本 (うち 200 が 2,522本) 保存されている

## 取り方 (上から当たったもの。どれも公式のページ)
    1. 今の公式サイズページ
    2. Wayback に保存されたサイズページ (200 の一番新しい保存)
    どちらにも表が無ければ空欄のまま。推測で埋めない。

## 値
    - ページは **cm だけ** (仕上がり寸)。**公式の cm をそのまま** `size_chart` に入れる
    - ★`size_chart_inch` には入れない (窓口 2026-09-14「inch に換算して保存しない」)。
      出品は「公式が表示した inch」だけを写す。cm しか無い物を出品に使うかは出品側が決める
    - 参考: `cm / 2.54` を 1/4 インチに四捨五入すると、公式モーダルの inch と
      2,580組すべて一致した (2026-09-14)。換算が要ると決まった時は `to_inch()` を使う
    - 列の並び・数は見出しから学ぶ (`uniqlo_ut_sizechart._COL`)
    - 同じサイズに違う値が2つ出るページ (男女の表が並ぶ等) は **入れない** (fail-closed)

## 途中保存
    - 取ったページは倉庫 (`_raw/uniqlo_ut/sizepage_<pid>.html.gz`) に残す
    - 1行ごとに commit。再実行は実寸が空の行だけ
    - 両方に無かった品番は `_sizepage_tried.jsonl` に書き、再実行で飛ばす (`--retry` で叩き直す)

実行:
    python scrapers/uniqlo_ut_sizepage.py --limit 20          # dry-run
    python scrapers/uniqlo_ut_sizepage.py --commit
"""
from __future__ import annotations

import argparse
import html as htmllib
import json
import math
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scrapers")]
import api  # noqa: E402
import _raw_store  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CATEGORY = "uniqlo_ut"
PAGE = "https://www.uniqlo.com/jp/ja/size/{n}_size.html"
CDX = ("https://web.archive.org/cdx/search/cdx?url=uniqlo.com/jp/ja/size/{n}_size.html"
       "&output=json&fl=timestamp&filter=statuscode:200")
WB = "https://web.archive.org/web/{ts}id_/https://www.uniqlo.com/jp/ja/size/{n}_size.html"
TRIED = _raw_store.RAW_ROOT / CATEGORY / "_sizepage_tried.jsonl"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36",
      "Accept": "text/html,application/xhtml+xml,*/*;q=0.8", "Accept-Language": "ja-JP,ja;q=0.9"}
KID_GENDERS = {"KIDS", "BABY", "キッズ", "ベビー"}

_COL = {"身丈": "length", "着丈": "length", "肩幅": "shoulder", "身幅": "chest",
        "裄丈": "sleeve", "袖丈": "sleeve"}
_NUM = re.compile(r"\d+(?:\.\d+)?")


def _get(url: str, timeout: int = 40) -> tuple[int, bytes]:
    for attempt in range(3):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout)
            return r.status, r.read()
        except urllib.error.HTTPError as e:
            if e.code in (403, 404, 410):
                return e.code, b""
            time.sleep(3 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(3 * (attempt + 1))
    return 0, b""


def _decode(b: bytes) -> str:
    m = re.search(rb'charset=["\']?([\w\-]+)', b[:3000])
    enc = (m.group(1).decode() if m else "utf-8").lower()
    for e in (enc, "utf-8", "cp932"):
        try:
            return b.decode(e)
        except (LookupError, UnicodeDecodeError):
            continue
    return b.decode("utf-8", "replace")


def _cells(tr: str) -> list[tuple[str, int]]:
    out = []
    for m in re.finditer(r"<t([hd])([^>]*)>(.*?)</t[hd]>", tr, re.S | re.I):
        span = re.search(r'colspan\s*=\s*"?(\d+)', m.group(2), re.I)
        text = htmllib.unescape(re.sub(r"<[^>]+>", "", m.group(3))).strip()
        out.append((text, int(span.group(1)) if span else 1))
    return out


def parse_size_page(h: str) -> list[dict] | None:
    """サイズページの表 (複数に分かれている) -> [{size, length, chest, ...}] (cm の文字列)."""
    table: dict[str, dict] = {}
    order: list[str] = []
    for t in re.findall(r"<table[^>]*>(.*?)</table>", h, re.S | re.I):
        trs = re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S | re.I)
        if not trs:
            continue
        head = _cells(trs[0])
        if not head or head[0][0] != "サイズ":
            continue
        sizes = [c for c, _ in head[1:]]
        for tr in trs[1:]:
            cells = _cells(tr)
            if not cells or cells[0][0] not in _COL:
                continue
            col = _COL[cells[0][0]]
            vals: list[str] = []
            for text, span in cells[1:]:
                vals.extend([text] * span)
            if len(vals) != len(sizes):
                return None                            # 列が揃わない表は入れない
            for size, v in zip(sizes, vals):
                if not _NUM.fullmatch(v):
                    continue
                row = table.setdefault(size, {"size": size})
                if size not in order:
                    order.append(size)
                if col in row and row[col] != v:
                    return None                        # 同じサイズに違う値 = 決められない
                row[col] = v
    rows = [table[s] for s in order if len(table[s]) >= 3]
    return rows or None


def to_inch(cm: str) -> str:
    """cm -> 公式の inch 表記 (1/4 に四捨五入。`27 1/4`)。公式モーダルと 2,580/2,580 一致."""
    q = Fraction(cm) / Fraction("2.54") * 4
    n = Fraction(math.floor(q + Fraction(1, 2)), 4)
    w, r = int(n), n - int(n)
    if not r:
        return str(w)
    return f"{w} {r.numerator}/{r.denominator}" if w else f"{r.numerator}/{r.denominator}"


INDEX = _raw_store.RAW_ROOT / CATEGORY / "_sizepage_wayback_index.json"
_INDEX_CACHE: list = []


def _wayback_index() -> dict | None:
    """Wayback のサイズページ保存一覧 {品番6桁: [timestamp 新しい順]}。無ければ None (品番ごとに CDX).

    作り方 (2026-09-14 に 3,454保存 / 2,452ページ):
        cdx?url=uniqlo.com/jp/ja/size/*&fl=original,timestamp&filter=statuscode:200
    """
    if not _INDEX_CACHE:
        _INDEX_CACHE.append(json.loads(INDEX.read_text(encoding="utf-8"))["pages"]
                            if INDEX.exists() else None)
    return _INDEX_CACHE[0]


def fetch(pid: str) -> tuple[list[dict] | None, str, str]:
    """(表, 出所, URL)。"""
    n = pid[1:7]
    st, b = _get(PAGE.format(n=n))
    if st == 200 and b:
        h = _decode(b)
        rows = parse_size_page(h)
        if rows:
            _raw_store.save(CATEGORY, f"sizepage_{pid}", h, PAGE.format(n=n))
            return rows, "official_size_page", PAGE.format(n=n)
    idx = _wayback_index()
    if idx is not None:
        # ★保存一覧をまとめて取った索引を先に使う (2026-09-14)。品番ごとに CDX を
        #   問い合わせると 1件30秒かかり、615件で5時間になった。索引に無い = 保存が無い
        stamps = idx.get(n, [])
    else:
        st, b = _get(CDX.format(n=n), timeout=90)
        try:
            stamps = [x[0] for x in json.loads(b or b"[]")[1:]]
        except ValueError:
            stamps = []
    for ts in sorted(set(stamps), reverse=True)[:3]:           # 新しい保存から
        st, b = _get(WB.format(ts=ts, n=n), timeout=90)
        if st != 200 or not b:
            continue
        h = _decode(b)
        rows = parse_size_page(h)
        if rows:
            _raw_store.save(CATEGORY, f"sizepage_{pid}", h, WB.format(ts=ts, n=n))
            return rows, f"official_size_page_wayback_{ts}", WB.format(ts=ts, n=n)
        time.sleep(1)
    return None, "", ""


def tried() -> set[str]:
    if not TRIED.exists():
        return set()
    return {json.loads(x)["pid"] for x in TRIED.read_text(encoding="utf-8").splitlines() if x.strip()}


def targets(db, retry: bool) -> list[tuple]:
    done = set() if retry else tried()
    out, skip = [], Counter()
    for rid, pid, sp in db.execute("SELECT id, product_id, specs FROM products "
                                   "WHERE category=? AND product_id LIKE 'E%'", (CATEGORY,)):
        s = json.loads(sp or "{}")
        if s.get("data_level") == "fp_design" or s.get("not_tee"):
            continue
        if str(s.get("gender") or "").upper() in KID_GENDERS:
            continue
        if s.get("size_chart_inch") or s.get("size_chart"):
            skip["実寸あり"] += 1
            continue
        if pid in done:
            skip["前回 どこにも無かった"] += 1
            continue
        out.append((rid, pid))
    print(f"  対象 {len(out)}行 / 飛ばす {dict(skip)}", flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--retry", action="store_true", help="前回どこにも無かった品番も叩き直す")
    args = ap.parse_args()

    db = sqlite3.connect(api._DB_PATH, timeout=120)
    rows = targets(db, args.retry)
    if args.limit:
        rows = rows[:args.limit]
    stat = Counter()
    for i, (rid, pid) in enumerate(rows, 1):
        try:
            cm, how, url = fetch(pid)
        except Exception as e:                      # 1件の失敗で走行を落とさない
            stat[type(e).__name__] += 1
            continue
        if not cm:
            stat["どこにも無い"] += 1
            if args.commit:
                with TRIED.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"pid": pid, "at": datetime.now().isoformat(timespec="seconds")}) + "\n")
        else:
            stat["取れた: " + ("wayback" if "wayback" in how else "公式")] += 1
            if args.commit:
                now = datetime.now().isoformat(timespec="seconds")
                s = json.loads(db.execute("SELECT specs FROM products WHERE id=?", (rid,)).fetchone()[0] or "{}")
                if not (s.get("size_chart_inch") or s.get("size_chart")):   # 走行中に別経路で入った分は触らない
                    s.update({"size_chart": cm, "size_chart_unit": "cm",
                              "size_chart_at": now, "size_chart_source": how,
                              "size_chart_page_url": url})
                    db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                               (json.dumps(s, ensure_ascii=False), now, rid))
                    db.commit()                              # ★1行ごとに保存
        if i % 25 == 0:
            print(f"  {i}/{len(rows)} {dict(stat)}", flush=True)
        time.sleep(1.0)
    print("結果:", dict(stat), "commit" if args.commit else "dry-run", flush=True)


if __name__ == "__main__":
    main()
