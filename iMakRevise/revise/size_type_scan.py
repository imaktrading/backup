"""size_type_scan.py - 3XL以上 Size Type 残存スキャン (read-only、直さない).

窓口回答 2026-09-12_size_type_3xl_remaining_items_response.md [IMPLEMENT-GO] に従う実装。
Size Type が効くのは衣類 (商品管理シート R列 = Tシャツ / アウトドア・ジャケット) だけなので、
その行だけ GetItem (IncludeItemSpecifics=true) で Department/Size/Size Type を読み、
「3XL以上なのに Size Type が Regular のまま」の itemID を一覧化する。

判定: ②出品くんの Size Type 決め方の残存不具合調査 (カタログ無関係、依頼書に明記済)。
直すのはまだ。ここでは読んで報告するだけ。
"""
from __future__ import annotations

import csv
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from revise import price_revise, ebay_trading_api  # noqa: E402

# 窓口指定の対象カテゴリ (商品管理シート R列 生値、2026-09-14実測: Tシャツ79/アウトドア・ジャケット2)
TARGET_CATEGORIES = {"Tシャツ", "アウトドア・ジャケット"}

# listing_common.size_type_for の判定表 (本元 SSOT、read-only import。price_revise.py の
# _import_v8_pricing() と同じ既存パターンを踏襲、修正連鎖回避のため複製しない)
_IMAK_EBAY_API_PATH = r"C:/dev/iMak/iMakeBayAPI"


def import_size_type_for() -> Callable[[str], str]:
    if _IMAK_EBAY_API_PATH not in sys.path:
        sys.path.insert(0, _IMAK_EBAY_API_PATH)
    from listing_common import size_type_for  # type: ignore  # noqa: PLC0415
    return size_type_for


def collect_target_rows(sheet_keys=("HIGH", "LOW")) -> list:
    """商品管理シート R列 in TARGET_CATEGORIES かつ B列(itemID)あり の行を抽出.

    Returns: [{"item_id":.., "category":.., "title":.., "sheet": "HIGH"/"LOW"}, ...]
    """
    targets = []
    for sheet_key in sheet_keys:
        _, rows, _, schema = price_revise.load_sheet_rows(sheet_key)
        if schema != "high_low":
            continue
        for row in rows:
            if len(row) <= price_revise.COL_CATEGORY:
                continue
            item_id = (row[price_revise.COL_ITEM_ID] or "").strip() if len(row) > price_revise.COL_ITEM_ID else ""
            category = (row[price_revise.COL_CATEGORY] or "").strip()
            if not item_id or category not in TARGET_CATEGORIES:
                continue
            title = (row[price_revise.COL_TITLE] or "").strip() if len(row) > price_revise.COL_TITLE else ""
            targets.append({"item_id": item_id, "category": category, "title": title, "sheet": sheet_key})
    return targets


def judge_item(size: Optional[str], size_type: Optional[str],
                size_type_for_fn: Callable[[str], str]) -> Optional[dict]:
    """現在の Size/Size Type が eBay 規則 (size_type_for) と食い違えば問題 dict を返す (純関数).

    Size/SizeType いずれか未取得なら判定不能として None (= 誤検知しない、fail-closed)。
    """
    if not size or not size_type:
        return None
    expected = size_type_for_fn(size)
    current = size_type.strip()
    if current != expected:
        return {"size": size, "current_size_type": current, "expected_size_type": expected}
    return None


def scan(targets: list, size_type_for_fn: Optional[Callable[[str], str]] = None,
          sleep_sec: float = 0.5, verbose: bool = True) -> list:
    """targets の各 itemID を GetItem し、Size Type 不整合を検出.

    Returns: [{"item_id", "sheet", "category", "title", "department",
               "size", "current_size_type", "expected_size_type"}, ...]
    """
    if size_type_for_fn is None:
        size_type_for_fn = import_size_type_for()
    problems = []
    access_token = ebay_trading_api.load_access_token()
    for i, t in enumerate(targets, 1):
        if verbose:
            print(f"  [{i}/{len(targets)}] GetItem {t['item_id']} ({t['category']}) ...", flush=True)
        specifics = ebay_trading_api.get_item_specifics(t["item_id"], access_token=access_token)
        if specifics.get("error"):
            if verbose:
                print(f"    [WARN] 取得失敗: {specifics['error']}")
            continue
        problem = judge_item(specifics.get("size"), specifics.get("size_type"), size_type_for_fn)
        if problem:
            problems.append({**t, "department": specifics.get("department"), **problem})
        if i < len(targets) and sleep_sec > 0:
            time.sleep(sleep_sec)
    return problems


def write_report(problems: list, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"size_type_3xl_scan_{ts}.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["item_id", "sheet", "category", "title", "department",
                          "size", "current_size_type", "expected_size_type"])
        for p in problems:
            writer.writerow([p["item_id"], p["sheet"], p["category"], p["title"],
                              p.get("department", ""), p["size"], p["current_size_type"],
                              p["expected_size_type"]])
    return path


def main():
    targets = collect_target_rows()
    print(f"対象 {len(targets)} 件 (Tシャツ/アウトドア・ジャケット かつ itemIDあり)")
    problems = scan(targets)
    print(f"問題 {len(problems)} 件")
    if problems:
        path = write_report(problems, PROJECT_ROOT / "decision_log")
        print(f"report: {path}")
    else:
        print("問題なし (0件)")


if __name__ == "__main__":
    main()
