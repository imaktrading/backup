# -*- coding: utf-8 -*-
"""ユーザーが手で集めた UT の画像を、catalog の画像と突き合わせる (2026-09-12).

## なぜ要るか

ユーザーは `OneDrive/デスクトップ/ebay/出品関係/UNIQLO UT/` に、年月＋コラボ名のフォルダで
UT の画像を貯めている (35フォルダ・約540枚)。ユーザー指摘「これの画像は使った？画像から検索とか」。
= **catalog に無い柄を、画像から洗い出す。**

## やり方

1. catalog (uniqlo_ut / gu) の画像を **縮小版で倉庫へ** (`_raw/uniqlo_ut/thumb/`)。
   済みは飛ばす (次回から取り直さない)
2. 知覚ハッシュ (pHash) で突き合わせる。同じ写真 (Fashion Press の平置き = 公式の写真) なら当たる。
   写真の中の商品部分だけのこともあるので、画像の中央を切り抜いた版でも比べる
3. 画像ごとに一番近い catalog の品番と距離を出す。**距離が閾値を超えたら「catalog に無い柄の候補」**

出力: `C:/dev/iMak_data/catalog/user_ut_image_match.json` と HTML (並べて目で確かめる用)
★DB は触らない。候補を出すだけ。

実行:
    python tools/match_user_ut_images.py
"""
from __future__ import annotations

import concurrent.futures as cf
import html
import json
import sqlite3
import sys
import urllib.request
from pathlib import Path

from PIL import Image
import imagehash

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

USER_DIR = Path("C:/Users/imax2/OneDrive/デスクトップ/ebay/出品関係/UNIQLO UT")
THUMB = Path("C:/dev/iMak_data/catalog/_raw/uniqlo_ut/thumb")
OUT = Path("C:/dev/iMak_data/catalog/user_ut_image_match.json")
OUT_HTML = Path("C:/dev/iMak_data/catalog/user_ut_image_match.html")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/140.0 Safari/537.36"}
EXT = {".jpg", ".jpeg", ".png", ".webp", ".avif"}
NEAR = 10          # pHash の距離。これ以下なら同じ写真とみなす (64bit 中)


def thumb_url(u: str) -> str:
    return u.split("?")[0] + "?width=320"


def thumb_path(pid: str, i: int) -> Path:
    return THUMB / f"{pid}_{i}.jpg"


def fetch_thumb(job: tuple[str, int, str]) -> str:
    pid, i, url = job
    p = thumb_path(pid, i)
    if p.exists() and p.stat().st_size > 0:
        return "skip"
    try:
        with urllib.request.urlopen(urllib.request.Request(thumb_url(url), headers=UA), timeout=30) as r:
            data = r.read()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)                    # ★1枚ずつ保存
        return "ok"
    except Exception:
        return "err"


def hashes(path: Path) -> list[imagehash.ImageHash]:
    """全体と、中央を切り抜いた版の pHash."""
    try:
        im = Image.open(path).convert("RGB")
    except Exception:
        return []
    w, h = im.size
    crops = [im, im.crop((w * 0.15, h * 0.15, w * 0.85, h * 0.85))]
    return [imagehash.phash(c) for c in crops]


def main() -> None:
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    jobs, names = [], {}
    for pid, name, specs in db.execute(
            "SELECT product_id, name, specs FROM products WHERE category IN ('uniqlo_ut','gu')"):
        s = json.loads(specs or "{}")
        if s.get("not_tee"):
            continue
        names[pid] = name
        for i, u in enumerate(s.get("image_urls") or []):
            jobs.append((pid, i, u))
    db.close()
    print(f"=== catalog の画像を倉庫へ — {len(jobs):,}枚 ===", flush=True)
    stat: dict[str, int] = {}
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        for k, r in enumerate(ex.map(fetch_thumb, jobs), 1):
            stat[r] = stat.get(r, 0) + 1
            if k % 2000 == 0:
                print(f"    {k:,}/{len(jobs):,} {stat}", flush=True)
    print(f"    {stat}", flush=True)

    print("=== ハッシュ ===", flush=True)
    cat: list[tuple[str, int, imagehash.ImageHash]] = []
    for pid, i, _ in jobs:
        p = thumb_path(pid, i)
        if p.exists():
            for h in hashes(p):
                cat.append((pid, i, h))
    users = [f for f in USER_DIR.rglob("*") if f.suffix.lower() in EXT]
    print(f"    catalog {len(cat):,} / 手元の画像 {len(users):,}", flush=True)

    out = []
    for f in users:
        hs = hashes(f)
        if not hs:
            out.append({"file": str(f), "folder": f.parent.name, "error": "読めない"})
            continue
        best = min(((min(h - c for h in hs), pid, i) for pid, i, c in cat), default=(99, "", 0))
        out.append({"file": str(f), "folder": f.parent.name, "dist": int(best[0]),
                    "pid": best[1], "name": names.get(best[1], ""), "img": int(best[2]),
                    "match": bool(int(best[0]) <= NEAR)})   # numpy の値は JSON にできない
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    hit = sum(1 for x in out if x.get("match"))
    print(f"\n  手元の画像 {len(out)}枚 / catalog に同じ写真あり {hit}枚 / 無い {len(out) - hit}枚")

    # 並べて見る HTML (合わなかったものが上)
    e = html.escape
    rows = []
    for x in sorted(out, key=lambda x: (x.get("match", False), x["folder"])):
        ci = thumb_path(x.get("pid", ""), x.get("img", 0))
        right = (f'<img src="{ci.as_uri()}"><br>{e(x["pid"])} {e(x.get("name", ""))} (距離 {x.get("dist")})'
                 if x.get("pid") and ci.exists() else "")
        rows.append(f'<tr class="{"ok" if x.get("match") else "ng"}"><td>{e(x["folder"])}</td>'
                    f'<td><img src="{Path(x["file"]).as_uri()}"></td><td>{right}</td></tr>')
    OUT_HTML.write_text(
        "<!doctype html><meta charset=utf-8><title>手元の UT 画像 と catalog</title>"
        "<style>body{font:13px system-ui;margin:0 16px}img{max-width:180px;max-height:220px}"
        "td{border-bottom:1px solid #ddd;padding:4px;vertical-align:top}.ng{background:#fff3f3}"
        ".ok{background:#f3fff5}</style>"
        f"<h2>手元の UT 画像 {len(out)}枚 — catalog に同じ写真あり {hit} / 無い {len(out) - hit}</h2>"
        "<p>赤 = catalog に同じ写真が見つからない (無い柄の候補。着用写真だと合わないこともある)</p>"
        "<table><tr><th>フォルダ</th><th>手元の画像</th><th>catalog で一番近い</th></tr>"
        + "".join(rows) + "</table>", encoding="utf-8")
    print(f"  {OUT_HTML}")


if __name__ == "__main__":
    main()
