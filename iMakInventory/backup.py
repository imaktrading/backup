"""backup - スプシ D 列バックアップ + 復元 (Phase 8).

巡回開始時 (Phase 0.7) に listings シートの D 列スナップショットを
backup_<cycle_ts> という別シートに保存する。
誤動作 / 仕様変更 / 全件 SOLD 化 等の事故から復旧するための保険。

【保持ルール】
直近 BACKUP_MAX_KEEP=24 シートを残す (= 4h × 6 回 / 日 × 4日 ≒ 1 週間弱)。
古いものから自動削除。listings タブ・audit タブ等の運用シートは絶対削除しない
(プレフィックス "backup_" + 日時 サフィックスで厳格判定)。

【復元】
restore_from_backup() は dry_run=True でプレビュー、False で実際に D 列書込。
プレビューは差分 (row, before, after) のリスト + 件数を返す。
"""
from __future__ import annotations

import re
from typing import Optional

# 既存 helpers (SSOT)
from sheet_updater import (  # noqa: E402
    LISTINGS_GID,
    LISTINGS_COL_URL,
    LISTINGS_COL_ITEM_ID,
    LISTINGS_COL_SOLD,
    get_listings_worksheet,
    read_listings_rows,
    update_listings_sold_marks,
)

BACKUP_PREFIX = "backup_"
BACKUP_MAX_KEEP = 24
BACKUP_HEADERS = ["row", "item_id", "url", "d_value", "cycle_ts"]
# backup_YYYYMMDD_HHMMSS 形式のみ matching
BACKUP_TAB_NAME_RE = re.compile(r"^backup_(\d{8}_\d{6})$")


# ============================================================================
# 8a: D 列スナップショット
# ============================================================================
def backup_d_column(sh, cycle_ts: str) -> dict:
    """listings シートの D 列スナップショットを backup_<cycle_ts> シートに複製.

    Args:
        sh:        gspread spreadsheet (HIGH or LOW or 単一)
        cycle_ts:  "YYYYMMDD_HHMMSS" 形式の cycle 識別子

    Returns: {
        "backup_tab_name": "backup_20260430_140000",
        "backup_tab_id": <gid>,
        "row_count": 421,
        "cycle_ts": cycle_ts,
        "error": None or "ExceptionName: msg",
    }
    """
    result = {
        "backup_tab_name": f"{BACKUP_PREFIX}{cycle_ts}",
        "backup_tab_id": None,
        "row_count": 0,
        "cycle_ts": cycle_ts,
        "error": None,
    }
    try:
        ws = get_listings_worksheet(sh, gid=LISTINGS_GID)
        # 全行 (URL なしも含めて) D 列スナップショット ─ 復元時の整合性のため
        rows = read_listings_rows(ws, start_row=2, end_row=None, only_with_url=False)

        # 既存 backup シートが残っていれば例外でなく上書きする (rerun 想定)
        try:
            old = sh.worksheet(result["backup_tab_name"])
            sh.del_worksheet(old)
        except Exception:
            pass

        new_ws = sh.add_worksheet(
            title=result["backup_tab_name"],
            rows=str(max(len(rows) + 10, 100)),
            cols="5",
        )
        result["backup_tab_id"] = new_ws.id

        body = [BACKUP_HEADERS]
        for r in rows:
            body.append([
                r["row_index"],
                r.get("item_id", ""),
                r.get("url", ""),
                r.get("current_sold", ""),
                cycle_ts,
            ])
        new_ws.update(values=body, range_name="A1", value_input_option="RAW")
        result["row_count"] = len(rows)
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
    return result


def list_backup_tabs(sh) -> list[dict]:
    """spreadsheet 内の backup_* タブ一覧 (新しい順 ts 降順)."""
    tabs = []
    for ws in sh.worksheets():
        m = BACKUP_TAB_NAME_RE.match(ws.title)
        if m:
            tabs.append({"title": ws.title, "id": ws.id, "ts": m.group(1)})
    tabs.sort(key=lambda x: x["ts"], reverse=True)
    return tabs


