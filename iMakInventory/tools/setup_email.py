"""setup_email - Gmail SMTP 認証情報を DPAPI 暗号化保存する初回セットアップツール.

使い方:
    python tools/setup_email.py

App Password 発行手順:
    1. https://myaccount.google.com/apppasswords にアクセス (要 2 段階認証 ON)
    2. アプリ名「iMakInventory」で発行
    3. 表示された 16 文字 (スペース含む / 含まずどちらでも OK) を入力

保存先: decision_log/.encrypted_gmail.dat
(.gitignore で commit から除外済)

確認:
    python tools/setup_email.py --check

送信テスト (保存後の smoke test):
    python tools/setup_email.py --test

ロールバック (= 即時送信停止):
    python tools/setup_email.py --delete
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auth.encrypted_gmail import (  # noqa: E402
    save_gmail_config, load_gmail_config, has_gmail_config, delete_gmail_config,
    ENCRYPTED_GMAIL_FILE,
)


def cmd_setup():
    print("=" * 60)
    print("Gmail SMTP 認証情報 暗号化セットアップ (DPAPI)")
    print("=" * 60)
    print(f"保存先: {ENCRYPTED_GMAIL_FILE}")
    print()
    print("注意:")
    print("  - Gmail App Password が必要 (通常パスワードは使えない)")
    print("    発行: https://myaccount.google.com/apppasswords")
    print("  - DPAPI 暗号化、同一 Windows ユーザー + 同一マシンのみ復号可能")
    print("  - .gitignore で commit から除外されています")
    print("  - 削除すると cycle 完了メールが止まります")
    print()

    if has_gmail_config():
        old = load_gmail_config()
        print(f"⚠️ 既に保存済 (address={old[0]}, to={old[2]})。上書きしますか? [y/N]: ", end="")
        ans = input().strip().lower()
        if ans != "y":
            print("中止しました")
            return

    print()
    address = input("送信元 Gmail アドレス (例: imax2303@gmail.com): ").strip()
    if not address:
        print("⚠️ address が空、中止")
        return
    if "@" not in address:
        print(f"⚠️ Gmail アドレス形式不正: {address}、中止")
        return

    app_password = getpass.getpass("Gmail App Password (16 文字、非表示): ").strip()
    if not app_password:
        print("⚠️ app_password が空、中止")
        return
    if len(app_password.replace(" ", "")) != 16:
        print(f"⚠️ App Password は 16 文字 (スペース除く) のはず、入力長={len(app_password.replace(' ', ''))}")
        print("  続行しますか? [y/N]: ", end="")
        if input().strip().lower() != "y":
            print("中止しました")
            return

    to_default = address
    to_input = input(f"通知メール送信先 (default: {to_default}): ").strip()
    to = to_input if to_input else to_default

    save_gmail_config(address, app_password, to)
    print()
    print(f"✅ 保存完了: {ENCRYPTED_GMAIL_FILE}")
    print(f"   address = {address}")
    print(f"   to      = {to}")
    print()
    print("次に動作確認:")
    print("  python tools/setup_email.py --test")


def cmd_check():
    print(f"保存先: {ENCRYPTED_GMAIL_FILE}")
    if not ENCRYPTED_GMAIL_FILE.exists():
        print("❌ ファイル不在 (= opt-in 未有効化、cycle メールは送信されない)")
        sys.exit(1)
    cfg = load_gmail_config()
    if cfg is None:
        print("❌ ファイル存在するが復号失敗 (別ユーザー/別マシン or 破損)")
        sys.exit(2)
    address, _pw, to = cfg
    print(f"✅ 復号成功: address={address}, to={to} (app_password は非表示)")


def cmd_delete():
    if delete_gmail_config():
        print(f"✅ 削除完了: {ENCRYPTED_GMAIL_FILE}")
        print("  → cycle 完了メールは送信されなくなります")
    else:
        print(f"ファイル不在: {ENCRYPTED_GMAIL_FILE}")


def cmd_test():
    """ダミー cycle_log で 1 通送信 (smoke test)."""
    if not has_gmail_config():
        print("❌ credentials 未保存。先に `python tools/setup_email.py` を実行してください")
        sys.exit(1)

    print("ダミー cycle_log で送信テスト中...")
    from email_notifier import send_cycle_report  # noqa: PLC0415
    dummy_log = {
        "ts_start": "2026-05-09T12:34:56",
        "ts_end": "2026-05-09T13:00:00",
        "sheet": "both",
        "test_mode": True,
        "status": "success",
        "phases": {
            "monitor": {"processed": 100, "newly_sold": 1, "newly_in_stock": 0, "errors": 0},
            "revise_csv": {"candidates": 1, "allowed": 1, "deferred": 0, "reason": "OK"},
            "upload": {"success": True, "csv_lines": 1,
                       "result_text": "Warning 1 + safe Failure 0 + action-needed Failure 0",
                       "error": None},
            "upload_health": {"alert_fired": False, "reason": "",
                              "not_logged_in_streak": 0, "flaky_streak": 0,
                              "generic_failure_streak": 0},
        },
    }
    res = send_cycle_report(dummy_log)
    if res.get("sent"):
        print("✅ 送信成功 (受信箱を確認してください)")
    else:
        print(f"❌ 送信失敗: {res}")
        sys.exit(3)


def main():
    p = argparse.ArgumentParser(description="Gmail SMTP 認証情報 セットアップ")
    p.add_argument("--check", action="store_true", help="保存済 config を確認 (read-only)")
    p.add_argument("--delete", action="store_true", help="config を削除 (即時送信停止)")
    p.add_argument("--test", action="store_true", help="ダミー cycle_log で送信テスト")
    args = p.parse_args()

    if sum([args.check, args.delete, args.test]) > 1:
        print("❌ --check / --delete / --test は排他")
        sys.exit(2)

    if args.check:
        cmd_check()
    elif args.delete:
        cmd_delete()
    elif args.test:
        cmd_test()
    else:
        cmd_setup()


if __name__ == "__main__":
    main()
