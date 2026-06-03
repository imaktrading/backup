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
    revise_inventory_status_variation,
    load_access_token,
)


def _parse_variation_specifics(details_str: str) -> dict:
    """RelationshipDetails 'Sizes=US M(JP L)|Color=BL' → {'Sizes': 'US M(JP L)', 'Color': 'BL'}."""
    out = {}
    for part in (details_str or "").split("|"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _parse_csv_rows(csv_path: Path) -> list:
    """CSV 自動判定: 3 col (single) or 6 col (variation) 両対応.

    Returns: list of dict
      single: {"kind": "single", "item_id": str, "quantity": int}
      variation: {"kind": "variation", "item_id": str, "specifics": dict,
                  "quantity": int, "start_price": float|None}
    """
    rows = []
    parent_iid = None
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        # 6 col CSV か判定 (= Relationship 列 存在)
        is_variation_csv = "Relationship" in (reader.fieldnames or [])
        for row in reader:
            iid = (row.get("ItemID") or "").strip().strip('"')
            qty_raw = (row.get("*Quantity") or "").strip().strip('"')
            relationship = (row.get("Relationship") or "").strip().strip('"') if is_variation_csv else ""

            if not is_variation_csv:
                # 3 col (single listing)
                if iid:
                    try:
                        qty = int(qty_raw or "0")
                    except (ValueError, TypeError):
                        qty = 0
                    rows.append({"kind": "single", "item_id": iid, "quantity": qty})
                continue

            # 6 col (variation)
            if iid and not relationship:
                # 親行: ItemID + variation structure 定義。 親 qty 指定があれば single 扱い
                parent_iid = iid
                if qty_raw:
                    try:
                        qty = int(qty_raw)
                    except (ValueError, TypeError):
                        qty = 0
                    rows.append({"kind": "single", "item_id": iid, "quantity": qty})
            elif relationship == "Variation" and parent_iid:
                # 子行: variation 単位 qty 改訂
                details = (row.get("RelationshipDetails") or "").strip().strip('"')
                specifics = _parse_variation_specifics(details)
                try:
                    qty = int(qty_raw or "0")
                except (ValueError, TypeError):
                    qty = 0
                price_raw = (row.get("*StartPrice") or "").strip().strip('"')
                try:
                    price = float(price_raw) if price_raw else None
                except (ValueError, TypeError):
                    price = None
                if specifics:
                    rows.append({
                        "kind": "variation", "item_id": parent_iid,
                        "specifics": specifics, "quantity": qty, "start_price": price,
                    })
    return rows


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
    rows = _parse_csv_rows(csv_path)

    if not rows:
        return {"success": True, "total": 0, "ok": 0, "ng": 0,
                "results": [], "decision_log": None}

    if dry_run:
        kinds = {}
        for r in rows:
            kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
        print(f"  [dry-run] Trading API revise {len(rows)} 件 / CSV: {csv_path.name} "
              f"({kinds})")
        return {"success": True, "total": len(rows), "ok": 0, "ng": 0,
                "results": rows, "decision_log": None, "dry_run": True}

    # token 1 回 load (= refresh は call 内自動 retry)
    token = load_access_token()
    results = []
    ok_count = ng_count = 0

    def _call_one(item):
        if item["kind"] == "variation":
            return revise_inventory_status_variation(
                item["item_id"], item["specifics"], item["quantity"],
                start_price=item.get("start_price"), access_token=token)
        return revise_inventory_status(item["item_id"], item["quantity"],
                                        access_token=token)

    def _is_transient_failure(res: dict) -> bool:
        """DNS / ConnectionError / Timeout 系は 偶発失敗 → 同 cycle 内 retry 対象."""
        if res["success"] or res.get("ack") is not None:
            return False
        msg = (res.get("error_message") or "")
        return any(kw in msg for kw in (
            "ConnectionError", "Timeout", "NameResolutionError",
            "getaddrinfo failed", "Max retries exceeded",
        ))

    # run_daily.py の _parse_qty_output で 「CSV 行数」 文言を regex match させるため
    # 件数を 明示出力 (= sell_feed_uploader stdout 互換)。
    # 「listing」 keyword で single CSV 認識、 含まれない場合は variation 集計に倒す
    has_variation = any(r["kind"] == "variation" for r in rows)
    kind_label = "variation" if has_variation else "single listing"
    print(f"  Trading API ReviseInventoryStatus ({kind_label}): CSV 行数 {len(rows)} 件 "
          f"(pacing {pacing_sec}s)...", flush=True)
    for i, item in enumerate(rows, 1):
        if item["kind"] == "variation":
            label = f"iid={item['item_id']} var={item['specifics']} qty={item['quantity']}"
        else:
            label = f"iid={item['item_id']} qty={item['quantity']}"
        # 1 回目 call
        res = _call_one(item)
        # DNS / ConnectionError 系は 1 回だけ retry (= 偶発失敗救済、 同 cycle 内)
        if _is_transient_failure(res):
            print(f"  [{i}/{len(rows)}] transient fail (DNS/Timeout) → 2s sleep + retry",
                  flush=True)
            time.sleep(2.0)
            res = _call_one(item)
        # eBay Trading API の 「既に取下げ済 / listing 不在」 系は safe failure (= 既に
        # 目的達成、 監視くんとしては 取下げ完了扱い)。 互換性のため sell_feed_uploader
        # 系の code 17 も同列で扱う。
        # - 231 "Item not found" (= ended/削除済 listing に Revise 投げた)
        # - 17 "listing has been deleted or you are not the seller" (= FileExchange 系の旧 code)
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
        print(f"  [{i}/{len(rows)}] {flag} {label} ack={res['ack']} "
              f"err={res['error_code']}{suffix}", flush=True)
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

    # sell_feed_uploader 互換 field (= 既存 cycle log / inventory_monitor から読まれる)
    success_count = sum(1 for r in results if r["ack"] == "Success")
    warning_count = sum(1 for r in results if r["ack"] == "Warning")
    safe_failure_count = sum(1 for r in results if r.get("safe_failure"))
    action_needed_failure = sum(
        1 for r in results
        if r["ack"] == "Failure" and not r.get("safe_failure")
    )
    transient_failure = sum(
        1 for r in results
        if r.get("ack") is None and not r.get("safe_failure") and not r["success"]
    )
    # 旧 sell_feed_uploader 互換: 「Warning N + safe Failure M + action-needed Failure J」
    # + Trading API 拡張: Success N (= 成功) + Transient K (= DNS/Timeout 系)
    result_text = (f"Success {success_count} + Warning {warning_count} "
                   f"+ safe Failure {safe_failure_count} "
                   f"+ action-needed Failure {action_needed_failure} "
                   f"+ Transient {transient_failure}")
    failure_details = [
        {"item_id": r["item_id"], "error_code": r["error_code"],
         "error_message": r["error_message"], "safe": r.get("safe_failure", False)}
        for r in results
        if r["ack"] == "Failure" or not r["success"]
    ]
    return {
        "success": ng_count == 0,
        "total": len(rows),
        "ok": ok_count,
        "ng": ng_count,
        "results": results,
        "decision_log": str(log_path),
        # sell_feed_uploader 互換
        "result_text": result_text,
        "warning": warning_count,
        "safe_failure": safe_failure_count,
        "action_needed_failure": action_needed_failure,
        "failure_details": failure_details,
        "csv_lines": len(rows),
        "log_path": str(log_path),
        # 旧 path で参照されてた field (= 既存 logic 互換)
        "popup_text": "",
        "page_url": "",
        "screenshot": None,
        "error": None if ng_count == 0 else f"Trading API: {ng_count}/{len(rows)} failures",
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
