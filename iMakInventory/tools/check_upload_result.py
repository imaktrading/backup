"""check_upload_result - eBay 履歴から直近 upload の結果ファイルを DL → CSV 中身解析.

flaky (popup 検出 false negative) で inventory 側 success=False と判定された
upload が、eBay 側で実際には Warning 受理 / Failure / 未送信 のどれか確定する
ための ad-hoc ツール。

設計方針:
- 既存 sell_feed_uploader.py / run_cycle.py / control_panel.py には一切触らない
- 完全に独立した ad-hoc 実行 (手動 or 定期 cron 化は別判断)
- chrome profile (login cookie) を流用、再ログイン不要

使い方:
    python tools/check_upload_result.py                   # 直近の revise_BOTH_*.csv 自動選択
    python tools/check_upload_result.py revise_BOTH_20260506_140521.csv
    python tools/check_upload_result.py --csv revise_BOTH_20260506_140521.csv
    python tools/check_upload_result.py --history-rows 20  # eBay 側で同じ stem の何件まで採用するか

出力:
    decision_log/check_result_<ts>.json  (Status 集計 + 行詳細)
    stdout に Warning / Failure / Error 件数表示
"""
from __future__ import annotations

import argparse
import csv
import html
import io
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from collections import Counter

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ebay_actions.sell_feed_uploader import create_ebay_driver, is_logged_in  # noqa: E402

import requests  # noqa: E402

DECISION_LOG_DIR = ROOT / "decision_log"
CSV_OUTPUT_DIR = ROOT / "csv_output"
EBAY_UPLOADS_URL = "https://www.ebay.com/sh/reports/uploads"


