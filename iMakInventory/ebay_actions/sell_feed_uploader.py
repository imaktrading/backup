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
# 2026-05-29: 旧 chrome_profile_ebay が外部 process (= Windows search indexer 等)
# の lock で rename / delete 不能になる事故あり。 新 path ebay2 に切替 + 旧 path
# は backup として残置 (= 自然解放後に手動削除予定)。
EBAY_CHROME_PROFILE_DIR = r"C:\Users\imax2\local_data\iMakInventory\chrome_profile_ebay2"
EBAY_RESULT_DL_DIR = r"C:\Users\imax2\local_data\iMakInventory\ebay_result_dl"   # 結果 CSV download 用

# eBay URLs
EBAY_SIGNIN_URL = "https://signin.ebay.com/ws/eBayISAPI.dll?SignIn"
EBAY_HOME_URL = "https://www.ebay.com"
# 2026-04-30 トラバホ解析反映: Seller Hub の uploads ページに直接遷移する
# (旧 k2b-bulk URL も eBay 側で 自動 redirect されるが、明示的に新 URL を使う)
EBAY_FILEEXCHANGE_UPLOAD_URL = "https://www.ebay.com/sh/reports/uploads"
EBAY_FILEEXCHANGE_RESULTS_URL = "https://www.ebay.com/sh/reports/uploads"

# タイムアウト + リトライ
LOGIN_WAIT_SEC = 300            # 手動ログイン猶予 (5分)
UPLOAD_WAIT_SEC = 120           # アップロード後の結果ページ表示待ち
PAGE_LOAD_WAIT_SEC = 10         # 通常ページロード待ち

# 2026-05-08 flaky 撲滅改造: popup 監視 + 履歴 refresh ロジック → CSV DL + Status パース
# (旧仕様: trabajo __UploadCSVwithSoldedWithRetry 踏襲)
UPLOAD_RETRY_MAX = 1            # 1 cycle 1 Submit (= eBay に重複送信しない、check_upload_result 統合で確実判定)
UPLOAD_RETRY_SLEEP_SEC = 3      # リトライ間隔 (= 真の未送信時のみ再試行)
LOGIN_RETRY_MAX = 3             # login 3 回リトライ
LOGIN_RETRY_SLEEP_SEC = 3
RESULT_WAIT_SEC = 30            # Submit 後に eBay 側が結果ファイル生成する時間
RESULT_PARSE_RETRY_MAX = 3      # 履歴 page_source の filename リンク取得リトライ (生成遅延吸収)
RESULT_PARSE_RETRY_SLEEP_SEC = 10

# Failure 分類: 安全な (= 既に終了/削除済の listing) は通知不要、それ以外は要対応 (= 通知発火)
SAFE_FAILURE_ERROR_CODES = {
    "291",  # "You are not allowed to revise ended listings" = 既に listing 終了済
    "17",   # "This item cannot be accessed because the listing has been deleted" = 削除済
}

# 2026-05-29: 致命的 Warning (= success 扱いだが実は qty/price 反映されてない)
# これらが Warning に含まれてたら action_needed_failure として扱う = 「success と
# 楽観的判定」 の盲点を塞ぐ。 数週間 silent fail した 21916619 が代表例。
CRITICAL_WARNING_CODES = {
    "21916619",  # "Item level quantity will be ignored" → variation qty 変更失敗 確定
    "21916618",  # "Item level start price will be ignored" → variation price 変更失敗 確定
}

DECISION_LOG_DIR = ROOT_DIR / "decision_log"
CSV_OUTPUT_DIR = ROOT_DIR / "csv_output"
UPLOAD_STATE_FILE = DECISION_LOG_DIR / "upload_state.json"


# ============================================================================
# Driver factory
# ============================================================================
CHROMIUM_PORTABLE_PATH = r"C:\トラバホセット\BoostListing（出品・在庫管理一体型ツール）\BoostListing\BoostListing\chrome\chromep.exe"
CHROMIUM_PORTABLE_VERSION = 136   # chromep.exe 136.0.7103.93 同梱
TRABAJO_CHROMEDRIVER_PATH = r"C:\トラバホセット\BoostListing（出品・在庫管理一体型ツール）\BoostListing\BoostListing\dll\chromedriver.exe"   # v136.0.7103.92


