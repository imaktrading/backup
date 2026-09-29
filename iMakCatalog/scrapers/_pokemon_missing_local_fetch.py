"""Pokemon-card.com 未取得 cardID fetch (= 別 PC ローカル実行用).

依頼: ユーザー指示 (2026-05-30) Pokemon 1,126 件取り漏れ追加投入
+ ShockBase / OPCG / DBFW / Gundam と同パターンの local fetch script。

flow:
  1. catalog 既存 cardID JSON 読込 (= `_pokemon_existing_cardIDs.json`、 メイン PC で出力済)
  2. pokemon-card.com の list API で全 cardID 取得
  3. 不在 cardID list 生成
  4. 各 cardID で detail HTML fetch → cache + JSON 出力

実行:
  py _pokemon_missing_local_fetch.py --probe        # list API + 不在件数のみ表示
  py _pokemon_missing_local_fetch.py                # 全件 fetch (= checkpoint resume)

必要 install:
  py -m pip install requests
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import requests

BASE = "https://www.pokemon-card.com"
LIST_API = f"{BASE}/card-search/resultAPI.php"
DETAIL_BASE = f"{BASE}/card-search/details.php/card"

# 共有領域 (= OneDrive 経由でメイン PC と同期)
# 別 PC で実行時は OneDrive デスクトップを優先 (= ローカル `C:/dev/iMak_data/` は別 PC 不在)
def _resolve_data_dir() -> Path:
    candidates = [
        Path("C:/dev/iMak_data/catalog"),  # メイン PC
        Path(r"C:/Users/imax2/OneDrive/デスクトップ/_pokemon_share"),  # 別 PC: OneDrive 内
        Path(r"C:/Users/imax2/OneDrive/デスクトップ"),  # fallback: デスクトップ直下
    ]
    for c in candidates:
        if c.exists():
            # _pokemon_existing_cardIDs.json が見える dir を採用
            if (c / "_pokemon_existing_cardIDs.json").exists():
                return c
    # どこにもなければ最初の candidate に作成
    candidates[0].mkdir(parents=True, exist_ok=True)
    return candidates[0]


DATA_DIR = _resolve_data_dir()
EXISTING_IDS_FILE = DATA_DIR / "_pokemon_existing_cardIDs.json"
DUMP_DIR = DATA_DIR / "_pokemon_missing_dumps"
CHECKPOINT_FILE = DUMP_DIR / "_progress.json"
ALL_IDS_FILE = DUMP_DIR / "_all_cardIDs.json"
RAW_HTML_DIR = DUMP_DIR / "_raw_html"

print(f"[init] DATA_DIR = {DATA_DIR}")
print(f"[init] EXISTING_IDS_FILE exists = {EXISTING_IDS_FILE.exists()}")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

RATE_MIN_SEC = 6.0
RATE_JITTER_SEC = 4.0  # avg 8 sec
LIST_RATE_SEC = 3.0    # list API は軽いので短め
BATCH_SIZE = 50
BATCH_REST_SEC = 1200  # 20 min


def polite_sleep(rate_min=RATE_MIN_SEC, rate_jitter=RATE_JITTER_SEC):
    time.sleep(rate_min + random.uniform(0, rate_jitter))


def fetch_all_cardIDs(session: requests.Session) -> list[int]:
    """list API で全 cardID を取得 (= 22k cards / 590 page 想定)."""
    if ALL_IDS_FILE.exists():
        ids = json.loads(ALL_IDS_FILE.read_text(encoding="utf-8"))
        print(f"  cache hit: {len(ids):,} cardIDs")
        return ids
    print("  fetching list API ...")
    params = {"page": 1, "regulation_sidebar_form": "all"}
    r = session.get(LIST_API, params=params, timeout=30)
    d = r.json()
    max_page = int(d.get("maxPage", 1))
    hit_cnt = int(d.get("hitCnt", 0))
    print(f"  hitCnt={hit_cnt:,} maxPage={max_page}")
    all_ids: list[int] = []
    for c in d.get("cardList", []) or []:
        cid = c.get("cardID")
        if cid:
            all_ids.append(int(cid))
    time.sleep(LIST_RATE_SEC)
    for page in range(2, max_page + 1):
        try:
            r = session.get(LIST_API, params={**params, "page": page}, timeout=30)
            d = r.json()
            for c in d.get("cardList", []) or []:
                cid = c.get("cardID")
                if cid:
                    all_ids.append(int(cid))
        except Exception as e:
            print(f"  ⚠️ page {page} fail: {e}")
        if page % 50 == 0:
            print(f"  ... list page {page}/{max_page} (ids so far: {len(all_ids):,})")
        time.sleep(LIST_RATE_SEC)
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    ALL_IDS_FILE.write_text(json.dumps(sorted(set(all_ids))), encoding="utf-8")
    print(f"  saved: {ALL_IDS_FILE} ({len(set(all_ids)):,} unique IDs)")
    return sorted(set(all_ids))


def fetch_detail(session: requests.Session, card_id: int, save_raw: bool = True) -> str | None:
    url = f"{DETAIL_BASE}/{card_id}"
    try:
        r = session.get(url, timeout=20)
        if r.status_code != 200:
            return None
    except Exception as e:
        print(f"  ⚠️ {card_id} fail: {e}")
        return None
    html = r.text
    if save_raw:
        RAW_HTML_DIR.mkdir(parents=True, exist_ok=True)
        (RAW_HTML_DIR / f"{card_id}.html").write_text(html, encoding="utf-8")
    return html


def load_checkpoint() -> set[int]:
    if CHECKPOINT_FILE.exists():
        return set(json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8")))
    return set()


def save_checkpoint(done: set[int]):
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_FILE.write_text(json.dumps(sorted(done)), encoding="utf-8")


def cmd_probe(session):
    print("=== probe ===")
    all_ids = fetch_all_cardIDs(session)
    print(f"  全 cardID: {len(all_ids):,}")
    if EXISTING_IDS_FILE.exists():
        existing = set(json.loads(EXISTING_IDS_FILE.read_text(encoding="utf-8")))
        print(f"  catalog 既存: {len(existing):,}")
        missing = sorted(set(all_ids) - existing)
        print(f"  未取得 (= INSERT 候補): {len(missing):,}")
        print(f"  既存にあって公式に無い: {len(existing - set(all_ids)):,}")
        if missing:
            print(f"  sample missing cardIDs: {missing[:10]}")
    else:
        print(f"  ⚠️ existing IDs file not found: {EXISTING_IDS_FILE}")


def cmd_all(session, limit: int | None = None):
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    if not EXISTING_IDS_FILE.exists():
        print(f"  ⚠️ existing IDs file not found: {EXISTING_IDS_FILE}")
        return
    all_ids = fetch_all_cardIDs(session)
    existing = set(json.loads(EXISTING_IDS_FILE.read_text(encoding="utf-8")))
    missing = sorted(set(all_ids) - existing)
    done = load_checkpoint()
    targets = [m for m in missing if m not in done]
    print(f"=== fetch missing cardID: {len(targets):,} ({len(done):,} done) ===")
    if limit:
        targets = targets[:limit]
        print(f"  limit applied: {len(targets):,}")
    fetched = 0
    failed = 0
    started = time.time()
    for i, cid in enumerate(targets, 1):
        polite_sleep()
        html = fetch_detail(session, cid)
        if html:
            done.add(cid)
            fetched += 1
        else:
            failed += 1
        if i % BATCH_SIZE == 0:
            save_checkpoint(done)
            elapsed = int(time.time() - started)
            remaining_sec = int(elapsed / i * (len(targets) - i))
            print(f"  ... {i}/{len(targets)} | OK={fetched} FAIL={failed} "
                  f"elapsed={elapsed//60}min ETA={remaining_sec//60}min")
            print(f"  sleeping {BATCH_REST_SEC} sec before next batch...")
            time.sleep(BATCH_REST_SEC)
    save_checkpoint(done)
    print(f"\n=== complete ===")
    print(f"  fetched: {fetched}")
    print(f"  failed:  {failed}")
    print(f"  total elapsed: {int((time.time() - started) / 60)} min")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--probe", action="store_true")
    p.add_argument("--limit", type=int)
    args = p.parse_args()
    session = requests.Session()
    session.headers.update(UA)
    if args.probe:
        cmd_probe(session)
        return
    cmd_all(session, args.limit)


if __name__ == "__main__":
    main()
