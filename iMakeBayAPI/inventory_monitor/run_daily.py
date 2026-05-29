"""run_daily - 1 日 1 回 cycle の wrapper + 統合 cycle report メール送信.

実行内容:
  1. main.py --supplier all --ebay-report auto  (= DL + K 列同期 + 監視)
  2. auto_qty_zero.py --mode=zero --execute     (= qty=0 化)
  3. auto_qty_zero.py --mode=restore --execute  (= qty=1 復活)

監視くん (mercari 系) に合わせて 1 cycle = 1 メールに統合。
各 subprocess の個別メール送信は INVENTORY_MONITOR_SUPPRESS_EMAIL=1 で抑制、
本 wrapper が最後に統合 cycle report を 1 通送信する。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

PY = sys.executable

EBAY_REPORT_DIR = Path(r"C:\Users\imax2\local_data\iMakInventory\ebay_active_listing_dl")


def _latest_ebay_report() -> str:
    """main.py の --ebay-report auto で DL された最新 CSV path を取得."""
    if not EBAY_REPORT_DIR.exists():
        return ""
    csvs = sorted(
        EBAY_REPORT_DIR.glob("eBay-all-active-listings-report-*.csv"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    return str(csvs[0]) if csvs else ""




def _log(msg: str):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def _parse_monitor_output(out: str) -> dict:
    """main.py の stdout から集計を抽出."""
    info = {"listings": 0, "updates": 0, "needs_action": 0, "errors": 0,
            "prev_needs_action": None, "k_sync_changed": None}
    for line in out.splitlines():
        m = re.search(r"処理 listing\s*[:：]\s*(\d+)", line)
        if m: info["listings"] = int(m.group(1))
        m = re.search(r"生成 update\s*[:：]\s*(\d+)", line)
        if m: info["updates"] = int(m.group(1))
        m = re.search(r"要対処 SKU\s*[:：]\s*(\d+)", line)
        if m: info["needs_action"] = int(m.group(1))
        m = re.search(r"エラー\s*[:：]\s*(\d+)", line)
        if m: info["errors"] = int(m.group(1))
        m = re.search(r"前回\s*(\d+)\s*→\s*今回\s*(\d+)", line)
        if m: info["prev_needs_action"] = int(m.group(1))
        m = re.search(r"K 列乖離\s*(\d+)", line)
        if m: info["k_sync_changed"] = int(m.group(1))
    return info


def _parse_qty_output(out: str) -> dict:
    """auto_qty_zero.py の stdout から処理結果を抽出."""
    info = {"variation_executed": 0, "variation_success": None,
            "single_executed": 0, "single_success": None,
            "candidates": 0, "two_cycle_pass": 0}
    for line in out.splitlines():
        m = re.search(r"候補.*?(\d+)\s*件", line)
        if m and info["candidates"] == 0:
            info["candidates"] = int(m.group(1))
        m = re.search(r"二段確認 pass[:：]\s*(\d+)\s*件", line)
        if m: info["two_cycle_pass"] = int(m.group(1))
        m = re.search(r"CSV 行数 .*?[:：]\s*(\d+)", line)
        if m:
            if "listing" in line.lower() or "単独" in line:
                info["single_executed"] = int(m.group(1))
            else:
                info["variation_executed"] += int(m.group(1))
        m = re.search(r"upload (?:結果|:).*?success[=:]?\s*(True|False)", line)
        if m:
            ok = m.group(1) == "True"
            if info["variation_success"] is None: info["variation_success"] = ok
            else: info["single_success"] = ok
    return info


def _format_report(start: datetime, end: datetime,
                   monitor: dict, zero: dict, restore: dict,
                   step_results: list) -> tuple[str, str]:
    """監視くん風の 1 通レポート (subject, body) を生成."""
    all_ok = all(ok for _, ok in step_results)
    dur = end - start
    dur_str = f"{int(dur.total_seconds() // 60)}分{int(dur.total_seconds() % 60)}秒"

    total_processed = (zero["variation_executed"] + zero["single_executed"]
                       + restore["variation_executed"] + restore["single_executed"])
    overall = "正常" if all_ok else "異常"
    if total_processed > 0 and all_ok:
        overall = "正常 (qty 変更実施)"
    elif not all_ok:
        overall = "異常: step 失敗あり"

    subject = f"[公式監視くん] 巡回レポート: {overall} (処理 {total_processed} 件)"

    lines = [
        "=" * 50,
        "公式監視くん 巡回レポート",
        "=" * 50,
        f"結果      : {overall}",
        f"開始時刻   : {start.strftime('%Y-%m-%d %H:%M')}",
        f"終了時刻   : {end.strftime('%Y-%m-%d %H:%M')}",
        f"所要時間   : {dur_str}",
        f"対象スプシ  : ★公式在庫要チェック",
        "",
        "【在庫監視】(uniqlo / gu / montbell / amazon 公式サイト巡回)",
        f"  処理 listing  : {monitor['listings']} 件",
        f"  生成 update   : {monitor['updates']} 件",
        f"  要対処 SKU    : {monitor['needs_action']} 件 (前回比 "
        f"{monitor['prev_needs_action'] if monitor['prev_needs_action'] is not None else '-'} → "
        f"{monitor['needs_action']})",
        f"  scrape error  : {monitor['errors']} 件",
    ]
    if monitor.get("k_sync_changed") is not None:
        lines.append(f"  K 列同期      : {monitor['k_sync_changed']} 件 更新")
    lines.append("")
    lines.append("【eBay qty=0 化 (= 仕入元切れ × 出品中)】")
    lines.append(f"  variation Revise : {zero['variation_executed']} 件 "
                 f"({'成功' if zero['variation_success'] else 'なし/失敗'})")
    lines.append(f"  listing Revise   : {zero['single_executed']} 件 "
                 f"({'成功' if zero['single_success'] else 'なし/失敗'})")
    lines.append("")
    lines.append("【eBay qty=1 復活 (= 仕入元復活 × 出品停止中)】")
    lines.append(f"  variation Revise : {restore['variation_executed']} 件 "
                 f"({'成功' if restore['variation_success'] else 'なし/失敗'})")
    lines.append(f"  listing Revise   : {restore['single_executed']} 件 "
                 f"({'成功' if restore['single_success'] else 'なし/失敗'})")
    lines.append("")
    lines.append("【step 結果】")
    for name, ok in step_results:
        lines.append(f"  {name:>8}: {'OK' if ok else 'NG'}")
    lines.append("=" * 50)
    return subject, "\n".join(lines)


def _send_report_email(subject: str, body: str) -> bool:
    """iMakInventory の既存 email_notifier 流用."""
    try:
        inv_root = SCRIPT_DIR.parent.parent / "iMakInventory"
        if str(inv_root) not in sys.path:
            sys.path.insert(0, str(inv_root))
        from email_notifier import _send_via_gmail  # noqa: PLC0415
        from auth.encrypted_gmail import load_gmail_config  # noqa: PLC0415
        cfg = load_gmail_config()
        if cfg is None:
            _log("[mail] DPAPI Gmail 未設定、メール送信 skip")
            return False
        addr, pw, to = cfg
        _send_via_gmail(addr, pw, to, subject, body)
        return True
    except Exception as e:
        _log(f"[mail] 送信失敗: {type(e).__name__}: {e}")
        return False


def main():
    start = datetime.now()
    _log("=" * 60)
    _log("公式監視くん 1 cycle 開始")
    _log("=" * 60)

    # 個別メール抑制 (= 統合 report のみ送る)
    env = os.environ.copy()
    env["INVENTORY_MONITOR_SUPPRESS_EMAIL"] = "1"

    step_results = []
    outputs = {}
    # monitor で eBay report DL してから uuid_sync が最新 path を取れるよう、
    # STEPS を 2 段階で構築: monitor 単独実行 → uuid_sync+zero+restore
    initial_steps = [("monitor", [PY, "main.py", "--supplier", "all", "--ebay-report", "auto"])]
    for name, cmd in initial_steps:
        _log(f">>> step: {name}")
        try:
            res = subprocess.run(cmd, cwd=str(SCRIPT_DIR), env=env,
                                 capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", check=False)
            ok = res.returncode == 0
            outputs[name] = (res.stdout or "") + "\n" + (res.stderr or "")
            _log(f"<<< step {name}: rc={res.returncode} ({'OK' if ok else 'NG'})")
            step_results.append((name, ok))
        except Exception as e:
            _log(f"<<< step {name}: 例外 {type(e).__name__}: {e}")
            outputs[name] = f"EXCEPTION: {e}"
            step_results.append((name, False))

    # monitor 後の最新 report を sku_uuid_sync に渡す
    after_steps = []
    latest_report = _latest_ebay_report()
    if latest_report:
        after_steps.append(("uuid_sync",
                            [PY, "sku_uuid_sync.py", "--report", latest_report, "--execute"]))
    else:
        _log(">>> step uuid_sync: skip (eBay report 未 DL)")
        step_results.append(("uuid_sync", False))
    after_steps.append(("zero",    [PY, "auto_qty_zero.py", "--mode=zero", "--execute"]))
    after_steps.append(("restore", [PY, "auto_qty_zero.py", "--mode=restore", "--execute"]))
    # 2026-05-29 cycle 末 audit (= sheet 対処済 vs eBay 実 qty 全件照合、 silent fail 検知)
    if latest_report:
        after_steps.append(("audit",
                            [PY, "audit_sheet_vs_ebay.py", "--report", latest_report]))

    for name, cmd in after_steps:
        _log(f">>> step: {name}")
        try:
            res = subprocess.run(cmd, cwd=str(SCRIPT_DIR), env=env,
                                 capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", check=False)
            ok = res.returncode == 0
            outputs[name] = (res.stdout or "") + "\n" + (res.stderr or "")
            _log(f"<<< step {name}: rc={res.returncode} ({'OK' if ok else 'NG'})")
            step_results.append((name, ok))
        except Exception as e:
            _log(f"<<< step {name}: 例外 {type(e).__name__}: {e}")
            outputs[name] = f"EXCEPTION: {e}"
            step_results.append((name, False))

    end = datetime.now()
    monitor = _parse_monitor_output(outputs.get("monitor", ""))
    zero = _parse_qty_output(outputs.get("zero", ""))
    restore = _parse_qty_output(outputs.get("restore", ""))

    subject, body = _format_report(start, end, monitor, zero, restore, step_results)
    _log("\n" + body)
    sent = _send_report_email(subject, body)
    _log(f"[mail] 統合 report 送信: {'OK' if sent else 'NG'}")

    sys.exit(0 if all(ok for _, ok in step_results) else 1)


if __name__ == "__main__":
    main()
