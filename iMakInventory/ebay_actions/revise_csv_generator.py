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
import os
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
# verify_against_sheet で「sheet で D が ○ でなくなった/itemID が変わった」と
# 判定された entry の archive 先 (= pending 肥大化防止、 traceability 維持)
DISCARDED_REVISE_FILE = DECISION_LOG_DIR / "discarded_revise.jsonl"

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

# HQ 2026-06-10 confirm 指示 A 急増ガード (= mass-reinclude 暴発防止):
# 1 cycle で reinclude (= prune が「eBay qty>0」 判定で CSV 再投入する entry) 件数が
# 閾値を超えたら全件保留 + critical alert (= sheet 書込系の系統的異常を前兆検出)。
# env var INVENTORY_REINCLUDE_BURST_THRESHOLD で override 可。
#
# 実機 reinclude 分布 (commit 300dc8f 以降の計測): 過去全て 0 件
#   (= 6/9 sweep 167 件は全件 qty=0 → reinclude 0、 6/10 09:30 2 件も qty=0 化済 → reinclude 0)
# 閾値 10 件は実機分布 0 件 + transient/レース由来 false positive 用 conservative マージン。
DEFAULT_REINCLUDE_BURST_THRESHOLD = int(
    os.environ.get("INVENTORY_REINCLUDE_BURST_THRESHOLD", "10")
)

# HQ 2026-06-10 Phase 1.6 取下げ側急増ガード (= 6/3 偽 OOS 95 件型対策):
# 1 cycle の newly_sold 起因 candidates (= 取下げ送信対象) が閾値を超えたら全件 HOLD。
# scraper 系異常 (= 偽 OOS 大量発生) を早期検出、 per_run_cap=100 で素通る 30-99 件帯を守る。
#
# 実機 newly_sold 分布 (= 189 cycle 集計、 commit 直前):
#   中央 2 件 / 平均 4.4 件 / 90 %tile 6 件 / 95 %tile 10 件 / 通常 max 21 件
#   偽 OOS incident: 152 件 (6/2) / 50 件 (6/2) / 95 件 (6/3 memory) ← 全件 catch すべき
# 閾値 30 件 = 95 %tile の 3 倍、 通常 max 21 + 50% マージン、 偽 OOS 100% catch。
#
# HQ affirm #1 ★重要: HOLD された entry は action_required.jsonl 記録 + email release CLI 手順明示。
# burst HOLD が 「本物の大量売切」 だった場合 = 出品継続 = 新 fail-OPEN になるため、
# 即時 SLA + 人手 release 経路 (= `tools/release_holdouts.py`) が load-bearing。
# HQ affirm #2: 22-29 件帯の隙間は reverse_audit が backstop (= 翌 09:30 で D=○ vs qty>0 検知)。
DEFAULT_NEWLY_SOLD_BURST_THRESHOLD = int(
    os.environ.get("INVENTORY_NEWLY_SOLD_BURST_THRESHOLD", "30")
)


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
    high_sheet_id: Optional[str] = None,
    low_sheet_id: Optional[str] = None,
    single_sheet_id: Optional[str] = None,
    single_sheet_label: Optional[str] = None,
) -> tuple[list, list]:
    """pending_revise.jsonl から取り下げ候補を収集.

    Args:
        sheet_filter: "high" / "low" / "both" (HIGH/LOW モード時)
        verify_against_sheet: True の場合、スプシ側で D が依然 "○" の行のみ採用
        high_sheet_id / low_sheet_id: TEST スプシ等で本番 ID 上書き
        single_sheet_id / single_sheet_label: Phase 6a 単一スプシ mode

    Returns: (candidates, skipped_pending)
    """
    queue = read_pending_queue()
    if not queue:
        return [], []

    # スプシ照合用 sheet_state 構築
    sheet_state: dict[tuple[str, int], dict] = {}
    if verify_against_sheet:
        targets = []
        if single_sheet_id:
            targets.append((single_sheet_label or "SHEET", single_sheet_id))
        else:
            h_id = high_sheet_id or HIGH_SHEET_ID
            l_id = low_sheet_id or LOW_SHEET_ID
            if sheet_filter in ("high", "both"):
                targets.append(("HIGH", h_id))
            if sheet_filter in ("low", "both"):
                targets.append(("LOW", l_id))
        for label, sid in targets:
            try:
                sold = collect_sold_listings(label, sid)
                for s in sold:
                    sheet_state[(label, s["row_index"])] = s
            except Exception as e:
                print(f"  [!] [{label}] 現状取得失敗: {type(e).__name__}: {e}")
                return [], queue

    candidates = []
    skipped = []
    for q in queue:
        label = q.get("sheet", "")
        # filter (mode 別)
        if single_sheet_id:
            # 単一スプシ mode: ラベルが一致する entry のみ採用
            if label != (single_sheet_label or "SHEET"):
                skipped.append({**q, "skip_reason": "filter_single_label_mismatch"})
                continue
        else:
            # HIGH/LOW mode
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


