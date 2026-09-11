# -*- coding: utf-8 -*-
"""Fashion Press の UT 記事ごとに「記事の柄数」と「catalog の件数」を突き合わせる (2026-09-11).

## なぜ要るか

ユーザー指示「Google で検索して公式データが取れるものの取りこぼしをなくして。
例外は、ファッションプレスで画像データを拡充させよう」。
何が取りこぼしかを **数で** 出す。記事の【詳細】欄には柄数が書いてある
(例「メンズ Tシャツ 4柄 1,990円」)。catalog の件数がそれに届かないコラボが
Google で深掘りする対象、0件のコラボが Fashion Press の写真で補う例外。

## 突き合わせ方

- 記事側の名前: タイトルと【詳細】1行目の「」『』の中身 (UT / ユニクロ は外す)
- catalog 側: 大人の UT (not_tee でない) の商品名 / コラボ名に、その名前が含まれるか
  (空白・中黒・記号をそろえてから比べる)
- 柄数: 【詳細】の「メンズ/ウィメンズ/男女兼用 … N柄 / 全N種 / N型」を足す (キッズは除く)
  ★柄数の書いていない記事は「不明」。推測で埋めない

出力: `fashion_press/ut_gap.json` (記事ID → 名前 / 記事の柄数 / catalog 件数 / 品番)

実行:
    python tools/fp_ut_gap.py
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
import api  # noqa: E402
sys.path.insert(0, str(_ROOT / "scrapers"))
import fashion_press_uniqlo as F  # noqa: E402  (UT の記事かの判定は1か所)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SRC = Path("C:/dev/iMak_data/catalog/fashion_press/uniqlo_articles.json")
OUT = Path("C:/dev/iMak_data/catalog/fashion_press/ut_gap.json")
GOOGLE = Path("C:/dev/iMak_data/catalog/google_ut_search.tsv")
KID = {"KIDS", "BABY"}
DROP = {"UT", "ユニクロ", "ユニクロUT", "UTコレクション", "UNIQLO"}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"\(.*?\)|（.*?）", "", s)
    return re.sub(r"[\s・･×x&＆!！?？:：/／「」『』\-—–~〜\"'“”’.,、。]+", "", s)


def names_of(a: dict) -> list[str]:
    first = (a.get("detail_text") or "").split("\n")[0]
    out = []
    for t in re.findall(r"[「『]([^」』]{2,40})[」』]", (a.get("title") or "") + " " + first):
        t = re.sub(r"\s*UT\s*$|UTコレクション$|コレクション$", "", t).strip()
        if t and t not in DROP and len(norm(t)) >= 2:
            out.append(t)
    return list(dict.fromkeys(out))


def pattern_count(a: dict) -> int | None:
    txt = a.get("detail_text") or ""
    total, hit = 0, False
    for ln in txt.split("\n"):
        if "キッズ" in ln or "ベビー" in ln:
            continue
        if not re.search(r"Tシャツ|スウェット|UT", ln):
            continue
        m = re.search(r"(\d+)\s*(?:柄|種|型|デザイン)", ln)
        if m:
            total += int(m.group(1))
            hit = True
    return total if hit else None


def main() -> None:
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    rows = []
    for pid, name, specs in db.execute(
            "SELECT product_id, name, specs FROM products WHERE category='uniqlo_ut'"):
        s = json.loads(specs or "{}")
        if str(s.get("gender") or "").upper() in KID or s.get("not_tee"):
            continue
        rows.append((pid, norm(name) + "|" + norm(s.get("collab") or "")))
    in_cat = {p for p, _ in rows}
    # Google で「ユニクロ UT <名前>」を引いた結果 (名前 → 品番)。名前の表記ゆれ
    # (ディズニー×フォーミュラ1 / Disney x Formula 1) を品番でつなぐ
    by_kw: dict[str, set[str]] = {}
    if GOOGLE.exists():
        for ln in GOOGLE.read_text(encoding="utf-8").splitlines():
            k, _, p = ln.partition("\t")
            if p in in_cat:
                by_kw.setdefault(norm(k), set()).add(p)
    arts = json.loads(SRC.read_text(encoding="utf-8"))["articles"]
    out = {}
    zero = short = ok = unknown = 0
    for a in arts.values():
        if not F.is_ut_article(a.get("title") or "", a.get("detail_text") or ""):
            continue
        names = names_of(a)
        keys = [norm(n) for n in names]
        pids = {p for p, hay in rows for k in keys if k and k in hay}
        for k in keys:
            pids |= by_kw.get(k, set())
        pids = sorted(pids)
        want = pattern_count(a)
        out[a["id"]] = {"title": a.get("title"), "published": (a.get("published") or "")[:10],
                        "names": names, "article_patterns": want,
                        "catalog_count": len(pids), "catalog_pids": pids}
        if not pids:
            zero += 1
        elif want is None:
            unknown += 1
        elif len(pids) < want:
            short += 1
        else:
            ok += 1
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  UT の記事 {len(out)}件")
    print(f"    catalog 0件 (例外。Fashion Press の写真で補う)   {zero}")
    print(f"    記事の柄数に届かない (Google で深掘り)          {short}")
    print(f"    柄数が書いていない (catalog には在る)            {unknown}")
    print(f"    記事の柄数以上ある                               {ok}")
    print(f"  {OUT}")


if __name__ == "__main__":
    main()