def prune_old_backups(sh, max_keep: int = BACKUP_MAX_KEEP) -> dict:
    """古い backup シートを削除して max_keep 件まで残す.

    backup_YYYYMMDD_HHMMSS の正規表現に match するシートのみ対象。
    listings / audit / 運用シートは絶対削除しない。
    """
    tabs = list_backup_tabs(sh)
    result = {"deleted": 0, "kept": len(tabs), "errors": []}
    if len(tabs) <= max_keep:
        return result
    to_delete = tabs[max_keep:]
    for t in to_delete:
        # 二重防御: 名前再 match を確認してから削除
        if not BACKUP_TAB_NAME_RE.match(t["title"]):
            result["errors"].append(f"refused non-backup tab: {t['title']}")
            continue
        try:
            ws = sh.worksheet(t["title"])
            sh.del_worksheet(ws)
            result["deleted"] += 1
        except Exception as e:
            result["errors"].append(f"{t['title']}: {type(e).__name__}: {e}")
    result["kept"] = len(tabs) - result["deleted"]
    return result


# ============================================================================
# 8b: 差分計算
# ============================================================================
def compute_d_diff(before_rows: list, after_rows: list) -> dict:
    """before/after の row dict 配列から D 列差分を抽出.

    Args:
        before_rows: [{row_index, current_sold, url, item_id, title}, ...]
        after_rows:  同上 (post-monitor)

    Returns: {
        "newly_sold":     [{row, url, item_id, title}, ...],  # 空→○
        "newly_in_stock": [...],  # ○→空
        "unchanged_count": int,
    }
    """
    by_row = {r["row_index"]: r for r in after_rows}
    newly_sold = []
    newly_in_stock = []
    unchanged = 0
    for b in before_rows:
        idx = b["row_index"]
        a = by_row.get(idx)
        if a is None:
            continue
        before_d = (b.get("current_sold") or "").strip()
        after_d = (a.get("current_sold") or "").strip()
        if before_d == after_d:
            unchanged += 1
            continue
        info = {
            "row": idx,
            "url": a.get("url", ""),
            "item_id": a.get("item_id", ""),
            "title": (a.get("title") or "")[:40],
        }
        if not before_d and after_d == "○":
            newly_sold.append(info)
        elif before_d == "○" and not after_d:
            newly_in_stock.append(info)
    return {
        "newly_sold": newly_sold,
        "newly_in_stock": newly_in_stock,
        "unchanged_count": unchanged,
    }


def render_diff_md(diff: dict, sheet_label: str, cycle_ts: str) -> str:
    """差分を markdown 文字列に整形 (decision_log/diff_<cycle_ts>.md 用)."""
    lines = [f"# D 列差分 [{sheet_label}] cycle_ts={cycle_ts}", ""]
    n_sold = len(diff["newly_sold"])
    n_back = len(diff["newly_in_stock"])
    lines.append(f"- newly_sold (空→○): **{n_sold} 件**")
    lines.append(f"- newly_in_stock (○→空): **{n_back} 件**")
    lines.append(f"- unchanged: {diff['unchanged_count']} 件")
    lines.append("")
    if n_sold > 0:
        lines.append("## newly_sold (取り下げ対象になった行)")
        lines.append("| row | item_id | title | url |")
        lines.append("|---|---|---|---|")
        for r in diff["newly_sold"][:50]:
            lines.append(f"| {r['row']} | {r['item_id']} | {r['title']} | {r['url']} |")
        if n_sold > 50:
            lines.append(f"\n... +{n_sold - 50} 件")
        lines.append("")
    if n_back > 0:
        lines.append("## newly_in_stock (○ が外れた行 ─ 誤復活疑い要確認)")
        lines.append("| row | item_id | title | url |")
        lines.append("|---|---|---|---|")
        for r in diff["newly_in_stock"][:50]:
            lines.append(f"| {r['row']} | {r['item_id']} | {r['title']} | {r['url']} |")
        if n_back > 50:
            lines.append(f"\n... +{n_back - 50} 件")
        lines.append("")
    return "\n".join(lines)


