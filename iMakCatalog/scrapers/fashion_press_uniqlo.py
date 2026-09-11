# -*- coding: utf-8 -*-
"""Fashion Press の UNIQLO 記事を集める (2026-09-11 新設・ユーザー指示).

## なぜ要るか

公式から取れる UT は、品番が今も公式 API に残っているものだけ。
2021年より前のコラボはほぼ全部が公式から消えていて、**何が出ていたかを知る手段が無い**。
Fashion Press は 2011年頃から UT のコラボを記事にしていて、記事には
コラボ名 / 発売日 / 価格 / サイズ / 柄の数 / 写真 が載っている。

★記事に **UNIQLO の品番は載っていない** (2026-09-11 実測)。
  = catalog の行 (products) にはしない。**公式ではない出所**なので、
  別の置き場 (`fashion_press/uniqlo_articles.json`) に持つ。

## 取り方

    1. 一覧   /news/brand/244?page=N   (244 = ユニクロ。2026-09-11 時点で 24ページ)
    2. 記事   /news/<id>               生の HTML を `_raw/fashion_press/` に保管
    3. 読む   タイトル / 公開日 / 本文 / 【詳細】欄 / 写真URL (大きい形)

- robots.txt は全許可 (2026-09-11 確認)。それでも 1.5秒ずつ空ける
- **済みは飛ばす**: 出力 JSON に在る記事は取り直さない (飛ばした件数を出す)
- **途中保存**: 10記事ごとに JSON を書く。落ちても続きから走る
- 一覧は毎回見る (新しい記事が先頭に増えるため。24ページで40秒ほど)

## UT の記事かどうか

タイトルか【詳細】欄に `UT` がある / タイトルに Tシャツ・スウェット がある。
★UT なのにタイトルに UT が無い記事がある (例 150873「ユニクロ×隈研吾の”花束”Tシャツ」)。
  判定は印 (`is_ut`) だけで、**記事は全部残す** (後から判定を変えても取り直さない)。

実行:
    python scrapers/fashion_press_uniqlo.py --limit 5     # 動作確認 (保存しない)
    python scrapers/fashion_press_uniqlo.py --commit
"""
from __future__ import annotations

import argparse
import html as htmllib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

_CATALOG_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_CATALOG_ROOT / "scrapers"))
import _raw_store  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = "https://www.fashion-press.net"
BRANDS = {"uniqlo": 244}
OUT = Path("C:/dev/iMak_data/catalog/fashion_press/uniqlo_articles.json")
RAW_CAT = "fashion_press"
UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"),
      "Accept-Language": "ja-JP"}
PACE = 1.5
MAX_PAGES = 200


def _get(url: str, tries: int = 3) -> str | None:
    """404 は None。それ以外の失敗は粘って、駄目なら例外."""
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                        timeout=40) as r:
                return r.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if i == tries - 1:
                raise
        except Exception:
            if i == tries - 1:
                raise
        time.sleep(5 * (i + 1))
    return None


# ---------------------------------------------------------------- 一覧
def list_articles(brand_id: int) -> dict[str, str]:
    """ブランドの記事一覧 {記事ID: タイトル}。ページが尽きるまで歩く."""
    found: dict[str, str] = {}
    for page in range(1, MAX_PAGES + 1):
        h = _get(f"{BASE}/news/brand/{brand_id}?page={page}")
        time.sleep(PACE)
        if not h:
            break
        # ★一覧の本体だけを見る (横の「おすすめ」欄に他ブランドの記事が混ざる)
        new = 0
        for nid, title in re.findall(r'href="/news/(\d+)"[^>]*title="([^"]+)"', h):
            if nid not in found:
                found[nid] = htmllib.unescape(title)
                new += 1
        if new == 0:
            break
        print(f"    一覧 {page}ページ / 記事 {len(found)}件", flush=True)
    return found


# ---------------------------------------------------------------- 記事を読む
def _text(h: str) -> str:
    h = re.sub(r"<(script|style|noscript)[\s\S]*?</\1>", "", h)
    h = re.sub(r"<br\s*/?>", "\n", h)
    t = htmllib.unescape(re.sub(r"<[^>]+>", "\n", h))
    return re.sub(r"\n\s*\n+", "\n", t).strip()


