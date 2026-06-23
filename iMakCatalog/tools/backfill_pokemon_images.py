"""空 images の Pokemon カードを公式(resultAPI.php)から backfill する.

2026-06-24 新設。scrapers.pokemon_tcg.find_official_card(pg+keyword 絞り→印刷番号照合)を使い、
catalog の images 空 pokemon を:
  - 公式DBに該当あり → cardThumbFile/image_url を images に backfill(+ fetch200 検証)
  - 公式DBに該当なし → **phantom(不正 product_id)** として報告(画像投入しない=Precision-100%)
  - cardID-fallback / NOIMAGE → 対象外(画像源が無い)

使い方:
  python tools/backfill_pokemon_images.py --dry-run   # 判定のみ
  python tools/backfill_pokemon_images.py             # backup後に backfill 適用
"""
from __future__ import annotations
import argparse, json, re, shutil, sqlite3, sys, urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402
from scrapers import pokemon_tcg as P  # noqa: E402
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CAT = "pokemon_tcg"
SRC = "official_image_backfill_20260624"


def head_200(url: str) -> bool:
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
        return urllib.request.urlopen(req, timeout=15).status == 200
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(str(api._DB_PATH)); con.row_factory = sqlite3.Row; cur = con.cursor()
    rows = cur.execute(
        "SELECT id, product_id, name_jp, name_en, specs FROM products "
        "WHERE category=? AND (images IS NULL OR images IN ('','[]')) ORDER BY product_id", (CAT,)
    ).fetchall()
    print(f"空 images pokemon: {len(rows)} 件")

    backfill, phantom, skip = [], [], []
    for r in rows:
        pid = r["product_id"]
        if pid.startswith("cardID-"):
            skip.append((pid, "cardID-fallback (公式noimage/番号体系外)")); continue
        m = re.match(r"^(.*)-(\d+)$", pid)
        if not m:
            skip.append((pid, "product_id 形不正")); continue
        set_code, num = m.group(1), m.group(2)
        name = r["name_jp"] or None
        try:
            hit = P.find_official_card(set_code, name=name, card_number=num)
        except Exception as e:
            skip.append((pid, f"lookup err {e}")); continue
        if hit and hit.get("image_url"):
            backfill.append((r, hit))
        else:
            phantom.append((pid, set_code, num, r["name_en"]))

    print(f"\n=== backfill 可(公式該当) {len(backfill)} ===")
    for r, hit in backfill:
        print(f"  {r['product_id']:14s} <- {hit['product_id']} #{hit['card_number_text']} {hit['image_url']}")
    print(f"\n=== phantom(公式DBに該当番号なし=要データ是正) {len(phantom)} ===")
    for pid, sc, num, nm in phantom:
        print(f"  {pid:14s} set={sc} #{num} ({nm}) — 公式 {sc} に #{num} 無し")
    print(f"\n=== 対象外 {len(skip)} ===")
    for pid, why in skip:
        print(f"  {pid:14s} {why}")

    if args.dry_run or not backfill:
        print("\n(dry-run or backfill対象なし: 書込なし)")
        con.close(); return

    shutil.copy2(api._DB_PATH, str(api._DB_PATH) + ".pre_imgbackfill_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    NOW = datetime.now().isoformat(timespec="seconds"); n = 0
    for r, hit in backfill:
        url = hit["image_url"]
        if not head_200(url):
            print(f"  ⚠️ 200不可 skip: {r['product_id']} {url}"); continue
        cur.execute("UPDATE products SET images=?, updated_at=? WHERE id=?",
                    (json.dumps([url], ensure_ascii=False), NOW, r["id"]))
        n += 1
    con.commit(); con.close()
    print(f"\n✅ backfilled {n}/{len(backfill)} (fetch200 検証済)")


if __name__ == "__main__":
    main()
