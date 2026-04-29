"""TEST_HIGH 商品管理シート D列を書換え:
  1. random sample 20 行の〇 (前 build_inspection_sheet が書いた抜き取り検査マーク) をクリア
  2. scraper が SOLD 検出した 8 行に〇を新規書込

Phase 5 final dry-run 結果 (decision_log/listings_HIGH_20260429_221600.jsonl)
の SOLD 8 行 (4 SOLD_OUT + 4 DELETED) をマーク → Takaaki さん目視で precision 検証。
"""
from __future__ import annotations
import json, sys, random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sheet_updater import open_sheet_by_id

TEST_HIGH_ID = "1oDjQC8WN_3WC2InPHAV-hPKmsa96rdNd4jxbGBzDimc"
LATEST_LOG = ROOT / "decision_log" / "listings_HIGH_20260429_221600.jsonl"
LISTINGS_GID = 851100680
SAMPLE_N = 20
SEED = 42


def collect_in_stock(log_path: Path) -> list:
    rows = []
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("supplier") != "mercari": continue
            if r.get("error"): continue
            if r.get("is_sold"): continue
            rows.append({"row_index": r["row_index"], "item_id": r.get("item_id",""),
                         "url": r.get("url",""), "title": r.get("title","")})
    return rows


def collect_sold(log_path: Path) -> list:
    rows = []
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("supplier") != "mercari": continue
            if r.get("error"): continue
            if not r.get("is_sold"): continue
            rows.append({"row_index": r["row_index"], "item_id": r.get("item_id",""),
                         "url": r.get("url",""), "title": r.get("title",""),
                         "raw_status": r.get("raw_status","?")})
    return rows


def main():
    in_stock = collect_in_stock(LATEST_LOG)
    sold = collect_sold(LATEST_LOG)
    rng = random.Random(SEED)
    sample20 = rng.sample(in_stock, SAMPLE_N) if len(in_stock) >= SAMPLE_N else in_stock

    sample20_rows = [s["row_index"] for s in sample20]
    sold_rows = [s["row_index"] for s in sold]

    print(f"=== D列書換え ===")
    print(f"  クリア対象 (random sample 20): {sorted(sample20_rows)}")
    print(f"  〇付与対象 (SOLD 検出 {len(sold)}): {sorted(sold_rows)}")
    print()

    sh = open_sheet_by_id(TEST_HIGH_ID)
    listings_ws = None
    for ws in sh.worksheets():
        if ws.id == LISTINGS_GID:
            listings_ws = ws; break
    if listings_ws is None:
        print("商品管理シート not found"); sys.exit(1)
    print(f"  open: {sh.title} / {listings_ws.title}")

    # クリア対象から SOLD 重複を除く (SOLD 行はすぐ上書きで〇 → 二度手間避ける)
    clear_targets = [r for r in sample20_rows if r not in sold_rows]
    cell_updates = []
    for row in clear_targets:
        cell_updates.append({"range": f"D{row}", "values": [[""]]})
    for row in sold_rows:
        cell_updates.append({"range": f"D{row}", "values": [["〇"]]})

    listings_ws.batch_update(cell_updates, value_input_option="USER_ENTERED")
    print(f"  クリア: {len(clear_targets)} 行")
    print(f"  〇付与: {len(sold_rows)} 行")
    print()
    print(f"  シート URL:")
    print(f"  https://docs.google.com/spreadsheets/d/{TEST_HIGH_ID}/edit#gid={LISTINGS_GID}")
    print()
    print(f"=== 〇 付与した SOLD 検出 {len(sold)} 行 (Takaaki さん目視確認用) ===")
    for s in sorted(sold, key=lambda r: r["row_index"]):
        print(f"  row{s['row_index']:>3}  status={s['raw_status']:>10}  {s['url']}")
        print(f"           title: {s['title'][:55]}")


if __name__ == "__main__":
    main()