# ============================================================================
# 8c: 復元
# ============================================================================
def restore_from_backup(
    sh,
    backup_tab_name: str,
    dry_run: bool = True,
) -> dict:
    """指定 backup シートから D 列を listings に書き戻す.

    Args:
        sh:               gspread spreadsheet
        backup_tab_name:  "backup_20260430_140000"
        dry_run:          True なら差分のみ計算、False なら実際に書込

    Returns: {
        "to_restore":     int,  # 書き戻し対象件数
        "diff_preview":   [{row, before, after}, ...],  # 先頭 50 件
        "applied":        bool,
        "error":          None | str,
        "backup_tab":     str,
    }
    """
    out = {
        "to_restore": 0, "diff_preview": [], "applied": False, "error": None,
        "backup_tab": backup_tab_name,
    }
    try:
        backup_ws = sh.worksheet(backup_tab_name)
        backup_data = backup_ws.get_all_values()
        if not backup_data or backup_data[0][:5] != BACKUP_HEADERS:
            out["error"] = f"backup tab schema mismatch: header={backup_data[:1]}"
            return out

        listings_ws = get_listings_worksheet(sh, gid=LISTINGS_GID)
        listings_rows = read_listings_rows(
            listings_ws, start_row=2, end_row=None, only_with_url=False,
        )
        current_by_row = {r["row_index"]: (r.get("current_sold") or "").strip()
                          for r in listings_rows}

        updates = []
        for line in backup_data[1:]:
            if len(line) < 4:
                continue
            try:
                row_idx = int(line[0])
            except (ValueError, TypeError):
                continue
            backup_d = (line[3] or "").strip()
            current_d = current_by_row.get(row_idx, "")
            if backup_d != current_d:
                updates.append({
                    "row_index": row_idx,
                    "is_sold": (backup_d == "○"),
                    "checked_at": "",  # 復元では時刻上書きしない
                })
                if len(out["diff_preview"]) < 50:
                    out["diff_preview"].append({
                        "row": row_idx,
                        "before": current_d,
                        "after": backup_d,
                    })
        out["to_restore"] = len(updates)
        if not dry_run and updates:
            update_listings_sold_marks(listings_ws, updates)
            out["applied"] = True
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out


# ============================================================================
# CLI (debug 用)
# ============================================================================
if __name__ == "__main__":
    import argparse
    import json
    from datetime import datetime

    parser = argparse.ArgumentParser(description="D 列 backup / restore (Phase 8)")
    parser.add_argument("--mode", choices=["backup", "list", "prune", "restore"],
                        required=True)
    parser.add_argument("--sheet-id", required=True, help="spreadsheet ID")
    parser.add_argument("--backup-tab", help="restore 対象 backup_YYYYMMDD_HHMMSS")
    parser.add_argument("--apply", action="store_true",
                        help="restore 実行 (default は dry_run プレビュー)")
    parser.add_argument("--max-keep", type=int, default=BACKUP_MAX_KEEP)
    args = parser.parse_args()

    from sheet_updater import open_sheet_by_id  # noqa: PLC0415
    sh = open_sheet_by_id(args.sheet_id)

    if args.mode == "backup":
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        r = backup_d_column(sh, cycle_ts=ts)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif args.mode == "list":
        print(json.dumps(list_backup_tabs(sh), ensure_ascii=False, indent=2))
    elif args.mode == "prune":
        r = prune_old_backups(sh, max_keep=args.max_keep)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif args.mode == "restore":
        if not args.backup_tab:
            parser.error("--backup-tab required for restore")
        r = restore_from_backup(sh, args.backup_tab, dry_run=not args.apply)
        print(json.dumps(r, ensure_ascii=False, indent=2))
