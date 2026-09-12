# -*- coding: utf-8 -*-
"""Google フォトの共有アルバムの写真を倉庫に保存する (2026-09-13 新設・ユーザー提供).

ユーザーが手で集めた UT の写真がアルバムにある。**画像が肝** (公式から消えると二度と取れない)
なので、出所を問わず倉庫に残す。

## 取り方 (2026-09-13 実測)

    https://photos.app.goo.gl/xxxx  → 302 → https://photos.google.com/share/AF1Qip...?key=...
    そのページの JS に写真IDが `/pw/AP1Gcz...` の形で入っている
    画像は https://lh3.googleusercontent.com/pw/<ID>=w2400 で取れる (=d でも可)

★`photos.google.com/album/...` (共有リンクでない方) は**ログインが要る**ので取れない。
  共有リンク (`photos.app.goo.gl` / `/share/...?key=`) をもらうこと。

## 保存 / 重複

    _raw/gphotos/<アルバム名>/<写真ID の末尾>.jpg
  倉庫に既に在る画像 (手元フォルダ・Fashion Press など) と **中身のハッシュで照合**し、
  同じ画像なら保存せず「どこに在るか」だけ記録する (ユーザー「同じ画像があるかもしれない」)。

実行:
    python scrapers/gphotos_album.py <共有URL> [<共有URL> ...]
    python scrapers/gphotos_album.py --list <URLを並べたファイル>
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DATA = Path("C:/dev/iMak_data/catalog")
DST = DATA / "_raw/gphotos"
INDEX = DATA / "gphotos_index.json"
UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"),
      "Accept-Language": "ja-JP"}
PHOTO = re.compile(r"/pw/[A-Za-z0-9_\-]{60,}")
EXT = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"}


def known_hashes() -> dict[str, str]:
    """倉庫に既に在る画像の中身ハッシュ (重複を二重に保存しないため)."""
    out = {}
    for f in (DATA / "_raw").rglob("*"):
        if f.is_file() and f.suffix.lower() in EXT:
            try:
                out[hashlib.sha1(f.read_bytes()).hexdigest()] = str(f)
            except Exception:
                pass
    return out


def album_photos(url: str) -> tuple[str, str, list[str]]:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        h = r.read().decode("utf-8", "ignore")
        final = r.geturl()
    title = (re.findall(r"<title>(.*?)</title>", h) or [""])[0].replace(" - Google フォト", "").strip()
    return final, title, sorted(set(PHOTO.findall(h)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="*")
    ap.add_argument("--list", help="URL を並べたファイル")
    a = ap.parse_args()
    urls = list(a.urls)
    if a.list:
        urls += [x.strip() for x in Path(a.list).read_text(encoding="utf-8").splitlines() if x.strip()]
    print("倉庫の画像を数えています (重複の照合用)...", flush=True)
    seen = known_hashes()
    print(f"  倉庫 {len(seen):,}枚", flush=True)
    idx = json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.exists() else {}

    for url in urls:
        final, title, ids = album_photos(url)
        key = re.sub(r"[^A-Za-z0-9]", "", (re.findall(r"/share/([^/?]+)", final) or [url])[0])[:24]
        name = (title or key)[:40]
        print(f"\n=== {name} — 写真 {len(ids)}枚 ({url}) ===", flush=True)
        got = dup = err = 0

        def one(pid: str) -> str:
            p = DST / key / (pid[-24:] + ".jpg")
            if p.exists():
                return "skip"
            for i in range(3):
                try:
                    with urllib.request.urlopen(urllib.request.Request(
                            "https://lh3.googleusercontent.com" + pid + "=w2400",
                            headers=UA), timeout=60) as r:
                        b = r.read()
                    hsh = hashlib.sha1(b).hexdigest()
                    if hsh in seen:              # 既に倉庫に在る画像 (手元フォルダ等)
                        return "dup:" + seen[hsh]
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(b)             # ★1枚ずつ保存
                    seen[hsh] = str(p)
                    time.sleep(0.3)
                    return "ok"
                except Exception:
                    time.sleep(3 * (i + 1))
            return "err"

        with cf.ThreadPoolExecutor(max_workers=4) as ex:
            for r in ex.map(one, ids):
                if r == "ok":
                    got += 1
                elif r.startswith("dup"):
                    dup += 1
                elif r == "err":
                    err += 1
        print(f"  保存 {got} / 倉庫に同じ画像が在った {dup} / 取れない {err}")
        idx[key] = {"url": url, "share": final, "title": title, "photos": len(ids),
                    "saved": got, "duplicate": dup, "error": err}
        INDEX.write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n  {INDEX}")


if __name__ == "__main__":
    main()
