"""diagnostic: listing_verifier の取得 URL 妥当性検証 (Phase 7 #2).

実 Selenium で https://www.ebay.com/itm/<id> を取得し、
HTTP 相当のシグナル + HTML 内容をレポートする。

判定基準:
  - 200 OK 相当 (実 listing 内容が見える)              → 現状維持
  - 403/login wall (空 HTML / login form のみ)         → seller hub 経由に切替

使い方:
  python tools/verify_itm_url_diag.py [item_id1 item_id2 ...]
  (引数なしで upload_state.json から最新 upload 分を取得)

出力: stdout に判定結果 + decision_log/itm_url_diag_<ts>.jsonl
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DECISION_LOG_DIR = ROOT / "decision_log"
DECISION_LOG_DIR.mkdir(parents=True, exist_ok=True)


def diagnose(item_ids: list[str]) -> dict:
    from ebay_actions.sell_feed_uploader import create_ebay_driver, is_logged_in
    from ebay_actions.listing_verifier import _detect_qty_state

    summary = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "item_count": len(item_ids),
        "results": [],
        "verdict": "unknown",
    }

    if not item_ids:
        summary["verdict"] = "no_input"
        return summary

    driver = None
    try:
        driver = create_ebay_driver(headless=True)
        logged = is_logged_in(driver)
        summary["logged_in"] = logged

        for iid in item_ids:
            url = f"https://www.ebay.com/itm/{iid}"
            entry = {"item_id": iid, "requested_url": url}
            try:
                driver.get(url)
                time.sleep(6)
                entry["current_url"] = driver.current_url or ""
                html = driver.page_source or ""
                entry["html_len"] = len(html)
                entry["title"] = driver.title or ""
                # キーシグナル抽出
                signals = {
                    "has_atc_btn": 'id="atcRedesignId_btn"' in html,
                    "has_atc_btn_v2": 'data-test-id="ATC_BTN"' in html,
                    "has_listing_ended": "This listing has ended" in html,
                    "has_out_of_stock": "Out of stock" in html or "Out Of Stock" in html,
                    "has_login_form": "Sign in to" in html and "passwordType" in html,
                    "has_blocked_403": "403 Forbidden" in html or "Access Denied" in html,
                    "has_limited_stock": "Limited stock" in html,
                    "redirected_to_login": "/signin/" in (driver.current_url or ""),
                    "stayed_on_itm_path": f"/itm/{iid}" in (driver.current_url or ""),
                }
                entry["signals"] = signals
                state, hint = _detect_qty_state(html)
                entry["new_state"] = state
                entry["new_hint"] = hint
            except Exception as e:
                entry["error"] = f"{type(e).__name__}: {e}"
            summary["results"].append(entry)
            time.sleep(2)
    finally:
        if driver is not None:
            try: driver.quit()
            except Exception: pass

    # 判定
    n_ok = sum(
        1 for r in summary["results"]
        if r.get("signals", {}).get("stayed_on_itm_path")
        and not r.get("signals", {}).get("redirected_to_login")
        and not r.get("signals", {}).get("has_blocked_403")
        and r.get("html_len", 0) > 5000
    )
    if n_ok == len(item_ids):
        summary["verdict"] = "200_ok_keep_itm_url"
    elif n_ok == 0:
        summary["verdict"] = "all_failed_consider_seller_hub"
    else:
        summary["verdict"] = "partial_review_individually"

    return summary


def main():
    if len(sys.argv) > 1:
        ids = sys.argv[1:]
    else:
        # upload_state.json から最新を取得
        from ebay_actions.listing_verifier import get_last_uploaded_item_ids
        ids = get_last_uploaded_item_ids()
    if not ids:
        print("no item_ids; pass via argv or run after a real upload")
        sys.exit(0)
    print(f"diagnosing {len(ids)} items: {ids[:5]}{'...' if len(ids) > 5 else ''}")
    summary = diagnose(ids)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = DECISION_LOG_DIR / f"itm_url_diag_{ts}.jsonl"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nsaved: {out}")
    print(f"\n=== VERDICT: {summary['verdict']} ===")


if __name__ == "__main__":
    main()
