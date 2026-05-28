"""Yu-Gi-Oh! Konami JP DB から OCG print image 取得 + catalog 投入.

依頼: ユーザー指示 (5/28 21:18) 「カタログは正確な公式データを持つことが目的」
背景: catalog YGO 11,646 件 全 ygoprodeck artwork URL (= TCG English 印刷)。
      OCG JA 印刷画像が公式の JA データ → Konami JP DB scrape で取得。

flow:
  1. ygoprodeck misc=yes 全件 fetch → passcode → konami_id mapping
  2. catalog YGO entries に konami_id 紐付け
  3. 各 konami_id で Konami JP DB scrape:
     - page fetch → enc + ciid extract
     - get_image.action?...&enc=... で image fetch
     - local 保存 `_ygo_jp_images/{passcode}.jpg`
     - phash 計算
  4. catalog UPDATE:
     - images 列に local JA path append
     - variants.default に jp_image_phash + konami_id

checkpoint: 100 件毎 commit + log to JSON resume marker
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB = str(api._DB_PATH)
NOW = datetime.now().isoformat()
JP_IMG_DIR = Path("C:/dev/iMak_data/catalog/_ygo_jp_images")
JP_IMG_DIR.mkdir(parents=True, exist_ok=True)
CHECKPOINT_FILE = Path("C:/dev/iMak_data/catalog/_ygo_konami_progress.json")
YGOPRODECK_DUMP = Path("C:/dev/iMak_data/catalog/_ygoprodeck_dump.json")

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
POLITE_DELAY = 0.6  # 1 card あたり 2 req + delay = ~1.5 sec
FETCH_TIMEOUT = 20


def fetch_ygoprodeck_dump() -> dict[int, int]:
    """ygoprodeck 全件 misc=yes 取得 + passcode → konami_id mapping 返却.

    catalog 高速 build のため local 1 度 dump。
    """
    if YGOPRODECK_DUMP.exists():
        data = json.loads(YGOPRODECK_DUMP.read_text(encoding="utf-8"))
        print(f"  ygoprodeck dump cache hit: {len(data)} entries")
        return {int(k): v for k, v in data.items()}
    import requests
    print("  ygoprodeck misc=yes fetch ...")
    r = requests.get(
        "https://db.ygoprodeck.com/api/v7/cardinfo.php?misc=yes",
        timeout=60,
    )
    cards = r.json().get("data", [])
    mapping = {}
    for c in cards:
        passcode = c.get("id")
        misc = c.get("misc_info", [])
        if not passcode or not misc:
            continue
        konami_id = misc[0].get("konami_id") if isinstance(misc, list) else None
        if konami_id:
            mapping[int(passcode)] = int(konami_id)
    YGOPRODECK_DUMP.write_text(
        json.dumps({str(k): v for k, v in mapping.items()}, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  ygoprodeck dump saved: {len(mapping)} passcode→konami_id entries")
    return mapping


def fetch_konami_jp_image(session, konami_id: int) -> tuple[bytes, str] | None:
    """Konami JP DB から 1 card の OCG JA image bytes 取得.

    手順:
      1. page fetch (= /yugiohdb/card_search.action?ope=2&cid={konami_id}&request_locale=ja)
      2. enc + ciid 抽出 (= image URL の signed token)
      3. image fetch (= /yugiohdb/get_image.action?...&enc=...)

    Returns:
        (image_bytes, image_url_used) or None (= 失敗時)
    """
    try:
        page_url = (
            f"https://www.db.yugioh-card.com/yugiohdb/card_search.action"
            f"?ope=2&cid={konami_id}&request_locale=ja"
        )
        r = session.get(page_url, timeout=FETCH_TIMEOUT)
        if r.status_code != 200:
            return None
        m = re.search(
            rf"get_image\.action\?type=1&osplang=1&cid={konami_id}&ciid=(\d+)&enc=([^&\"\s]+)",
            r.text,
        )
        if not m:
            return None
        ciid = m.group(1)
        enc = m.group(2)
        time.sleep(POLITE_DELAY)
        img_url = (
            f"https://www.db.yugioh-card.com/yugiohdb/get_image.action"
            f"?type=1&osplang=1&cid={konami_id}&ciid={ciid}&enc={enc}"
            f"&app=tournament&request_locale=ja"
        )
        r2 = session.get(img_url, timeout=FETCH_TIMEOUT)
        if r2.status_code != 200:
            return None
        # PNG magic check (= Konami は PNG で配信)
        if not (r2.content.startswith(b"\x89PNG") or r2.content.startswith(b"\xff\xd8\xff")):
            return None
        # canonical URL (= enc 省略形、 catalog storage 用)
        canonical_url = (
            f"https://www.db.yugioh-card.com/yugiohdb/get_image.action"
            f"?type=1&osplang=1&cid={konami_id}&ciid={ciid}"
        )
        return r2.content, canonical_url
    except Exception:
        return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--probe", action="store_true", help="件数集計のみ")
    p.add_argument("--limit", type=int, help="先頭 N 件のみ")
    p.add_argument("--resume", action="store_true", help="checkpoint から再開")
    args = p.parse_args()

    import requests
    import imagehash
    from PIL import Image

    # 1. ygoprodeck dump (= passcode → konami_id)
    print("=== Step 1: ygoprodeck mapping ===")
    konami_map = fetch_ygoprodeck_dump()

    # 2. catalog YGO entries pull
    print("\n=== Step 2: catalog YGO entries ===")
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT id, product_id, images, variants FROM products WHERE category='yugioh_tcg'"
    ).fetchall()
    print(f"  YGO total: {len(rows)}")

    # 3. checkpoint 読込
    completed: set[int] = set()
    if args.resume and CHECKPOINT_FILE.exists():
        completed = set(json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8")))
        print(f"  resume: skip {len(completed)} done entries")

    # 4. 対象 entry filter
    targets = []
    no_konami = 0
    for r in rows:
        try:
            passcode = int(r["product_id"])
        except (TypeError, ValueError):
            continue
        if passcode in completed:
            continue
        konami_id = konami_map.get(passcode)
        if not konami_id:
            no_konami += 1
            continue
        targets.append({
            "id": r["id"],
            "passcode": passcode,
            "konami_id": konami_id,
            "images": json.loads(r["images"]) if r["images"] else [],
            "variants": json.loads(r["variants"]) if r["variants"] else {},
        })
    print(f"  with konami_id: {len(targets)} / no konami_id: {no_konami}")

    if args.probe:
        return
    if args.limit:
        targets = targets[: args.limit]

    # 5. Konami scrape batch
    print(f"\n=== Step 3: Konami scrape (target {len(targets)}) ===")
    session = requests.Session()
    session.headers.update(UA)
    ok, failed = 0, 0
    started_at = time.time()
    for i, t in enumerate(targets, start=1):
        # 既に local image あれば skip
        img_path = JP_IMG_DIR / f"{t['passcode']}.jpg"
        if img_path.exists() and img_path.stat().st_size > 1000:
            completed.add(t["passcode"])
            ok += 1
            continue

        result = fetch_konami_jp_image(session, t["konami_id"])
        if not result:
            failed += 1
            time.sleep(POLITE_DELAY)
            continue
        img_bytes, canonical_url = result
        img_path.write_bytes(img_bytes)

        # phash
        try:
            img = Image.open(io.BytesIO(img_bytes))
            phash = str(imagehash.phash(img))
        except Exception:
            phash = None

        # catalog UPDATE
        new_images = list(t["images"])
        if canonical_url not in new_images:
            new_images.append(canonical_url)
        local_path = str(img_path).replace("\\", "/")
        if local_path not in new_images:
            new_images.append(local_path)

        new_variants = dict(t["variants"])
        new_variants.setdefault("default", {})
        if phash:
            new_variants["default"]["jp_image_phash"] = phash
        new_variants["default"]["konami_id"] = t["konami_id"]
        new_variants["default"]["jp_image_source"] = "konami_jp_db"

        db.execute(
            "UPDATE products SET images=?, variants=?, updated_at=? WHERE id=?",
            (
                json.dumps(new_images, ensure_ascii=False),
                json.dumps(new_variants, ensure_ascii=False),
                NOW,
                t["id"],
            ),
        )
        completed.add(t["passcode"])
        ok += 1
        time.sleep(POLITE_DELAY)

        if i % 50 == 0:
            db.commit()
            CHECKPOINT_FILE.write_text(json.dumps(list(completed)), encoding="utf-8")
            elapsed = int(time.time() - started_at)
            remaining = len(targets) - i
            eta_min = int(elapsed / i * remaining / 60) if i else 0
            print(f"  ... {i}/{len(targets)} | OK={ok} FAIL={failed} "
                  f"elapsed={elapsed//60}min ETA={eta_min}min", flush=True)

    db.commit()
    CHECKPOINT_FILE.write_text(json.dumps(list(completed)), encoding="utf-8")
    db.close()

    elapsed = int(time.time() - started_at)
    print(f"\n=== 完了 ===")
    print(f"  OK:   {ok}")
    print(f"  FAIL: {failed}")
    print(f"  elapsed: {elapsed//60} min")


if __name__ == "__main__":
    main()
