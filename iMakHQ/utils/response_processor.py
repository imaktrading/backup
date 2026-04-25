#!/usr/bin/env python3
"""iMak Trading Japan - eBay File Exchange Response 自動学習プロセッサ

eBay File Exchange アップロード後に返ってくる Response CSV を読み、
- Failure 行を検出
- 元の upload CSV と CustomLabel で突合 → 該当行の Item Specifics を取得
- iMakHQ/tests/fixtures_listing.json の FAILURE_CASES に重複なく追加
- iMakHQ/review_logs/ebay_failure_log.jsonl に詳細記録

これにより、eBay からの「拒絶」が自動で回帰テストの fixture に組み込まれ、
次回以降 audit_csv_row が同じパターンを未然に物理ブロックする。

実行:
  python iMakHQ/utils/response_processor.py <response_csv> [<upload_csv>]

upload_csv 省略時は同名の "<base>-upload.csv" 等を自動推定（命名規則次第で要修正）。
"""
import csv
import json
import sys
import os
import re
from pathlib import Path
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

WORKSPACE = Path(__file__).resolve().parent.parent.parent  # iMak_workspace/
FIXTURES_PATH = WORKSPACE / "iMakHQ" / "tests" / "fixtures_listing.json"
FAILURE_LOG_PATH = WORKSPACE / "iMakHQ" / "review_logs" / "ebay_failure_log.jsonl"
CSV_OUTPUT_DIR = WORKSPACE / "iMakHQ" / "csv_output"


# eBay エラーコード → audit_csv_row フィールド名 マッピング (既知パターンのみ)
# 未マッピングは "*Title" や該当ErrorMessage内のフィールド名から抽出
EBAY_ERROR_TO_FIELD = {
    "21919308": "C:Features",  # Features value too long
    "21919189": "C:Brand",      # Brand required
    "21916664": "*Title",       # Title length issue
    # 追加随時
}


def parse_response_csv(response_csv_path: str) -> list:
    """eBay File Exchange Response CSV を読み、Failure行を抽出。
    Returns: [{"sku": ..., "error_code": ..., "error_message": ..., "field": ...}, ...]
    """
    failures = []
    with open(response_csv_path, 'r', encoding='utf-8-sig', newline='', errors='replace') as f:
        reader = csv.DictReader(f)
        for row in reader:
            status = (row.get("Status") or "").strip()
            error_code = (row.get("ErrorCode") or "").strip()
            if status.lower() != "failure" and not error_code:
                continue
            sku = (row.get("CustomLabel") or "").strip()
            error_message = (row.get("ErrorMessage") or "").strip()
            # ErrorMessage から フィールド名を抽出 (例: "Features's value of...")
            field = EBAY_ERROR_TO_FIELD.get(error_code, "")
            if not field:
                # Heuristic: "<Field>'s value..." or "Field <Name>..."
                m = re.search(r"^([A-Za-z][A-Za-z0-9 ]+?)['\"]s value", error_message)
                if m:
                    field_name = m.group(1).strip()
                    # eBay UI 名 → 内部キー
                    field = f"C:{field_name}" if field_name not in ("Title", "Category", "StartPrice", "ConditionID") else f"*{field_name}"
            failures.append({
                "sku": sku,
                "error_code": error_code,
                "error_message": error_message[:500],  # 切り詰め
                "field": field,
                "line_number": row.get("Line Number", ""),
                "item_id": row.get("ItemID", ""),
            })
    return failures


def find_upload_csv(response_csv_path: str) -> str:
    """response CSV のパスから対応する upload CSV を推定。
    eBay は "<original>-Apr-2026-XX-XX-XX-XXXXXXXXX.csv" の形式で返してくるので、先頭部分を抽出。
    """
    base = Path(response_csv_path).stem  # 拡張子除く
    # "reel_upload_20260423_135857-Apr-2026-..." → "reel_upload_20260423_135857"
    m = re.match(r"^(\w+_upload_\d{8}_\d{6})", base)
    if m:
        candidate = CSV_OUTPUT_DIR / f"{m.group(1)}.csv"
        if candidate.exists():
            return str(candidate)
    # フォールバック: 同じディレクトリ内で _upload_ パターン検索
    for f in CSV_OUTPUT_DIR.glob("*_upload_*.csv"):
        if f.stem in response_csv_path:
            return str(f)
    return ""


