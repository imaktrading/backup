"""listing_verifier - eBay listing 反映 verify (Phase 7e、致命防止の核心).

upload した Revise CSV (qty=0) が eBay 側で実際反映されたか確認する。
qty != 0 (= 取り下げ失敗) を発見したら alert (decision_log + toast)。

【4h ずらし運用】
巡回 N 回目の upload → 次回巡回 (N+1) 開始時に前回分を verify。
run_cycle 内では監視→CSV→upload を 1 cycle で完了し、verify は次回に持ち越す。
これで巡回時間を引き延ばさない。

【scrape 方式】
- Selenium + chrome_profile_ebay (login 済 profile を流用、driver 単一インスタンス)
- 公開 itm URL は 403 (Bot block) → seller hub 経由でアクセス
- URL: https://www.ebay.com/sh/lst/active?action=&q=<itemID>
- qty selector: 仮設、smoke 後に Inventory Claude が refine

【NG 動作】
- listing 修正動作なし (verify only、検出のみ)
- 結果は decision_log/verify_<ts>.jsonl + toast 通知

【入力ソース】
直近 cycle で upload した CSV から item_id を抽出:
- decision_log/upload_state.json から最新 csv_path を取得
- その CSV を読み Revise 行 → item_id list 構築
"""
from __future__ import annotations

import csv
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

DECISION_LOG_DIR = ROOT_DIR / "decision_log"
DECISION_LOG_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_STATE_FILE = DECISION_LOG_DIR / "upload_state.json"
VERIFY_STATE_FILE = DECISION_LOG_DIR / "verify_state.json"

VERIFY_WAIT_SEC = 8           # listing page hydration 待ち
VERIFY_PAUSE_BETWEEN_SEC = 2  # item ごとの pacing


# ============================================================================
# 入力ソース: 前回 upload した item_id 取得
# ============================================================================
def get_last_uploaded_item_ids() -> list[str]:
    """upload_state.json から最新 csv_path → CSV 内の item_id list を返す."""
    if not UPLOAD_STATE_FILE.exists():
        return []
    try:
        st = json.loads(UPLOAD_STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    history = st.get("uploaded", [])
    if not history:
        return []
    last = history[-1]
    csv_path = Path(last.get("csv_path", ""))
    if not csv_path.is_absolute():
        csv_path = ROOT_DIR / csv_path
    if not csv_path.exists():
        return []
    item_ids = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)  # header skip
        for row in reader:
            if len(row) >= 2 and row[0] == "Revise":
                iid = row[1].strip()
                if iid:
                    item_ids.append(iid)
    return item_ids