def _cleanup_uc_patched_driver_cache() -> bool:
    """undetected_chromedriver の patched driver cache を削除.

    2026-05-22 事故対策: uc が自動 download した v149 driver (= Chrome 本体追従)
    が cache 残ってると、明示指定の trabajo chromedriver v136 と内部的に衝突して
    "cannot connect to chrome" エラーになる。
    cycle ごとに毎回 cache を破棄して strict に明示指定 driver のみ使う。

    2026-05-28 修正: 前 cycle 由来の chromedriver/chromep process が cache 内 file の
    lock を握ったままだと rmtree が silent fail (= ignore_errors=True) → cache 残置
    → 次 cycle で「cannot connect to chrome」 SessionNotCreatedException。
    対策: rmtree 前に残骸 process kill + retry + 検証で完全削除を保証。
    """
    import shutil   # noqa: PLC0415
    import subprocess  # noqa: PLC0415
    import time as _time  # noqa: PLC0415

    cache_dir = os.path.join(
        os.environ.get("APPDATA", ""), "undetected_chromedriver"
    )
    # Microsoft Store Python の場合 APPDATA が Packages 配下にリダイレクトされる
    if not os.path.exists(cache_dir):
        alt = os.path.join(
            os.environ.get("LOCALAPPDATA", ""),
            "Packages\\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0",
            "LocalCache\\Roaming\\undetected_chromedriver"
        )
        if os.path.exists(alt):
            cache_dir = alt
    if not os.path.exists(cache_dir):
        return False

    # 2026-05-28: cache 内 file lock を握りうる残骸 process を kill
    for procname in ("undetected_chromedriver.exe", "chromedriver.exe", "chromep.exe"):
        try:
            subprocess.run(["taskkill", "/F", "/IM", procname],
                           capture_output=True, timeout=5)
        except Exception:
            pass
    _time.sleep(1)   # process 終了待ち

    # rmtree 試行 (= 最大 3 回 retry、 lock 解放待ち)
    for attempt in range(3):
        try:
            shutil.rmtree(cache_dir, ignore_errors=True)
            if not os.path.exists(cache_dir):
                return True   # 完全削除確認
        except Exception:
            pass
        _time.sleep(1)

    # 全 retry 失敗 → 部分削除でも実害最小化、 cache 内 .exe 個別削除試行
    try:
        for fname in os.listdir(cache_dir):
            fpath = os.path.join(cache_dir, fname)
            if fname.endswith(".exe"):
                try:
                    os.remove(fpath)
                except Exception:
                    pass
    except Exception:
        pass

    return not os.path.exists(cache_dir) or not any(
        f.endswith(".exe") for f in os.listdir(cache_dir) if os.path.exists(cache_dir)
    )


def _cleanup_stale_chrome_locks(profile_dir: str) -> int:
    """profile dir の stale lock 系ファイルを削除 (chrome 異常終了の残骸).

    chrome が異常終了 (= driver.quit() なしで kill / crash) すると Singleton* /
    LOCK 系のファイルが残り、次回起動時に「別 process が使用中」と誤判定して
    "chrome not reachable" で起動失敗する。
    本関数は chrome process が動いてない時のみ呼出され、stale lock を片付ける。

    Returns: 削除したファイル数
    """
    if not os.path.exists(profile_dir):
        return 0
    removed = 0
    # profile dir 直下
    for fname in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        p = os.path.join(profile_dir, fname)
        if os.path.exists(p):
            try:
                os.remove(p)
                removed += 1
            except Exception:
                pass
    # Default 配下の LOCK
    default_lock = os.path.join(profile_dir, "Default", "LOCK")
    if os.path.exists(default_lock):
        try:
            os.remove(default_lock)
            removed += 1
        except Exception:
            pass
    return removed


