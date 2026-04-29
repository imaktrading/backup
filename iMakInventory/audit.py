"""audit - 巡回ごと IN_STOCK 抜き取り 5 件 (Phase 7d').

cycle 終了後、IN_STOCK 判定された listing から random.sample(5, seed=cycle_ts) で
抽出し、入力スプシの「audit」タブに append。

Takaaki さんが朝 1 回目視 (1 日 30 件 = 5 分) → false negative 発見の早期検知。

audit タブ列構成:
  A: cycle_ts | B: row | C: item_id | D: URL | E: 判定 | F: 目視結果(空欄) | G: 備考

各 cycle が 5 行追記。タブが大きくなりすぎたら手動でアーカイブ。
"""
from __future__ import annotations

import json
import random
from datetime import datetime
from pathlib import Path
from typing import Optional

from sheet_updater import open_sheet_by_id, LISTINGS_GID

AUDIT_TAB_NAME = "audit"
AUDIT_HEADERS = ["cycle_ts", "row", "item_id", "URL", "判定", "目視結果", "備考"]


def _ensure_audit_tab(sh, tab_name: str = AUDIT_TAB_NAME):
    """audit タブを取得 (なければ作成して header 書込)."""
    for ws in sh.worksheets():
        if ws.title == tab_name:
            return ws
    new_ws = sh.add_worksheet(title=tab_name, rows="100", cols=str(len(AUDIT_HEADERS) + 2))
    new_ws.update(values=[AUDIT_HEADERS], range_name="A1", value_input_option="USER_ENTERED")
    return new_ws


def collect_in_stock_from_log(decision_log_path: Path) -> list:
    """listings_<label>_<ts>.jsonl から in_stock 判定行を抽出."""
    items = []
    if not decision_log_path.exists():
        return items
    with open(decision_log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("error"):
                continue
            if r.get("is_sold") is False:  # in_stock
                items.append({
                    "row_index": r.get("row_index"),
                    "item_id":   r.get("item_id", ""),
                    "url":       r.get("url", ""),
                    "title":     r.get("title", ""),
                    "supplier":  r.get("supplier", ""),
                    "raw_status": r.get("raw_status", ""),
                })
    return items


def find_latest_listings_log(decision_log_dir: Path, sheet_label: str) -> Optional[Path]:
    """指定 label の最新 listings_<label>_<ts>.jsonl を返す."""
    pattern = f"listings_{sheet_label}_*.jsonl"
    candidates = sorted(decision_log_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def sample_and_append(
    sheet_id: str,
    sheet_label: str,
    decision_log_dir: Path,
    cycle_ts: Optional[str] = None,
    n: int = 5,
    seed: Optional[int] = None,
    audit_tab_name: str = AUDIT_TAB_NAME,
) -> dict:
    """1 シート分の audit 抽出 + append.

    Returns: {"sampled": N, "appended": M, "log_used": path or None, "error": str or None}
    """
    if cycle_ts is None:
        cycle_ts = datetime.now().strftime("%Y/%m/%d %H:%M")
    if seed is None:
        seed = int(datetime.now().timestamp())

    log_path = find_latest_listings_log(decision_log_dir, sheet_label)
    if log_path is None:
        return {"sampled": 0, "appended": 0, "log_used": None,
                "error": f"listings_{sheet_label}_*.jsonl not found"}

    in_stock = collect_in_stock_from_log(log_path)
    if len(in_stock) == 0:
        return {"sampled": 0, "appended": 0, "log_used": str(log_path),
                "error": "no in_stock items in latest log"}

    rng = random.Random(seed)
    sample = rng.sample(in_stock, min(n, len(in_stock)))

    try:
        sh = open_sheet_by_id(sheet_id)
        ws = _ensure_audit_tab(sh, audit_tab_name)
    except Exception as e:
        return {"sampled": len(sample), "appended": 0, "log_used": str(log_path),
                "error": f"sheet open: {type(e).__name__}: {e}"}

    rows = []
    for s in sample:
        rows.append([
            cycle_ts,
            str(s["row_index"]) if s["row_index"] is not None else "",
            s["item_id"],
            s["url"],
            "IN_STOCK",
            "",   # 目視結果 (空欄、Takaaki さん埋める)
            "",   # 備考
        ])

    try:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
    except Exception as e:
        return {"sampled": len(sample), "appended": 0, "log_used": str(log_path),
                "error": f"append: {type(e).__name__}: {e}"}

    return {
        "sampled": len(sample),
        "appended": len(rows),
        "log_used": str(log_path),
        "error": None,
        "audit_tab_id": ws.id,
    }
