#!/usr/bin/env python3
"""ポケモンの公式ページを1枚ずつ取り直し、生HTMLを残して空欄だけ埋める.

2026-08-22。目的は2つ:
  1. **生HTMLを残す** (`_raw_store`)。次に別の項目が要るとき取り直さないで済む
  2. 今空いている項目を、同じ1回のスキャンでまとめて埋める

## 埋める項目 (公式ページに載っていることを実物で確認済 / card/44532)
    タイプ / HP / 進化段階 / 弱点 / 抵抗力 / にげる / イラストレーター /
    番号 / 収録弾 / レアリティ(表示がある分だけ) / 弾記号 / 画像

## 守ること
- **既に値がある項目は上書きしない**。空欄だけ埋める
- レアリティは公式に表示が無いカードが多い。増えなくても正常
  (CLAUDE.md 「Rarity の空欄は天井」参照)
- 生HTMLが既にあるカードは **取りに行かない** (手元を読む)。--refetch で強制取得

実行:
  python scrapers/pokemon_detail_refetch.py --limit 20            # dry-run
  python scrapers/pokemon_detail_refetch.py --limit 20 --commit
  python scrapers/pokemon_detail_refetch.py --commit              # 全件 (約9時間)
"""
from __future__ import annotations

import argparse
import html as _html
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scrapers"))
import api  # noqa: E402
import _raw_store  # noqa: E402
from pokemon_tcg import _get, _parse_detail_html, SLEEP_BETWEEN_CALLS  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CATEGORY = "pokemon_tcg"
SOURCE = "detail_refetch_20260822"
# 公式ページの値 -> specs のキー (空欄のときだけ入れる)
FIELDS = ["type_en", "type_jp", "hp", "stage", "weakness", "resistance", "retreat",
          "illustrator", "rarity", "card_number_text", "card_number_total",
          "regulation_set", "attack_name", "attack_damage", "ability_name"]
CARD_ID_RE = re.compile(r"/card/(\d+)")


def _extra_from_html(html: str) -> dict:
    """_parse_detail_html が拾わない分を足す (ワザ / 特性 / 画像)."""
    def clean(v):
        return re.sub(r"\s+", " ", _html.unescape(v or "")).strip()

    out = {}
    m = re.search(r'<h2[^>]*>ワザ</h2>(.*?)(?:<h2|<div class="Section)', html, re.S)
    if m:
        blk = m.group(1)
        mn = re.search(r"<h4[^>]*>(?:<span[^>]*></span>)*\s*([^<]+?)\s*(?:<span[^>]*>(\d+)</span>)?</h4>", blk)
        if mn:
            out["attack_name"] = clean(mn.group(1))
            if mn.group(2):
                out["attack_damage"] = mn.group(2)
    m = re.search(r'<h2[^>]*>特性</h2>\s*<h4[^>]*>([^<]+)</h4>', html, re.S)
    if m:
        out["ability_name"] = clean(m.group(1))
    m = re.search(r'src="(/assets/images/card_images/large/[^"]+)"', html)
    if m:
        out["image_url"] = "https://www.pokemon-card.com" + m.group(1)
    return out


def _commit(db, updates):
    """ロックされていたら少し待って粘る (最大5回)."""
    for attempt in range(5):
        try:
            db.executemany("UPDATE products SET specs=?, set_name_official=?, images=?, "
                           "updated_at=? WHERE id=?", updates)
            db.commit()
            return True
        except sqlite3.OperationalError as e:
            if "locked" not in str(e).lower() or attempt == 4:
                raise
            print(f"   ! DB ロック中。{(attempt + 1) * 10}秒待って再試行", flush=True)
            time.sleep((attempt + 1) * 10)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--refetch", action="store_true", help="生HTMLが有っても取り直す")
    args = ap.parse_args()

    # ★2026-08-22: 9時間走る間に別の migration が同じ DB を書くと
    #   'database is locked' で落ちる (実際に 6,400/21,982 で落ちた)。
    #   待ち時間を伸ばし、commit は数回まで粘る。
    db = sqlite3.connect(api._DB_PATH, timeout=120)
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT id, product_id, source_url, set_name_official, images, specs "
        "FROM products WHERE category=? AND source_url LIKE '%card-search/details.php%' "
        "ORDER BY product_id", (CATEGORY,)).fetchall()
    if args.limit:
        rows = rows[:args.limit]

    filled, updates, from_disk, fetched, failed = Counter(), [], 0, 0, 0
    t0 = time.time()
    for i, r in enumerate(rows, 1):
        m = CARD_ID_RE.search(r["source_url"] or "")
        if not m:
            continue
        cid = m.group(1)
        html = None if args.refetch else _raw_store.load(CATEGORY, cid)
        if html:
            from_disk += 1
        else:
            resp = _get(r["source_url"])
            if resp.status_code != 200 or not resp.text:
                failed += 1
                continue
            html = resp.text
            if args.commit:
                _raw_store.save(CATEGORY, cid, html, r["source_url"])
            fetched += 1
            time.sleep(SLEEP_BETWEEN_CALLS)

        parsed = _parse_detail_html(html, cid) or {}
        parsed.update(_extra_from_html(html))
        # ★2026-08-23: 9時間走る間に別の migration が同じ行を直すことがある。
        #   起動時に読んだスナップショットを書き戻すと **その修正を巻き戻す**
        #   (実害: 8/22 に直した SV4K/SV4M/SV9 の 322行が戻った)。
        #   書く直前に必ず読み直す。
        cur_row = db.execute("SELECT specs, set_name_official, images FROM products "
                             "WHERE id=?", (r["id"],)).fetchone()
        s = json.loads(cur_row["specs"] or "{}")
        touched = False
        for k in FIELDS:
            v = parsed.get(k)
            if v and not str(s.get(k) or "").strip():
                s[k] = v
                filled[k] += 1
                touched = True
        sno = cur_row["set_name_official"]
        new_sno = None
        if not sno and parsed.get("set_name_official"):
            new_sno = parsed["set_name_official"]
            filled["set_name_official"] += 1
            touched = True
        imgs = json.loads(cur_row["images"] or "[]") if cur_row["images"] else []
        new_imgs = None
        if not imgs and parsed.get("image_url"):
            new_imgs = json.dumps([parsed["image_url"]], ensure_ascii=False)
            filled["images"] += 1
            touched = True
        if touched:
            s["detail_refetch_source"] = SOURCE
            updates.append((json.dumps(s, ensure_ascii=False),
                            new_sno or sno, new_imgs or cur_row["images"],
                            datetime.now().isoformat(timespec="seconds"), r["id"]))
        if args.commit and len(updates) >= 200:
            _commit(db, updates)
            updates = []
        if i % 200 == 0:
            el = time.time() - t0
            print(f"  {i}/{len(rows)}  取得{fetched} 手元{from_disk} 失敗{failed}  "
                  f"経過{el/60:.1f}分  埋めた: {dict(filled.most_common(5))}", flush=True)

    if args.commit and updates:
        _commit(db, updates)
    print(f"\n=== {'APPLY' if args.commit else 'DRY-RUN'} 完了 {len(rows)}枚 ===")
    print(f"  取得 {fetched} / 手元の生HTML {from_disk} / 失敗 {failed}")
    for k, n in filled.most_common():
        print(f"  {k:20s} +{n}")
    if not args.commit:
        print("\n(dry-run — --commit で適用・生HTMLの保存も --commit 時のみ)")
    db.close()


if __name__ == "__main__":
    main()