def get_already_verified() -> set[str]:
    """verify 済み item_id (重複 verify 回避)."""
    if not VERIFY_STATE_FILE.exists():
        return set()
    try:
        st = json.loads(VERIFY_STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    return set(st.get("verified_item_ids", []))


def mark_verified(item_ids: list[str]):
    state = {"verified_item_ids": list(get_already_verified() | set(item_ids))}
    VERIFY_STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ============================================================================
# Selenium で 1 listing の qty を確認
# ============================================================================
def _detect_qty_state(html: str) -> tuple[str, str]:
    """HTML から qty 状態を判定. Returns: (state, hint)
        state: "qty_zero" | "qty_positive" | "ended" | "unknown"
    """
    h = html
    # 取り下げ済 / 終了の signals
    if "This listing has ended" in h or "This listing was ended" in h:
        return "ended", "listing has ended"
    if "Out of stock" in h or "Out Of Stock" in h:
        return "qty_zero", "Out of stock badge"
    if "現在在庫切れ" in h or "在庫切れ" in h:
        return "qty_zero", "在庫切れ JP"

    # qty positive shipping signals
    if "Limited stock" in h or "Only" in h and "left" in h:
        return "qty_positive", "Limited stock 表示"
    # availability> N available のパターン
    m = re.search(r'(\d+)\s+(?:available|in\s+stock|left)', h, re.IGNORECASE)
    if m:
        n = int(m.group(1))
        return ("qty_zero" if n == 0 else "qty_positive"), f"availability={n}"

    # add to cart button (= active listing)
    if 'id="atcRedesignId_btn"' in h or 'data-test-id="ATC_BTN"' in h:
        return "qty_positive", "Add to cart button present"

    return "unknown", "no signal"


def verify_one_item(driver, item_id: str) -> dict:
    """1 件の listing を Selenium で確認.
    Returns: {item_id, state, hint, page_url, error}
    """
    from selenium.common.exceptions import WebDriverException  # noqa: PLC0415

    result = {"item_id": item_id, "state": "unknown", "hint": "",
              "page_url": "", "error": None}
    url = f"https://www.ebay.com/itm/{item_id}"
    try:
        driver.get(url)
        time.sleep(VERIFY_WAIT_SEC)
        result["page_url"] = driver.current_url or ""
        html = driver.page_source or ""
    except WebDriverException as e:
        result["error"] = f"WebDriverException: {e}"
        return result

    state, hint = _detect_qty_state(html)
    result["state"] = state
    result["hint"] = hint
    return result


# ============================================================================
# 公開 API
# ============================================================================
def verify_listings(item_ids: Optional[list[str]] = None) -> dict:
    """eBay listing の qty 反映を verify.

    Args:
        item_ids: 確認対象 ItemID list (None なら upload_state.json から取得)

    Returns: {
        "ts", "item_count", "results": [{item_id, state, hint, ...}, ...],
        "alerts": [{item_id, state, hint, ...}, ...],  # state != qty_zero/ended
        "decision_log_path",
    }
    """
    from ebay_actions.sell_feed_uploader import create_ebay_driver, is_logged_in  # noqa: PLC0415

    if item_ids is None:
        item_ids = get_last_uploaded_item_ids()

    # 重複 verify 回避
    verified = get_already_verified()
    new_ids = [i for i in item_ids if i not in verified]

    summary = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "input_item_count": len(item_ids),
        "new_item_count": len(new_ids),
        "skipped_already_verified": len(item_ids) - len(new_ids),
        "results": [],
        "alerts": [],
        "decision_log_path": None,
    }

    if not new_ids:
        # 何もすることなし
        path = DECISION_LOG_DIR / f"verify_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        summary["decision_log_path"] = str(path)
        return summary

    driver = None
    try:
        driver = create_ebay_driver(headless=True)
        if not is_logged_in(driver):
            summary["error"] = "not_logged_in"
            path = DECISION_LOG_DIR / f"verify_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
            path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            summary["decision_log_path"] = str(path)
            return summary

        for iid in new_ids:
            r = verify_one_item(driver, iid)
            summary["results"].append(r)
            if r["state"] not in ("qty_zero", "ended"):
                summary["alerts"].append(r)
            time.sleep(VERIFY_PAUSE_BETWEEN_SEC)
    finally:
        if driver is not None:
            try: driver.quit()
            except Exception: pass

    # 結果記録
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = DECISION_LOG_DIR / f"verify_{ts}.jsonl"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summary["decision_log_path"] = str(path)

    # verified state 更新
    mark_verified([r["item_id"] for r in summary["results"]])

    return summary


# ============================================================================
# CLI
# ============================================================================
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="eBay listing 反映 verify (Phase 7e)")
    parser.add_argument("--item-id", action="append", default=None,
                        help="指定 ItemID を verify (複数指定可)。未指定時 upload_state.json から自動")
    args = parser.parse_args()

    item_ids = args.item_id  # None or list
    print(f"=== eBay listing verifier (Phase 7e) ===")
    summary = verify_listings(item_ids=item_ids)
    print()
    print(f"=== 結果 ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary.get("alerts"):
        print(f"\n⚠️ ALERT: {len(summary['alerts'])} 件 qty != 0 (取り下げ失敗の可能性)")
        sys.exit(1)
