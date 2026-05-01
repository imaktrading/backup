"""expand_sheet - Google Sheets ワークシートの行数を拡張するユーティリティ.

事故 (2026-05-01 18:46): psa_to_csv のスプシ追記で
  `APIError: [400]: Range ('商品管理シート'!A927) exceeds grid limits. Max rows: 926`
発生. 既存スプシの最大行数 (926) に到達 → 新規 cert 追記不能.

設計原則 (修正連鎖回避):
  - psa_to_csv / control_panel など本体は一切修正しない
  - 必要時に手動実行するワンショット script
  - 確認プロンプト付きで誤操作防止 (--yes で skip)

使用例:
    # デフォルト: 商品管理シート (PSA_SHEET_ID + PSA_GID) を 1500 行に拡張
    python expand_sheet.py

    # 指定 worksheet を指定行数に拡張
    python expand_sheet.py --target-rows 2000

    # 確認プロンプト skip (script 化用)
    python expand_sheet.py --target-rows 1500 --yes

引数:
    --target-rows N : 拡張後の総行数 (default 1500)
    --yes           : 確認プロンプト skip
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


# 修正 (2026-05-01 19:48): 当初 PSA_SHEET_ID (PSA 仕入参照元) を指してたが、
# psa_to_csv の `_append_to_spreadsheet()` が追記するのは GSHEET_TCG_ID の sheet1
# (= 商品管理シート、出品ログ追記先). エラー対象を正確に拡張する.
GSHEET_TCG_ID = "1RbGaiQxhYDd7s8nqT0jHeh7sQ6FJNCVnVxkEJLFmz9s"
# sheet1 (= 一番左のタブ、商品管理シート)

# 認証 JSON は repo root に置いてある (psa_to_csv L1741 と同じ場所)
SCRIPT_DIR = Path(__file__).resolve().parent
GSHEET_CREDS_FILE = SCRIPT_DIR.parent / "double-hold-421922-7c0d38d3f73d.json"


def expand(target_rows: int, confirm: bool = True) -> int:
    """商品管理シート (GSHEET_TCG_ID の sheet1) を target_rows まで拡張.

    Returns: 0 = 成功, 1 = 失敗.
    """
    if not GSHEET_CREDS_FILE.exists():
        print(f"❌ Google認証ファイルなし: {GSHEET_CREDS_FILE}")
        return 1

    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError as e:
        print(f"❌ ライブラリ不足: {e}. `pip install gspread google-auth` で導入.")
        return 1

    creds = Credentials.from_service_account_file(
        str(GSHEET_CREDS_FILE),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(GSHEET_TCG_ID)
    ws = sh.sheet1   # psa_to_csv._append_to_spreadsheet と同じ worksheet 参照

    current = ws.row_count
    print(f"対象 worksheet: '{ws.title}' (sheet1)")
    print(f"  現在行数: {current}")
    print(f"  目標行数: {target_rows}")

    if current >= target_rows:
        print(f"✅ 既に {current} 行あり (≥ {target_rows})、拡張不要.")
        return 0

    delta = target_rows - current
    print(f"  追加行数: +{delta}")

    if confirm:
        ans = input("実行しますか? [y/N]: ").strip().lower()
        if ans not in ("y", "yes"):
            print("中止.")
            return 1

    ws.add_rows(delta)
    new_count = ws.row_count
    print(f"✅ 拡張完了: {current} → {new_count} 行")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Google Sheets 行数拡張")
    parser.add_argument("--target-rows", type=int, default=1500,
                        help="拡張後の総行数 (default: 1500)")
    parser.add_argument("--yes", action="store_true",
                        help="確認プロンプトを skip")
    args = parser.parse_args()

    return expand(args.target_rows, confirm=not args.yes)


if __name__ == "__main__":
    sys.exit(main())
