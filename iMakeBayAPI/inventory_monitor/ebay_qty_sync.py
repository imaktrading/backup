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
    """parse_ebay_report の戻り値 → {(listing_id, uuid): qty(int)} 辞書化.

    ★ 2026-07-08 修正: 旧実装は {uuid: qty} で UUID 単独キーだったが、 eBay の variation
    SKU (Custom label) UUID は **listing 固有でなく size ごとの共通テンプレ** で、 同一 UUID が
    数百 listing で共有される (実測: XL の UUID が 330 listing で共有)。 UUID 単独キーだと
    dict の last-wins で report 末尾 listing の qty が全 listing の同 size 行に書かれ、 K 列
    (eBay 現Qty) が壊れる → 在庫あるのに restore されない (◎ × K=0 条件を満たさず) 機会損失。
    → (listing_id, uuid) 複合キーにして listing 別に正しく qty を保持する
    (audit_sheet_vs_ebay.load_ebay_qty と同方式)。
    qty は int 化、parse 失敗時は -1 (= マッチしても書込スキップ判定に使う)。
    """
    key_qty: dict = {}
    for listing_id, variations in ebay_data.items():
        for v in variations:
            sku = v.get("sku", "").strip()
            if not UUID_RE.match(sku):
                continue
            try:
                qty = int(v.get("qty", "0").strip() or 0)
            except (ValueError, AttributeError):
                qty = -1
            key_qty[(str(listing_id).strip(), sku)] = qty
    return key_qty


def match_qty_updates(uuid_qty: dict, sheet_skus: list) -> list:
    """SKU シート行 ↔ (listing_id, uuid)→qty で match、K 列書換対象を抽出.

    対処済 (B=TRUE) 行は **スキップ** (= auto_qty_zero の qty 上書きを保護、
    古い eBay report で書き戻すと自動処理結果を巻き戻すため)。
    照合は (listing_id, uuid) 複合キー (= UUID が listing 跨ぎで共有される問題への対策)。
    """
    results = []
    for sheet_idx, row in enumerate(sheet_skus, start=2):
        r = list(row) + [""] * max(0, 12 - len(row))
        # 対処済 (B=TRUE) 行は原則スキップ。ただし **下げる方向 (qty を減らす)** だけは
        # 反映する。skip の目的は「古い report で取下げ結果を巻き戻さない」ことなので、
        # 減らす向きは巻き戻しにならない。
        # ★ 2026-09-07: この skip のせいで、取下げ済なのに K=1 のまま残った行が
        #   76 件あり、「仕入元✕ × eBay在庫あり」として永久に対処要と数えられていた。
        _done = r[1].strip().upper() in ("TRUE", "VRAI")
        listing_id = r[3].strip()
        sku_uuid = r[5].strip()
        if not UUID_RE.match(sku_uuid):
            continue
        key = (listing_id, sku_uuid)
        if key not in uuid_qty:
            continue
        new_qty = uuid_qty[key]
        if new_qty < 0:
            continue
        try:
            current_qty = int(r[10]) if r[10].strip() not in ("", "-") else 0
        except ValueError:
            current_qty = 0
        if _done and new_qty >= current_qty:
            continue                     # 対処済 行は 増やす/据置 の書込をしない
        results.append({
            "row_index":  sheet_idx,
            "listing_id": r[3].strip(),
            "sku_id":     sku_uuid,
            "current_qty": current_qty,
            "new_qty":    new_qty,
            "changed":    current_qty != new_qty,
        })
    return results


VANISHED_SURGE_MAX = 300     # 1 回で K=0 にする上限 (超えたら止めて報告 = 誤一括の防止)
REPORT_MIN_ROWS = 500        # report がこの行数未満なら壊れている疑い → 何もしない


