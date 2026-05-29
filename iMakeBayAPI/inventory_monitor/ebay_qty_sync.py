"""ebay_qty_sync - eBay active listing report から SKU シート K 列 (eBay 現Qty) 同期.

Phase 4a-1 補完 (2026-05-14): K 列が古いままだと auto_qty_zero の zero/restore 判定が
誤動作するため、毎 cycle 開始時に listing report を取り込み K 列を最新化する。

データ source:
- eBay active listing report CSV (Takaaki さん seller hub から手動 DL or Selenium 自動)
  - 列 0: Item number (= ItemID)
  - 列 2: Variation details (例: "Sizes=US XS(JP S)|Color=BK")
  - 列 3: Custom label (SKU UUID)
  - 列 4: Available quantity ← 本 script で SKU シート K 列に反映

マッチングロジック:
  - UUID で SKU シート F 列と完全一致 (= UUID 形式の行のみ)
  - UUID 未正規化行 (= sku_uuid_sync 未通過) は skip

実行:
    python ebay_qty_sync.py --report <report.csv>            # dry-run
    python ebay_qty_sync.py --report <report.csv> --execute  # K 列実書込
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# stdout/stderr UTF-8 化
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from sku_uuid_sync import parse_ebay_report, UUID_RE  # noqa: E402
from sheet_updater import open_sheet, get_sku_worksheet, read_sku_rows  # noqa: E402

LOG_DIR = SCRIPT_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def build_uuid_to_qty(ebay_data: dict) -> dict:
    """parse_ebay_report の戻り値 → {uuid: qty(int)} 辞書化.

    qty は int 化、parse 失敗時は -1 (= マッチしても書込スキップ判定に使う)。
    """
    uuid_qty: dict = {}
    for variations in ebay_data.values():
        for v in variations:
            sku = v.get("sku", "").strip()
            if not UUID_RE.match(sku):
                continue
            try:
                qty = int(v.get("qty", "0").strip() or 0)
            except (ValueError, AttributeError):
                qty = -1
            uuid_qty[sku] = qty
    return uuid_qty


def match_qty_updates(uuid_qty: dict, sheet_skus: list) -> list:
    """SKU シート行 ↔ uuid_qty で match、K 列書換対象を抽出.

    対処済 (B=TRUE) 行は **スキップ** (= auto_qty_zero の qty 上書きを保護、
    古い eBay report で書き戻すと自動処理結果を巻き戻すため)。
    """
    results = []
    for sheet_idx, row in enumerate(sheet_skus, start=2):
        r = list(row) + [""] * max(0, 12 - len(row))
        # 対処済 (B=TRUE) 行はスキップ
        if r[1].strip().upper() in ("TRUE", "VRAI"):
            continue
        sku_uuid = r[5].strip()
        if not UUID_RE.match(sku_uuid):
            continue
        if sku_uuid not in uuid_qty:
            continue
        new_qty = uuid_qty[sku_uuid]
        if new_qty < 0:
            continue
        try:
            current_qty = int(r[10]) if r[10].strip() not in ("", "-") else 0
        except ValueError:
            current_qty = 0
        results.append({
            "row_index":  sheet_idx,
            "listing_id": r[3].strip(),
            "sku_id":     sku_uuid,
            "current_qty": current_qty,
            "new_qty":    new_qty,
            "changed":    current_qty != new_qty,
        })
    return results


def sync_from_csv(csv_path: Path, execute: bool = False) -> dict:
    """report CSV → SKU シート K 列同期 (= main.py から呼べる API).

    Returns: {"checked": N, "changed": M, "executed": bool}
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"report not found: {csv_path}")
    ebay_data = parse_ebay_report(csv_path)
    uuid_qty = build_uuid_to_qty(ebay_data)
    sh = open_sheet()
    sheet_skus = read_sku_rows(sh)
    updates = match_qty_updates(uuid_qty, sheet_skus)
    changed = [u for u in updates if u["changed"]]
    if execute and changed:
        sku_ws = get_sku_worksheet(sh)
        cell_updates = [
            {"range": f"K{u['row_index']}", "values": [[u["new_qty"]]]}
            for u in changed
        ]
        sku_ws.batch_update(cell_updates, value_input_option="USER_ENTERED")
    return {
        "checked": len(updates),
        "changed": len(changed),
        "executed": bool(execute and changed),
        "details": changed[:20],  # 先頭 20 件のみ
    }


def main():
    parser = argparse.ArgumentParser(description="eBay listing report → SKU シート K 列 同期")
    parser.add_argument("--report", required=True, help="eBay active listing report CSV path")
    parser.add_argument("--execute", action="store_true", help="本番書込 (default dry-run)")
    args = parser.parse_args()
    is_dry_run = not args.execute

    csv_path = Path(args.report)
    print(f"[1/3] report 読込: {csv_path.name}")
    ebay_data = parse_ebay_report(csv_path)
    uuid_qty = build_uuid_to_qty(ebay_data)
    print(f"  variation listing: {len(ebay_data)} 件、UUID→qty entry: {len(uuid_qty)} 件")

    print(f"[2/3] スプシ読込 + matching")
    sh = open_sheet()
    sheet_skus = read_sku_rows(sh)
    updates = match_qty_updates(uuid_qty, sheet_skus)
    changed = [u for u in updates if u["changed"]]
    print(f"  match: {len(updates)} 件、うち K 列乖離: {len(changed)} 件")

    if changed[:10]:
        print(f"\n  サンプル (max 10 件):")
        for u in changed[:10]:
            print(f"    row {u['row_index']} listing {u['listing_id']}: "
                  f"K {u['current_qty']} → {u['new_qty']}")

    print(f"\n[3/3] {'dry-run' if is_dry_run else '実書込'}")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if is_dry_run:
        out_path = LOG_DIR / f"ebay_qty_sync_dryrun_{ts}.json"
        out_path.write_text(json.dumps(updates, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"  dry-run 結果: {out_path}")
    else:
        if not changed:
            print("  K 列乖離なし、書込スキップ")
            return
        sku_ws = get_sku_worksheet(sh)
        cell_updates = [
            {"range": f"K{u['row_index']}", "values": [[u["new_qty"]]]}
            for u in changed
        ]
        sku_ws.batch_update(cell_updates, value_input_option="USER_ENTERED")
        print(f"  [OK] K 列書換: {len(cell_updates)} cells")
        out_path = LOG_DIR / f"ebay_qty_sync_executed_{ts}.json"
        out_path.write_text(json.dumps(changed, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"  実行記録: {out_path}")


if __name__ == "__main__":
    main()
