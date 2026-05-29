"""auto_qty_zero - inventory_monitor の自動 qty 変更 (Phase 4b エントリ).

inventory_monitor の二段確認 pass SKU を eBay に Revise upload する。
既存 iMakInventory sell_feed_uploader.py を流用 (memory: reuse_existing_proven_solution.md)。

mode:
  --mode=zero    (default) 仕入元 ✕ × eBay Qty>0 → qty=0 化 (出品停止相当)
  --mode=restore           仕入元 ◎ × eBay Qty=0 → qty=1 復活 (無在庫運用前提)

実行モード:
  python auto_qty_zero.py                              # dry-run (zero mode)
  python auto_qty_zero.py --execute                    # 本番 upload (zero mode)
  python auto_qty_zero.py --mode=restore               # dry-run (restore mode)
  python auto_qty_zero.py --mode=restore --execute     # 本番 upload (restore mode)
  python auto_qty_zero.py --rollback <snapshot_id>     # snapshot から qty 復元

安全網 (Phase 4 設計書 6 機構): どちらの mode でも適用。
  #1 dry-run 必須 (default、--execute で解除)
  #2 max件数キャップ (= 5 SKU、Takaaki さん安定後 10)
  #3 snapshot 保存 (rollback 用)
  #4 二段確認 (前 cycle 必須)
  #5 アラート発火 (= 自動実行件数をメール通知)
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
    read_sheet_needs_action, read_sheet_restore_target,
    read_sheet_listing_zero, read_sheet_listing_restore,
    generate_listing_revise_csv,
    is_valid_uuid, save_qty_snapshot,
    generate_revise_csv, DEFAULT_MAX_SKUS, SNAPSHOT_DIR, CSV_OUT_DIR,
)
from main import (  # noqa: E402
    filter_two_cycle_confirmed,
    filter_restore_two_cycle_confirmed,
    _send_alert_email,
)
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


def update_sku_sheet_after_success(sh, applied_skus: list, exec_ts: str,
                                   new_qty: int = 0) -> int:
    """upload 成功した SKU について SKU シートに反映.

    更新列:
      A (対処要) = FALSE  ← 処理済 = もう対処不要
      B (対処済) = TRUE
      C (対処日) = exec_ts
      K (eBay 現Qty) = new_qty   ← upload で eBay 側 qty 変わるので即時反映

    Returns: 書込 cell 数
    """
    ws = get_sku_worksheet(sh)
    cell_updates = []
    for s in applied_skus:
        row_idx = s.get("row_index")
        if not row_idx:
            continue
        cell_updates.append({"range": f"A{row_idx}", "values": [[False]]})
        cell_updates.append({"range": f"B{row_idx}", "values": [[True]]})
        cell_updates.append({"range": f"C{row_idx}", "values": [[exec_ts]]})
        cell_updates.append({"range": f"K{row_idx}", "values": [[new_qty]]})
    if cell_updates:
        ws.batch_update(cell_updates, value_input_option="USER_ENTERED")
    return len(cell_updates)


def send_qty_change_alert(applied_skus: list, upload_result: dict, snapshot_path: str,
                          mode: str, target_qty: int) -> bool:
    """自動 qty 変更実行のアラートメール送信 (Phase 4 安全網 #5).

    mode は "zero" / "restore"。実行 1 件でも必ず発火 (= 監視者が即気付ける)。
    """
    n = len(applied_skus)
    action_label = "qty=0 化" if mode == "zero" else f"qty={target_qty} 復活"
    subject = f"[CRITICAL] inventory_monitor: 自動 {action_label} {n} 件 実行"
    body_lines = [
        "=" * 50,
        f"inventory_monitor: 自動 {action_label} 実行通知",
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
        f"【{action_label} した SKU 一覧】",
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


# 後方互換 alias (= 旧 import を壊さないため)
def send_qty_zero_alert(applied_skus: list, upload_result: dict, snapshot_path: str) -> bool:
    return send_qty_change_alert(applied_skus, upload_result, snapshot_path, mode="zero", target_qty=0)


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
    parser = argparse.ArgumentParser(description="inventory_monitor 自動 qty 変更 (Phase 4b)")
    parser.add_argument("--mode", choices=["zero", "restore"], default="zero",
                        help="zero=qty=0 化 (default), restore=qty 復活")
    parser.add_argument("--restore-qty", type=int, default=1,
                        help="restore mode の qty 値 (default: 1、無在庫運用前提)")
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
    mode = args.mode
    target_qty = 0 if mode == "zero" else args.restore_qty
    action_label = "qty=0 化" if mode == "zero" else f"qty={target_qty} 復活"
    _log(f"=== auto_qty_zero ({mode.upper()} {'DRY RUN' if is_dry_run else 'EXECUTE'}) ===")

    # 1. 候補抽出 (mode 別)
    _log(f"[1/5] SKU シート {action_label} 候補抽出")
    if mode == "zero":
        candidates = read_sheet_needs_action()
        filter_fn = filter_two_cycle_confirmed
    else:
        candidates = read_sheet_restore_target()
        filter_fn = filter_restore_two_cycle_confirmed
    candidates_uuid = [n for n in candidates if is_valid_uuid(n["sku_id"])]
    _log(f"  候補 (UUID 形式): {len(candidates_uuid)} 件 / 全 {len(candidates)} 件")

    _log("[2/5] 二段確認")
    if args.skip_two_cycle:
        confirmed = candidates_uuid
    else:
        confirmed = filter_fn(candidates_uuid)
    _log(f"  二段確認 pass: {len(confirmed)} 件")

    _log(f"[3/5] max件数キャップ {args.max_skus} (0 = 無制限)")
    if args.max_skus > 0 and len(confirmed) > args.max_skus:
        _log(f"  [!] {len(confirmed)} > {args.max_skus} → 上位 {args.max_skus} 件のみ")
        confirmed = confirmed[:args.max_skus]
    else:
        _log(f"  全 {len(confirmed)} 件処理")
    if not confirmed:
        _log("variation 対象 0 件 → 単独 listing 処理へ")
        # 仮 sh 用に open
        from sheet_updater import open_sheet as _open  # noqa: PLC0415
        _sh = _open()
        _process_single_listings(_sh, mode, target_qty, args.max_skus)
        return

    # 2. snapshot 保存
    _log("[4/5] snapshot 保存 (rollback 用)")
    snap_path = save_qty_snapshot(confirmed, mode=mode)
    _log(f"  {snap_path}")

    # 3. CSV 生成
    csv_path = generate_revise_csv(confirmed, target_qty=target_qty, mode=mode)
    _log(f"  CSV: {csv_path}")

    # SKU シートに Phase 4 状態反映 (M/N/O 列、ヘッダー含む)
    sh = open_sheet()
    ensure_phase4_header(sh)
    tried_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    dryrun_label = "dry-run 候補" if mode == "zero" else "dry-run 復活候補"
    if is_dry_run:
        status_updates = [
            {"row_index": s.get("row_index"),
             "phase4_status": dryrun_label,
             "tried_at": tried_at,
             "ebay_status": ""}
            for s in confirmed if s.get("row_index")
        ]
        write_phase4_status(sh, status_updates)
        _log(f"  SKU シート M/N 列に「{dryrun_label}」反映: {len(status_updates)} 件")
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
        n_cells = update_sku_sheet_after_success(sh, confirmed, exec_ts, new_qty=target_qty)
        _log(f"  SKU シート反映 (B/C/K 列): {n_cells} cells")

    # Phase 4 状態 (M/N/O 列) は成功失敗問わず反映
    ebay_status_text = upload_result.get("result_text", "")[:80]
    ok_label = "Submit OK" if mode == "zero" else "qty 復活 Submit OK"
    ng_label_prefix = "Submit 失敗" if mode == "zero" else "qty 復活 Submit 失敗"
    status_label = ok_label if success else f"{ng_label_prefix} ({upload_result.get('error', '')[:40]})"
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
    sent = send_qty_change_alert(confirmed, upload_result, str(snap_path),
                                 mode=mode, target_qty=target_qty)
    if sent:
        _log("  [mail] アラートメール送信完了")

    # 7. 単独 listing (= variation Revise 対象外) も同 mode で処理 (3 列 format)
    _process_single_listings(sh, mode, target_qty, args.max_skus)


def _process_single_listings(sh, mode: str, target_qty: int, max_skus: int) -> None:
    """単独 listing (= F 非 UUID + main_active) を listing level Revise で処理."""
    if mode == "zero":
        items = read_sheet_listing_zero()
    else:
        items = read_sheet_listing_restore()
    if not items:
        return
    # 同 listing 重複は除外
    by_lid = {}
    for it in items:
        by_lid.setdefault(it["listing_id"], it)
    deduped = list(by_lid.values())
    if max_skus > 0 and len(deduped) > max_skus:
        deduped = deduped[:max_skus]

    _log(f"[単独 listing {mode}] 対象 {len(deduped)} listing")
    snap = save_qty_snapshot(deduped, mode=f"{mode}_listing")
    _log(f"  snapshot: {snap}")
    csv_path = generate_listing_revise_csv(deduped, target_qty=target_qty, mode=mode)
    _log(f"  CSV: {csv_path}")

    from sell_feed_uploader import upload_one_csv  # noqa: PLC0415
    res = upload_one_csv(csv_path, dry_run=False)
    _log(f"  upload: success={res.get('success')} result={res.get('result_text', '')[:80]}")

    success = bool(res.get("success"))
    exec_ts = datetime.now().strftime("%Y/%m/%d %H:%M")
    if success:
        # SKU シート全行から該当 listing の全行を update (= 単独 listing は同 listing 行が 1+ 個)
        # B/C/K 更新は listing_id ベースで全行に反映
        ws = get_sku_worksheet(sh)
        from sheet_updater import read_sku_rows  # noqa: PLC0415
        rows = read_sku_rows(sh)
        target_lids = {it["listing_id"] for it in deduped}
        cell_updates = []
        for sheet_idx, r in enumerate(rows, start=2):
            r = list(r) + [""] * max(0, 12 - len(r))
            if r[3].strip() not in target_lids: continue
            cell_updates.append({"range": f"A{sheet_idx}", "values": [[False]]})
            cell_updates.append({"range": f"B{sheet_idx}", "values": [[True]]})
            cell_updates.append({"range": f"C{sheet_idx}", "values": [[exec_ts]]})
            cell_updates.append({"range": f"K{sheet_idx}", "values": [[target_qty]]})
        if cell_updates:
            ws.batch_update(cell_updates, value_input_option="USER_ENTERED")
            _log(f"  SKU シート反映 (A/B/C/K): {len(cell_updates)} cells")
    send_qty_change_alert(deduped, res, str(snap), mode=f"{mode}_listing", target_qty=target_qty)


if __name__ == "__main__":
    main()