def parse_article(nid: str, h: str) -> dict:
    title = htmllib.unescape((re.findall(r"<title>(.*?)</title>", h) or [""])[0])
    title = re.sub(r"\s*-\s*ファッションプレス\s*$", "", title)
    pub = (re.findall(r'"datePublished"\s*:\s*"([^"]+)"', h) or [""])[0]
    brands = sorted(set(re.findall(r'href=["\']/brands/(\d+)["\'][^>]*class="fp_tag', h)))
    # 本文 = <div id="news" ...> の中身 (2026-09-11 実測の形)
    m = re.search(r'<div id="news"[^>]*>([\s\S]*?)<div class="clear"></div>', h)
    body_html = m.group(1) if m else ""
    body = _text(body_html)
    # 本文の写真と説明文 (例「メンズ Tシャツ 1,990円 ※背面」)。何の商品かが分かる唯一の手がかり
    figures = []
    for fig in re.findall(r"<figure>([\s\S]*?)</figure>", body_html):
        src = re.search(r'(?:data-src|src)=[\'"](/img/news/[^\'"]+)[\'"]', fig)
        cap = re.search(r"<figcaption[^>]*>([\s\S]*?)</figcaption>", fig)
        if src:
            figures.append({"url": BASE + src.group(1).replace("/w300_", "/"),
                            "caption": _text(cap.group(1)) if cap else ""})
    detail = ""
    if "【詳細】" in body:
        detail = body[body.find("【詳細】") + len("【詳細】"):]
        cut = min([i for i in (detail.find("©"), detail.find("Photos(")) if i >= 0] or [len(detail)])
        detail = detail[:cut].strip()
    fields: dict[str, str] = {}
    for key in ("発売日", "発売時期", "販売店舗", "取扱店舗", "価格", "アイテム例", "サイズ", "展開"):
        mm = re.search(rf"(?:^|\n){key}\s*[：:]\s*([^\n]*(?:\n(?:・|※)[^\n]+)*)", detail)
        if mm:
            fields[key] = mm.group(1).strip()
    photos = []
    for w300 in re.findall(rf'data-src="(/img/news/{nid}/w300_[^"]+)"', h):
        photos.append(BASE + w300.replace("/w300_", "/"))
    photos = list(dict.fromkeys(photos))
    is_ut = bool(re.search(r"UT", title) or re.search(r"\bUT\b|「UT」|UT」", detail)
                 or re.search(r"Tシャツ|スウェット", title))
    return {
        "id": nid, "url": f"{BASE}/news/{nid}", "title": title, "published": pub,
        "brands": brands, "is_ut": is_ut, "detail_text": detail, "detail": fields,
        "body": body, "figures": figures, "photos": photos,
    }


# ---------------------------------------------------------------- 本体
def load() -> dict:
    if OUT.exists():
        return json.loads(OUT.read_text(encoding="utf-8"))
    return {"articles": {}}


def save(db: dict) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(db, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(OUT)


def run(commit: bool, limit: int | None) -> None:
    db = load()
    have = db["articles"]
    listed: dict[str, str] = {}
    for name, bid in BRANDS.items():
        print(f"=== {name} (brand {bid}) の一覧 ===", flush=True)
        listed.update(list_articles(bid))
    todo = [nid for nid in sorted(listed, key=int, reverse=True) if nid not in have]
    print(f"\n  一覧の記事 {len(listed)}件 / 取り込み済み {len(listed) - len(todo)}件 は飛ばす")
    if limit:
        todo = todo[:limit]
    print(f"=== 記事を取る ({'APPLY' if commit else 'DRY-RUN'}) — 対象 {len(todo)}件 ===",
          flush=True)
    now = datetime.now().isoformat(timespec="seconds")
    got = ut = gone = 0
    for i, nid in enumerate(todo, 1):
        url = f"{BASE}/news/{nid}"
        try:
            h = _get(url)
        except Exception as e:                      # ★1件の失敗で走行を落とさない
            print(f"    ! {nid} 取れない ({type(e).__name__})", flush=True)
            time.sleep(PACE)
            continue
        time.sleep(PACE)
        if h is None:
            gone += 1
            continue
        a = parse_article(nid, h)
        a["list_title"] = listed.get(nid, "")
        a["fetched_at"] = now
        got += 1
        ut += a["is_ut"]
        if not commit:
            print(f"    {nid} UT={a['is_ut']!s:5} 写真{len(a['photos']):3d} "
                  f"{a['published'][:10]} {a['title'][:40]}  {a['detail']}")
            continue
        _raw_store.save(RAW_CAT, f"news_{nid}", h, url, ext="html")
        have[nid] = a
        if i % 10 == 0:                             # ★途中保存
            db["updated_at"] = now
            save(db)
            print(f"    {i}/{len(todo)} 済み (UT {ut})", flush=True)
    if commit:
        db["updated_at"] = now
        save(db)
    print("")
    print(f"  取れた {got}件 (うち UT {ut}) / 消えていた {gone}件")
    print(f"  {'保存' if commit else '(dry-run — --commit で保存)'}: {OUT}")
    if commit:
        n_ut = sum(1 for x in have.values() if x.get("is_ut"))
        print(f"  手元の記事 {len(have)}件 / UT {n_ut}件")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--limit", type=int, help="取る記事の数を絞る (動作確認用)")
    a = ap.parse_args()
    run(a.commit, a.limit)


if __name__ == "__main__":
    main()
