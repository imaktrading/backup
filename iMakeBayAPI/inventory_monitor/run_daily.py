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
    """auto_qty_zero.py の stdout から処理結果を抽出.

    Trading API 移行後 (2026-06-03) は trading_api_uploader が
    'CSV 行数 N 件 (variation / single listing)' + 'upload 件数: ok=N ng=M / 計 K' +
    'result_text: Success S + Warning W + safe Failure F + action-needed Failure A + Transient T'
    を出力する。 旧 sell_feed_uploader 文言とも互換維持。
    """
    info = {"variation_executed": 0, "variation_success": None,
            "single_executed": 0, "single_success": None,
            "candidates": 0, "two_cycle_pass": 0,
            "ok": 0, "ng": 0, "total": 0,
            "success": 0, "warning": 0,
            "safe_failure": 0, "action_needed_failure": 0, "transient": 0}
    for line in out.splitlines():
        m = re.search(r"候補.*?(\d+)\s*件", line)
        if m and info["candidates"] == 0:
            info["candidates"] = int(m.group(1))
        m = re.search(r"二段確認 pass[:：]\s*(\d+)\s*件", line)
        if m: info["two_cycle_pass"] = int(m.group(1))
        m = re.search(r"CSV 行数 .*?[:：]?\s*(\d+)", line)
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
        # Trading API 件数内訳 (= 'upload 件数: ok=N ng=M / 計 K')
        m = re.search(r"upload 件数[:：]\s*ok=(\d+)\s+ng=(\d+)\s*/\s*計\s*(\d+)", line)
        if m:
            info["ok"] += int(m.group(1))
            info["ng"] += int(m.group(2))
            info["total"] += int(m.group(3))
        # result_text 内訳 (= 'Success S + Warning W + safe Failure F + action-needed Failure A + Transient T')
        m = re.search(r"Success\s+(\d+)\s*\+\s*Warning\s+(\d+)\s*\+\s*safe Failure\s+(\d+)\s*\+\s*action-needed Failure\s+(\d+)(?:\s*\+\s*Transient\s+(\d+))?", line)
        if m:
            info["success"] += int(m.group(1))
            info["warning"] += int(m.group(2))
            info["safe_failure"] += int(m.group(3))
            info["action_needed_failure"] += int(m.group(4))
            info["transient"] += int(m.group(5) or 0)
    return info