def load_upload_csv_by_sku(upload_csv_path: str) -> dict:
    """upload CSV を読み、CustomLabel(SKU) → 全行データの dict を返す"""
    if not upload_csv_path or not os.path.exists(upload_csv_path):
        return {}
    out = {}
    with open(upload_csv_path, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            sku = (row.get("CustomLabel") or "").strip()
            if sku:
                out[sku] = row
    return out


def build_fixture_entry(failure: dict, original_row: dict, response_csv_name: str) -> dict:
    """Failure + 元Row → fixtures_listing.json の FAILURE_CASES エントリ生成"""
    sku = failure["sku"]
    name = f"AutoFromEbay_{sku}_{failure['error_code']}"
    # row は eBay必須項目のみに絞って fixture サイズを抑制
    keys_to_keep = (
        "*Title", "*Category", "*StartPrice", "ConditionID", "ConditionDescription",
        "C:Brand", "C:Features", "CustomLabel",
    )
    row_for_fixture = {k: original_row.get(k, "") for k in keys_to_keep if k in original_row}
    # category 推定: SKU prefix から
    sku_upper = sku.upper()
    category = None
    if sku_upper.startswith("REEL"):
        category = "reel"
    elif sku_upper.startswith("PORT"):
        category = "porter"
    elif sku_upper.startswith("TSHT") or sku_upper.startswith("TSHIRT"):
        category = "tshirt"
    elif sku_upper.startswith("MONT"):
        category = "montbell"
    elif sku_upper.startswith("KUJI"):
        category = "ichibankuji"
    elif sku_upper.startswith("TOMI"):
        category = "tomica"
    elif sku_upper.startswith("GSHK"):
        category = "gshock"
    elif sku_upper.startswith("STRADIC") or sku_upper.startswith("BASS") or sku_upper.startswith("DAIWA"):
        # 旧 SKU prefixの推定（SKU命名規則変わる前のもの）
        category = "reel"
    return {
        "name": name,
        "category": category,
        "mercari_state": "",  # 不明
        "row": row_for_fixture,
        "expected_error_field": failure["field"] or "*Title",
        "_meta": {
            "source": "ebay_response_auto",
            "response_csv": response_csv_name,
            "ebay_error_code": failure["error_code"],
            "ebay_error_message": failure["error_message"][:200],
            "added_ts": datetime.now().isoformat(),
        },
    }


def append_to_failure_log(failures: list, response_csv_name: str) -> None:
    """ebay_failure_log.jsonl に全 failure を追記（fixture追加可否を問わず記録）"""
    FAILURE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with FAILURE_LOG_PATH.open("a", encoding="utf-8") as f:
        for fl in failures:
            entry = {
                "ts": datetime.now().isoformat(),
                "response_csv": response_csv_name,
                **fl,
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def update_fixtures(new_entries: list) -> tuple:
    """fixtures_listing.json に new_entries を重複排除して追加。
    Returns: (added_count, skipped_count)
    """
    if not FIXTURES_PATH.exists():
        fixtures = {"SUCCESS_CASES": [], "FAILURE_CASES": []}
    else:
        with FIXTURES_PATH.open("r", encoding="utf-8") as f:
            fixtures = json.load(f)
    existing_names = {c.get("name", "") for c in fixtures.get("FAILURE_CASES", [])}
    added = 0
    skipped = 0
    for entry in new_entries:
        if entry["name"] in existing_names:
            skipped += 1
            continue
        fixtures["FAILURE_CASES"].append(entry)
        existing_names.add(entry["name"])
        added += 1
    if added > 0:
        with FIXTURES_PATH.open("w", encoding="utf-8") as f:
            json.dump(fixtures, f, ensure_ascii=False, indent=2)
    return added, skipped


def process_response(response_csv_path: str, upload_csv_path: str = None) -> dict:
    """メイン: response → failure抽出 → 元row取得 → fixture追加 + log記録
    Returns: 統計dict
    """
    if not os.path.exists(response_csv_path):
        return {"error": f"Response CSV not found: {response_csv_path}"}
    failures = parse_response_csv(response_csv_path)
    response_csv_name = Path(response_csv_path).name
    if not failures:
        return {"failures": 0, "added": 0, "skipped": 0, "log_path": str(FAILURE_LOG_PATH)}
    # upload CSV 推定
    if not upload_csv_path:
        upload_csv_path = find_upload_csv(response_csv_path)
    upload_rows = load_upload_csv_by_sku(upload_csv_path) if upload_csv_path else {}
    # fixture entry 生成
    new_entries = []
    for fl in failures:
        original = upload_rows.get(fl["sku"], {})
        if not original:
            continue  # 元Row無しは fixture化スキップ (logには残る)
        new_entries.append(build_fixture_entry(fl, original, response_csv_name))
    # 適用
    append_to_failure_log(failures, response_csv_name)
    added, skipped = update_fixtures(new_entries)
    return {
        "response_csv": response_csv_name,
        "upload_csv": Path(upload_csv_path).name if upload_csv_path else None,
        "failures": len(failures),
        "matched_to_upload": len(new_entries),
        "fixture_added": added,
        "fixture_skipped_dup": skipped,
        "log_path": str(FAILURE_LOG_PATH),
        "fixtures_path": str(FIXTURES_PATH),
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python response_processor.py <response_csv> [<upload_csv>]")
        sys.exit(1)
    response_csv = sys.argv[1]
    upload_csv = sys.argv[2] if len(sys.argv) > 2 else None
    result = process_response(response_csv, upload_csv)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