def find_latest_revise_csv() -> Path:
    """csv_output 内の最新 revise_BOTH_*.csv を返す."""
    candidates = sorted(
        CSV_OUTPUT_DIR.glob("revise_BOTH_*.csv"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(f"revise_BOTH_*.csv が {CSV_OUTPUT_DIR} に見つからない")
    return candidates[0]


def find_result_link(driver, target_filename: str, max_history_rows: int = 10) -> str | None:
    """eBay /sh/reports/uploads ページで filename 一致行を探し、結果ファイル URL を返す.

    eBay 履歴は <tr> ベースじゃなく Shopify UI (shui-dt--*) の独自 DOM を使うため、
    table/tr ベースの selector ではなく page_source 全体を regex で抽出する。

    target_filename = "revise_BOTH_20260506_140521.csv"
    eBay 側の filename = "revise_BOTH_20260506_140521-May-2026-...-XXX.csv"
    両者は **stem (.csv 抜き)** が prefix 一致する。

    Args:
        driver: ログイン済 ChromeDriver
        target_filename: 探したい upload 元 CSV ファイル名 (basename)
        max_history_rows: 同じ stem に対する eBay 側結果の採用上限 (3 連続 retry など)

    Returns: 結果ファイル URL (string) or None (見つからない時)
    """
    print(f"  [1/3] eBay 履歴ページ open: {EBAY_UPLOADS_URL}")
    driver.get(EBAY_UPLOADS_URL)
    time.sleep(5)  # 履歴表 render 待ち

    src = driver.page_source
    # 「.csv 抜きの target stem」が eBay 側 filename の prefix
    stem = target_filename[:-4] if target_filename.endswith(".csv") else target_filename
    print(f"  検索 stem: {stem}")

    # 結果ダウンロード URL は filetype=output、ソース側は filetype=input
    pattern = re.compile(
        r'href="(?P<href>[^"]*?requestId=\d+&(?:amp;)?filetype=output&(?:amp;)?[^"]*?fileName=(?P<fname>'
        + re.escape(stem) + r'[^"]*?\.csv)[^"]*)"'
    )
    matches = list(pattern.finditer(src))
    print(f"  filetype=output 一致 リンク数: {len(matches)}")
    if not matches:
        any_mention = stem in src
        print(f"  page_source 中の stem 言及: {any_mention}")
        return None

    # eBay 側 filename の suffix で sort して latest を取る (最新 retry 採用)
    matches = matches[:max_history_rows * 4]  # 余裕持たせる

    def _ts_key(m):
        return m.group("fname")
    matches.sort(key=_ts_key, reverse=True)
    chosen = matches[0]
    href = chosen.group("href")
    fname = chosen.group("fname")

    href = html.unescape(href)
    if href.startswith("/"):
        href = "https://www.ebay.com" + href
    print(f"  [OK] 採用: {fname}")
    print(f"     href[:100]: {href[:100]}")
    return href


def download_result_csv(driver, url: str, target_hint: str = "") -> str:
    """driver.get で結果ファイルをダウンロード (Gemini 推奨、503 回避).

    Args:
        driver: 既に EBAY_RESULT_DL_DIR を download dir に設定済の driver
        url: 結果 CSV の getfiledetails URL
        target_hint: 期待ファイル名のヒント
    """
    print(f"  [2/3] 結果 CSV download (driver.get): {url[:80]}...")
    # sell_feed_uploader 側の実装を流用
    from ebay_actions.sell_feed_uploader import _download_result_csv  # noqa: PLC0415
    text = _download_result_csv(driver, url, target_fname_hint=target_hint, timeout_sec=30)
    print(f"  download OK: {len(text)} chars")
    return text


def parse_csv(csv_text: str) -> tuple[Counter, list[dict]]:
    """CSV テキストを Status 集計 + 行詳細 に分解."""
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = list(reader)
    counter = Counter()
    for r in rows:
        counter[r.get("Status", "?")] += 1
    return counter, rows


def main():
    parser = argparse.ArgumentParser(
        description="eBay 履歴から直近 upload の結果ファイルを DL → CSV パース"
    )
    parser.add_argument("csv", nargs="?", default=None,
                        help="upload 元 CSV ファイル名 (basename or full path)。省略時は最新 revise_BOTH_*.csv 自動検出")
    parser.add_argument("--csv", dest="csv_kw", default=None,
                        help="csv (positional と同等の named 形式)")
    parser.add_argument("--history-rows", type=int, default=10,
                        help="同じ stem に対する eBay 側結果採用上限 (default 10)")
    parser.add_argument("--headless", action="store_true",
                        help="headless mode で起動 (default は headful = 視認可)")
    args = parser.parse_args()

    csv_arg = args.csv or args.csv_kw
    if csv_arg:
        target_path = Path(csv_arg)
        if not target_path.is_absolute():
            target_path = CSV_OUTPUT_DIR / target_path.name
        target_filename = target_path.name
    else:
        latest = find_latest_revise_csv()
        target_filename = latest.name
        print(f"[INFO] 最新 CSV 自動検出: {latest}")

    print(f"[START] check_upload_result for {target_filename}")
    print(f"  driver 起動 (headless={args.headless})")
    driver = create_ebay_driver(headless=args.headless, use_profile=True)

    try:
        if not is_logged_in(driver):
            print("  [!] ログイン未確認、続行試行")

        href = find_result_link(driver, target_filename, max_history_rows=args.history_rows)
        if href is None:
            print("[FAIL] 結果ファイルが eBay 履歴で見つからなかった")
            print("  → 真に未受理 or 履歴更新遅延 or DOM 構造変更")
            sys.exit(2)

        # csv stem を hint として渡す (= 正しいファイルを特定するため)
        target_stem = target_filename[:-4] if target_filename.endswith(".csv") else target_filename
        csv_text = download_result_csv(driver, href, target_hint=target_stem)
        counter, rows = parse_csv(csv_text)

        print()
        print(f"[3/3] Status 集計 (total={len(rows)}):")
        for st, n in counter.most_common():
            print(f"  {n:>4}  {st}")
        non_warning = [r for r in rows if r.get("Status") != "Warning"]
        if non_warning:
            print()
            print(f"  [!] Warning 以外 {len(non_warning)} 件:")
            for r in non_warning:
                print(f"    item={r.get('ItemID')} status={r.get('Status')} "
                      f"err={(r.get('ErrorMessage') or '')[:60]!r}")

        DECISION_LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = DECISION_LOG_DIR / f"check_result_{ts}.json"
        out.write_text(json.dumps({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "target_filename": target_filename,
            "result_url": href,
            "status_counter": dict(counter),
            "total_rows": len(rows),
            "rows": rows,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print()
        print(f"[OK] saved: {out}")

        # 終了コード: Warning のみなら 0、Failure/Error 含むなら 1
        if non_warning:
            sys.exit(1)
        sys.exit(0)
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