def _format_report(start: datetime, end: datetime,
                   monitor: dict, zero: dict, restore: dict,
                   step_results: list) -> tuple[str, str]:
    """監視くん風の 1 通レポート (subject, body) を生成.

    HQ 2026-06-10 ユーザー要件: メール冒頭 2 行で 2 系統判定可能化
    - 仕入元在庫監視 (= UNIQLO/GU/montbell/workman/amazon の variation scrape)
    - eBay 在庫調整 (= variation/listing の qty=0 化 + qty=1 復活)
    """
    all_ok = all(ok for _, ok in step_results)
    dur = end - start
    dur_str = f"{int(dur.total_seconds() // 60)}分{int(dur.total_seconds() % 60)}秒"

    total_processed = (zero["variation_executed"] + zero["single_executed"]
                       + restore["variation_executed"] + restore["single_executed"])

    # 判定方針 (ユーザー指示 2026-06-10、 = 漏れ 0 最優先原則):
    # 「100% でなければ異常」。 1 件でも不確実 = 売れたら履行不能 = BAN risk。
    # 「N% 以内なら正常」 は漏れ容認思想で禁止。
    #   ✅: 完全成功 (= errors=0 / ng=0 / 100%)
    #   ⚠️: 1 件でも error / ng (= 即対応要)
    #   ❌: 系統的異常 (= step 失敗 = 動作不能)

    # 仕入元在庫監視ステータス
    listings_count = monitor.get("listings", 0) or 0
    scrape_errors = monitor.get("errors", 0) or 0
    scrape_step_failed = any(not ok for name, ok in step_results if "monitor" in name.lower())
    if scrape_step_failed:
        scrape_status = "❌ 異常 (monitor step 失敗、 scrape phase 自体が動作不能)"
    elif scrape_errors == 0:
        scrape_status = f"✅ 正常 ({listings_count} listing 全件 scrape 成功)"
    else:
        # 1 件でも error あれば ⚠️ (= その listing の variation 在庫状況不明 → 売れたら履行不能 risk)
        err_rate = (scrape_errors / listings_count) if listings_count else 0
        scrape_status = f"⚠️ 要対応 ({listings_count} listing 中 scrape error {scrape_errors} 件 ({err_rate*100:.1f}%) — 該当 listing の variation 在庫状況不明)"

    # eBay 在庫調整ステータス
    zero_ng = zero.get("ng", 0) or 0
    restore_ng = restore.get("ng", 0) or 0
    total_ng = zero_ng + restore_ng
    revise_step_failed = any(not ok for name, ok in step_results
                              if "qty_zero" in name.lower() or "restore" in name.lower()
                              or "audit" in name.lower())
    if revise_step_failed:
        ebay_status = f"❌ 異常 (revise step 失敗、 動作不能 or 部分実行) — 処理 {total_processed} 件 / 失敗 {total_ng} 件"
    elif total_processed == 0:
        ebay_status = "✅ 対象なし (= qty 変更要なし)"
    elif total_ng > 0:
        ebay_status = f"⚠️ 要対応 (処理 {total_processed} 件 / 失敗 {total_ng} 件 — variation ng={zero_ng + restore_ng}、 1 件でも 漏れたら BAN risk)"
    else:
        ebay_status = f"✅ 全件 qty 変更完了 (処理 {total_processed} 件、 zero {zero['variation_executed']+zero['single_executed']} + restore {restore['variation_executed']+restore['single_executed']})"

    # subject 用: 全体判定
    if scrape_step_failed or revise_step_failed:
        overall = "異常: step 失敗あり"
    elif total_ng > 0 or err_rate >= 0.1:
        overall = "要確認 or 要対応"
    elif total_processed > 0:
        overall = "正常 (qty 変更実施)"
    else:
        overall = "正常"

    subject = f"[公式監視くん] 巡回レポート: {overall} (処理 {total_processed} 件)"

    lines = [
        "=" * 50,
        "公式監視くん 巡回レポート",
        "=" * 50,
        # ★ HQ 2026-06-10 ユーザー要件: 冒頭 2 行で 2 系統判定可能化
        f"仕入元在庫監視 : {scrape_status}",
        f"eBay 在庫調整  : {ebay_status}",
        f"開始時刻   : {start.strftime('%Y-%m-%d %H:%M')}",
        f"終了時刻   : {end.strftime('%Y-%m-%d %H:%M')}",
        f"所要時間   : {dur_str}",
        f"対象スプシ  : ★公式在庫要チェック",
    ]
    # ⚠️ / ❌ のときの対応手順 (= ユーザー指示 2026-06-10 load-bearing 化)
    if scrape_step_failed:
        lines.append("")
        lines.append("【★仕入元在庫監視 要対応】")
        lines.append("  対応手順 (= scrape phase 自体停止、 全 listing 在庫不明):")
        lines.append("  1. logs/2026-XX-XX.log の末尾を確認 → 何で詰まったか")
        lines.append("  2. UNIQLO/GU 公式 API 障害 / chromedriver / login 切れ を chk")
        lines.append("  3. 復旧後、 手動 cycle 再実行: `python iMakeBayAPI/inventory_monitor/run_daily.py`")
        lines.append("  対応期限: **即時** (= 全 listing 在庫状況不明)")
    elif scrape_errors > 0:
        lines.append("")
        lines.append("【★仕入元在庫監視 要対応】")
        lines.append(f"  該当 listing は logs/2026-XX-XX.log の \"⚠️\" or \"scrape 失敗\" を grep")
        lines.append("  対応手順 (= 漏れ 0 最優先):")
        lines.append("  1. error 内容を確認:")
        lines.append("     - 'ConnectionError' / 'getaddrinfo' = transient → 次 cycle (翌 08:00) で auto retry、 待つで OK")
        lines.append("     - 公式 API 404 / 構造変更 = supplier 側の変更 → scraper 修正依頼")
        lines.append("     - login 失敗 = 認証切れ → 手動 login 再実施")
        lines.append("  2. 持続的に同 listing で error → 手動 chk")
        lines.append("  対応期限: 24 時間以内 (翌日 08:00 cycle 前)")
    if revise_step_failed:
        lines.append("")
        lines.append("【★eBay 在庫調整 要対応】")
        lines.append("  対応手順 (= revise step 失敗、 動作不能):")
        lines.append("  1. logs/2026-XX-XX.log の zero / restore / audit_heal step 詳細 chk")
        lines.append("  2. eBay Trading API 障害 / OAuth token 切れ / quota 超過 を chk")
        lines.append("  3. 復旧後、 手動再実行")
        lines.append("  対応期限: **即時** (= 取下げ/復活全件 漏れ)")
    elif total_ng > 0:
        lines.append("")
        lines.append("【★eBay 在庫調整 要対応】")
        lines.append(f"  ng {total_ng} 件 (= variation 個別 revise 失敗、 csv_output/ の最新 CSV で詳細確認)")
        lines.append("  対応手順:")
        lines.append("  1. csv_output/heal_zero_<ts>.csv or revise_qty0_<ts>.csv で 失敗 itemID + variation specifics chk")
        lines.append("  2. eBay で手動 qty 確認 (= eventual consistency なら既に qty=0 化済 = false positive)")
        lines.append("  3. qty>0 残存なら 手動 ReviseInventoryStatus or 翌 cycle で audit_heal phase が自動再 revise")
        lines.append("  対応期限: 24 時間以内")
    lines.extend([
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
    def _detail(info: dict) -> str:
        """件数 内訳: 'ok=N / ng=M (transient=T)' (= Trading API output 由来、 件数あり時のみ)."""
        if info.get("total", 0) == 0 and info.get("ok", 0) == 0 and info.get("ng", 0) == 0:
            return ""
        parts = [f"ok={info.get('ok', 0)}", f"ng={info.get('ng', 0)}"]
        if info.get("transient", 0) > 0:
            parts.append(f"transient={info['transient']}")
        if info.get("safe_failure", 0) > 0:
            parts.append(f"safe={info['safe_failure']}")
        return " (" + " / ".join(parts) + ")"

    lines.append("【eBay qty=0 化 (= 仕入元切れ × 出品中)】")
    lines.append(f"  variation Revise : {zero['variation_executed']} 件 "
                 f"({'成功' if zero['variation_success'] else 'なし/失敗'})"
                 + (_detail(zero) if zero['variation_executed'] else ""))
    lines.append(f"  listing Revise   : {zero['single_executed']} 件 "
                 f"({'成功' if zero['single_success'] else 'なし/失敗'})"
                 + (_detail(zero) if zero['single_executed'] else ""))
    lines.append("")
    lines.append("【eBay qty=1 復活 (= 仕入元復活 × 出品停止中)】")
    lines.append(f"  variation Revise : {restore['variation_executed']} 件 "
                 f"({'成功' if restore['variation_success'] else 'なし/失敗'})"
                 + (_detail(restore) if restore['variation_executed'] else ""))
    lines.append(f"  listing Revise   : {restore['single_executed']} 件 "
                 f"({'成功' if restore['single_success'] else 'なし/失敗'})"
                 + (_detail(restore) if restore['single_executed'] else ""))
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
    # 2026-05-29 cycle 末 audit + 自動修復 (= silent fail 検知 + heal、 課題 #2 拡張版)
    # 「ヘンだったら 自動で やり直す」 仕組み。 audit のみ → 不整合 0 件で silent、
    # 1+ で 自動 revise CSV 生成 + upload + 15 分後 反映検証。
    # --no-verify で 待機 skip も可能 (= cron 時間短縮)
    if latest_report:
        after_steps.append(("audit_heal",
                            [PY, "audit_and_heal.py", "--report", latest_report,
                             "--no-verify"]))   # daily 内では verify skip、 別 cron で
    # 2026-05-29 scrape 精度 audit (= 10 件 sample re-scrape)
    after_steps.append(("scrape_audit",
                        [PY, "audit_scrape_accuracy.py", "--sample", "10"]))

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
