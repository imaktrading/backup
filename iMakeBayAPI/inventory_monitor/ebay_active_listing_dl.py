"""ebay_active_listing_dl - Active Listings Report の Selenium 自動 DL.

Phase 4a-1 (2026-05-14、Takaaki さん要求): 1 日 1 回 cycle 用に listing report を
自動 DL する。既存 sell_feed_uploader.py の Chromium portable + 永続 cookie
インフラを流用 (memory: reuse_existing_proven_solution.md)。

フロー:
  1. eBay 永続 cookie で driver 起動
  2. /sh/reports/downloads にアクセス
  3. 過去 24h 内に「Active Listings Report」あれば DL link 取得
  4. なければ Schedule new report → 生成完了まで polling (最大 30 分)
  5. driver.get で DL → polling で完了確認 → CSV path 返却

DL 先: C:\\Users\\imax2\\local_data\\iMakInventory\\ebay_active_listing_dl\\

実行:
    python ebay_active_listing_dl.py            # DL のみ (path を最終行に表示)
    python ebay_active_listing_dl.py --max-wait-min 30   # 生成完了待ち上限
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# stdout/stderr UTF-8 化
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# iMakInventory の sell_feed_uploader を流用
_inv_root = SCRIPT_DIR.parent.parent / "iMakInventory"
_ebay_actions_dir = _inv_root / "ebay_actions"
for p in (_inv_root, _ebay_actions_dir):
    if str(p) not in sys.path:
        sys.path.append(str(p))

# DL 先 (revise 結果と分離)
DL_DIR = Path(r"C:\Users\imax2\local_data\iMakInventory\ebay_active_listing_dl")
DL_DIR.mkdir(parents=True, exist_ok=True)

REPORTS_URL = "https://www.ebay.com/sh/reports/downloads"
REPORTS_SCHEDULE_URL = "https://www.ebay.com/sh/reports/schedule"


def _log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _create_driver_with_custom_dl(dl_dir: str):
    """sell_feed_uploader.create_ebay_driver を踏襲、DL 先だけ差し替え."""
    import undetected_chromedriver as uc  # noqa: PLC0415
    from sell_feed_uploader import (  # noqa: PLC0415
        EBAY_CHROME_PROFILE_DIR, _cleanup_stale_chrome_locks,
        CHROMIUM_PORTABLE_PATH, CHROMIUM_PORTABLE_VERSION, TRABAJO_CHROMEDRIVER_PATH,
    )

    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--lang=en-US")
    options.add_argument("--start-maximized")
    os.makedirs(EBAY_CHROME_PROFILE_DIR, exist_ok=True)
    removed = _cleanup_stale_chrome_locks(EBAY_CHROME_PROFILE_DIR)
    if removed > 0:
        _log(f"  [INFO] stale chrome lock 削除: {removed} 件")
    options.add_argument(f"--user-data-dir={EBAY_CHROME_PROFILE_DIR}")

    os.makedirs(dl_dir, exist_ok=True)
    options.add_experimental_option("prefs", {
        "download.default_directory":   dl_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade":   True,
        "safebrowsing.enabled":         True,
    })

    if os.path.exists(CHROMIUM_PORTABLE_PATH) and os.path.exists(TRABAJO_CHROMEDRIVER_PATH):
        return uc.Chrome(
            options=options,
            browser_executable_path=CHROMIUM_PORTABLE_PATH,
            driver_executable_path=TRABAJO_CHROMEDRIVER_PATH,
            version_main=CHROMIUM_PORTABLE_VERSION,
        )
    return uc.Chrome(options=options)


def _find_recent_active_listing_link(driver) -> str | None:
    """downloads ページから「Active Listings Report」最新 DL URL を抽出.

    eBay の DL URL 形式 (2026-05-14 実機調査):
        /sh/fpp/getfiledetails?client=sh-listings&requestId=<ID>
            &filetype=output&fileName=eBay-all-active-listings-report-YYYY-MM-DD-<ID>.csv

    page_source を直接 regex で抽出 → 最新 (= 日付 + requestId が最大) を選択。
    Selenium DOM 探索より頑健 (SPA で render 完了前の状態でも捕捉できる)。
    """
    import re  # noqa: PLC0415
    try:
        html = driver.page_source or ""
    except Exception as e:
        _log(f"  [WARN] page_source 取得失敗: {type(e).__name__}: {e}")
        return None

    # 「eBay-all-active-listings-report-YYYY-MM-DD-ID.csv」を含む getfiledetails URL を全部抽出
    pattern = re.compile(
        r"/sh/fpp/getfiledetails\?[^\"'<>\s]*?"
        r"fileName=eBay-all-active-listings-report-(\d{4}-\d{2}-\d{2})-(\d+)\.csv"
    )
    matches = pattern.findall(html)
    if not matches:
        _log("  [WARN] downloads ページに eBay-all-active-listings-report-* が見つからない")
        return None

    # 最新 (= 日付 desc → requestId desc)
    matches_sorted = sorted(matches, key=lambda m: (m[0], int(m[1])), reverse=True)
    date_str, req_id = matches_sorted[0]
    fname = f"eBay-all-active-listings-report-{date_str}-{req_id}.csv"
    url = (f"https://www.ebay.com/sh/fpp/getfiledetails"
           f"?client=sh-listings&requestId={req_id}"
           f"&filetype=output&fileName={fname}")
    _log(f"  最新 report: {fname} (req {req_id})")
    return url


def _wait_for_download(dl_dir: Path, before: set, max_wait_sec: int = 120) -> Path | None:
    """DL dir に新規 csv が現れて .crdownload が消えるまで polling."""
    deadline = time.time() + max_wait_sec
    while time.time() < deadline:
        time.sleep(2)
        files = set(p for p in dl_dir.iterdir() if p.is_file())
        new = files - before
        new_csv = [p for p in new if p.suffix.lower() == ".csv"]
        if new_csv and not any(p.suffix == ".crdownload" for p in dl_dir.iterdir()):
            # サイズ安定確認 (= write 完了)
            sizes = {p: p.stat().st_size for p in new_csv}
            time.sleep(2)
            stable = [p for p in new_csv if p.stat().st_size == sizes[p] and p.stat().st_size > 0]
            if stable:
                return max(stable, key=lambda p: p.stat().st_mtime)
    return None


def _schedule_new_report(driver) -> bool:
    """Active Listings Report を新規スケジュール (生成依頼)."""
    try:
        from selenium.webdriver.common.by import By  # noqa: PLC0415
    except ImportError:
        return False

    driver.get(REPORTS_SCHEDULE_URL)
    time.sleep(5)

    # 「Active Listings Report」を含むボタン/ラベルをクリック
    try:
        candidates = driver.find_elements(By.XPATH,
            "//*[contains(translate(text(), 'ACTIVE', 'active'), 'active listing')]")
        for el in candidates:
            try:
                el.click()
                time.sleep(2)
                _log("  Active Listing ラベル click 成功")
                break
            except Exception:
                continue
    except Exception as e:
        _log(f"  [WARN] Active Listing ラベル click 失敗: {type(e).__name__}: {e}")
        return False

    # 「Schedule」/「Generate」/「Create」 ボタンをクリック
    for btn_text in ("schedule", "generate", "create", "submit", "run"):
        try:
            btns = driver.find_elements(By.XPATH,
                f"//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                f"'abcdefghijklmnopqrstuvwxyz'), '{btn_text}')]")
            for b in btns:
                try:
                    b.click()
                    _log(f"  '{btn_text}' button click 成功")
                    time.sleep(3)
                    return True
                except Exception:
                    continue
        except Exception:
            continue
    _log("  [WARN] Schedule ボタン見つからず")
    return False


def download_active_listing_report(max_wait_min: int = 30,
                                   force_new: bool = True) -> Path:
    """Active Listings Report を Selenium で自動 DL → Path 返却.

    Args:
        max_wait_min: report 生成完了の最大待機時間 (分)
        force_new: True (= default) で必ず新規生成 (= 既存 DL link 無視)
                  2026-05-29 変更: 常に最新を取るため default True 化。
                  既存 report 再利用 (= eBay 側で同 file 返却ループ) で sheet が
                  古い state に固定される事故 (= 358596384438 新規 listing 未反映)
                  の再発防止。 False を明示指定すれば旧挙動 (existing 優先) になる。

    Raises:
        RuntimeError: 未ログイン / DL link 取得失敗
        TimeoutError: max_wait_min 超過
    """
    from sell_feed_uploader import is_logged_in, manual_login  # noqa: PLC0415

    _log("=" * 60)
    _log("Active Listings Report 自動 DL")
    _log("=" * 60)

    driver = _create_driver_with_custom_dl(str(DL_DIR))
    try:
        if not is_logged_in(driver):
            _log("eBay 未ログイン → manual_login 試行")
            if not manual_login(driver):
                raise RuntimeError("eBay ログイン失敗、cookie 焼き直しが必要")

        before = set(p for p in DL_DIR.iterdir() if p.is_file())

        # Step 1: 既存 DL link を探す
        if not force_new:
            _log(f"[1] {REPORTS_URL} アクセス、既存 report を確認")
            driver.get(REPORTS_URL)
            time.sleep(8)
            link = _find_recent_active_listing_link(driver)
            if link:
                _log(f"  既存 DL link 発見: {link[:80]}...")
                _log("  driver.get で DL trigger")
                driver.get(link)
                csv_path = _wait_for_download(DL_DIR, before, max_wait_sec=180)
                if csv_path:
                    _log(f"  [OK] DL 完了: {csv_path}")
                    return csv_path
                _log("  [!] 既存 link の DL timeout、新規生成へ fallback")

        # Step 2: 新規スケジュール
        _log(f"[2] 新規 report スケジュール")
        if not _schedule_new_report(driver):
            raise RuntimeError("Active Listing Report のスケジュール失敗 (UI 構造変更?)")

        # Step 3: 生成完了 polling (downloads ページを refresh しつつ確認)
        _log(f"[3] 生成完了 polling (最大 {max_wait_min} 分)")
        deadline = datetime.now() + timedelta(minutes=max_wait_min)
        while datetime.now() < deadline:
            time.sleep(60)
            driver.get(REPORTS_URL)
            time.sleep(8)
            link = _find_recent_active_listing_link(driver)
            if link:
                _log(f"  新 DL link 発見、DL trigger")
                driver.get(link)
                csv_path = _wait_for_download(DL_DIR, before, max_wait_sec=180)
                if csv_path:
                    _log(f"  [OK] DL 完了: {csv_path}")
                    return csv_path
        raise TimeoutError(f"{max_wait_min} 分待っても report 完成せず")

    finally:
        try:
            driver.quit()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="Active Listings Report 自動 DL")
    parser.add_argument("--max-wait-min", type=int, default=30,
                        help="report 生成完了待ち最大 (分、default 30)")
    parser.add_argument("--force-new", action="store_true",
                        help="既存 DL link を無視して新規生成")
    args = parser.parse_args()

    try:
        path = download_active_listing_report(
            max_wait_min=args.max_wait_min, force_new=args.force_new)
        print(f"\nCSV_PATH={path}")
    except Exception as e:
        _log(f"❌ DL 失敗: {type(e).__name__}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
