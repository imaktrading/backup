"""LOW スプシ D列 "DUP" マーカー書込 (= 2026-06-12 G-shock 重複行 抽選キュー除外).

spec: iMak_data/dedupe/requests/2026-06-12_gshock_dup_writeback_METHOD_APPROVED_greenlight.md
方式: D列 (= col 4 「売り切れ」) に "DUP" 書込 (= 3 downstream 全部無害確認済).

scope:
- scope1 (= 都度): check_csv 重複検出時、 同 canonical KEY の LOW B空 AND D空 row に "DUP"
- scope2 (= 初回フルスキャン): LOW R='G-shock' B空 AND D空 全件 resolver 解決 → 既存出品と一致を一括 mark

fail-closed:
- 既存出品 (= 監視くん管理の B非空 row) の canonical KEY と **完全一致** した B空 row のみ mark
- 解決不能 ("" 返却) / catalog 未登録 / 真の新規は touch しない
- B非空 / D非空 row は対象外 (= 既出品 / 売切 / 既マーク)

downstream 安全:
- 出品くん `_select_gshock_row`: D非空で自動 skip ✅ (改修不要)
- 監視くん `compute_d_diff`: 「空↔○」 のみ追跡、 "DUP" 無視 ✅
- リバイスくん `is_sold`: SOLD_MARKERS set 厳密判定で "DUP" は SOLD と区別 ✅
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

DUP_MARKER = "DUP"

# LOW/HIGH 商品管理シート col 位置 (= 2026-06-12 schema)
LOW_COL_URL = 1
LOW_COL_ITEM_ID = 2  # B列
LOW_COL_TITLE = 3
LOW_COL_SOLD = 4  # D列 (= "売り切れ"、 マーカー書込先)
LOW_COL_CATEGORY = 18  # R列
LOW_COL_KEY = 35  # AI列 (= canonical KEY)


def _safe_cell(row: List[str], col_1based: int) -> str:
    if col_1based <= 0 or col_1based > len(row):
        return ""
    return (row[col_1based - 1] or "").strip()


def collect_existing_canonical_keys(
    ws_high,
    ws_low,
    *,
    key_col: int = LOW_COL_KEY,
    item_id_col: int = LOW_COL_ITEM_ID,
    sold_col: int = LOW_COL_SOLD,
) -> Set[str]:
    """HIGH/LOW スプシから「既出品」 row の canonical KEY を集約.

    既出品 = B列 (= itemID) NOT NULL の row (= eBay listing と紐付済).
    D列状態は不問 (= 売切 ○ も「過去に出品済」 として既出品扱い).

    Returns: frozen-style set of canonical KEY (= AI 列 値).
    """
    keys: Set[str] = set()
    for ws in (ws_high, ws_low):
        values = ws.get_all_values()
        for row in values[1:]:  # skip header
            item_id = _safe_cell(row, item_id_col)
            if not item_id:
                continue  # B空 = 未出品 → 既出品ではない
            k = _safe_cell(row, key_col)
            if k:
                keys.add(k)
    return keys


def find_b_empty_d_empty_targets(
    ws_low,
    *,
    category_filter: Optional[str] = "G-shock",
    item_id_col: int = LOW_COL_ITEM_ID,
    sold_col: int = LOW_COL_SOLD,
    category_col: int = LOW_COL_CATEGORY,
    key_col: int = LOW_COL_KEY,
    title_col: int = LOW_COL_TITLE,
    url_col: int = LOW_COL_URL,
) -> List[Dict]:
    """LOW スプシの B空 AND D空 row を検索 (= 抽選キュー対象).

    category_filter: 'G-shock' 等の R列値で絞込み (None なら全カテゴリ).

    Returns: [{row_idx, url, title, key, category}, ...]
    """
    out: List[Dict] = []
    values = ws_low.get_all_values()
    for offset, row in enumerate(values[1:], start=2):  # 1-based row_idx (header=1)
        item_id = _safe_cell(row, item_id_col)
        sold = _safe_cell(row, sold_col)
        if item_id or sold:
            continue  # B非空 or D非空 = 対象外
        cat = _safe_cell(row, category_col)
        if category_filter and cat != category_filter:
            continue
        out.append({
            "row_idx": offset,
            "url": _safe_cell(row, url_col),
            "title": _safe_cell(row, title_col),
            "key_current": _safe_cell(row, key_col),  # 既書込済の AI 列 (= 既 canonical KEY)
            "category": cat,
        })
    return out


def resolve_targets_canonical_keys(
    targets: List[Dict],
    *,
    resolve_sheet_row_fn: Callable[..., str],
) -> List[Dict]:
    """各 target を resolver で canonical KEY 解決 (= AI 列既書込済優先、 未書込なら resolver).

    Returns: targets に "resolved_key" 追加した list.
    """
    out: List[Dict] = []
    for t in targets:
        # AI 列 既書込み済 (= Step 4a/4b で backfill 済) ならそのまま採用
        if t["key_current"]:
            t["resolved_key"] = t["key_current"]
            t["resolved_source"] = "ai_column"
        else:
            key = resolve_sheet_row_fn(
                title=t["title"],
                url=t["url"],
                purpose="dedup",
            )
            t["resolved_key"] = key
            t["resolved_source"] = "resolver"
        out.append(t)
    return out


def select_dup_marks(
    targets_resolved: List[Dict],
    existing_keys: Set[str],
) -> List[Dict]:
    """resolved key が existing_keys と完全一致する row のみ抽出 (= fail-closed).

    Returns: mark 対象 list (= "" 解決不能 / 不一致 は除外).
    """
    out: List[Dict] = []
    for t in targets_resolved:
        key = t.get("resolved_key") or ""
        if not key:
            continue  # 解決不能 = fail-closed
        if key in existing_keys:
            out.append(t)
    return out


def write_dup_markers(
    ws_low,
    marks: List[Dict],
    *,
    dry_run: bool = True,
    sold_col: int = LOW_COL_SOLD,
    backup_path: Optional[Path] = None,
) -> Dict:
    """mark 対象 row の D列に "DUP" 書込 (= dry-run なら print のみ).

    backup_path: 指定なら 書込前に LOW 全 row JSON dump (= rollback 用).

    Returns: {marked: N, dry_run: bool, backup_path: str, sample: [...]}.
    """
    import gspread  # 遅延

    result = {
        "marked": 0,
        "dry_run": dry_run,
        "backup_path": "",
        "sample": [],
    }
    if not marks:
        return result

    # .bak (= 本実行時のみ)
    if not dry_run and backup_path is not None:
        values = ws_low.get_all_values()
        backup = {
            "phase": "dup_marker_pre_write",
            "timestamp_iso": datetime.utcnow().isoformat() + "Z",
            "rows": values,
        }
        backup_path = Path(backup_path)
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        with backup_path.open("w", encoding="utf-8") as f:
            json.dump(backup, f, ensure_ascii=False, indent=1)
        result["backup_path"] = str(backup_path)

    # batch_update 構築
    updates = [
        {
            "range": gspread.utils.rowcol_to_a1(m["row_idx"], sold_col),
            "values": [[DUP_MARKER]],
        }
        for m in marks
    ]

    if not dry_run:
        CHUNK = 500
        for i in range(0, len(updates), CHUNK):
            ws_low.batch_update(
                updates[i : i + CHUNK], value_input_option="USER_ENTERED"
            )

    result["marked"] = len(updates)
    SAMPLE_MAX = 20
    for m in marks[:SAMPLE_MAX]:
        result["sample"].append(
            f"row {m['row_idx']:4}: key={m['resolved_key']:20} "
            f"({m.get('resolved_source', '?'):10}) title={m['title'][:40]}"
        )
    return result


def mark_dup_in_low(
    ws_high,
    ws_low,
    removed_canonical_keys: List[str],
    *,
    dry_run: bool = True,
    category_filter: Optional[str] = "G-shock",
    backup_path: Optional[Path] = None,
) -> Dict:
    """scope1: 既知の重複 KEY list (= check_csv の removed) を LOW にマーク.

    既存 existing_keys 集計不要、 直接「LOW の B空 AND D空 + 同 KEY」 を探して mark.

    Returns: write_dup_markers の結果 dict.
    """
    targets = find_b_empty_d_empty_targets(
        ws_low, category_filter=category_filter
    )
    # AI 列 既書込み済の row だけ突合 (= resolver 呼ぶ必要なし)
    # AI 列なしの場合は resolver にかける選択肢もあるが、 scope1 は known KEY なので
    # 既書込み (= Step 4a/4b 後の状態) を期待するのが現実的.
    removed_set = set(removed_canonical_keys)
    marks = [
        {**t, "resolved_key": t["key_current"] or "", "resolved_source": "ai_column"}
        for t in targets
        if t["key_current"] and t["key_current"] in removed_set
    ]
    return write_dup_markers(
        ws_low, marks, dry_run=dry_run, backup_path=backup_path
    )


def fullscan_dup_mark(
    ws_high,
    ws_low,
    *,
    resolve_sheet_row_fn: Callable[..., str],
    dry_run: bool = True,
    category_filter: Optional[str] = "G-shock",
    backup_path: Optional[Path] = None,
) -> Dict:
    """scope2: LOW B空 AND D空 全件 → resolver 解決 → 既存出品 (HIGH/LOW B非空) と一致を mark.

    依頼書 §scope2 = 初回フルスキャン一括 (= ユーザー必須要望).
    dry-run で件数報告 → ユーザー確認 → 本実行.
    """
    targets = find_b_empty_d_empty_targets(
        ws_low, category_filter=category_filter
    )
    targets_resolved = resolve_targets_canonical_keys(
        targets, resolve_sheet_row_fn=resolve_sheet_row_fn
    )
    existing_keys = collect_existing_canonical_keys(ws_high, ws_low)
    marks = select_dup_marks(targets_resolved, existing_keys)

    result = write_dup_markers(
        ws_low, marks, dry_run=dry_run, backup_path=backup_path
    )
    # scope2 統計拡張
    result["scanned"] = len(targets)
    result["resolved"] = sum(1 for t in targets_resolved if t.get("resolved_key"))
    result["unresolved"] = sum(
        1 for t in targets_resolved if not t.get("resolved_key")
    )
    result["matched_existing"] = len(marks)
    result["existing_keys_count"] = len(existing_keys)
    return result
