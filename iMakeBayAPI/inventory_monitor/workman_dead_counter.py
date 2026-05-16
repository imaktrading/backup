"""workman_dead_counter - Workman 廃番判定 7 日カウンター + Catalog API 通知.

Phase 2 (2026-05-16): Workman variation 化対応の廃番判定 logic。

判定条件 (= 仕様書 v2 section 6.2):
- AJAX 404 / endpoint 消失 → parent_mpn 廃番 (即時)
- 全 variant 連続 7 日 `no-stock` → parent_mpn 廃番

state file: `logs/_workman_dead_counter.json`
形式:
{
  "parent_mpn": {
    "first_all_nostock_date": "2026-05-16",
    "consecutive_days": 1,
    "last_check_date": "2026-05-16"
  }
}

廃番確定時: Catalog API (`update_active_status(product_id, is_active=False)`) 呼出。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
STATE_FILE = SCRIPT_DIR / "logs" / "_workman_dead_counter.json"
DEAD_THRESHOLD_DAYS = 7


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def update_workman_dead_counter(parent_mpn: str, all_nostock: bool,
                                today: Optional[date] = None) -> dict:
    """1 cycle 分の廃番カウンター update.

    Args:
        parent_mpn: 13 桁
        all_nostock: 今 cycle で全 variant が no-stock だったか
        today: date object (test 用、default 今日)

    Returns: {"is_dead": bool, "consecutive_days": int, "should_notify_catalog": bool}
    """
    today = today or date.today()
    today_str = today.isoformat()
    state = _load_state()
    entry = state.get(parent_mpn, {})

    if not all_nostock:
        # 在庫あり → counter reset
        if parent_mpn in state:
            del state[parent_mpn]
        _save_state(state)
        return {"is_dead": False, "consecutive_days": 0, "should_notify_catalog": False}

    # 全 no-stock
    first_date_str = entry.get("first_all_nostock_date")
    if not first_date_str:
        # 初回検知
        state[parent_mpn] = {
            "first_all_nostock_date": today_str,
            "consecutive_days": 1,
            "last_check_date": today_str,
        }
        _save_state(state)
        return {"is_dead": False, "consecutive_days": 1, "should_notify_catalog": False}

    # 既存 entry update
    first_date = date.fromisoformat(first_date_str)
    days = (today - first_date).days + 1
    last_check = entry.get("last_check_date", first_date_str)

    # gap check (= 一度でも在庫復活した場合、その時点で reset されてるはず)
    # ここに来てる = 連続 no-stock の継続中
    state[parent_mpn] = {
        "first_all_nostock_date": first_date_str,
        "consecutive_days": days,
        "last_check_date": today_str,
    }
    _save_state(state)

    is_dead = days >= DEAD_THRESHOLD_DAYS
    # 廃番判定の遷移瞬間のみ catalog 通知 (= last_check より前は通知してない)
    last_check_date = date.fromisoformat(last_check)
    last_days = (last_check_date - first_date).days + 1
    just_crossed = (last_days < DEAD_THRESHOLD_DAYS) and is_dead

    return {
        "is_dead": is_dead,
        "consecutive_days": days,
        "should_notify_catalog": just_crossed,
    }


def mark_ajax_failed(parent_mpn: str) -> dict:
    """AJAX 失敗 (= 404 / endpoint 消失) → 即時廃番判定."""
    state = _load_state()
    state[parent_mpn] = {
        "first_all_nostock_date": date.today().isoformat(),
        "consecutive_days": DEAD_THRESHOLD_DAYS,   # 即廃番扱い
        "last_check_date": date.today().isoformat(),
        "reason": "ajax_failed",
    }
    _save_state(state)
    return {"is_dead": True, "consecutive_days": DEAD_THRESHOLD_DAYS,
            "should_notify_catalog": True}


def notify_catalog_dead(parent_mpn: str) -> bool:
    """Catalog API に廃番通知.

    Catalog 側で `update_active_status(product_id, is_active=False)` を expose してる想定。
    Phase 2 v2 で Catalog 側追加予定 (Catalog Claude 担当)。
    現状は state file 更新 + log 出力のみ、Catalog API ready 時に切替。

    Returns: True=通知済 (or stub success), False=失敗
    """
    # Catalog 側 API ready まで stub 実装
    print(f"  [workman_dead_counter] catalog 廃番通知 (stub): "
          f"product_id=workman:series:{parent_mpn[-5:]} parent_mpn={parent_mpn}",
          flush=True)
    return True


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Workman 廃番カウンター CLI")
    parser.add_argument("parent_mpn")
    parser.add_argument("--all-nostock", action="store_true")
    parser.add_argument("--ajax-failed", action="store_true")
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()

    if args.show:
        print(json.dumps(_load_state(), ensure_ascii=False, indent=2))
        sys.exit(0)
    if args.ajax_failed:
        r = mark_ajax_failed(args.parent_mpn)
    else:
        r = update_workman_dead_counter(args.parent_mpn, args.all_nostock)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    if r.get("should_notify_catalog"):
        notify_catalog_dead(args.parent_mpn)
