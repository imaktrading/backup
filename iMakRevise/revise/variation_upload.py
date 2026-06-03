"""variation_upload.py - リバイスくん variation CSV を sell_feed_uploader 経由で upload.

監視くん (iMakInventory) worktree の sell_feed_uploader を sys.path import 経由で使う
(= worktree 越境なし、read-only)。

事前 cleanup:
  - stale undetected_chromedriver.exe 終了 (= 前回異常終了で残存している process kill)
  - stale chromep.exe 終了 (= trabajo Chromium portable の残骸)
  - user の通常 Chrome (= chrome.exe) は touch しない

2026-05-24 HQ 4 回連続失敗対応:
  原因仮説: sell_feed_uploader 異常終了で undetected_chromedriver.exe が cleanup されず
            次回起動時 port 衝突 / connect 失敗 (SessionNotCreatedException)
  対策    : wrapper で stale process を taskkill してから sell_feed_uploader 呼出
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# 監視くん worktree (= sell_feed_uploader モジュール、read-only)
INVENTORY_WORKTREE = Path(r"c:/dev/iMak_inventory/iMakInventory")


# sell_feed_uploader 専用 profile (= EBAY_CHROME_PROFILE_DIR と同期)
EBAY_PROFILE_DIR = Path(r"C:/Users/imax2/local_data/iMakInventory/chrome_profile_ebay")

# 監視くん _cleanup_stale_chrome_locks の対象外で残りやすい stale file
EXTRA_STALE_FILES = [
    "DevToolsActivePort",   # 前回 chromep 異常終了の痕跡、新規起動で connect error 引き起こす
    "Default/SingletonLock",
    "Default/SingletonCookie",
    "Default/SingletonSocket",
]


def cleanup_stale_chrome_processes(verbose: bool = True) -> dict:
    """前回異常終了で残存している driver process + 残骸 file を kill / 削除.

    user の通常 Chrome (= chrome.exe) は触らない。
    sell_feed_uploader 専用 process (= undetected_chromedriver.exe / chromep.exe) のみ kill。
    profile dir の DevToolsActivePort 等 stale file も削除 (= 起動 connect error 防止)。

    Returns: {"chromedriver_killed": int, "chromep_killed": int, "stale_files_removed": int}
    """
    result = {"chromedriver_killed": 0, "chromep_killed": 0, "stale_files_removed": 0}

    for proc_name, key in [
        ("undetected_chromedriver.exe", "chromedriver_killed"),
        ("chromep.exe", "chromep_killed"),
    ]:
        try:
            r = subprocess.run(
                ["taskkill", "/F", "/IM", proc_name],
                capture_output=True, text=True, encoding="cp932", errors="replace",
            )
            if r.returncode == 0:
                result[key] = r.stdout.count("PID")
                if verbose and result[key] > 0:
                    print(f"  [cleanup] {proc_name}: killed {result[key]} process")
            elif "見つかりません" not in r.stderr and "not found" not in r.stderr.lower():
                if verbose:
                    print(f"  [cleanup] {proc_name}: {r.stderr.strip()}")
        except FileNotFoundError:
            if verbose:
                print(f"  [cleanup] taskkill 未対応環境 (= non-Windows?) skip {proc_name}")
            break

    # profile dir の stale file 削除 (= 監視くん _cleanup_stale_chrome_locks の補完)
    if EBAY_PROFILE_DIR.exists():
        for fname in EXTRA_STALE_FILES:
            p = EBAY_PROFILE_DIR / fname
            if p.exists():
                try:
                    p.unlink()
                    result["stale_files_removed"] += 1
                    if verbose:
                        print(f"  [cleanup] removed stale file: {fname}")
                except Exception as e:
                    if verbose:
                        print(f"  [cleanup] {fname} 削除失敗: {e}")

    return result


def upload_variation_csv(csv_path: Path, dry_run: bool = False) -> dict:
    """variation CSV を sell_feed_uploader 経由で upload.

    Returns: sell_feed_uploader.upload_one_csv() 返り値
    """
    # Step 1: stale process cleanup
    print(f"[variation_upload] stale Chrome driver process cleanup...")
    cleanup_result = cleanup_stale_chrome_processes()

    # Step 2: 監視くん worktree を import path に追加
    if str(INVENTORY_WORKTREE) not in sys.path:
        sys.path.insert(0, str(INVENTORY_WORKTREE))

    try:
        from ebay_actions.sell_feed_uploader import upload_one_csv  # type: ignore
    except ImportError as e:
        return {
            "success": False,
            "error": f"sell_feed_uploader import 失敗: {e}",
            "cleanup": cleanup_result,
        }

    # Step 3: upload 実行
    print(f"[variation_upload] sell_feed_uploader 呼出: {csv_path.name}")
    result = upload_one_csv(csv_path, dry_run=dry_run)
    result["cleanup"] = cleanup_result
    return result


def main():
    parser = argparse.ArgumentParser(
        description="variation CSV を sell_feed_uploader 経由で upload"
    )
    parser.add_argument("--csv", type=str, required=True,
                        help="upload する variation CSV path")
    parser.add_argument("--dry-run", action="store_true",
                        help="dry-run mode (= Submit せず検証のみ)")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"[NG] CSV not found: {csv_path}")
        return 1

    result = upload_variation_csv(csv_path, dry_run=args.dry_run)
    print()
    print(f"=== 結果 ===")
    import json
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
