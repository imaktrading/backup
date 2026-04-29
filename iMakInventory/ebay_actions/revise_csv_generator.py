"""revise_csv_generator - HIGH/LOW スプシの D="○" 行から FileExchange Revise CSV を生成 (Phase 3).

入力:
  HIGH/LOW スプシの「商品管理シート」(gid=851100680) の D="○" or D="〇" 行
  → 各行の B (itemID) が eBay 取り下げ対象

出力:
  csv_output/revise_<sheet_label>_<ts>.csv  (FileExchange 形式 / Quantity=0)

CSV 形式 (トラバホ delete*.csv 互換):
  *Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8),ItemID,*Quantity
  Revise,356802747021,0
  ...

安全装置 (Takaaki さん確定 2026-04-29、戦略修正版):
  原則: 「取り下げ漏れ (false negative) > 過剰取り下げ (false positive)」
        Defect Rate 直撃→永久 BAN リスク回避のため、漏れ絶対 NG。
        過剰取り下げは機会損失だが再出品で復旧可能。

  - per-run cap (= per-CSV): 100 件 (4時間サイクルで通常 6-12件想定の十分な余裕)
                             100件超は構造異常 (false positive 大量発生疑い) → manual approval
                             --force で override 可
  - daily cap: なし (取り下げ優先、寝てる間も止めない)
  - dedup: 同 itemID 重複は同一 run 内で除外 (HIGH/LOW 両方に出ている等)
  - Q1 統一: D="○" は ツール ○ / 人手 ○ 区別なく全て eBay 取り下げ対象
  - 片方向 (Phase 3 範囲): ○ → 取り下げ CSV → 終了。復活フローは Phase 4+ で検討

state 永続化 (運用記録のみ、cap 判定には使わない):
  decision_log/revise_state.json:
    {"date": "2026-04-29", "count": 5, "history": [...]}

使用例:
  python -m ebay_actions.revise_csv_generator --dry-run
  python -m ebay_actions.revise_csv_generator --sheet both
  python -m ebay_actions.revise_csv_generator --force  # 100件超を強制承認
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Optional

# 親ディレクトリ (iMakInventory) を sys.path へ
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sheet_updater import (  # noqa: E402
    HIGH_SHEET_ID,
    LOW_SHEET_ID,
    LISTINGS_GID,
    open_sheet_by_id,
    get_listings_worksheet,
    read_listings_rows,
)


# ============================================================================
# pending_revise queue (Phase 2 monitor_listings との連携)
# ============================================================================
# monitor_listings が delta="newly_sold" を検知した行のみキューに append される。
# 既存〇 (手動 / 過去の Inventory 処理結果) はキューに入らない → Phase 3 で取り込まない。


# ============================================================================
# 設定
# ============================================================================
CSV_OUTPUT_DIR = ROOT_DIR / "csv_output"
DECISION_LOG_DIR = ROOT_DIR / "decision_log"
STATE_FILE = DECISION_LOG_DIR / "revise_state.json"
PENDING_REVISE_FILE = DECISION_LOG_DIR / "pending_revise.jsonl"
PROCESSED_REVISE_FILE = DECISION_LOG_DIR / "processed_revise.jsonl"

# 売り切れマーカー (○ U+25CB / 〇 U+3007 両対応)
SOLD_MARKERS = ("○", "〇")

# FileExchange 標準ヘッダ (トラバホ delete*.csv と同一)
CSV_HEADER = [
    "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)",
    "ItemID",
    "*Quantity",
]
CSV_ACTION = "Revise"
CSV_QUANTITY = "0"

# Cap defaults (Takaaki さん確定 2026-04-29、戦略修正版: 漏れ NG / 過剰 OK)
DEFAULT_MAX_PER_RUN = 100  # 1回 (4時間サイクル) の上限
                            # 通常想定 6-12 件、超過は構造異常 → manual approval (--force)


# ============================================================================
# 売切候補の収集
# ============================================================================
def collect_sold_listings(sheet_label: str, sheet_id: str) -> list:
    """1 spreadsheet から D="○" 行を抽出.

    Returns: [
        {
            "sheet_label": "HIGH" / "LOW",
            "row_index":   2,
            "item_id":     "356802747021",
            "url":         "https://jp.mercari.com/item/...",
            "title":       "...",
            "current_sold": "○",
            "checked_at":  "2026/04/29 17:00:00",
        },
        ...
    ]
    """
    sh = open_sheet_by_id(sheet_id)
    ws = get_listings_worksheet(sh, gid=LISTINGS_GID)
    rows = read_listings_rows(ws, only_with_url=True)

    sold = []
    for r in rows:
        mark = r.get("current_sold", "")
        if mark not in SOLD_MARKERS:
            continue
        item_id = r.get("item_id", "").strip()
        if not item_id:
            # itemID 不在 → eBay 取り下げ対象にできない (skip)
            continue
        sold.append({
            "sheet_label": sheet_label,
            "row_index":   r["row_index"],
            "item_id":     item_id,
            "url":         r.get("url", ""),
            "title":       r.get("title", ""),
            "current_sold": mark,
            "checked_at":  r.get("checked_at", ""),
        })
    return sold


# ============================================================================
# pending_revise queue (Q2 Takaaki さん確定: 「今回付与した行のみ」)
# ============================================================================
def read_pending_queue() -> list:
    """pending_revise.jsonl を読込み、entries のリストを返す.

    各 entry: {ts, sheet, row_index, url, item_id, title, supplier, raw_status, dry_run}
    """
    if not PENDING_REVISE_FILE.exists():
        return []
    entries = []
    with open(PENDING_REVISE_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def collect_from_pending_queue(
    sheet_filter: str = "both",
    verify_against_sheet: bool = True,
) -> tuple[list, list]:
    """pending_revise.jsonl から取り下げ候補を収集.

    Args:
        sheet_filter: "high" / "low" / "both"
        verify_against_sheet: True の場合、スプシ側で D が依然 "○" の行のみ採用
                             (Phase 2 → Phase 3 間に手動取消された行を除外)

    Returns: (candidates, skipped_pending)
        candidates:      Phase 3 で取り下げる対象
        skipped_pending: queue にあったが verify で落ちた、または filter 外
    """
    queue = read_pending_queue()
    if not queue:
        return [], []

    # スプシ照合用に現状の D="○" 行を取得
    sheet_state: dict[tuple[str, int], dict] = {}
    if verify_against_sheet:
        targets = []
        if sheet_filter in ("high", "both"):
            targets.append(("HIGH", HIGH_SHEET_ID))
        if sheet_filter in ("low", "both"):
            targets.append(("LOW", LOW_SHEET_ID))
        for label, sid in targets:
            try:
                sold = collect_sold_listings(label, sid)
                for s in sold:
                    sheet_state[(label, s["row_index"])] = s
            except Exception as e:
                print(f"  ⚠️ [{label}] 現状取得失敗: {type(e).__name__}: {e}")
                # 照合失敗 → 安全側で全件 skip (誤取り下げ防止)
                return [], queue

    candidates = []
    skipped = []
    for q in queue:
        label = q.get("sheet", "")
        # filter
        if sheet_filter == "high" and label != "HIGH":
            skipped.append({**q, "skip_reason": "filter_high"})
            continue
        if sheet_filter == "low" and label != "LOW":
            skipped.append({**q, "skip_reason": "filter_low"})
            continue

        # verify against sheet
        if verify_against_sheet:
            key = (label, q.get("row_index", -1))
            cur = sheet_state.get(key)
            if cur is None or cur["item_id"] != q.get("item_id", ""):
                # スプシで〇が外れている / itemID が変わっている → skip (安全側)
                skipped.append({**q, "skip_reason": "no_longer_sold_or_id_changed"})
                continue
            # スプシの最新値で上書き (title 等を最新に)
            candidates.append({
                "sheet_label": label,
                "row_index":   cur["row_index"],
                "item_id":     cur["item_id"],
                "url":         cur.get("url", q.get("url", "")),
                "title":       cur.get("title", q.get("title", "")),
                "current_sold": cur.get("current_sold", "○"),
                "checked_at":  cur.get("checked_at", ""),
                "queue_ts":    q.get("ts", ""),
            })
        else:
            candidates.append({
                "sheet_label": label,
                "row_index":   q.get("row_index", -1),
                "item_id":     q.get("item_id", ""),
                "url":         q.get("url", ""),
                "title":       q.get("title", ""),
                "current_sold": "○",
                "checked_at":  "",
                "queue_ts":    q.get("ts", ""),
            })
    return candidates, skipped


def drain_pending_queue(consumed_item_ids: list[str]) -> int:
    """processed として archive し、pending から該当 entry を除去.

    consumed_item_ids: 今回 CSV に含めた itemID のリスト

    pending_revise.jsonl の中身を再書込 (consumed を除外)、
    processed_revise.jsonl に append.

    Returns: 移動した件数
    """
    if not PENDING_REVISE_FILE.exists():
        return 0
    if not consumed_item_ids:
        return 0

    consumed = set(consumed_item_ids)
    moved = 0
    keep = []
    with open(PENDING_REVISE_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                # 壊れた行は維持 (debug 可能にする)
                keep.append(line)
                continue
            if entry.get("item_id") in consumed:
                # archive
                entry["consumed_at"] = datetime.now().isoformat(timespec="seconds")
                with open(PROCESSED_REVISE_FILE, "a", encoding="utf-8") as af:
                    af.write(json.dumps(entry, ensure_ascii=False) + "\n")
                moved += 1
            else:
                keep.append(line)

    PENDING_REVISE_FILE.write_text(
        ("\n".join(keep) + "\n") if keep else "",
        encoding="utf-8",
    )
    return moved


# ============================================================================
# 状態管理 (日次 cap 用)
# ============================================================================
def load_state() -> dict:
    """revise_state.json から本日分の状態を読込.
    日付が変わっていたらリセットして返す.
    """
    today_str = date.today().isoformat()
    if not STATE_FILE.exists():
        return {"date": today_str, "count": 0, "history": []}

    try:
        st = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"date": today_str, "count": 0, "history": []}

    # 日付チェック (跨いでいたらリセット)
    if st.get("date") != today_str:
        return {"date": today_str, "count": 0, "history": []}
    return st


def save_state(state: dict) -> None:
    DECISION_LOG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ============================================================================
# Cap 適用
# ============================================================================
def apply_caps(
    candidates: list,
    max_per_run: int,
    force: bool = False,
) -> tuple[list, list, str]:
    """per-run cap (1 CSV = 4時間サイクル) と dedup を適用.

    戦略 (Takaaki さん確定 2026-04-29):
      - 漏れ NG > 過剰 OK (Defect Rate 直撃回避)
      - 日次 cap なし (寝てる間も止めない)
      - 1 回 100件超 → 構造異常疑い、manual approval (--force) で override

    Returns: (allowed, deferred, reason)
        allowed:  今回 CSV に含める対象
        deferred: 今回 skip (per-run cap 超過 or 重複)
        reason:   "OK" / "PER_RUN_CAP_EXCEEDED" / "FORCED"
    """
    # dedup (同 itemID 重複 — HIGH/LOW 両方に出現等)
    seen = set()
    unique = []
    duplicate_skipped = []
    for c in candidates:
        iid = c["item_id"]
        if iid in seen:
            duplicate_skipped.append({**c, "skip_reason": "duplicate"})
            continue
        seen.add(iid)
        unique.append(c)

    if len(unique) > max_per_run and not force:
        # 構造異常疑い → 全件保留して manual approval を仰ぐ
        deferred = [{**c, "skip_reason": "per_run_cap_exceeded_needs_approval"} for c in unique]
        deferred.extend(duplicate_skipped)
        return [], deferred, "PER_RUN_CAP_EXCEEDED"

    if force and len(unique) > max_per_run:
        # 強制実行: 全件 allowed
        allowed = unique
        deferred = list(duplicate_skipped)
        return allowed, deferred, "FORCED"

    # 通常運用: 件数 cap 以内
    allowed = unique
    deferred = list(duplicate_skipped)
    return allowed, deferred, "OK"


# ============================================================================
# CSV 出力
# ============================================================================
def write_revise_csv(allowed: list, output_path: Path) -> int:
    """FileExchange 形式の Revise CSV を書出.

    Returns: 行数 (header 含まず)
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(CSV_HEADER)
        for c in allowed:
            writer.writerow([CSV_ACTION, c["item_id"], CSV_QUANTITY])
    return len(allowed)


