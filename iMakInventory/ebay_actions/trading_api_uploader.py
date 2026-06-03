"""Trading API による qty 改訂 / 取下げ (= sell_feed_uploader の Trading API 版).

HQ 2026-06-03 「監視くんを Trading API 化」 指示で新規実装。
sell_feed_uploader (= Selenium FileExchange UI) の脆さ (chromedriver DevTools 2GB
JSONDecodeError 等) を回避し、 ReviseInventoryStatus direct call で qty=0 化する。

CSV (= eBay FileExchange 形式、 既存 revise_csv_generator 出力) をそのまま受け、
各行 ItemID + Quantity を ReviseInventoryStatus に投げる。 fail-closed: 個別失敗は
記録 + 続行、 cycle 全体は通る。
"""
from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

from ebay_actions.trading_api_client import (
    revise_inventory_status,
    load_access_token,
)


def upload_csv_via_trading_api(csv_path: Path, dry_run: bool = False,
                                pacing_sec: float = 0.3) -> dict:
    """CSV (= eBay FileExchange format) を Trading API ReviseInventoryStatus で処理.

    CSV format (3 col、 既存 revise_csv_generator 出力):
      "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)","ItemID","*Quantity"
      "Revise","357008108111","0"

    Returns:
      {
        "success": bool (= 全件 OK か。 fail-closed: ng>0 でも cycle は通る、 success=False のみ),
        "total": int,
        "ok": int (= ack=Success/Warning、 既に取下げ済の safe failure も ok 扱い),
        "ng": int (= ack=Failure 系、 要 人手対処),
        "results": list,
        "decision_log": str (= jsonl path) | None,
      }
    """
    csv_path = Path(csv_path)
    rows = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            iid = (row.get("ItemID") or "").strip().strip('"')
            qty_raw = (row.get("*Quantity") or "0").strip().strip('"')
            try:
                qty = int(qty_raw)
            except (ValueError, TypeError):
                qty = 0
            if iid:
                rows.append({"item_id": iid, "quantity": qty})

    if not rows:
        return {"success": True, "total": 0, "ok": 0, "ng": 0,
                "results": [], "decision_log": None}

    if dry_run:
        print(f"  [dry-run] Trading API revise {len(rows)} 件 / CSV: {csv_path.name}")
        return {"success": True, "total": len(rows), "ok": 0, "ng": 0,
                "results": rows, "decision_log": None, "dry_run": True}

    # token 1 回 load (= refresh は call 内自動 retry)
    token = load_access_token()
    results = []
    ok_count = ng_count = 0

    print(f"  Trading API ReviseInventoryStatus ({len(rows)} 件、 pacing {pacing_sec}s)...",
          flush=True)
    for i, item in enumerate(rows, 1):
        res = revise_inventory_status(item["item_id"], item["quantity"],
                                       access_token=token)
        # eBay Trading API の 「既に取下げ済 / listing 不在」 系は safe failure (= 既に
        # 目的達成、 監視くんとしては 取下げ完了扱い)。 互換性のため sell_feed_uploader
        # 系の code 17 も同列で扱う。
        # - 231 "Item not found" (= ended/削除済 listing に Revise 投げた)
        # - 17 "listing has been deleted or you are not the seller" (= FileExchange 系の旧 code)
        # - 21916719 "ended" 系 / 21916786 "qty 改訂不可" 系も追加候補だが現状未観測のため
        #   実例検出時に追加 (= 過度の wildcard 化 回避)
        is_safe_failure = res["error_code"] in ("17", "231")
        success = res["success"] or is_safe_failure
        entry = {
            **item,
            "success": success,
            "ack": res["ack"],
            "error_code": res["error_code"],
            "error_message": res["error_message"],
            "safe_failure": is_safe_failure,
        }
        results.append(entry)
        if success:
            ok_count += 1
        else:
            ng_count += 1
        flag = "OK" if success else "NG"
        suffix = " (safe: 既取下げ済)" if is_safe_failure else ""
        print(f"  [{i}/{len(rows)}] {flag} iid={item['item_id']} qty={item['quantity']} "
              f"ack={res['ack']} err={res['error_code']}{suffix}", flush=True)
        if i < len(rows):
            time.sleep(pacing_sec)

    # decision_log
    log_dir = Path(__file__).resolve().parent.parent / "decision_log"
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"trading_api_upload_{ts}.jsonl"
    with open(log_path, "w", encoding="utf-8") as f:
        for entry in results:
            f.write(json.dumps(
                {**entry, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                 "csv_path": str(csv_path)},
                ensure_ascii=False) + "\n")

    return {
        "success": ng_count == 0,
        "total": len(rows),
        "ok": ok_count,
        "ng": ng_count,
        "results": results,
        "decision_log": str(log_path),
    }


def main():
    import argparse  # noqa: PLC0415
    parser = argparse.ArgumentParser(
        description="Trading API ReviseInventoryStatus 経由で qty 改訂")
    parser.add_argument("csv", type=Path, help="upload 対象 CSV パス")
    parser.add_argument("--dry-run", action="store_true",
                        help="dry-run mode (= API call せず件数のみ)")
    parser.add_argument("--pacing", type=float, default=0.3,
                        help="inter-call sleep sec (default 0.3)")
    args = parser.parse_args()
    result = upload_csv_via_trading_api(args.csv, dry_run=args.dry_run,
                                          pacing_sec=args.pacing)
    print(f"\n=== 結果 ===")
    print(f"  total={result['total']} ok={result['ok']} ng={result['ng']}")
    print(f"  decision_log: {result.get('decision_log')}")
    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
