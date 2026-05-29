"""check_ebay_login - eBay session の有効性 check + 残時間推定 alert.

cron で 1h おき実行を想定。 session 切れ検知時に alert email (= 操作者が
朝の作業開始時に「今 login 必要」 を 早期把握できる)。

実行:
    python check_ebay_login.py
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def check_login_state() -> bool:
    """eBay 上 session 有効か headless で確認."""
    try:
        sys.path.insert(0, r"C:\dev\iMak_inventory\iMakInventory")
        from ebay_actions.sell_feed_uploader import (   # noqa: PLC0415
            create_ebay_driver, is_logged_in,
        )
    except Exception as e:
        _log(f"[NG] module 不在: {e}")
        return False

    driver = None
    try:
        driver = create_ebay_driver(headless=True, use_profile=True)
        return is_logged_in(driver)
    except Exception as e:
        _log(f"[NG] driver 起動失敗: {type(e).__name__}: {e}")
        return False
    finally:
        if driver:
            try: driver.quit()
            except Exception: pass


def send_alert_email(logged_in: bool):
    """login 切れ時 alert email."""
    if logged_in:
        return
    try:
        from email_notifier import _send_via_gmail   # noqa: PLC0415
        from auth.encrypted_gmail import load_gmail_config   # noqa: PLC0415
    except Exception as e:
        _log(f"  [WARN] email module 不在: {e}")
        return
    cfg = load_gmail_config()
    if cfg is None:
        return
    addr, pw, to = cfg
    subj = "[公式監視くん login] eBay session 切れ検知、 手動 re-login 要"
    body = ("\n".join([
        "eBay session 切れを check_ebay_login.py が検知しました。",
        "",
        "復旧手順:",
        "  1. C:\\トラバホセット\\BoostListing\\BoostListing\\chrome\\chromep.exe を起動",
        "     --user-data-dir=C:\\Users\\imax2\\local_data\\iMakInventory\\chrome_profile_ebay2",
        "  2. eBay にログイン",
        "  3. https://www.ebay.com/myb/Summary で MyeBay 画面 表示確認",
        "  4. window 閉じる",
        "",
        "復旧前は upload 系 cron が連鎖失敗します。 早めの対応推奨。",
    ]))
    try:
        _send_via_gmail(addr, pw, to, subj, body)
        _log(f"  [alert] email 送信: {subj}")
    except Exception as e:
        _log(f"  [alert] email 送信失敗: {type(e).__name__}: {e}")


def main():
    _log("eBay session check 開始")
    logged_in = check_login_state()
    _log(f"  is_logged_in: {logged_in}")
    if not logged_in:
        _log("  [ALERT] session 切れ確定 → email 送信")
        send_alert_email(logged_in)
        sys.exit(1)
    _log("  [OK] session 有効")


if __name__ == "__main__":
    main()
