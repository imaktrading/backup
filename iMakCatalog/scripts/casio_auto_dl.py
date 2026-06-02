r"""Casio 公式 ページソース 自動 DL (= PyAutoGUI 物理操作シミュレート)

ユーザー作業 (= URL click → Ctrl+U → Ctrl+S → Enter → Ctrl+W) を自動化。
Sheet 1ypdMx3i8VPYLSxLixUP4oDbJrloMJ4yML8x7pkmC9mM の A 列 URL 全件を
ゆっくり (= 60-120s jitter) 処理 = Akamai 検出回避。

前提:
1. Chrome の DL 設定:
   - 設定 > ダウンロード > 「ダウンロード前に各ファイルの保存場所を確認する」 = OFF
   - デフォルトの保存場所 = C:\Users\imax2\OneDrive\デスクトップ\新しいフォルダー (2)
2. Chrome ウィンドウを **前面 + アクティブ** にしてから起動
3. 起動後 5 秒以内に Chrome 上にマウス置いて待機

使い方:
    python casio_auto_dl.py
"""
from __future__ import annotations
import sys, io, time, random, json
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

try:
    import pyautogui
    import pyperclip
except ImportError:
    print('ERROR: pip install pyautogui pyperclip')
    sys.exit(1)

import gspread
from google.oauth2.service_account import Credentials

# =========================================
# 設定
# =========================================
SHEET_ID = '1ypdMx3i8VPYLSxLixUP4oDbJrloMJ4yML8x7pkmC9mM'
CREDS = r'c:\dev\iMak\double-hold-421922-7c0d38d3f73d.json'
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

DL_FOLDER = Path(r'C:/Users/imax2/OneDrive/デスクトップ/新しいフォルダー (2)')

# 各 step の待機 (= page load / DL 完了等)
WAIT_AFTER_URL_LOAD = 8        # page load 待ち
WAIT_AFTER_VIEW_SOURCE = 3     # view-source tab load 待ち
WAIT_AFTER_SAVE_DIALOG = 2     # 保存 dialog 表示待ち
WAIT_AFTER_SAVE_CONFIRM = 6    # DL 完了待ち
WAIT_AFTER_CLOSE_TAB = 1       # tab 閉じ待ち

# URL 間 jitter (= 人間ペース偽装、 Akamai 検出回避)
JITTER_MIN_SEC = 60
JITTER_MAX_SEC = 120

# fail-safe: マウスを画面左上 (0,0) に動かすと即停止
pyautogui.FAILSAFE = True

# =========================================
# Sheet 接続
# =========================================
def load_urls_from_sheet() -> list[tuple[str, str]]:
    """Sheet から URL + product_id を取得 (= [(url, pid), ...])"""
    creds = Credentials.from_service_account_file(CREDS, scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.get_worksheet(0)
    rows = ws.get_all_values()
    out = []
    for r in rows[1:]:
        if len(r) >= 3 and r[0] and r[2]:
            out.append((r[0].strip(), r[2].strip()))
    return out


# =========================================
# DL 1 件処理
# =========================================
def download_one(url: str, pid: str, idx: int, total: int) -> bool:
    """1 URL の DL 処理. 成功 True、 失敗 False."""
    print(f'\n[{idx}/{total}] {pid}')
    print(f'  URL: {url}')

    # Step 1: Ctrl+L (= アドレスバーフォーカス)
    pyautogui.hotkey('ctrl', 'l')
    time.sleep(0.5)

    # Step 2: URL paste + Enter
    pyperclip.copy(url)
    pyautogui.hotkey('ctrl', 'v')
    time.sleep(0.3)
    pyautogui.press('enter')

    # Step 3: page load 待ち
    print(f'  wait page load ({WAIT_AFTER_URL_LOAD}s)...')
    time.sleep(WAIT_AFTER_URL_LOAD)

    # Step 4: Ctrl+U (= ページのソース表示、 新 tab で開く)
    pyautogui.hotkey('ctrl', 'u')
    time.sleep(WAIT_AFTER_VIEW_SOURCE)

    # Step 5: Ctrl+S (= 名前を付けて保存)
    pyautogui.hotkey('ctrl', 's')
    time.sleep(WAIT_AFTER_SAVE_DIALOG)

    # Step 6: Enter (= 保存 dialog 承認、 既定ファイル名 + 既定フォルダ)
    pyautogui.press('enter')

    # Step 7: DL 完了待ち
    print(f'  wait DL ({WAIT_AFTER_SAVE_CONFIRM}s)...')
    time.sleep(WAIT_AFTER_SAVE_CONFIRM)

    # Step 8: Ctrl+W ×2 (= source tab + 元 page tab 閉じる)
    pyautogui.hotkey('ctrl', 'w')
    time.sleep(WAIT_AFTER_CLOSE_TAB)
    pyautogui.hotkey('ctrl', 'w')
    time.sleep(WAIT_AFTER_CLOSE_TAB)

    print(f'  OK')
    return True


# =========================================
# main
# =========================================
def main():
    print('=== Casio 公式 自動 DL ===')
    print(f'Sheet: {SHEET_ID}')
    print(f'DL folder: {DL_FOLDER}')
    print(f'jitter: {JITTER_MIN_SEC}-{JITTER_MAX_SEC}s/URL')

    if not DL_FOLDER.exists():
        print(f'ERROR: DL folder not found: {DL_FOLDER}')
        sys.exit(1)

    print('\n=== Sheet 読込 ===')
    urls = load_urls_from_sheet()
    total = len(urls)
    print(f'対象 URL: {total}')

    if not total:
        print('対象 URL なし。 終了。')
        return

    print('\n*** 5 秒後に開始。 Chrome ウィンドウを前面 + アクティブにしてください ***')
    print('*** 緊急停止 = マウスを画面左上 (0,0) に動かす ***')
    for i in range(5, 0, -1):
        print(f'  {i}...', end='\r', flush=True)
        time.sleep(1)
    print('\n開始!')

    success = 0
    failed = []

    for idx, (url, pid) in enumerate(urls, 1):
        try:
            if download_one(url, pid, idx, total):
                success += 1
        except pyautogui.FailSafeException:
            print('\n*** FAIL-SAFE 緊急停止 (= マウス左上検出) ***')
            break
        except Exception as e:
            print(f'  ERR: {e}')
            failed.append((pid, str(e)))

        # jitter wait
        if idx < total:
            wait = random.randint(JITTER_MIN_SEC, JITTER_MAX_SEC)
            print(f'  次まで {wait}s 待機...')
            time.sleep(wait)

    print(f'\n=== 完了 ===')
    print(f'成功: {success} / {total}')
    print(f'失敗: {len(failed)}')
    if failed:
        for pid, err in failed[:10]:
            print(f'  {pid}: {err}')


if __name__ == '__main__':
    main()
