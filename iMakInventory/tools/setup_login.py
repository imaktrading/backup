"""setup_login - eBay credentials を DPAPI 暗号化保存する初回セットアップツール.

使い方:
    python tools/setup_login.py

入力時 password は非表示 (getpass)。保存先は decision_log/.encrypted_passwd.dat
(.gitignore で commit から除外済)。

ロールバック (= 旧挙動 = 手動 prompt manual_login に戻す):
    python tools/setup_login.py --delete

確認:
    python tools/setup_login.py --check
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

from auth.encrypted_passwd import (  # noqa: E402
    save_credentials, load_credentials, has_credentials, delete_credentials,
    ENCRYPTED_PASSWD_FILE,
)


def cmd_setup():
    print("=" * 60)
    print("eBay credentials 暗号化セットアップ (DPAPI)")
    print("=" * 60)
    print(f"保存先: {ENCRYPTED_PASSWD_FILE}")
    print()
    print("注意:")
    print("  - DPAPI 暗号化のため、同一 Windows ユーザー + 同一マシンでのみ復号可能")
    print("  - .gitignore で commit から除外されています")
    print("  - 削除すると旧挙動 (手動 prompt manual_login) に戻ります")
    print()

    if has_credentials():
        old = load_credentials()
        print(f"[!] 既に credentials 保存済 (email={old[0]})。上書きしますか? [y/N]: ", end="")
        ans = input().strip().lower()
        if ans != "y":
            print("中止しました")
            return

    print()
    email = input("eBay email: ").strip()
    if not email:
        print("[!] email が空、中止")
        return
    password = getpass.getpass("eBay password (非表示): ")
    if not password:
        print("[!] password が空、中止")
        return
    password2 = getpass.getpass("もう一度 (確認): ")
    if password != password2:
        print("[!] password 不一致、中止")
        return

    path = save_credentials(email, password)
    print()
    print(f"[OK] 保存完了: {path}")
    print()
    print("動作確認:")
    creds = load_credentials()
    if creds:
        print(f"  email roundtrip: {creds[0]}")
        print(f"  password roundtrip: {'*' * len(creds[1])} ({len(creds[1])} chars)")
    else:
        print("  [!] load 失敗、save 失敗の可能性")


def cmd_delete():
    print("=" * 60)
    print("eBay credentials 削除 (= 旧挙動に戻す)")
    print("=" * 60)
    if not has_credentials():
        print("[!] credentials 未設定 (削除対象なし)")
        return
    creds = load_credentials()
    print(f"対象: email={creds[0]}")
    print("削除しますか? [y/N]: ", end="")
    ans = input().strip().lower()
    if ans != "y":
        print("中止しました")
        return
    deleted = delete_credentials()
    if deleted:
        print(f"[OK] 削除完了: {ENCRYPTED_PASSWD_FILE}")
        print("  以後 manual_login は手動 prompt mode (= 旧挙動) で動作")
    else:
        print("[!] 削除失敗")


def cmd_check():
    print("=" * 60)
    print("eBay credentials 状態確認")
    print("=" * 60)
    print(f"path: {ENCRYPTED_PASSWD_FILE}")
    print(f"exists: {ENCRYPTED_PASSWD_FILE.exists()}")
    if has_credentials():
        creds = load_credentials()
        print(f"  email: {creds[0]}")
        print(f"  password: {'*' * len(creds[1])} ({len(creds[1])} chars)")
        print("  → manual_login は自動入力 mode で動作")
    else:
        print("  → credentials 未設定 / 復号不可")
        print("  → manual_login は手動 prompt mode (= 旧挙動) で動作")


def main():
    parser = argparse.ArgumentParser(
        description="eBay credentials 暗号化セットアップ (DPAPI、opt-in)"
    )
    parser.add_argument("--delete", action="store_true", help="credentials 削除 (= 旧挙動に戻す)")
    parser.add_argument("--check", action="store_true", help="現状確認")
    args = parser.parse_args()

    if args.delete:
        cmd_delete()
    elif args.check:
        cmd_check()
    else:
        cmd_setup()


if __name__ == "__main__":
    main()
