"""auto_qty_zero - inventory_monitor の自動 qty=0 化 (Phase 4b エントリ).

inventory_monitor の二段確認 pass SKU を eBay に Revise upload する。
既存 iMakInventory sell_feed_uploader.py を流用 (memory: reuse_existing_proven_solution.md)。

実行モード:
  python auto_qty_zero.py                  # dry-run (= CSV 生成のみ、upload しない)
  python auto_qty_zero.py --execute        # 本番 upload + SKU シート反映 + アラート
  python auto_qty_zero.py --rollback <snapshot_id>   # snapshot から qty 復元 (安全網 #6)
  python auto_qty_zero.py --max-skus 10    # max件数キャップ変更

安全網 (Phase 4 設計書 6 機構):
  #1 dry-run 必須 (default、--execute で解除)
  #2 max件数キャップ (= 5 SKU、Takaaki さん安定後 10)
  #3 snapshot 保存 (rollback 用)
  #4 二段確認 (前 cycle 必須)
  #5 アラート発火 (= 自動 qty=0 実行件数をメール通知)
  #6 rollback コマンド
"""
from __future__ import annotations

import argparse
import csv
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

# 既存 iMakInventory の sell_feed_uploader を流用
# inventory_monitor 側の sheet_updater を先に解決させるため、
# SCRIPT_DIR を sys.path 先頭に再挿入してから iMakInventory 系を末尾追加
if str(SCRIPT_DIR) in sys.path:
    sys.path.remove(str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR))

# inventory_monitor の Phase 4a-5 で作った generator を流用 (= SCRIPT_DIR 配下)
from revise_qty_csv_generator import (  # noqa: E402
    read_sheet_needs_action, is_valid_uuid, save_qty_snapshot,
    generate_revise_csv, DEFAULT_MAX_SKUS, SNAPSHOT_DIR, CSV_OUT_DIR,
)
from main import filter_two_cycle_confirmed, _send_alert_email  # noqa: E402
from sheet_updater import (  # noqa: E402
    open_sheet, get_sku_worksheet,
    write_phase4_status, ensure_phase4_header,
)

# iMakInventory の sell_feed_uploader を末尾に追加 (= SCRIPT_DIR の解決を優先)
_inv_root = SCRIPT_DIR.parent.parent / "iMakInventory"
_ebay_actions_dir = _inv_root / "ebay_actions"
for p in (_inv_root, _ebay_actions_dir):
    if str(p) not in sys.path:
        sys.path.append(str(p))   # append: 末尾 = inventory_monitor の解決を優先


def _log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def update_sku_sheet_after_success(sh, applied_skus: list, exec_ts: str) -> int:
    """upload 成功した SKU について SKU シートに「対処日 + 対処済 TRUE」を反映.

    SKU シート列: A=対処要, B=対処済, C=対処日, ...

    Returns: 書込 cell 数
    """
    ws = get_sku_worksheet(sh)
    cell_updates = []
    for s in applied_skus:
        row_idx = s.get("row_index")
        if not row_idx:
            continue
        cell_updates.append({"range": f"B{row_idx}", "values": [[True]]})   # 対処済
        cell_updates.append({"range": f"C{row_idx}", "values": [[exec_ts]]})  # 対処日
    if cell_updates:
        ws.batch_update(cell_updates, value_input_option="USER_ENTERED")
    return len(cell_updates)


def send_qty_zero_alert(applied_skus: list, upload_result: dict, snapshot_path: str) -> bool:
    """自動 qty=0 化実行のアラートメール送信 (Phase 4 安全網 #5).

    実行 1 件でも必ず発火 (= 監視者が即気付ける、誤動作で listing 全消去を早期発見)。
    """
    n = len(applied_skus)
    subject = f"[CRITICAL] inventory_monitor: 自動 qty=0 化 {n} 件 実行"
    body_lines = [
        "=" * 50,
        "inventory_monitor: 自動 qty=0 化 実行通知",
        "=" * 50,
        f"実行件数: {n} 件",
        f"実行時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"snapshot (rollback 用): {snapshot_path}",
        "",
        f"upload 結果:",
        f"  success: {upload_result.get('success')}",
        f"  result_text: {upload_result.get('result_text', '')}",
        f"  error: {upload_result.get('error', '')}",
        "",
        f"【qty=0 化した SKU 一覧】",
    ]
    for s in applied_skus:
        body_lines.append(
            f"  - listing {s.get('listing_id', '?')} "
            f"SKU={s.get('sku_id', '')[:36]} "
            f"size={s.get('size', '')} color={s.get('color', '')}"
        )
    body_lines.append("")
    body_lines.append(f"rollback: python auto_qty_zero.py --rollback {Path(snapshot_path).stem}")
    body_lines.append("=" * 50)
    body = "\n".join(body_lines)
    return _send_alert_email(subject, body)


