"""
sync_sheet_to_yaml.py - スプシ V8 → global.yaml 一方向同期

V8 FIX 2026-05-24 新規作成。 完成形 Phase 1-C に基づく。

仕様:
- 一方向: スプシ V8 → yaml のみ (= 逆同期禁止)
- sync 対象: v6_pricing.groups[A/B/C].split のみ
  (= スプシ設定 sheet r10-r30 列 F から、 グループ別 (列 E= hts_rate) に集約)
- スプシ列 E (hts_rate) は「グループ識別子」 として読む (= V7 既存運用維持)
- yaml.categories[*].hts_duty_rate は対象外 (= 別 SSOT、 yaml 直接編集)
- READY_TO_SYNC フラグ (= スプシ A1 セル等) が "ON" でなければ即 abort (= fail-closed)
- 完了時 yaml に last_synced_at: YYYY-MM-DDTHH:MM:SS+09:00 を書込
- グループ内で split 不一致なら abort (= 整合性チェック)

使い方:
  python sync_sheet_to_yaml.py

依存: gspread, pyyaml
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict

import gspread
import yaml
from google.oauth2.service_account import Credentials

# ------------ 設定 ------------
SHEET_ID = "1LnEixfUp3XnWlqjMDXXrVfL-AF6EpHJHrWRdCr-Mh8k"  # V8 スプシ
YAML_PATH = Path(r"c:\dev\iMak\iMakeBayAPI\config\global.yaml")
CREDS_PATH = Path(r"c:\dev\iMak\double-hold-421922-7c0d38d3f73d.json")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
JST = timezone(timedelta(hours=9))

# スプシ設定 sheet 列マップ (1-indexed)
COL_CATEGORY = 1  # A
COL_HTS_RATE = 5  # E (= グループ識別子)
COL_SPLIT = 6     # F

# READY_TO_SYNC フラグ位置 (= 設定 sheet の特定セル)
# A1 が "Cpa" だったので、 末尾の空き行を使う前提で A99 に配置を想定
# 未設定でも sync 進められるよう、 セル値 "ON" で許可、 それ以外 abort
READY_FLAG_CELL = "A99"  # 設定 sheet の最終行付近

# ------------ ユーティリティ ------------
def log(msg: str) -> None:
    ts = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


def hts_rate_to_group(rate: float) -> str | None:
    """スプシ列 E (hts_rate) → グループ識別。 V7 既存運用と整合"""
    if abs(rate - 0.18) < 0.001:
        return "A"
    if abs(rate - 0.30) < 0.001:
        return "B"
    if abs(rate - 0.43) < 0.001:
        return "C"
    return None  # group 不明


# ------------ main ------------
def main() -> int:
    log("=== sync_sheet_to_yaml.py 開始 ===")

    # スプシ接続
    creds = Credentials.from_service_account_file(str(CREDS_PATH), scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.worksheet("設定")

    # 1. READY_TO_SYNC フラグ確認 (= fail-closed)
    flag = ws.acell(READY_FLAG_CELL).value
    if (flag or "").strip().upper() != "ON":
        log(f"ABORT: READY_TO_SYNC フラグが ON ではない (current={flag!r})")
        log(f"  -> スプシ {READY_FLAG_CELL} に 'ON' を入力してから再実行してください")
        return 1
    log(f"OK: READY_TO_SYNC = ON")

    # 2. スプシ r10-r30 読込
    rows = ws.get(f"A10:F30")
    log(f"スプシ {len(rows)} 行読込")

    # 3. グループ別に split を集約
    group_splits: Dict[str, list[tuple[str, float]]] = {"A": [], "B": [], "C": []}
    for i, r in enumerate(rows, start=10):
        if len(r) < 6:
            continue
        cat = (r[COL_CATEGORY - 1] or "").strip()
        if not cat or cat.startswith("■"):
            continue
        try:
            hts = float(r[COL_HTS_RATE - 1])
            split = float(r[COL_SPLIT - 1])
        except (ValueError, IndexError):
            log(f"  r{i}: skip (= 数値変換不可)")
            continue
        gid = hts_rate_to_group(hts)
        if gid is None:
            log(f"  r{i}: skip (= group 不明 hts={hts})")
            continue
        group_splits[gid].append((cat, split))

    # 4. グループ内整合チェック
    group_consensus: Dict[str, float] = {}
    for gid, entries in group_splits.items():
        if not entries:
            log(f"WARN: group {gid} は スプシに 0 件")
            continue
        splits = {s for _, s in entries}
        if len(splits) > 1:
            log(f"ABORT: group {gid} 内で split 不一致: {entries}")
            return 2
        group_consensus[gid] = entries[0][1]
        log(f"  group {gid}: split={group_consensus[gid]} ({len(entries)} カテゴリ)")

    # 5. yaml 読込 (= 現状値確認用) + 検証用 parse
    yaml_text = YAML_PATH.read_text(encoding="utf-8")
    cfg = yaml.safe_load(yaml_text)
    v6 = cfg.get("v6_pricing", {})
    groups = v6.get("groups", {})

    # 6. split を pin-point regex 置換 (= 既存 yaml の flow style 維持、 最小差分)
    import re
    changed = []
    for gid, split in group_consensus.items():
        if gid not in groups:
            log(f"WARN: yaml.v6_pricing.groups.{gid} 不在、 skip")
            continue
        old_split = groups[gid].get("split")
        if old_split == split:
            continue
        # 行例: "    A: {hts_rate: 0.18, split: 1.0}  # 低関税 (TCG/G-SHOCK/玩具/文具)"
        pattern = re.compile(
            rf"^(\s+{gid}:\s*\{{[^}}]*split:\s*)([0-9.]+)(.*)$",
            re.MULTILINE,
        )
        new_text, n = pattern.subn(rf"\g<1>{split}\g<3>", yaml_text)
        if n == 0:
            log(f"ABORT: yaml 内の {gid}: split 行が見つからない (regex 不一致)")
            return 3
        if n > 1:
            log(f"ABORT: yaml 内の {gid}: split 行が複数 ({n} 件)、 曖昧で停止")
            return 4
        yaml_text = new_text
        changed.append(f"{gid}.split: {old_split} -> {split}")

    # 7. last_synced_at 書込 (= v6_pricing: 行の直後に挿入 or 既存 last_synced_at を更新)
    now_iso = datetime.now(JST).isoformat(timespec="seconds")
    new_last_synced_line = f"  last_synced_at: '{now_iso}'  # sync_sheet_to_yaml.py 自動更新\n"
    last_synced_pattern = re.compile(r"^  last_synced_at:.*$\n", re.MULTILINE)
    if last_synced_pattern.search(yaml_text):
        yaml_text = last_synced_pattern.sub(new_last_synced_line, yaml_text)
    else:
        # v6_pricing: 直下に挿入
        yaml_text = re.sub(
            r"^(v6_pricing:\s*\n)",
            r"\1" + new_last_synced_line,
            yaml_text,
            count=1,
            flags=re.MULTILINE,
        )

    # 8. yaml 書出 (= 構造変化なし、 pin-point 差分のみ)
    YAML_PATH.write_text(yaml_text, encoding="utf-8")

    log(f"yaml 更新完了:")
    if changed:
        for c in changed:
            log(f"  {c}")
    else:
        log(f"  (変更なし、 last_synced_at のみ刻印)")
    log(f"  last_synced_at: {now_iso}")
    log("=== sync_sheet_to_yaml.py 正常終了 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