def create_ebay_driver(headless: bool = False, use_profile: bool = True):
    """eBay 用 ChromeDriver を生成.

    2026-05-13: Chrome (Google Chrome) では eBay CAPTCHA が通らず anti-bot 検出
    される問題 → trabajo の Chromium portable (chromep.exe 136) に切替。
    chromep.exe があればそれを使い、無ければ通常の uc.Chrome (Google Chrome) で fallback。

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
    # 2026-05-22: uc cache の v149 driver と trabajo v136 driver の衝突対策
    if _cleanup_uc_patched_driver_cache():
        print(f"  [INFO] uc patched driver cache 削除")

    if use_profile:
        os.makedirs(EBAY_CHROME_PROFILE_DIR, exist_ok=True)
        removed = _cleanup_stale_chrome_locks(EBAY_CHROME_PROFILE_DIR)
        if removed > 0:
            print(f"  [INFO] stale chrome lock 削除: {removed} 件")
        options.add_argument(f"--user-data-dir={EBAY_CHROME_PROFILE_DIR}")
    if headless:
        options.add_argument("--headless=new")

    # 結果 CSV を直接 download するための prefs 設定 (Gemini 推奨、503 回避)
    # = requests で叩くと TLS fingerprint 不一致で 503 になるので driver.get で
    #   download bar dialog 出さず自動保存に切り替える
    os.makedirs(EBAY_RESULT_DL_DIR, exist_ok=True)
    options.add_experimental_option("prefs", {
        "download.default_directory":   EBAY_RESULT_DL_DIR,
        "download.prompt_for_download": False,
        "download.directory_upgrade":   True,
        "safebrowsing.enabled":         True,
    })

    # Chromium portable + 同梱 chromedriver があれば優先 (anti-bot 回避 + download 不要)
    if os.path.exists(CHROMIUM_PORTABLE_PATH) and os.path.exists(TRABAJO_CHROMEDRIVER_PATH):
        return uc.Chrome(
            options=options,
            browser_executable_path=CHROMIUM_PORTABLE_PATH,
            driver_executable_path=TRABAJO_CHROMEDRIVER_PATH,
            version_main=CHROMIUM_PORTABLE_VERSION,
        )
    # fallback: Chromium のみあれば uc に driver download させる
    if os.path.exists(CHROMIUM_PORTABLE_PATH):
        return uc.Chrome(
            options=options,
            browser_executable_path=CHROMIUM_PORTABLE_PATH,
            version_main=CHROMIUM_PORTABLE_VERSION,
        )
    # fallback: 通常の Google Chrome (uc 自動追従)
    return uc.Chrome(options=options)


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
    """ブラウザを開いて eBay にログイン → cookie 保存 → 完了確認。

    モード:
    1. **自動 (opt-in)**: auth/encrypted_passwd の DPAPI 暗号化 credentials が
       存在すれば、email/password を Selenium で自動入力 + Stay signed in 自動 ON
       → Submit → 2FA だけ人間操作 (or 不要)。trabajo 同等。
    2. **手動 (default)**: credentials ファイル無しなら従来通り全部手動 + Enter 待ち。

    どちらでも login 確定するまでに失敗したら旧 path (= 手動) に fallback。
    既存挙動 (credentials 無しの状態) は完全保持。
    """
    print("=" * 60)
    print("eBay ログイン")
    print("=" * 60)

    # opt-in: credentials があれば自動 login 試行
    try:
        from auth.encrypted_passwd import load_credentials  # noqa: PLC0415
        creds = load_credentials()
    except Exception as e:
        creds = None
        print(f"  (credentials load 失敗: {type(e).__name__}、手動 mode に fallback)")

    if creds is not None:
        email, password = creds
        print(f"  [OK] encrypted_passwd 検出 (email={email}) → 自動入力 mode")
        if _auto_login(driver, email, password):
            return True
        print("  [!] 自動 login 失敗 → 手動 mode に fallback")

    # 手動 mode (= 従来通り、既存挙動完全保持)
    return _manual_login_legacy(driver)


def _manual_login_legacy(driver) -> bool:
    """従来の全部手動 manual_login (Enter 待ち)。"""
    print("ブラウザが開きます。以下の手順でログインしてください:")
    print("  1. 開いたブラウザで eBay にログイン (2FA も含む)")
    print("  2. ホームに戻ったら、このターミナルに戻る")
    print("  3. Enter を押すと cookie が保存され、以降は自動")
    print()

    driver.get(EBAY_SIGNIN_URL)
    time.sleep(2)
    print("(ブラウザでログインを完了してから Enter を押してください...)")
    # cron 経由 (pythonw.exe) では sys.stdin が無いため input() で
    # RuntimeError "input(): lost sys.stdin" or EOFError or OSError が発生。
    # 全部 catch して例外漏れを防ぎ、is_logged_in 確認に進む (= cron 環境で
    # 自動 login 失敗時に従来同等の "not_logged_in" 確定動作になる)。
    try:
        input(">>> Enter to continue: ")
    except (EOFError, RuntimeError, OSError, AttributeError):
        pass

    if is_logged_in(driver):
        print("[OK] ログイン確認 OK、cookie 保存済 (永続プロファイルに記録)")
        return True
    else:
        print("[!] ログイン確認 NG、再度お試しください")
        return False


def _auto_login(driver, email: str, password: str) -> bool:
    """credentials を Selenium で自動入力 + Stay signed in 自動 ON + Submit。

    eBay の signin form 仕様 (2026 時点想定):
    - email: input#userid
    - 「Continue」: button#signin-continue-btn
    - password: input#pass
    - 「Stay signed in」: input#remember-me (永続 cookie 焼く)
    - 「Sign in」: button#sgnBt

    どこかで例外出たら False を返して fallback 先に投げる (既存挙動保持)。

    2FA は eBay 仕様で人間操作必須。submit 後 60 秒待って is_logged_in を polling、
    その間に人間が 2FA 入力すれば login 完了。
    """
    from selenium.webdriver.common.by import By  # noqa: PLC0415
    from selenium.webdriver.support.ui import WebDriverWait  # noqa: PLC0415
    from selenium.webdriver.support import expected_conditions as EC  # noqa: PLC0415

    try:
        driver.get(EBAY_SIGNIN_URL)
        time.sleep(2)

        # 1. email 入力
        email_field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "userid"))
        )
        email_field.clear()
        email_field.send_keys(email)
        print("    email 入力 OK")

        # 2. Continue button (= 1 ページ目で email + Continue → 2 ページ目で password の flow)
        try:
            continue_btn = driver.find_element(By.ID, "signin-continue-btn")
            continue_btn.click()
            time.sleep(2)
            print("    Continue OK")
        except Exception:
            print("    (Continue 不要、1 ページ完結 form の可能性)")

        # 3. password 入力
        try:
            passwd_field = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "pass"))
            )
            passwd_field.clear()
            passwd_field.send_keys(password)
            print("    password 入力 OK")
        except Exception as e:
            print(f"    [!] password field 不在: {e}")
            return False

        # 4. Stay signed in 自動 ON (Remember Me cookie 焼く、1 年級寿命期待)
        try:
            chk = driver.find_element(By.ID, "remember-me")
            if not chk.is_selected():
                chk.click()
                print("    Stay signed in: ON")
            else:
                print("    Stay signed in: 既に ON")
        except Exception:
            print("    (Stay signed in chk 見当たらず、続行)")

        # 5. Sign in button click
        try:
            submit_btn = driver.find_element(By.ID, "sgnBt")
            submit_btn.click()
            print("    Sign in click OK")
        except Exception:
            try:
                passwd_field.submit()
                print("    Sign in (form.submit fallback) OK")
            except Exception as e:
                print(f"    [!] Sign in click 失敗: {e}")
                return False

        # 6. 2FA / login 確定待ち (60 秒 polling)
        print("    2FA が必要な場合は手動入力してください (最大 60 秒待ち)")
        for i in range(30):
            time.sleep(2)
            if is_logged_in(driver):
                print(f"  [OK] 自動ログイン完了 ({i*2}s 経過)")
                return True
        print("  [!] 60 秒経過して login 完了確認できず")
        return False

    except Exception as e:
        print(f"  [!] 自動 login 例外: {type(e).__name__}: {e}")
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

    # トラバホ解析: file input が hidden 状態だと send_keys が拒否されるため
    # JavaScript で display:block に強制可視化
    try:
        driver.execute_script(
            "arguments[0].style.display = 'block'; "
            "arguments[0].style.visibility = 'visible'; "
            "arguments[0].style.opacity = '1';",
            file_input,
        )
    except WebDriverException:
        pass  # JS 失敗しても send_keys が動く可能性あり、続行

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

    # 2026-05-08 改造: popup 監視 + 履歴 refresh → CSV DL + Status パース
    # 旧仕様 (popup #shui-upload-file__pop-up + 履歴 refresh) は eBay UI 変更で flaky
    # 多発 (5/7 朝以降全 cycle で false negative)。tools/check_upload_result.py 同等
    # の方式 (page_source regex で結果ファイル URL 抽出 + cookie 流用 download)
    # に統合して、Status 列実体ベースで判定する。
    print(f"  Submit OK、{RESULT_WAIT_SEC}s 待機 (eBay 側結果ファイル生成)")
    time.sleep(RESULT_WAIT_SEC)

    href = _find_result_link(driver, csv_path.stem)
    if href is None:
        # 結果ファイルが履歴に出てこない = 真の未送信 or 結果生成遅延
        result["error"] = "result_not_in_history"
        result["page_url"] = driver.current_url
        return result

    # 結果 CSV ダウンロード (driver.get で実 ブラウザ経由、503 回避)
    try:
        csv_text = _download_result_csv(driver, href, target_fname_hint=csv_path.stem)
    except Exception as e:
        # 503 等で取得失敗 → 履歴ページの Status text を fallback で取得
        status_text = _extract_status_from_history(driver, csv_path.stem)
        if status_text:
            result["page_url"] = driver.current_url
            result["result_text"] = f"eBay Status: {status_text} (詳細 CSV 取得不能、Status のみ)"
            low = status_text.lower()
            if low == "completed":
                # 全件 Completed = 受理 (Warning も含めて成功)
                result["success"] = True
                result["error"] = None
                return result
            if "failed" in low:
                # N failed, M completed = 一部失敗
                result["success"] = False
                result["error"] = f"ebay_status_failed: {status_text} (詳細 CSV は 503 で取得不能)"
                return result
            # In progress / Pending 等
            result["success"] = False
            result["error"] = f"ebay_status_pending: {status_text}"
            return result
        # Status も取れない場合のみ true な failure
        result["error"] = f"result_csv_download_failed: {type(e).__name__}: {e}"
        result["page_url"] = driver.current_url
        return result

    # Status パース + ErrorCode 別分類
    status_summary = _classify_result_csv(csv_text)
    result.update(status_summary)
    # success 判定: action_needed Failure (写真要件等) が 0 件なら True
    # (= 全 Warning + safe Failure (ended/deleted) のみなら通知不要)
    result["success"] = status_summary["action_needed_failure"] == 0
    result["page_url"] = driver.current_url
    if not result["success"]:
        result["error"] = (
            f"action_needed_failure: {status_summary['action_needed_failure']} 件 "
            f"(safe={status_summary['safe_failure']}, warning={status_summary['warning']})"
        )
    result["result_text"] = (
        f"Warning {status_summary['warning']} + "
        f"safe Failure {status_summary['safe_failure']} + "
        f"action-needed Failure {status_summary['action_needed_failure']}"
    )

    return result


def _find_result_link(driver, target_filename_stem: str):
    """eBay /sh/reports/uploads ページの page_source から結果ファイル URL を抽出.

    target_filename_stem = "revise_BOTH_20260508_140123" (.csv 抜き)
    eBay 側の filename = "revise_BOTH_20260508_140123-May-2026-08-14-05-30-XXX.csv"
    両者は stem prefix が一致する。

    Returns: 結果ファイル URL (string) or None。
    """
    import re  # noqa: PLC0415
    import html  # noqa: PLC0415

    pattern = re.compile(
        r'href="(?P<href>[^"]*?requestId=\d+&(?:amp;)?filetype=output&(?:amp;)?[^"]*?fileName=(?P<fname>'
        + re.escape(target_filename_stem) + r'[^"]*?\.csv)[^"]*)"'
    )

    for attempt in range(1, RESULT_PARSE_RETRY_MAX + 1):
        try:
            driver.get(EBAY_FILEEXCHANGE_RESULTS_URL)
            time.sleep(5)  # 履歴表 render 待ち
        except Exception:
            pass
        src = driver.page_source or ""
        matches = list(pattern.finditer(src))
        if matches:
            # 最新採用 (= eBay 側 timestamp 最大、Stem 一致複数の場合は最新を取る)
            matches.sort(key=lambda m: m.group("fname"), reverse=True)
            href = html.unescape(matches[0].group("href"))
            if href.startswith("/"):
                href = "https://www.ebay.com" + href
            return href
        if attempt < RESULT_PARSE_RETRY_MAX:
            print(f"    結果 link 未発見、{RESULT_PARSE_RETRY_SLEEP_SEC}s 待機して retry ({attempt}/{RESULT_PARSE_RETRY_MAX})")
            time.sleep(RESULT_PARSE_RETRY_SLEEP_SEC)
    return None


def _download_result_csv(driver, url: str, target_fname_hint: str = "",
                          timeout_sec: int = 30) -> str:
    """driver.get(url) でブラウザ自身に download させて CSV テキストを返す.

    Gemini 推奨 (2026-05-14):
    - requests で別 session を作ると TLS fingerprint 不一致で eBay が 503 を返す
    - driver.get(url) で同じブラウザインスタンスに踏ませると 200 OK + 自動 download
      (= ChromeOptions の prefs で download dir / no prompt が設定済)

    Args:
        driver: Chromium portable で起動済 driver (login 済)
        url: 結果 CSV の getfiledetails URL
        target_fname_hint: 期待するファイル名のヒント (stem 一致で見つける)。空なら最新を取る
        timeout_sec: 出現待ちのタイムアウト

    Returns: CSV テキスト (utf-8-sig 解釈)
    """
    import os  # noqa: PLC0415 (top でも import 済だが明示)
    import time  # noqa: PLC0415

    dl_dir = EBAY_RESULT_DL_DIR
    os.makedirs(dl_dir, exist_ok=True)

    # 既存ファイル mtime の最大値を「download 前」として記録 (新規ファイル検出用)
    before_mtimes = {}
    for f in os.listdir(dl_dir):
        p = os.path.join(dl_dir, f)
        if os.path.isfile(p):
            before_mtimes[f] = os.path.getmtime(p)

    # driver にダウンロード実行させる
    driver.get(url)

    # download 完了 polling: target_fname_hint を含み .crdownload が消えるまで
    deadline = time.time() + timeout_sec
    found_path = None
    while time.time() < deadline:
        time.sleep(1)
        candidates = []
        for f in os.listdir(dl_dir):
            if f.endswith(".crdownload") or f.endswith(".tmp"):
                continue   # 進行中
            p = os.path.join(dl_dir, f)
            if not os.path.isfile(p):
                continue
            mt = os.path.getmtime(p)
            # 既存ファイルで mtime も変わってないもの = 別物 → skip
            if f in before_mtimes and before_mtimes[f] == mt:
                continue
            # hint 一致優先
            if target_fname_hint and target_fname_hint not in f:
                continue
            candidates.append((mt, p))
        if candidates:
            # 最新 mtime を採用
            candidates.sort(reverse=True)
            found_path = candidates[0][1]
            break

    if not found_path:
        raise TimeoutError(
            f"download timeout: {timeout_sec}s 待ったが target ファイル "
            f"(hint={target_fname_hint!r}) が {dl_dir} に出現しなかった"
        )

    with open(found_path, "rb") as f:
        raw = f.read()
    return raw.decode("utf-8-sig", errors="replace")


def _extract_status_from_history(driver, target_stem: str) -> Optional[str]:
    """eBay 履歴ページの page_source から target_stem 一致 row の Status text を抽出.

    eBay UI で各 row に Status カラム (Completed / 1 failed, 0 completed / In progress)
    が表示される。getfiledetails が 503 を返すような場面の fallback として、
    page_source 全体を regex で取って Status text を返す。

    Returns: Status text (例: "Completed", "1 failed, 0 completed") or None
    """
    import re  # noqa: PLC0415
    src = driver.page_source or ""
    idx = src.find(target_stem)
    if idx < 0:
        return None
    # filename 言及位置の後 ~5000 文字内に Status text が並ぶ (UI レイアウト依存)
    window = src[idx:idx + 5000]
    m = re.search(
        r"(\d+\s+failed,\s+\d+\s+completed|Completed|Failed|In\s+progress|Pending)",
        window,
    )
    if m:
        return m.group(1).strip()
    return None


def _classify_result_csv(csv_text: str) -> dict:
    """CSV テキストを Status × ErrorCode 別に集計.

    Returns: {
        "warning":                 全 Warning 件数,
        "safe_failure":            ended/deleted Failure 件数 (= 通知不要),
        "action_needed_failure":   写真要件等の Failure 件数 (= 通知発火),
        "total":                   全件数,
        "failure_details":         [{"item_id":..., "error_code":..., "error_message":..., "safe": bool}, ...],
    }
    """
    import csv as csv_module  # noqa: PLC0415
    import io  # noqa: PLC0415

    reader = csv_module.DictReader(io.StringIO(csv_text))
    rows = list(reader)

    warning = 0
    safe_failure = 0
    action_needed_failure = 0
    failure_details = []

    for r in rows:
        status = (r.get("Status") or "").strip()
        if status == "Warning":
            # 2026-05-29: 致命的 Warning (= 21916619 等) は実は qty/price 反映
            # されてない silent fail。 action_needed_failure に再分類する。
            wcodes = (r.get("WarningCode") or "").strip()
            wcode_set = set(c.strip() for c in wcodes.split("|") if c.strip())
            if wcode_set & CRITICAL_WARNING_CODES:
                action_needed_failure += 1
                failure_details.append({
                    "item_id":       r.get("ItemID", ""),
                    "error_code":    f"CRITICAL_WARNING:{','.join(sorted(wcode_set & CRITICAL_WARNING_CODES))}",
                    "error_message": (r.get("WarningMessage") or "")[:200],
                    "safe":          False,
                })
            else:
                warning += 1
        elif status == "Failure":
            code = (r.get("ErrorCode") or "").strip()
            is_safe = code in SAFE_FAILURE_ERROR_CODES
            if is_safe:
                safe_failure += 1
            else:
                action_needed_failure += 1
            failure_details.append({
                "item_id":      r.get("ItemID", ""),
                "error_code":   code,
                "error_message": (r.get("ErrorMessage") or "")[:200],
                "safe":         is_safe,
            })

    return {
        "warning":               warning,
        "safe_failure":          safe_failure,
        "action_needed_failure": action_needed_failure,
        "total":                 len(rows),
        "failure_details":       failure_details,
    }


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
        print("  [!] CSV が空、upload skip")
        result = {"success": False, "error": "csv_empty",
                  "result_text": "", "popup_text": "", "page_url": "", "screenshot": None}
        log_path = append_upload_log(csv_path, result, dry_run, csv_lines)
        return {**result, "log_path": str(log_path), "csv_lines": csv_lines}

    driver = None
    try:
        driver = create_ebay_driver(headless=False)

        # トラバホ __UploadCSVwithSoldedWithRetry 相当: 全体 3 回リトライ層
        result = {"success": False, "error": "not_attempted",
                  "result_text": "", "popup_text": "", "page_url": "", "screenshot": None}
        for attempt in range(1, UPLOAD_RETRY_MAX + 1):
            print(f"  upload attempt {attempt}/{UPLOAD_RETRY_MAX}")

            # ログイン 3 回リトライ層 (URL が uploads page に届くまで)
            login_ok = False
            for li in range(1, LOGIN_RETRY_MAX + 1):
                if is_logged_in(driver):
                    login_ok = True
                    break
                print(f"    login attempt {li}/{LOGIN_RETRY_MAX}: not logged in, retrying...")
                time.sleep(LOGIN_RETRY_SLEEP_SEC)
                # 失敗時は driver.refresh で signin redirect を再評価
                try:
                    driver.refresh()
                except Exception:
                    pass

            if not login_ok:
                # 自動再ログイン試行 (encrypted_passwd opt-in、無ければ legacy 手動 prompt)
                # cron 経由 (pythonw.exe / stdin 無し) でも legacy path は EOFError を catch
                # して False を返すため安全 (= 旧挙動と同等)
                print("  [!] 未ログイン、manual_login 自動 trigger")
                print("     (encrypted_passwd 有 → 自動入力 + Stay signed in / 無 → 手動 prompt)")
                if manual_login(driver):
                    if is_logged_in(driver):
                        login_ok = True
                        print("  [OK] 再ログイン成功、upload 再開")
                if not login_ok:
                    print("  [!] 再ログイン失敗、not_logged_in 確定")
                    result = {"success": False, "error": "not_logged_in",
                              "result_text": "", "popup_text": "", "page_url": "", "screenshot": None}
                    break  # 全体ループも抜ける

            print("  [OK] ログイン状態 OK")
            result = upload_csv_via_form(driver, csv_path, dry_run=dry_run)

            if result.get("success"):
                break

            # session_expired は relogin で復帰可能性
            if result.get("error") == "session_expired" and max_login_retries > 0:
                print("  [!] session 切れ検知、再ログインを促します")
                if manual_login(driver):
                    continue  # 次の attempt で再 upload
                else:
                    result["error"] = "session_expired_and_relogin_failed"
                    break

            # その他の失敗は次の attempt に進む (sleep 挟む)
            if attempt < UPLOAD_RETRY_MAX:
                print(f"  attempt {attempt} 失敗 ({result.get('error', 'unknown')}), {UPLOAD_RETRY_SLEEP_SEC}s 待機して retry")
                time.sleep(UPLOAD_RETRY_SLEEP_SEC)
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
        print(f"[NG] CSV not found: {csv_path}")
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
            print(f"  [!] {p.name}: 失敗 → 後続停止")
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