def rollback_from_snapshot(snapshot_id: str) -> None:
    """snapshot から qty を復元 (Phase 4 安全網 #6).

    snapshot_id = "qty_snapshot_20260514_183500" のようなファイル名 stem。
    snapshot 内の各 SKU について Revise(qty=元の値) の CSV を生成 → upload。
    """
    # snapshot path 推定
    candidates = list(SNAPSHOT_DIR.glob(f"{snapshot_id}*.json"))
    if not candidates:
        _log(f"[NG] snapshot 不在: {snapshot_id}")
        sys.exit(1)
    snap_path = candidates[0]
    _log(f"snapshot 読込: {snap_path}")
    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    skus = snap.get("skus", [])
    if not skus:
        _log("[!] snapshot に SKU なし、終了")
        return

    # rollback CSV (= qty を元の値に戻す)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rollback_csv = CSV_OUT_DIR / f"rollback_{snapshot_id}_{ts}.csv"
    with rollback_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        writer.writerow([
            "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)",
            "ItemID", "SKU", "*Quantity",
        ])
        for s in skus:
            # 元の qty。snapshot 時点で「対処要」だった = qty>0 だったはず
            orig_qty = s.get("ebay_qty") or 1
            writer.writerow(["Revise", s["listing_id"], s["sku_id"], orig_qty])
    _log(f"rollback CSV: {rollback_csv}")

    # upload
    from sell_feed_uploader import upload_one_csv  # noqa: PLC0415
    _log("rollback upload 実行...")
    res = upload_one_csv(rollback_csv, dry_run=False)
    _log(f"rollback 結果: success={res.get('success')}, result={res.get('result_text', '')[:80]}")

    # M 列を「rollback 済」に更新 (row_index は snapshot に保存してないので listing_id+sku で match)
    if res.get("success"):
        sh = open_sheet()
        # SKU シート全行読込 → snapshot 内の (listing_id, sku_id) と match で row_index 取得
        from sheet_updater import read_sku_rows  # noqa: PLC0415
        sheet_rows = read_sku_rows(sh)
        snap_key = {(s["listing_id"], s["sku_id"]): s for s in skus}
        ts_now = datetime.now().strftime("%Y-%m-%d %H:%M")
        status_updates = []
        for sheet_idx, row in enumerate(sheet_rows, start=2):
            r = list(row) + [""] * max(0, 12 - len(row))
            key = (r[3].strip(), r[5].strip())
            if key in snap_key:
                status_updates.append({
                    "row_index": sheet_idx,
                    "phase4_status": "rollback 済",
                    "tried_at": ts_now,
                    "ebay_status": res.get("result_text", "")[:80],
                })
        from sheet_updater import write_phase4_status  # noqa: PLC0415
        write_phase4_status(sh, status_updates)
        _log(f"  M 列「rollback 済」反映: {len(status_updates)} 件")


