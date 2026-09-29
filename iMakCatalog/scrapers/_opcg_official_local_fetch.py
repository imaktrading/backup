"""OPCG 公式 onepiece-cardgame.com cardlist ローカル fetch (= WebFetch IP block 回避).

依頼: ユーザー指示 (2026-05-30) 「限定商品収録カード 175 件含む 公式 series 全取得」
+ Gemini 助言 (= rate 5-10sec + jitter, ローカル ISP IP)

flow:
  1. series ID list で各 series page (= cardlist/?series=NNNNNN) fetch
  2. 各 page の <dl class="modalCol"> block を抽出
  3. fields: card_id / card_number / rarity / type / name / image / cost / power /
     counter / color / block / feature / text / getInfo / attribute
  4. JSON 蓄積 → C:/dev/iMak_data/catalog/_opcg_official_dumps/series_{id}.json

実行:
  python iMakCatalog/scrapers/_opcg_official_local_fetch.py --probe   # 1 series 試行
  python iMakCatalog/scrapers/_opcg_official_local_fetch.py           # 全 series 連鎖
  python iMakCatalog/scrapers/_opcg_official_local_fetch.py --series 550801  # 限定商品のみ
"""
from __future__ import annotations

import argparse
import json
import random
import re
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import requests
from bs4 import BeautifulSoup

# DNS bypass (= shockbase 同様の保険、 ただし onepiece-cardgame.com は通常 OK のはず)
# DNS 問題が出たら IP 直書きに切替え

BASE = "https://www.onepiece-cardgame.com"
LIST_URL = f"{BASE}/cardlist/?series={{series}}"

DUMP_DIR = Path("C:/dev/iMak_data/catalog/_opcg_official_dumps")
CHECKPOINT_FILE = DUMP_DIR / "_progress.json"
RAW_HTML_DIR = DUMP_DIR / "_raw_html"

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.8",
}

RATE_MIN_SEC = 6.0
RATE_JITTER_SEC = 4.0  # avg 8 sec/req (= series page 単位なので少ない)

# series ID 一覧 (= 公式 cardlist プルダウンから抽出、 2026-08-01 現在で 61 series)
#   ST-31〜36 (550031〜550036) は 2026-08-01 に追加 (窓口回答書 §B-1)。
#   `550037 / 550117 / 550118 / 550205` は空ページ (45710 bytes / cards=0) を返すため未発売判定で除外。
SERIES_LIST = [
    # 重要先頭 (= ユーザー指摘)
    ("550801", "限定商品収録カード"),
    ("550901", "プロモーションカード"),
    ("550701", "ファミリーデッキセット"),
    # プレミアムブースター
    ("550302", "プレミアムブースター PRB-02"),
    ("550301", "プレミアムブースター PRB-01"),
    # エクストラブースター
    ("550204", "エクストラブースター EB-04"),
    ("550203", "エクストラブースター EB-03"),
    ("550202", "エクストラブースター EB-02"),
    ("550201", "エクストラブースター EB-01"),
    # ブースターパック OP-01 〜 OP-16
    *[(f"5501{n:02d}", f"ブースターパック OP-{n:02d}") for n in range(1, 17)],
    # スタートデッキ ST-01 〜 ST-36
    *[(f"5500{n:02d}", f"スタートデッキ ST-{n:02d}") for n in range(1, 37)],
]


def polite_sleep():
    time.sleep(RATE_MIN_SEC + random.uniform(0, RATE_JITTER_SEC))


def fetch(url: str, session: requests.Session) -> str | None:
    try:
        r = session.get(url, timeout=30)
        if r.status_code != 200:
            print(f"  ⚠️ {r.status_code} {url}")
            return None
        return r.text
    except Exception as e:
        print(f"  ⚠️ fetch fail: {e}")
        return None


def _text(el):
    if el is None:
        return ""
    return el.get_text(" ", strip=True)