def prune_discarded_entries(skipped: list[dict]) -> dict:
    """verify で「sheet で D が ○ でなくなった/itemID が変わった」と判定された
    pending entry を **eBay GetItem qty=0 確認後にのみ** discard する。

    HQ 2026-06-10 確定指示 (= `_FINAL_design_directive`) 「取下げ義務 persist /
    取下げるべきものは eBay qty=0 を確認するまで閉じる」 に基づく fail-CLOSED 設計:

    - sheet D=空 だけでは削除しない (= sheet 書込 fail 由来の偽 D=空 で silent drop
      する 6/10 09:30 同型 bug を防ぐ)
    - eBay GetItem で qty=0 確認できた entry のみ discarded_revise.jsonl に archive
    - eBay qty>0 のまま entry = pending 残置 + 「sheet 不整合」 を逆検知 (= reverse audit
      機能を内蔵) → re-include CSV 候補に格上げ
    - GetItem call 失敗 / err 17 (Item not found = 既 ended) は qty=0 同等扱いで discard

    Args:
        skipped: collect_from_pending_queue が返す skipped list。
                 skip_reason == "no_longer_sold_or_id_changed" の entry のみ対象。
                 filter_* (= 別 sheet の cycle で verify される) や sheet 読込失敗 (=
                 skip_reason 無し) は対象外 = pending に残す。

    Returns: {"discarded": N, "kept_qty_gt0": M, "reincluded": [<entry>, ...]}
      - discarded: eBay qty=0 確認で archive した件数
      - kept_qty_gt0: eBay qty>0 残ってて pending 残置した件数 (= silent loss 候補)
      - reincluded: 再度 CSV 候補に格上げすべき entry list (= sheet が壊れてただけ)
    """
    if not PENDING_REVISE_FILE.exists():
        return {"discarded": 0, "kept_qty_gt0": 0, "reincluded": []}
    # 削除候補 entry の identifier set を作る
    targets = set()
    for s in skipped:
        if s.get("skip_reason") != "no_longer_sold_or_id_changed":
            continue
        key = (s.get("sheet", ""), s.get("row_index", -1), s.get("item_id", ""))
        targets.add(key)
    if not targets:
        return {"discarded": 0, "kept_qty_gt0": 0, "reincluded": []}

    # eBay GetItem で qty 確認 (= pending 残置 / discard を判定)
    # 循環 import 回避のため遅延 import
    from ebay_actions.trading_api_client import (  # noqa: PLC0415
        load_access_token, _call_trading,
    )
    import re as _re  # noqa: PLC0415
    try:
        token = load_access_token()
    except Exception as e:
        print(f"  [!] prune skip (token load 失敗): {type(e).__name__}: {e}")
        return {"discarded": 0, "kept_qty_gt0": 0, "reincluded": []}

    def _ebay_qty(iid: str) -> Optional[int]:
        """eBay GetItem で現在 qty 取得。 None = API 失敗 / 不明 = 削除保留。"""
        if not iid:
            return None
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
            f'<ItemID>{iid}</ItemID></GetItemRequest>'
        )
        try:
            res = _call_trading("GetItem", body, access_token=token)
        except Exception as e:
            print(f"    [!] GetItem 例外 iid={iid}: {type(e).__name__}: {e}")
            return None
        if res.get("error_code") == "17":
            # Item not found / already ended → qty=0 同等
            return 0
        if not res.get("success"):
            return None
        # ★ 修正 2026-06-10: <Quantity> は累計出品数、 available = Quantity - QuantitySold
        # で計算する。 旧 logic は Quantity をそのまま読んでて false positive 発生。
        xml = res.get("raw_xml", "")
        q_m = _re.search(r"<Quantity>(\d+)</Quantity>", xml)
        sold_m = _re.search(r"<QuantitySold>(\d+)</QuantitySold>", xml)
        if q_m:
            total_qty = int(q_m.group(1))
            sold = int(sold_m.group(1)) if sold_m else 0
            return max(0, total_qty - sold)
        return None

    # pending 全行を走査、 target 該当 entry のみ eBay qty 確認
    archived = 0
    kept_qty_gt0 = 0
    reincluded = []
    keep_lines = []
    with open(PENDING_REVISE_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                keep_lines.append(line)
                continue
            key = (entry.get("sheet", ""), entry.get("row_index", -1),
                   entry.get("item_id", ""))
            if key not in targets:
                keep_lines.append(line)
                continue
            # eBay qty 確認 (= fail-CLOSED 設計の核)
            iid = entry.get("item_id", "")
            qty = _ebay_qty(iid)
            if qty == 0:
                # 既 qty=0 → 安全に discard
                entry["discarded_at"] = datetime.now().isoformat(timespec="seconds")
                entry["discard_reason"] = "ebay_qty_zero_confirmed"
                with open(DISCARDED_REVISE_FILE, "a", encoding="utf-8") as af:
                    af.write(json.dumps(entry, ensure_ascii=False) + "\n")
                archived += 1
            elif qty is None:
                # API 失敗 → 保守的に pending 残置
                keep_lines.append(line)
            else:
                # qty > 0 → sheet 状態が誤、 pending 残置 + 再 include 候補に格上げ
                kept_qty_gt0 += 1
                reincluded.append(entry)
                keep_lines.append(line)

    PENDING_REVISE_FILE.write_text(
        ("\n".join(keep_lines) + "\n") if keep_lines else "",
        encoding="utf-8",
    )
    return {
        "discarded": archived,
        "kept_qty_gt0": kept_qty_gt0,
        "reincluded": reincluded,
    }


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
    high_sheet_id: Optional[str] = None,
    low_sheet_id: Optional[str] = None,
    single_sheet_id: Optional[str] = None,
    single_sheet_label: Optional[str] = None,
) -> dict:
    # 単一スプシ mode (Phase 6a)
    is_single_mode = bool(single_sheet_id)

    if is_single_mode:
        targets = [(single_sheet_label or "SHEET", single_sheet_id)]
    else:
        h_id = high_sheet_id or HIGH_SHEET_ID
        l_id = low_sheet_id or LOW_SHEET_ID
        targets = []
        if sheet in ("high", "both"):
            targets.append(("HIGH", h_id))
        if sheet in ("low", "both"):
            targets.append(("LOW", l_id))

    print(f"=== Revise CSV 生成 (sheet={sheet}, mode={mode}, dry_run={dry_run}, "
          f"force={force}, max_per_run={max_per_run}) ===")
    if is_single_mode:
        print(f"  [!] 単一スプシ mode: label={single_sheet_label or 'SHEET'} id={single_sheet_id[:25]}...")
    elif high_sheet_id or low_sheet_id:
        h_id = high_sheet_id or HIGH_SHEET_ID
        l_id = low_sheet_id or LOW_SHEET_ID
        print(f"  [!] TEST モード: HIGH={h_id[:25]}... LOW={l_id[:25]}...")

    candidates = []
    pending_skipped = []
    if mode == "pending":
        # Phase 2 で今回新規〇付与した行のみキューから取る
        candidates, pending_skipped = collect_from_pending_queue(
            sheet_filter=sheet, verify_against_sheet=True,
            high_sheet_id=high_sheet_id, low_sheet_id=low_sheet_id,
            single_sheet_id=single_sheet_id,
            single_sheet_label=single_sheet_label,
        )
        print(f"  pending queue から: {len(candidates)} 件 (skip {len(pending_skipped)} 件)")
        # 「sheet で ○ 解除」 entry の処理 (= HQ 2026-06-10 FINAL 指示 D に基づく fail-CLOSED 設計):
        # 1. eBay GetItem で qty=0 確認できた entry のみ discard
        # 2. eBay qty>0 残ってる entry は pending 残置 + 「sheet 書込 fail 由来の偽 D=空」 として
        #    再 include 候補に昇格 (= silent loss を逆に救済)
        # 3. GetItem 失敗は保守的に pending 残置 (= 再判定機会を捨てない)
        # 旧 b4c238d は sheet D=空 だけで discard → 6/10 09:30 で sheet 書込 DNS fail 由来の
        # 偽 D=空 で 2 件 silent drop 発生、 本実装で構造的に修正。
        try:
            prune_res = prune_discarded_entries(pending_skipped)
            disc = prune_res.get("discarded", 0)
            kept = prune_res.get("kept_qty_gt0", 0)
            reincluded = prune_res.get("reincluded", [])
            if disc:
                print(f"  pending prune (eBay qty=0 確認): {disc} 件 → discarded_revise.jsonl")
            if kept:
                print(f"  [!] pending 残置 (eBay qty>0 → sheet 状態誤と判定): {kept} 件")
            # HQ 2026-06-10 confirm A 急増ガード: reincluded 件数が閾値超 → 全件 HOLD
            # 「6/10 09:30 のような sheet 書込系統的異常で偽 D=空 大量発生」 を前兆検出。
            # HOLD = silent ではなく action_required.jsonl + critical alert に格納
            # (= HQ 条件 「HOLD した分は必ず action_required + alert に記録」 遵守)。
            burst_threshold = DEFAULT_REINCLUDE_BURST_THRESHOLD
            if len(reincluded) > burst_threshold:
                print(f"  [★急増ガード発火] reincluded {len(reincluded)} 件 > 閾値 {burst_threshold} 件 → 全件 HOLD")
                print(f"      (= sheet 書込系の系統的異常疑い、 fail-CLOSED で発火を抑制)")
                # HOLD 全件を action_required.jsonl に記録 + alert へ流す
                # 循環 import 回避のため遅延 import
                try:
                    from monitor_listings import append_action_required  # noqa: PLC0415
                    for q in reincluded:
                        append_action_required(
                            sheet_label=q.get("sheet", ""),
                            result={
                                "row_index": q.get("row_index", -1),
                                "url":       q.get("url", ""),
                                "item_id":   q.get("item_id", ""),
                                "title":     q.get("title", ""),
                                "supplier":  q.get("supplier", ""),
                                "raw_status": "reinclude_burst_holdout",
                            },
                            reason="reinclude_burst_guard_holdout",
                            dry_run=dry_run,
                        )
                    print(f"      → {len(reincluded)} 件を action_required.jsonl に記録 (silent化禁止)")
                except Exception as e:
                    print(f"  [!] action_required 記録失敗: {type(e).__name__}: {e}")
                # reincluded を空に倒して CSV 対象外化
                reincluded = []
            else:
                # 通常 path: 再昇格 entry を candidates に追加 (= 取下げ義務 persist)
                if reincluded:
                    print(f"      → {len(reincluded)} 件を CSV 候補に再昇格 (閾値 {burst_threshold} 件以下)")
                for q in reincluded:
                    candidates.append({
                        "sheet_label": q.get("sheet", ""),
                        "row_index":   q.get("row_index", -1),
                        "item_id":     q.get("item_id", ""),
                        "url":         q.get("url", ""),
                        "title":       q.get("title", ""),
                        "current_sold": "○",
                        "checked_at":  "",
                        "queue_ts":    q.get("ts", ""),
                        "reincluded_reason": "sheet_d_empty_but_ebay_qty_gt0",
                    })
        except Exception as e:
            print(f"  [!] prune_discarded_entries 失敗: {type(e).__name__}: {e}")
    elif mode == "all":
        # 全 D="○" 行を対象 (緊急時、過去未処理の一括処理用)
        for label, sid in targets:
            try:
                sold = collect_sold_listings(label, sid)
                print(f"  [{label}] D=○ 全件 (mode=all): {len(sold)} 件")
                candidates.extend(sold)
            except Exception as e:
                print(f"  [NG] [{label}] 読込失敗: {type(e).__name__}: {e}")
    else:
        raise ValueError(f"unsupported mode: {mode}")

    print(f"  合計候補: {len(candidates)} 件 (dedup 前)")

    # HQ 2026-06-10 Phase 1.6 取下げ側急増ガード (= 6/3 偽 OOS 95 件型対策):
    # candidates 件数が閾値超なら scraper 系異常疑い → 全件 HOLD + action_required 記録 + alert。
    # HQ affirm #1: HOLD 後の release 経路 (= tools/release_holdouts.py CLI) を email で誘導。
    # HQ affirm #2: 22-29 件帯は reverse_audit が backstop (= 翌 09:30 で D=○ vs qty>0 検知)。
    newly_sold_threshold = DEFAULT_NEWLY_SOLD_BURST_THRESHOLD
    if mode == "pending" and len(candidates) > newly_sold_threshold:
        print(f"  [★Phase 1.6 burst guard 発火] candidates {len(candidates)} 件 > 閾値 {newly_sold_threshold} 件")
        print(f"      (= scraper 系異常疑い (例: 偽 OOS 大量発生)、 fail-CLOSED で全件 HOLD)")
        # HOLD = silent 化禁止 → 全件 action_required.jsonl に記録
        try:
            from monitor_listings import append_action_required  # noqa: PLC0415
            for c in candidates:
                append_action_required(
                    sheet_label=c.get("sheet_label", ""),
                    result={
                        "row_index": c.get("row_index", -1),
                        "url":       c.get("url", ""),
                        "item_id":   c.get("item_id", ""),
                        "title":     c.get("title", ""),
                        "supplier":  c.get("supplier", ""),
                        "raw_status": "newly_sold_burst_holdout",
                    },
                    reason="newly_sold_burst_guard_holdout",
                    dry_run=dry_run,
                )
            print(f"      → {len(candidates)} 件を action_required.jsonl に記録 (silent 化禁止)")
            print(f"      release 手順: python -m tools.release_holdouts --reason newly_sold_burst_guard_holdout --execute")
        except Exception as e:
            print(f"  [!] action_required 記録失敗: {type(e).__name__}: {e}")
        # candidates を空に倒して以降の CSV 生成 / upload を skip
        candidates = []

    # state load (運用記録のみ、cap 判定には使わない)
    state = load_state()
    print(f"  本日 ({state['date']}) すでに送信済: {state['count']} (記録のみ、cap 判定なし)")

    # cap 適用 (per-run cap = 100 のみ、daily cap なし)
    allowed, deferred, reason = apply_caps(candidates, max_per_run, force=force)
    print(f"  許可: {len(allowed)} / 保留: {len(deferred)} / reason: {reason}")

    if reason == "PER_RUN_CAP_EXCEEDED":
        print(f"  [!]  per-run cap ({max_per_run}件) 超過。構造異常疑い。")
        print(f"      --force で override 可能 (manual approval)。確認なしの実行は推奨しない。")

    # CSV 出力
    csv_path = None
    if not dry_run and allowed:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        sheet_part = sheet.upper() if sheet != "both" else "BOTH"
        csv_path = CSV_OUTPUT_DIR / f"revise_{sheet_part}_{ts}.csv"
        n = write_revise_csv(allowed, csv_path)
        print(f"  [OK] CSV 出力: {csv_path} ({n} 行)")

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

        # NOTE: pending → processed drain は upload 完了後に caller (run_cycle.py) が
        # 成功 item のみを drain する (= 失敗 item を次 cycle で retry させる)。
        # 旧 実装は ここで一律 drain → DNS/Timeout 等 transient 失敗で eBay revise 不能の
        # 場合も pending から消えて、 次 cycle で再 enqueue 不能になる sliver loss bug
        # があった (2026-06-06 17:30 cycle で 1 件 silent 喪失、 手動 revise で復旧)。
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
        # upload 後の drain 用 (run_cycle.py が成功 item のみ drain)
        "mode":             mode,
        "allowed_item_ids": [c["item_id"] for c in allowed],
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
    # TEST スプシ向けの sheet ID 上書き (env var fallback)
    parser.add_argument("--high-sheet-id", default=os.environ.get("INVENTORY_HIGH_SHEET_ID"),
                        help="HIGH 用 spreadsheet ID 上書き (env: INVENTORY_HIGH_SHEET_ID)")
    parser.add_argument("--low-sheet-id", default=os.environ.get("INVENTORY_LOW_SHEET_ID"),
                        help="LOW 用 spreadsheet ID 上書き (env: INVENTORY_LOW_SHEET_ID)")
    # 単一スプシ mode (Phase 6a)
    parser.add_argument("--sheet-id", default=None,
                        help="単一スプシ mode: 指定 ID のみ処理 "
                             "(--high-sheet-id/--low-sheet-id と排他)")
    parser.add_argument("--sheet-label", default="SHEET",
                        help="--sheet-id 使用時のラベル (default: SHEET)")
    args = parser.parse_args()

    if args.sheet_id and (args.high_sheet_id or args.low_sheet_id):
        print("[NG] --sheet-id と --high-sheet-id/--low-sheet-id は併用不可")
        sys.exit(2)

    result = run(
        sheet=args.sheet,
        mode=args.mode,
        max_per_run=args.max_per_run,
        force=args.force,
        dry_run=args.dry_run,
        high_sheet_id=args.high_sheet_id,
        low_sheet_id=args.low_sheet_id,
        single_sheet_id=args.sheet_id,
        single_sheet_label=args.sheet_label,
    )
    print()
    print(f"=== 結果 ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