def main():
    parser = argparse.ArgumentParser(description="inventory_monitor 自動 qty=0 化 (Phase 4b)")
    parser.add_argument("--max-skus", type=int, default=DEFAULT_MAX_SKUS,
                        help=f"max件数キャップ (default: {DEFAULT_MAX_SKUS})")
    parser.add_argument("--execute", action="store_true",
                        help="本番 upload 実行 (default は dry-run)")
    parser.add_argument("--skip-two-cycle", action="store_true",
                        help="二段確認 skip (= 初回 / debug 用、通常使わない)")
    parser.add_argument("--rollback", help="snapshot ID から qty 復元")
    args = parser.parse_args()

    # rollback mode
    if args.rollback:
        rollback_from_snapshot(args.rollback)
        return

    is_dry_run = not args.execute
    _log(f"=== auto_qty_zero {'(DRY RUN)' if is_dry_run else '(EXECUTE)'} ===")

    # 1. 候補抽出 (= read_sheet_needs_action + UUID filter + 二段確認 + max件数)
    _log("[1/5] SKU シート 対処要 抽出")
    needs = read_sheet_needs_action()
    needs_uuid = [n for n in needs if is_valid_uuid(n["sku_id"])]
    _log(f"  対処要 (UUID 形式): {len(needs_uuid)} 件 / 全 {len(needs)} 件")

    _log("[2/5] 二段確認")
    if args.skip_two_cycle:
        confirmed = needs_uuid
    else:
        confirmed = filter_two_cycle_confirmed(needs_uuid)
    _log(f"  二段確認 pass: {len(confirmed)} 件")

    _log(f"[3/5] max件数キャップ {args.max_skus}")
    if len(confirmed) > args.max_skus:
        _log(f"  [!] {len(confirmed)} > {args.max_skus} → 上位 {args.max_skus} 件のみ")
        confirmed = confirmed[:args.max_skus]
    if not confirmed:
        _log("対象 0 件、終了")
        return

    # 2. snapshot 保存
    _log("[4/5] snapshot 保存 (rollback 用)")
    snap_path = save_qty_snapshot(confirmed)
    _log(f"  {snap_path}")

    # 3. CSV 生成
    csv_path = generate_revise_csv(confirmed)
    _log(f"  CSV: {csv_path}")

    # SKU シートに Phase 4 状態反映 (M/N/O 列、ヘッダー含む)
    sh = open_sheet()
    ensure_phase4_header(sh)
    tried_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    if is_dry_run:
        # dry-run: 候補リストを「dry-run 候補」状態で M 列に記録
        status_updates = [
            {"row_index": s.get("row_index"),
             "phase4_status": "dry-run 候補",
             "tried_at": tried_at,
             "ebay_status": ""}
            for s in confirmed if s.get("row_index")
        ]
        write_phase4_status(sh, status_updates)
        _log(f"  SKU シート M/N 列に「dry-run 候補」反映: {len(status_updates)} 件")
        _log("[5/5] dry-run、upload スキップ")
        _log(f"  実 upload するには --execute を付けて再実行")
        return

    # 4. upload (本番)
    _log("[5/5] upload 実行")
    from sell_feed_uploader import upload_one_csv  # noqa: PLC0415
    upload_result = upload_one_csv(csv_path, dry_run=False)
    _log(f"  upload 結果: success={upload_result.get('success')}")
    _log(f"  result_text: {upload_result.get('result_text', '')[:120]}")

    # 5. 成功なら SKU シート更新 (B/C 列 + M/N/O 列)
    success = bool(upload_result.get("success"))
    exec_ts = datetime.now().strftime("%Y/%m/%d %H:%M")
    if success:
        n_cells = update_sku_sheet_after_success(sh, confirmed, exec_ts)
        _log(f"  SKU シート反映 (B/C 列): {n_cells} cells")

    # Phase 4 状態 (M/N/O 列) は成功失敗問わず反映
    ebay_status_text = upload_result.get("result_text", "")[:80]
    status_label = "Submit OK" if success else f"Submit 失敗 ({upload_result.get('error', '')[:40]})"
    status_updates = [
        {"row_index": s.get("row_index"),
         "phase4_status": status_label,
         "tried_at": tried_at,
         "ebay_status": ebay_status_text}
        for s in confirmed if s.get("row_index")
    ]
    write_phase4_status(sh, status_updates)
    _log(f"  SKU シート反映 (M/N/O 列): {len(status_updates)} 件")

    # 6. アラート発火 (= 必須、成功失敗問わず)
    sent = send_qty_zero_alert(confirmed, upload_result, str(snap_path))
    if sent:
        _log("  [mail] アラートメール送信完了")


if __name__ == "__main__":
    main()