def find_vanished_rows(ebay_data: dict, uuid_qty: dict, sheet_skus: list) -> list:
    """eBay に枠が無いのに K 列が >0 のまま残っている行を拾う (仕入元 ✕ の行のみ)。

    ★ 2026-09-07: K 列 (eBay 現Qty) はシート自身の値を書き戻しているだけなので、
      出品や variation が終了しても 1 のまま残り、その行は「仕入元✕ × eBay在庫あり」
      = 永久に対処要として数え続けられていた (実測 136 行)。要対処の件数が実態と
      合わなくなり、増減アラートが意味を失う。

    ★ 仕入元 ✕ の行だけを対象にする。◎ の行を 0 にすると「仕入復活 × eBay 在庫0」
      = 復活対象と見なされ、存在しない枠に qty=1 を送りに行くため。

    Returns: [{"row_index", "listing_id", "sku_id", "current_qty", "new_qty": 0, "reason"}]
    """
    active = {str(k).strip() for k in ebay_data}
    out = []
    for sheet_idx, row in enumerate(sheet_skus, start=2):
        r = list(row) + [""] * max(0, 12 - len(row))
        if r[8].strip() != "✕":            # 仕入元 ✕ の行のみ
            continue
        try:
            cur = int(r[10]) if r[10].strip() not in ("", "-") else 0
        except ValueError:
            continue
        if cur <= 0:
            continue
        listing_id, sku_uuid = r[3].strip(), r[5].strip()
        if not listing_id:
            continue
        if listing_id not in active:
            reason = "listing_not_active"          # 出品自体が終了している
        elif UUID_RE.match(sku_uuid) and (listing_id, sku_uuid) not in uuid_qty:
            reason = "variation_not_in_listing"    # 出品はあるがその枠が無い
        else:
            continue                               # 判定できない行は触らない
        out.append({"row_index": sheet_idx, "listing_id": listing_id, "sku_id": sku_uuid,
                    "current_qty": cur, "new_qty": 0, "reason": reason})
    return out


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

    # eBay に枠が無いのに K>0 で残っている行 (= 対処要の万年カウント) を 0 に戻す
    vanished, vanished_held = [], False
    if len(sheet_skus) and sum(len(v) for v in ebay_data.values()) >= REPORT_MIN_ROWS:
        vanished = find_vanished_rows(ebay_data, uuid_qty, sheet_skus)
        if len(vanished) > VANISHED_SURGE_MAX:
            vanished_held, vanished = True, []     # 一括で消しにいかない (report 不良の疑い)
    if execute and (changed or vanished):
        sku_ws = get_sku_worksheet(sh)
        cell_updates = [
            {"range": f"K{u['row_index']}", "values": [[u["new_qty"]]]}
            for u in changed + vanished
        ]
        sku_ws.batch_update(cell_updates, value_input_option="USER_ENTERED")
    return {
        "checked": len(updates),
        "changed": len(changed),
        "vanished": len(vanished),
        "vanished_held": vanished_held,
        "executed": bool(execute and (changed or vanished)),
        "details": (changed + vanished)[:20],  # 先頭 20 件のみ
    }


def main():
    parser = argparse.ArgumentParser(description="eBay listing report → SKU シート K 列 同期")
    parser.add_argument("--report", required=True, help="eBay active listing report CSV path")
    parser.add_argument("--execute", action="store_true", help="本番書込 (default dry-run)")
    args = parser.parse_args()

    csv_path = Path(args.report)
    print(f"[1/2] report: {csv_path.name}")
    res = sync_from_csv(csv_path, execute=args.execute)
    print(f"[2/2] {'実書込' if args.execute else 'dry-run'}")
    print(f"  K 列乖離: {res['changed']} 件 / eBay に枠が無く K>0 のまま: {res['vanished']} 件"
          f"{' (件数が多すぎるため保留)' if res.get('vanished_held') else ''}")
    if res.get("vanished_held"):
        print(f"  ★ K=0 化を保留しました (上限 {VANISHED_SURGE_MAX} 件超)。"
              f"report が壊れていないか確認してください。")
    for u in res["details"][:10]:
        print(f"    row {u['row_index']} listing {u['listing_id']}: "
              f"K {u['current_qty']} → {u['new_qty']}"
              f"{' (' + u['reason'] + ')' if u.get('reason') else ''}")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = LOG_DIR / f"ebay_qty_sync_{'executed' if args.execute else 'dryrun'}_{ts}.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  記録: {out}")


if __name__ == "__main__":
    main()