# ============================================================================
# decision_log
# ============================================================================
def append_decision_log(
    sheet_labels: list,
    candidates: list,
    allowed: list,
    deferred: list,
    csv_path: Optional[Path],
    reason: str,
    dry_run: bool,
) -> Path:
    DECISION_LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = DECISION_LOG_DIR / f"revise_{ts}.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for c in allowed:
            f.write(json.dumps({
                "ts":           datetime.now().isoformat(timespec="seconds"),
                "phase":        "phase3_revise_csv",
                "decision":     "INCLUDED",
                "csv_path":     str(csv_path) if csv_path else None,
                "dry_run":      dry_run,
                "reason":       reason,
                "sheets":       sheet_labels,
                **c,
            }, ensure_ascii=False) + "\n")
        for c in deferred:
            f.write(json.dumps({
                "ts":           datetime.now().isoformat(timespec="seconds"),
                "phase":        "phase3_revise_csv",
                "decision":     "DEFERRED",
                "csv_path":     str(csv_path) if csv_path else None,
                "dry_run":      dry_run,
                "reason":       reason,
                "sheets":       sheet_labels,
                **c,
            }, ensure_ascii=False) + "\n")
    return path


# ============================================================================
# main
# ============================================================================
def run(
    sheet: str = "both",
    mode: str = "pending",
    max_per_run: int = DEFAULT_MAX_PER_RUN,
    force: bool = False,
    dry_run: bool = False,
) -> dict:
    targets = []
    if sheet in ("high", "both"):
        targets.append(("HIGH", HIGH_SHEET_ID))
    if sheet in ("low", "both"):
        targets.append(("LOW", LOW_SHEET_ID))

    print(f"=== Revise CSV 生成 (sheet={sheet}, mode={mode}, dry_run={dry_run}, "
          f"force={force}, max_per_run={max_per_run}) ===")

    candidates = []
    pending_skipped = []
    if mode == "pending":
        # Q2: Phase 2 で「今回新規〇付与した行のみ」キューから取る
        candidates, pending_skipped = collect_from_pending_queue(
            sheet_filter=sheet, verify_against_sheet=True,
        )
        print(f"  pending queue から: {len(candidates)} 件 (skip {len(pending_skipped)} 件)")
    elif mode == "all":
        # 全 D="○" 行を対象 (緊急時、過去未処理の一括処理用)
        for label, sid in targets:
            try:
                sold = collect_sold_listings(label, sid)
                print(f"  [{label}] D=○ 全件 (mode=all): {len(sold)} 件")
                candidates.extend(sold)
            except Exception as e:
                print(f"  ❌ [{label}] 読込失敗: {type(e).__name__}: {e}")
    else:
        raise ValueError(f"unsupported mode: {mode}")

    print(f"  合計候補: {len(candidates)} 件 (dedup 前)")

    # state load (運用記録のみ、cap 判定には使わない)
    state = load_state()
    print(f"  本日 ({state['date']}) すでに送信済: {state['count']} (記録のみ、cap 判定なし)")

    # cap 適用 (per-run cap = 100 のみ、daily cap なし)
    allowed, deferred, reason = apply_caps(candidates, max_per_run, force=force)
    print(f"  許可: {len(allowed)} / 保留: {len(deferred)} / reason: {reason}")

    if reason == "PER_RUN_CAP_EXCEEDED":
        print(f"  ⚠️  per-run cap ({max_per_run}件) 超過。構造異常疑い。")
        print(f"      --force で override 可能 (manual approval)。確認なしの実行は推奨しない。")

    # CSV 出力
    csv_path = None
    if not dry_run and allowed:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        sheet_part = sheet.upper() if sheet != "both" else "BOTH"
        csv_path = CSV_OUTPUT_DIR / f"revise_{sheet_part}_{ts}.csv"
        n = write_revise_csv(allowed, csv_path)
        print(f"  ✅ CSV 出力: {csv_path} ({n} 行)")

        # state update (記録のみ)
        state["count"] += n
        state["history"].append({
            "ts":       datetime.now().isoformat(timespec="seconds"),
            "csv":      str(csv_path),
            "count":    n,
            "item_ids": [c["item_id"] for c in allowed],
            "reason":   reason,
        })
        save_state(state)
        print(f"  state 更新 (運用記録): 本日合計 {state['count']}")

        # mode=pending: 消費した entries を queue から drain → processed へ archive
        if mode == "pending" and allowed:
            consumed_ids = [c["item_id"] for c in allowed]
            moved = drain_pending_queue(consumed_ids)
            print(f"  pending → processed archive: {moved} 件")
    elif dry_run and allowed:
        print(f"  [DRY RUN] CSV 出力 skip ({len(allowed)} 行が出力対象だった)")
        print(f"  サンプル先頭 5 件:")
        for c in allowed[:5]:
            print(f"    {c['sheet_label']} row{c['row_index']}: {CSV_ACTION},{c['item_id']},{CSV_QUANTITY} ({c['title'][:30]})")

    # decision_log
    log_path = append_decision_log(
        sheet_labels=[t[0] for t in targets],
        candidates=candidates,
        allowed=allowed,
        deferred=deferred,
        csv_path=csv_path,
        reason=reason,
        dry_run=dry_run,
    )
    print(f"  decision_log: {log_path}")

    return {
        "candidates":  len(candidates),
        "allowed":     len(allowed),
        "deferred":    len(deferred),
        "reason":      reason,
        "csv_path":    str(csv_path) if csv_path else None,
        "daily_count": state["count"],
    }


def main():
    parser = argparse.ArgumentParser(description="Revise CSV 生成 (FileExchange / Quantity=0)")
    parser.add_argument("--sheet", choices=["high", "low", "both"], default="both")
    parser.add_argument("--mode", choices=["pending", "all"], default="pending",
                        help="pending=Phase 2 で今回付与した行のみ (default、Q2 Takaaki さん確定); "
                             "all=スプシの全 D=○ 行 (緊急時の一括処理用)")
    parser.add_argument("--max-per-run", type=int, default=DEFAULT_MAX_PER_RUN,
                        help=f"1 run (4h cycle) の最大件数 (default: {DEFAULT_MAX_PER_RUN})")
    parser.add_argument("--force", action="store_true",
                        help="per-run cap 超過時に manual approval 相当で強行")
    parser.add_argument("--dry-run", action="store_true",
                        help="CSV 出力なし、判定のみ")
    args = parser.parse_args()

    result = run(
        sheet=args.sheet,
        mode=args.mode,
        max_per_run=args.max_per_run,
        force=args.force,
        dry_run=args.dry_run,
    )
    print()
    print(f"=== 結果 ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