def parse_cards(html: str, series_id: str) -> list[dict]:
    """series page の HTML から各 card block を抽出."""
    soup = BeautifulSoup(html, "html.parser")
    cards = []
    for dl in soup.select("dl.modalCol"):
        card_id = dl.get("id") or ""
        if not card_id:
            continue
        out = {"card_id": card_id, "series_id": series_id}

        # dt 内 info
        info_col = dl.select_one(".infoCol")
        if info_col:
            spans = [_text(s) for s in info_col.find_all("span")]
            # 期待形式: [card_number, rarity, type]
            if len(spans) >= 1:
                out["card_number"] = spans[0]
            if len(spans) >= 2:
                out["rarity"] = spans[1]
            if len(spans) >= 3:
                out["type"] = spans[2]

        name = dl.select_one(".cardName")
        if name:
            out["name_jp"] = _text(name)

        # image (= front)
        img = dl.select_one(".frontCol img.lazy")
        if img:
            src = img.get("data-src") or img.get("src") or ""
            # ../images → /images
            if src.startswith("../"):
                src = src[2:]
            if src.startswith("/"):
                src = BASE + src
            # query string 除去 (例 ?260518)
            out["image_url"] = src.split("?")[0]

        # 各 field
        for cls in ("cost", "power", "counter", "color", "block", "feature", "text"):
            div = dl.select_one(f".{cls}")
            if div:
                # h3 を除去して残り text
                h3 = div.find("h3")
                if h3:
                    h3.extract()
                out[cls] = _text(div)

        # attribute (= img alt)
        attr_img = dl.select_one(".attribute img")
        if attr_img:
            out["attribute"] = attr_img.get("alt", "")

        # getInfo (= 入手方法 = 商品名)
        get_info = dl.select_one(".getInfo")
        if get_info:
            h3 = get_info.find("h3")
            if h3:
                h3.extract()
            out["get_info"] = _text(get_info)

        cards.append(out)
    return cards


def load_checkpoint() -> set[str]:
    if CHECKPOINT_FILE.exists():
        return set(json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8")))
    return set()


def save_checkpoint(done: set[str]):
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_FILE.write_text(json.dumps(sorted(done)), encoding="utf-8")


def cmd_series_one(session: requests.Session, series_id: str, series_name: str,
                   save_raw: bool = True) -> dict | None:
    """1 series page を fetch + parse + JSON 出力."""
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    url = LIST_URL.format(series=series_id)
    polite_sleep()
    html = fetch(url, session)
    if not html:
        return None
    if save_raw:
        RAW_HTML_DIR.mkdir(parents=True, exist_ok=True)
        (RAW_HTML_DIR / f"series_{series_id}.html").write_text(html, encoding="utf-8")
    cards = parse_cards(html, series_id)
    out_file = DUMP_DIR / f"series_{series_id}.json"
    out_file.write_text(
        json.dumps({"series_id": series_id, "series_name": series_name, "cards": cards},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  ✓ {series_id} ({series_name}): {len(cards)} cards → {out_file.name}")
    return {"series_id": series_id, "count": len(cards)}


def cmd_all(session: requests.Session, resume: bool = True):
    done = load_checkpoint() if resume else set()
    print(f"=== OPCG 公式 全 series fetch ({len(SERIES_LIST)} series, "
          f"checkpoint={len(done)} done) ===")
    print(f"  rate: {RATE_MIN_SEC}-{RATE_MIN_SEC + RATE_JITTER_SEC} sec/req")

    total_cards = 0
    for sid, sname in SERIES_LIST:
        if sid in done:
            print(f"  ☐ {sid} ({sname}): skip (already done)")
            continue
        res = cmd_series_one(session, sid, sname)
        if res:
            done.add(sid)
            save_checkpoint(done)
            total_cards += res["count"]

    print(f"\n=== complete: {total_cards} cards total ===")


def cmd_probe(session: requests.Session):
    print("=== probe: series 550801 (限定商品収録カード) ===")
    cmd_series_one(session, "550801", "限定商品収録カード")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--probe", action="store_true")
    p.add_argument("--series", type=str, help="特定 series のみ")
    p.add_argument("--no-resume", action="store_true")
    args = p.parse_args()

    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(UA)

    if args.probe:
        cmd_probe(session)
        return
    if args.series:
        # series 名検索
        sname = next((n for s, n in SERIES_LIST if s == args.series), args.series)
        cmd_series_one(session, args.series, sname)
        return
    cmd_all(session, resume=not args.no_resume)


if __name__ == "__main__":
    main()
