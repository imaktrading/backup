"""sell_feed_uploader - eBay FileExchange Web UI 自動アップローダー (Phase 4).

トラバホ Log.txt 解析で判明した方式を踏襲:
  - eBay Sell Feed API は使わない (RuName / OAuth Authorization Code 不要)
  - Selenium で eBay にログイン → FileExchange Upload Form に CSV を POST
  - cookie 永続化でログイン状態を持ち越す
  - セッション切れ時は自動再ログイン (--manual-login で初回 + 切れ時)

事前準備 (初回のみ):
  python -m ebay_actions.sell_feed_uploader --login
  → ブラウザが開く → 手動でログイン → cookie 保存 → 以降は自動

通常運用:
  python -m ebay_actions.sell_feed_uploader --csv csv_output/revise_BOTH_20260429.csv
  python -m ebay_actions.sell_feed_uploader --csv ... --dry-run

queue 連動運用 (Phase 3 で生成された CSV を全部アップ):
  python -m ebay_actions.sell_feed_uploader --queue
  → csv_output/ 内の未アップロード CSV を全件処理

設計原則:
  - dry-run mode 必須: アップロード Submit しない検証モード
  - 全 upload を decision_log/upload_<ts>.jsonl に記録
  - Akamai bot 検知対策: undetected_chromedriver
  - Chrome window 最小化禁止 (Selenium が拒否)

参照ファイル:
  C:\\トラバホセット\\BoostListing\\BoostListing\\BoostListing\\Log.txt
    - "ebayにログイン中です" / "ファイルアップロードが完了しました - ポップアップ内のダウンロードリンクを確認"
    - StockChecktool.cs:61 ebay_Login() / SeleniumOperator.cs:144 WaitUrl()
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

# 親ディレクトリ (iMakInventory) を sys.path へ
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


# ============================================================================
# 設定
# ============================================================================
# Chrome プロファイル (Mercari と分離、eBay 専用)
EBAY_CHROME_PROFILE_DIR = r"C:\Users\imax2\local_data\iMakInventory\chrome_profile_ebay"

# eBay URLs
EBAY_SIGNIN_URL = "https://signin.ebay.com/ws/eBayISAPI.dll?SignIn"
EBAY_HOME_URL = "https://www.ebay.com"
EBAY_FILEEXCHANGE_UPLOAD_URL = (
    "https://k2b-bulk.ebay.com/ws/eBayISAPI.dll?FileExchangeUploadForm"
)
EBAY_FILEEXCHANGE_RESULTS_URL = (
    "https://k2b-bulk.ebay.com/ws/eBayISAPI.dll?FileExchangeResults"
)

# タイムアウト
LOGIN_WAIT_SEC = 300       # 手動ログイン猶予 (5分)
UPLOAD_WAIT_SEC = 120      # アップロード後の結果ページ表示待ち
PAGE_LOAD_WAIT_SEC = 10    # 通常ページロード待ち
CHROME_VERSION_MAIN = 146

DECISION_LOG_DIR = ROOT_DIR / "decision_log"
CSV_OUTPUT_DIR = ROOT_DIR / "csv_output"
UPLOAD_STATE_FILE = DECISION_LOG_DIR / "upload_state.json"


# ============================================================================
# Driver factory
# ============================================================================
def create_ebay_driver(headless: bool = False, use_profile: bool = True):
    """eBay 用 ChromeDriver を生成.

    Args:
        headless: True で headless mode (初回ログインは headless 不可、--login は headful)
        use_profile: True で永続プロファイル使用 (cookie 持越)
    """
    try:
        import undetected_chromedriver as uc  # noqa: PLC0415
    except ImportError:
        raise RuntimeError(
            "undetected_chromedriver 未インストール。"
            "pip install undetected-chromedriver で導入してください。"
        )

    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--lang=en-US")
    options.add_argument("--start-maximized")  # 最小化禁止 (Selenium が拒否)
    if use_profile:
        os.makedirs(EBAY_CHROME_PROFILE_DIR, exist_ok=True)
        options.add_argument(f"--user-data-dir={EBAY_CHROME_PROFILE_DIR}")
    if headless:
        options.add_argument("--headless=new")

    return uc.Chrome(options=options, version_main=CHROME_VERSION_MAIN)


# ============================================================================
# ログイン状態判定
# ============================================================================
def is_logged_in(driver) -> bool:
    """eBay ログイン状態を判定 (cookie 経由でセッション有効か).

    判定方式: ログイン必須の MyeBay Summary ページに遷移し、signin への
    リダイレクトが起きないことを確認。これは undetected_chromedriver の
    新規プロファイルでも安定する。
    """
    from selenium.common.exceptions import WebDriverException  # noqa: PLC0415
    MYEBAY_URL = "https://www.ebay.com/myb/Summary"
    try:
        driver.get(MYEBAY_URL)
        time.sleep(3)
        cur = (driver.current_url or "").lower()
        # ログイン未完了の signal:
        #   - signin.ebay.com への redirect
        #   - splashui/captcha (Akamai bot 検知; ログイン前に出やすい)
        #   - fyplogin
        if any(kw in cur for kw in ("signin.ebay.com", "splashui/captcha", "fyplogin")):
            return False
        # myb/Summary に到達 = 成功 (URL は /myb/ 配下に留まる)
        return "/myb/" in cur or "/myebay/" in cur
    except WebDriverException:
        return False


def manual_login(driver) -> bool:
    """ブラウザを開いてユーザーが手動ログイン → cookie 保存 → 完了確認."""
    print("=" * 60)
    print("eBay 手動ログイン")
    print("=" * 60)
    print("ブラウザが開きます。以下の手順でログインしてください:")
    print("  1. 開いたブラウザで eBay にログイン (2FA も含む)")
    print("  2. ホームに戻ったら、このターミナルに戻る")
    print("  3. Enter を押すと cookie が保存され、以降は自動")
    print()

    driver.get(EBAY_SIGNIN_URL)
    time.sleep(2)
    print("(ブラウザでログインを完了してから Enter を押してください...)")
    try:
        input(">>> Enter to continue: ")
    except EOFError:
        pass

    if is_logged_in(driver):
        print("✅ ログイン確認 OK、cookie 保存済 (永続プロファイルに記録)")
        return True
    else:
        print("⚠️ ログイン確認 NG、再度お試しください")
        return False


# ============================================================================
# CSV upload (FileExchange Web UI)
# ============================================================================
def upload_csv_via_form(driver, csv_path: Path, dry_run: bool = False) -> dict:
    """FileExchange Upload Form に CSV を POST.

    Args:
        driver:   ログイン済 ChromeDriver
        csv_path: アップロード対象 CSV (絶対パス推奨)
        dry_run:  True で Submit せず、フォーム到達まで確認のみ

    Returns: {
        "success":      bool,
        "result_text":  str (結果ページの抜粋),
        "popup_text":   str (popup 内容),
        "page_url":     str (Submit 後の URL),
        "screenshot":   Optional[str] (失敗時のスクリーンショットパス),
        "error":        Optional[str],
    }
    """
    from selenium.webdriver.common.by import By  # noqa: PLC0415
    from selenium.webdriver.support.ui import WebDriverWait  # noqa: PLC0415
    from selenium.webdriver.support import expected_conditions as EC  # noqa: PLC0415
    from selenium.common.exceptions import (  # noqa: PLC0415
        TimeoutException, WebDriverException, NoSuchElementException,
    )

    result = {
        "success":     False,
        "result_text": "",
        "popup_text":  "",
        "page_url":    "",
        "screenshot":  None,
        "error":       None,
    }

    if not csv_path.exists():
        result["error"] = f"CSV ファイル不在: {csv_path}"
        return result

    try:
        driver.get(EBAY_FILEEXCHANGE_UPLOAD_URL)
    except WebDriverException as e:
        result["error"] = f"FileExchange URL 到達失敗: {e}"
        return result

    time.sleep(PAGE_LOAD_WAIT_SEC)

    # セッション切れ / Akamai bot 検知判定
    cur_url = (driver.current_url or "").lower()
    if any(kw in cur_url for kw in (
        "signin.ebay.com",
        "fyplogin",
        "splashui/captcha",
    )):
        result["error"] = "session_expired"
        result["page_url"] = cur_url
        return result

    # <input type="file"> を探して CSV パスを送信
    file_input = None
    for selector in [
        'input[type="file"]',
        'input[name="file"]',
        'input[name="fileToUpload"]',
        'input[accept*=".csv"]',
    ]:
        try:
            file_input = driver.find_element(By.CSS_SELECTOR, selector)
            if file_input:
                break
        except NoSuchElementException:
            continue

    if file_input is None:
        # ページ構造が想定外 → スクリーンショット保存して abort
        try:
            shot = DECISION_LOG_DIR / f"upload_failure_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            DECISION_LOG_DIR.mkdir(parents=True, exist_ok=True)
            driver.save_screenshot(str(shot))
            result["screenshot"] = str(shot)
        except Exception:
            pass
        result["error"] = "file input 要素見つからず (ページ構造変更?)"
        return result

    try:
        file_input.send_keys(str(csv_path.resolve()))
        time.sleep(1)
    except WebDriverException as e:
        result["error"] = f"file input 送信失敗: {e}"
        return result

    if dry_run:
        result["success"] = True
        result["result_text"] = "(dry-run: Submit しなかった、ファイル選択まで OK)"
        result["page_url"] = driver.current_url
        return result

    # Submit ボタンを探して click
    submit_btn = None
    for selector in [
        'input[type="submit"]',
        'button[type="submit"]',
        'input[name="UploadButton"]',
        'button[name="upload"]',
    ]:
        try:
            submit_btn = driver.find_element(By.CSS_SELECTOR, selector)
            if submit_btn:
                break
        except NoSuchElementException:
            continue

    if submit_btn is None:
        result["error"] = "submit ボタン見つからず"
        return result

    try:
        submit_btn.click()
    except WebDriverException as e:
        result["error"] = f"submit click 失敗: {e}"
        return result

    # 結果ページ / popup を待つ
    end_at = time.time() + UPLOAD_WAIT_SEC
    success_kw = ["upload successful", "正常", "成功", "received", "submitted",
                  "your file has been", "fileexchangeresults"]
    failure_kw = ["upload failed", "失敗", "error occurred"]
    while time.time() < end_at:
        time.sleep(1)
        try:
            cur_url = driver.current_url or ""
            page = (driver.page_source or "").lower()
        except WebDriverException:
            continue

        # popup 検知 (alert)
        try:
            alert = driver.switch_to.alert
            result["popup_text"] = alert.text
            try:
                alert.accept()
            except Exception:
                pass
        except Exception:
            pass

        # 結果 URL に飛んでいる
        if "fileexchangeresults" in cur_url.lower():
            result["success"] = True
            result["result_text"] = page[:500]
            result["page_url"] = cur_url
            return result

        # 成功キーワード
        if any(kw in page for kw in success_kw):
            result["success"] = True
            result["result_text"] = page[:500]
            result["page_url"] = cur_url
            return result

        # 失敗キーワード
        if any(kw in page for kw in failure_kw):
            result["success"] = False
            result["result_text"] = page[:500]
            result["page_url"] = cur_url
            result["error"] = "upload reported failure on result page"
            return result

    result["error"] = f"upload result not detected within {UPLOAD_WAIT_SEC} sec"
    result["page_url"] = driver.current_url if driver else ""
    return result


# ============================================================================
# decision_log / state
# ============================================================================
def append_upload_log(csv_path: Path, result: dict, dry_run: bool, csv_lines: int) -> Path:
    DECISION_LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = DECISION_LOG_DIR / f"upload_{ts}.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts":          datetime.now().isoformat(timespec="seconds"),
            "phase":       "phase4_filexchange_upload",
            "csv_path":    str(csv_path),
            "csv_lines":   csv_lines,
            "dry_run":     dry_run,
            "success":     result.get("success", False),
            "result_text": (result.get("result_text") or "")[:1000],
            "popup_text":  (result.get("popup_text") or "")[:500],
            "page_url":    result.get("page_url", ""),
            "screenshot":  result.get("screenshot"),
            "error":       result.get("error"),
        }, ensure_ascii=False) + "\n")
    return path


def load_upload_state() -> dict:
    """uploaded CSV の履歴 (重複アップロード防止)."""
    if not UPLOAD_STATE_FILE.exists():
        return {"uploaded": []}
    try:
        return json.loads(UPLOAD_STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"uploaded": []}


def save_upload_state(state: dict) -> None:
    DECISION_LOG_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def count_csv_lines(csv_path: Path) -> int:
    """CSV の data 行数 (header 除く)."""
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            return max(0, sum(1 for _ in f) - 1)
    except OSError:
        return 0


# ============================================================================
# 公開 API: 1 CSV upload
# ============================================================================
def upload_one_csv(
    csv_path: Path,
    dry_run: bool = False,
    max_login_retries: int = 1,
) -> dict:
    """1 CSV を upload する一連の流れ.

    1. driver 起動 (永続プロファイル)
    2. ログイン状態確認
    3. ログインしていなければ → manual login (--login で実行済み想定、さもなくば失敗)
    4. CSV upload form に POST
    5. 結果記録、driver close

    Returns: append_upload_log の結果 dict + extra fields
    """
    print(f"=== eBay FileExchange Upload: {csv_path.name} (dry_run={dry_run}) ===")
    csv_lines = count_csv_lines(csv_path)
    print(f"  CSV 行数 (header 除く): {csv_lines}")

    if csv_lines == 0:
        print("  ⚠️ CSV が空、upload skip")
        result = {"success": False, "error": "csv_empty",
                  "result_text": "", "popup_text": "", "page_url": "", "screenshot": None}
        log_path = append_upload_log(csv_path, result, dry_run, csv_lines)
        return {**result, "log_path": str(log_path), "csv_lines": csv_lines}

    driver = None
    try:
        driver = create_ebay_driver(headless=False)
        if not is_logged_in(driver):
            print("  ⚠️ 未ログイン状態です。--login で先に手動ログインしてください")
            result = {"success": False, "error": "not_logged_in",
                      "result_text": "", "popup_text": "", "page_url": "", "screenshot": None}
        else:
            print("  ✅ ログイン状態 OK")
            result = upload_csv_via_form(driver, csv_path, dry_run=dry_run)

            # session_expired リトライ
            if result.get("error") == "session_expired" and max_login_retries > 0:
                print("  ⚠️ session 切れ検知、再ログインを促します")
                if manual_login(driver):
                    result = upload_csv_via_form(driver, csv_path, dry_run=dry_run)
                else:
                    result["error"] = "session_expired_and_relogin_failed"
    except Exception as e:
        result = {
            "success": False,
            "error": f"{type(e).__name__}: {e}",
            "result_text": "", "popup_text": "", "page_url": "",
            "screenshot": None,
        }
        traceback.print_exc()
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass

    # log + state 更新
    log_path = append_upload_log(csv_path, result, dry_run, csv_lines)
    print(f"  decision_log: {log_path}")

    if result.get("success") and not dry_run:
        state = load_upload_state()
        state["uploaded"].append({
            "ts":         datetime.now().isoformat(timespec="seconds"),
            "csv_path":   str(csv_path),
            "csv_lines":  csv_lines,
            "page_url":   result.get("page_url", ""),
        })
        save_upload_state(state)

    return {**result, "log_path": str(log_path), "csv_lines": csv_lines}


# ============================================================================
# CLI
# ============================================================================
def cmd_login():
    """初回 / セッション切れ時の手動ログイン."""
    print("eBay 手動ログインを開始します...")
    driver = create_ebay_driver(headless=False)
    try:
        ok = manual_login(driver)
        return 0 if ok else 1
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def cmd_upload(csv_path: Path, dry_run: bool):
    if not csv_path.exists():
        print(f"❌ CSV not found: {csv_path}")
        return 1
    result = upload_one_csv(csv_path, dry_run=dry_run)
    print()
    print(f"=== 結果 ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("success") else 1


def cmd_queue(dry_run: bool):
    """csv_output/ 内の未アップロード CSV を順次処理."""
    state = load_upload_state()
    uploaded_paths = {u["csv_path"] for u in state.get("uploaded", [])}
    pending = sorted([
        p for p in CSV_OUTPUT_DIR.glob("revise_*.csv")
        if str(p) not in uploaded_paths
    ])
    if not pending:
        print(f"  csv_output/ に未アップロード CSV なし")
        return 0
    print(f"  未アップロード CSV: {len(pending)} 件")
    overall_ok = True
    for p in pending:
        result = upload_one_csv(p, dry_run=dry_run)
        if not result.get("success"):
            overall_ok = False
            print(f"  ⚠️ {p.name}: 失敗 → 後続停止")
            break
    return 0 if overall_ok else 1


def main():
    parser = argparse.ArgumentParser(description="eBay FileExchange Web UI 自動アップローダー (Phase 4)")
    sub = parser.add_subparsers(dest="cmd")

    sp_login = sub.add_parser("login", help="初回 / セッション切れ時の手動ログイン")

    sp_upload = sub.add_parser("upload", help="指定 CSV を 1 件 upload")
    sp_upload.add_argument("csv", help="upload 対象 CSV パス")
    sp_upload.add_argument("--dry-run", action="store_true",
                          help="Submit しない検証モード")

    sp_queue = sub.add_parser("queue", help="csv_output/ の未アップロード CSV を順次処理")
    sp_queue.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    if args.cmd == "login":
        return cmd_login()
    elif args.cmd == "upload":
        return cmd_upload(Path(args.csv), dry_run=args.dry_run)
    elif args.cmd == "queue":
        return cmd_queue(dry_run=args.dry_run)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
