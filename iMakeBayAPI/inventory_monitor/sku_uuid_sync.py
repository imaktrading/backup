"""sku_uuid_sync - eBay active listing report から SKU シート F 列を UUID 同期.

Phase 4a-2 (2026-05-14): variation listing の qty=0 化に向け、SKU シートの
F 列 (eBay SKU ID) を eBay 側の実 UUID (= "53b869de-7e1c-4c16-bf3e-c13ffe04b2a2"
形式) に正規化する。

データ source:
- eBay active listing report (Takaaki さんが seller hub から download した CSV)
  - 列 0: Item number (= ItemID)
  - 列 2: Variation details (例: "Sizes=US XS(JP S)")
  - 列 3: Custom label (SKU、= UUID)
  - 列 4: Available quantity

マッチングロジック (= UNIQLO):
- listing_id (= ItemID) で SKU シート行を絞り込み
- JP <SIZE> を Variation details から抽出 (例: "JP S" → "S")
- SKU シートの G 列 (size) と完全一致で UUID を採用

montbell / Amazon は variation なし → 単独 listing で SKU=空 or 既存値維持。

実行:
    python sku_uuid_sync.py --report <report.csv> --dry-run
    python sku_uuid_sync.py --report <report.csv> --execute
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# stdout/stderr UTF-8 化 (cp932 文字化け回避)
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from sheet_updater import (  # noqa: E402
    open_sheet, get_sku_worksheet, read_sku_rows,
)

LOG_DIR = SCRIPT_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# UUID 形式判定 (= 8-4-4-4-12 桁の hex)
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# Variation details から JP size 抽出 (例: "Sizes=US XS(JP S)" → "S")
JP_SIZE_RE = re.compile(r"JP\s+([A-Z0-9]+)", re.IGNORECASE)
# Variation details から Color 抽出 (例: "Sizes=...(JP S)|Color=BK" → "BK")
# `|` 区切りまで全部取って後で normalize (UNIQLO は "Color=32 BEIGE" 形式、montbell は "Color=BLACK(BK)")
COLOR_RE = re.compile(r"Color\s*=\s*([^|]+)", re.IGNORECASE)


def parse_ebay_report(csv_path: Path) -> dict:
    """eBay active listing report を読込 → {ItemID: [{var_details, sku, qty}, ...]} に整理.

    Returns:
        { item_id: [ { "variation_details": "Sizes=US XS(JP S)",
                       "sku": "53b869de-...", "qty": 1 }, ... ] }
        variation なし listing は variation 行が無いので空 list。
    """
    by_itemid: dict = {}
    with csv_path.open(encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        hdr = next(reader)
        for row in reader:
            if len(row) < 5:
                continue
            item_id = row[0].strip()
            var_details = row[2].strip()
            sku = row[3].strip()
            qty = row[4].strip()
            if not item_id:
                continue
            # variation details に「Sizes=...(JP X)」のような個別 variation のみ採用
            # (= 親行は集約形式で複数 ; 含む、個別行は 1 size のみ)
            if not var_details or ";" in var_details:
                continue
            # SKU が UUID 形式の行だけ採用 (= 親行は「UNIQLO official website」等のラベル)
            if not UUID_RE.match(sku):
                continue
            by_itemid.setdefault(item_id, []).append({
                "variation_details": var_details,
                "sku": sku,
                "qty": qty,
            })
    return by_itemid


def extract_jp_size(variation_details: str) -> str:
    """Variation details から JP size を抽出 (例: "Sizes=US XS(JP S)" → "S")."""
    m = JP_SIZE_RE.search(variation_details or "")
    return m.group(1).upper() if m else ""


def extract_color(variation_details: str) -> str:
    """Variation details から Color code を抽出.

    対応形式:
      "Color=BK"            → "BK"
      "Color=BLACK(BK)"     → "BK"      (括弧内 code 優先、montbell)
      "Color=BLACK"         → "BLACK"
      "Color=32 BEIGE"      → "BEIGE"   (数字 prefix 除去、UNIQLO)
      "Color=09 OFF WHITE"  → "OFF WHITE"
    """
    m = COLOR_RE.search(variation_details or "")
    if not m:
        return ""
    val = m.group(1).strip().upper()
    # 数字 prefix + space 除去 (UNIQLO 形式)
    val = re.sub(r"^\d+\s+", "", val).strip()
    # "BLACK(BK)" 形式なら括弧内を優先 (montbell 形式)
    paren = re.search(r"\(([^)]+)\)", val)
    if paren:
        return paren.group(1).strip()
    return val


def normalize_size_for_match(s: str) -> str:
    """サイズ正規化 (大文字 + 空白除去 + montbell -R/-L/-S suffix 除去).

    montbell は size に `-R` (Regular)、`-L` (Long)、`-S` (Short) の suffix が付くが、
    eBay の Variation details には suffix なし → 比較時に除去で match させる。
    """
    out = (s or "").strip().upper().replace(" ", "")
    # montbell suffix 除去
    for suf in ("-R", "-L", "-S"):
        if out.endswith(suf):
            out = out[:-len(suf)]
            break
    return out


def match_sku_uuids(ebay_data: dict, sheet_skus: list) -> list:
    """SKU シート行 ↔ eBay variation を listing_id + JP size でマッチング.

    SKU シート列構成 (= read_sku_rows の戻り値 = list of list):
      A(0)=対処要, B(1)=対処済, C(2)=対処日, D(3)=listing ID, E(4)=title,
      F(5)=eBay SKU ID, G(6)=サイズ, H(7)=色, I(8)=仕入元在庫, J(9)=仕入元価格,
      K(10)=eBay 現Qty, L(11)=自動CHK日

    Returns:
        [{ "row_index": N, "listing_id": "...", "size": "S",
           "current_sku": "<sheet F 列>", "ebay_uuid": "<UUID>",
           "match_status": "ok" / "size_mismatch" / "no_variation" }, ...]
    """
    results = []
    for sheet_idx, row in enumerate(sheet_skus, start=2):  # 2 から (1 行目は header)
        # 列数足りない行は空欄補完
        r = list(row) + [""] * max(0, 12 - len(row))
        row_idx = sheet_idx
        listing_id = r[3].strip()
        sheet_size = normalize_size_for_match(r[6])
        sheet_color = normalize_size_for_match(r[7])
        current_sku = r[5].strip()
        rec = {
            "row_index": row_idx,
            "listing_id": listing_id,
            "size": r[6],
            "color": r[7],
            "current_sku": current_sku,
            "ebay_uuid": "",
            "match_status": "",
        }
        if not listing_id:
            rec["match_status"] = "no_listing_id"
            results.append(rec)
            continue
        ebay_variations = ebay_data.get(listing_id, [])
        if not ebay_variations:
            rec["match_status"] = "no_variation"
            results.append(rec)
            continue
        # eBay 側に Color もあるか判定:
        # - 全 variation が同じ color → size only match (= UNIQLO 系で全 variation 同色 code 1 つ)
        # - color が複数種 → compound match (= montbell 系で size × color combination)
        ebay_colors = {extract_color(ev["variation_details"]) for ev in ebay_variations}
        ebay_colors.discard("")
        ebay_has_color = len(ebay_colors) >= 2

        # match
        matched_uuid = ""
        for ev in ebay_variations:
            ev_size = normalize_size_for_match(extract_jp_size(ev["variation_details"]))
            ev_color = normalize_size_for_match(extract_color(ev["variation_details"]))
            if ev_size != sheet_size:
                continue
            if ebay_has_color:
                # color compound match (montbell)
                if ev_color and ev_color == sheet_color:
                    matched_uuid = ev["sku"]
                    break
            else:
                # size only match (UNIQLO)
                matched_uuid = ev["sku"]
                break
        if matched_uuid:
            rec["ebay_uuid"] = matched_uuid
            rec["match_status"] = "ok"
        else:
            rec["match_status"] = "size_color_mismatch" if ebay_has_color else "size_mismatch"
        results.append(rec)
    return results


def main():
    parser = argparse.ArgumentParser(
        description="eBay listing report から SKU シート F 列を UUID 正規化"
    )
    parser.add_argument("--report", required=True, help="eBay listing report CSV path")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="dry-run mode (= スプシ書込なし、レポート出力のみ)")
    parser.add_argument("--execute", action="store_true",
                        help="本番書込 mode (= dry-run を解除)")
    args = parser.parse_args()
    is_dry_run = not args.execute

    csv_path = Path(args.report)
    if not csv_path.exists():
        print(f"[NG] report not found: {csv_path}")
        sys.exit(1)

    print(f"[1/4] eBay report 読込: {csv_path.name}")
    ebay_data = parse_ebay_report(csv_path)
    total_var = sum(len(v) for v in ebay_data.values())
    print(f"  variation listing: {len(ebay_data)} 件、SKU UUID 行: {total_var} 件")

    print(f"[2/4] スプシ読込: SKU シート")
    sh = open_sheet()
    sheet_skus = read_sku_rows(sh)
    print(f"  SKU 行: {len(sheet_skus)} 件")

    print(f"[3/4] マッチング")
    results = match_sku_uuids(ebay_data, sheet_skus)
    from collections import Counter
    status_count = Counter(r["match_status"] for r in results)
    for st, n in status_count.most_common():
        print(f"  {st:>15}: {n} 件")

    # F 列書換対象: match_status=ok かつ current_sku != ebay_uuid
    needs_write = [r for r in results if r["match_status"] == "ok"
                   and r["current_sku"] != r["ebay_uuid"]]
    print(f"  → 書換対象 (current != ebay_uuid): {len(needs_write)} 件")

    if needs_write:
        print(f"\n  サンプル (max 5 件):")
        for r in needs_write[:5]:
            print(f"    row {r['row_index']}: listing {r['listing_id']} size={r['size']!r}")
            print(f"      current: {r['current_sku'][:40]!r}")
            print(f"      ebay   : {r['ebay_uuid']}")

    print(f"\n[4/4] {'dry-run (= 書込スキップ)' if is_dry_run else '実書込'}")
    if is_dry_run:
        # 結果を JSON で保存 (確認用)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = LOG_DIR / f"sku_uuid_sync_dryrun_{ts}.json"
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"  dry-run 結果: {out_path}")
    else:
        if not needs_write:
            print("  書換対象なし、終了")
            return
        # 実書込
        sku_ws = get_sku_worksheet(sh)
        cell_updates = []
        for r in needs_write:
            cell_updates.append({
                "range": f"F{r['row_index']}",
                "values": [[r["ebay_uuid"]]],
            })
        sku_ws.batch_update(cell_updates, value_input_option="USER_ENTERED")
        print(f"  [OK] F 列 UUID 書換完了: {len(cell_updates)} cells")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = LOG_DIR / f"sku_uuid_sync_executed_{ts}.json"
        out_path.write_text(json.dumps(needs_write, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"  実行記録: {out_path}")


if __name__ == "__main__":
    main()
