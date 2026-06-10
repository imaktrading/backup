"""email_notifier - cycle 完了時に Gmail SMTP で結果メールを送信.

設計:
- **opt-in**: auth.encrypted_gmail に config が無ければ送信 skip (= 既存挙動完全保持)
- **fail-safe**: 送信失敗は cycle 全体を落とさない (raise しない、stderr に warning のみ)
- **冪等**: cycle_log を入力に取り、副作用なし (= retry / dry-run 容易)
- 件名で結果が一目で分かる: [OK] / [NG] / [SKIP]
- 本文は cycle_log 全 phase の human-readable 整形

使い方 (run_cycle から):
    from email_notifier import send_cycle_report
    send_cycle_report(cycle_log)   # 失敗しても cycle は止まらない
"""
from __future__ import annotations

import smtplib
import sys
from email.mime.text import MIMEText
from email.utils import formatdate
from typing import Any, Dict, Optional


def _summarize_result_text(result_text: str) -> str:
    """eBay 上の result_text を日本語サマリに変換.

    eBay FileExchange の result_text 例:
        "Warning 4 + safe Failure 0 + action-needed Failure 0"
    分類:
        - Warning N      : 受理されたが軽微指摘あり (= 取下げ成功扱い)
        - safe Failure N : eBay 側の都合 (画像要件等)、当方の処理は問題なし
        - action-needed Failure N : 要対応の失敗 (実害あり)
    """
    if not result_text:
        return ""
    import re
    w = re.search(r"Warning\s*(\d+)", result_text)
    sf = re.search(r"safe\s*Failure\s*(\d+)", result_text)
    af = re.search(r"action-needed\s*Failure\s*(\d+)", result_text)
    parts = []
    if w:
        parts.append(f"受理 {w.group(1)} 件")
    if sf and sf.group(1) != "0":
        parts.append(f"画像要件等 {sf.group(1)} 件")
    if af and af.group(1) != "0":
        parts.append(f"要対応失敗 {af.group(1)} 件")
    return " / ".join(parts) if parts else result_text


def _translate_error(err: str) -> str:
    """よくあるエラー文字列を日本語に簡訳."""
    if not err:
        return ""
    head = err.split("\n", 1)[0]
    low = head.lower()
    if "not_logged_in" in low or "not logged in" in low:
        return "eBay ログイン切れ"
    if "ebay_status_failed" in low:
        # Status fallback で「N failed, M completed」を捕まえたケース
        return f"eBay 側で一部失敗 ({head.split(':', 1)[1].strip() if ':' in head else head})"
    if "ebay_status_pending" in low:
        return "eBay 側で処理中 (In progress / Pending、次 cycle で確定)"
    if "result_csv_download_failed" in low and "503" in low:
        return "結果 CSV 取得失敗 (eBay サーバ 503、Submit は届いている可能性大)"
    if "result_csv_download_failed" in low:
        return "結果 CSV 取得失敗 (Submit は届いている可能性大、要 eBay 履歴目視)"
    if "chrome not reachable" in low:
        return "Chrome 起動失敗 (profile lock 残存 等)"
    if "sessionnotcreated" in low or "this version of chromedriver" in low:
        return "Chrome バージョン不一致 (driver 更新待ち)"
    if "lost sys.stdin" in low:
        return "cron 環境で input() 失敗 (旧版 hotfix で対処済)"
    if "upload result not detected" in low:
        return "判定不安定 (eBay 側受理済みの可能性大、要 eBay 履歴目視)"
    if "action_needed_failure" in low:
        return "eBay 側で取下げ拒否 (画像要件 / Item Specifics 不備等、listing 個別対応必要)"
    if "timeout" in low:
        return "タイムアウト (一時的)"
    return head[:120]


def _is_submit_likely_succeeded(err: str) -> bool:
    """error 文字列から「Submit は実は届いている」が推定できるか判定.

    503 / 判定不安定 / 履歴に出てこない 等は「結果取得失敗だけで Submit は届いている」
    可能性が高い → 「異常」ではなく「警告」と表現する。
    """
    if not err:
        return False
    low = err.lower()
    return ("result_csv_download_failed" in low
            or "upload result not detected" in low
            or "result_not_in_history" in low)


def _format_subject(cycle_log: Dict[str, Any]) -> str:
    """件名: [OK]/[NG]/[SKIP] + 巡回時刻 + 結果 1 行サマリ."""
    status = cycle_log.get("status", "unknown")
    ts_start = cycle_log.get("ts_start", "")[:16].replace("T", " ")
    upload = cycle_log["phases"].get("upload", {}) if "phases" in cycle_log else {}

    if status == "success":
        prefix = "[OK]"
        summary = _summarize_result_text(upload.get("result_text", ""))
        tail = f" 取下げ {summary}" if summary else ""
    elif status in ("success_no_upload", "success_no_changes"):
        prefix = "[SKIP]"
        tail = " 取下げ対象なし"
    elif status == "upload_failed":
        err = upload.get('error', '')
        if _is_submit_likely_succeeded(err):
            prefix = "[警告]"
            tail = f" 結果取得不能 (Submit 届いた可能性大): {_translate_error(err)}"
        else:
            prefix = "[NG]"
            tail = f" 取下げ失敗: {_translate_error(err)}"
    elif status == "error":
        prefix = "[NG]"
        tail = f" 巡回中に例外: {_translate_error(cycle_log.get('error', ''))}"
    else:
        prefix = "[?]"
        tail = f" 不明な状態: {status}"

    return f"{prefix} iMakInventory 巡回 {ts_start}{tail}"


def _fmt_ts(iso_ts: str) -> str:
    """ISO 形式 (2026-05-09T17:30:02) → '2026-05-09 17:30' に短縮."""
    if not iso_ts:
        return "?"
    return iso_ts[:16].replace("T", " ")


def _fmt_duration(start_iso: str, end_iso: str) -> str:
    """所要時間を '35分' / '1時間2分' で返す."""
    try:
        from datetime import datetime  # noqa: PLC0415
        s = datetime.fromisoformat(start_iso)
        e = datetime.fromisoformat(end_iso)
        sec = int((e - s).total_seconds())
        if sec < 60:
            return f"{sec}秒"
        m, s = divmod(sec, 60)
        if m < 60:
            return f"{m}分{s:02d}秒" if s else f"{m}分"
        h, m = divmod(m, 60)
        return f"{h}時間{m:02d}分"
    except Exception:
        return "?"


_STATUS_JP = {
    "success": "正常 (取下げ実施)",
    "success_no_upload": "正常 (取下げ対象なし)",
    "success_no_changes": "正常 (在庫変動なし)",
    "upload_failed": "異常: 取下げ失敗",
    "error": "異常: 巡回中に例外",
}


def _status_label(cycle_log: Dict[str, Any]) -> str:
    """status を見て「結果」表示の日本語を返す.

    upload_failed の中でも「Submit 届いた可能性大」のときは「警告」と表現.
    """
    status = cycle_log.get("status", "unknown")
    if status == "upload_failed":
        up = cycle_log.get("phases", {}).get("upload", {}) or {}
        err = up.get("error", "")
        if _is_submit_likely_succeeded(err):
            return "警告: 結果取得不能 (Submit 届いた可能性大、要 eBay 履歴目視)"
    return _STATUS_JP.get(status, status)


def _format_sheet_label(cycle_log: Dict[str, Any]) -> str:
    """対象スプシの表示文字列を作る.

    sheet_id 単一指定 (= cron の通常運用) を最優先で判定し、HIGH / LOW を当てる。
    sheet_id 未指定の場合のみ sheet 引数 (high/low/both) で判定。
    """
    # 遅延 import (循環回避 + import コスト削減)
    try:
        from sheet_updater import HIGH_SHEET_ID, LOW_SHEET_ID  # noqa: PLC0415
    except Exception:
        HIGH_SHEET_ID = LOW_SHEET_ID = None

    sheet_id = cycle_log.get("sheet_id")
    if sheet_id:
        if sheet_id == HIGH_SHEET_ID:
            return "HIGH のみ"
        if sheet_id == LOW_SHEET_ID:
            return "LOW のみ"
        label = cycle_log.get("sheet_label") or "?"
        return f"単一スプシ ({label})"

    # sheet_id 未指定: sheet 引数 (high/low/both) で判定
    sheet_arg = cycle_log.get("sheet", "")
    return {
        "both": "HIGH + LOW 両方",
        "high": "HIGH のみ",
        "low":  "LOW のみ",
    }.get(sheet_arg, sheet_arg or "?")


def _format_body(cycle_log: Dict[str, Any]) -> str:
    """cycle_log を日本語の読みやすいレポートに整形.

    HQ 2026-06-10 FINAL 指示 C: 冒頭 1 行で「⚠️ 要対応 Y件」 or 「✅ 全件完了」 を
    明示。 詳細はその後でよい。 「正常」 は全件 qty=0 確認時のみ。

    ユーザー指示 2026-06-10 「放置禁止」: 本関数自体が例外で落ちると silent 化 risk。
    例外時は最小 fallback body を返して必ず通知を出す。
    """
    try:
        return _format_body_inner(cycle_log)
    except Exception as e:
        # 「format 失敗 → email 出さない」 = silent 化、 絶対禁止。
        # fallback 自体も例外で死なないよう、 全 access を try で保護した最小版。
        try:
            import traceback as _tb  # noqa: PLC0415
            def _safe(getter):
                try:
                    return getter()
                except Exception:
                    return "?"
            status = _safe(lambda: str(cycle_log.get("status", "?")))
            ts_start = _safe(lambda: str(cycle_log.get("ts_start", "?")))
            ts_end = _safe(lambda: str(cycle_log.get("ts_end", "?")))
            phases_keys = _safe(lambda: str(list((cycle_log.get("phases") or {}).keys())))
            tb_text = _safe(lambda: _tb.format_exc()[:1500])
            return (
                "=" * 50 + "\n"
                "iMakInventory 巡回レポート (★ format 例外、 fallback 表示)\n"
                + "=" * 50 + "\n"
                "★ 注意: email format コード自体が例外。 cycle 結果は decision_log/cycle_*.jsonl 参照。\n"
                "★ 対応期限: 即時 (= report 不完全 = 漏れ視認 困難)\n"
                "\n"
                f"format 例外: {type(e).__name__}: {str(e)[:200]}\n"
                "\n--- traceback ---\n" + tb_text + "\n"
                "\n--- cycle_log 抜粋 ---\n"
                f"status: {status}\n"
                f"ts_start: {ts_start}\n"
                f"ts_end:   {ts_end}\n"
                f"phases:   {phases_keys}\n"
                + "=" * 50 + "\n"
            )
        except Exception as e2:
            # fallback すら crash した最後の砦 (= 「気付き」 だけ最低限届ける)
            return (
                f"[★iMakInventory] email format 二重例外、 cycle 結果不明。\n"
                f"format error: {type(e).__name__}\n"
                f"fallback error: {type(e2).__name__}\n"
                f"=> decision_log/cycle_*.jsonl の最新ファイルを目視 chk してください。\n"
            )


def _format_body_inner(cycle_log: Dict[str, Any]) -> str:
    """旧 _format_body 本体 (= 通常ロジック)。 例外は外側 wrapper で fallback 処理。"""
    lines = []
    phases = cycle_log.get("phases", {}) or {}

    # HQ 2026-06-10 FINAL 指示 C: 取下げサマリ
    # 売切検知 N → 完了 X / 未取下げ Y を1 行で。
    # 後方互換性: action_required_summary 未投入 (= 旧形式 cycle_log) はスキップして status_jp 表示
    mon = phases.get("monitor", {}) or {}
    up = phases.get("upload", {}) or {}
    rc = phases.get("revise_csv", {}) or {}
    ar = phases.get("action_required_summary")
    has_action_summary = ar is not None  # 新形式 cycle_log フラグ
    ar = ar or {}
    newly_sold = (mon.get("newly_sold", 0) or 0) if mon else 0
    # 完了 = upload で success かつ verified、 または safe_failure (= 既 ended)
    completed = 0
    for res in (up.get("results") or []):
        if res.get("success"):
            completed += 1
    action_count = ar.get("count", 0) or 0
    untaken = action_count

    status_jp = _status_label(cycle_log)

    lines.append("=" * 50)
    lines.append("iMakInventory 巡回レポート")
    lines.append("=" * 50)

    # ★最重要 2 行: 2 系統 (= 仕入元在庫監視 / eBay 在庫調整) の冒頭ステータス
    # (= 「うまくいったか」 を一目で判定可能、 ユーザー要件 2026-06-10)
    #
    # 判定方針 (ユーザー指示 2026-06-10、 = 漏れ 0 最優先原則):
    # 「100% でなければ異常」。 1 件でも不確実 = 売れたら履行不能 = BAN risk。
    # 「N% 以内なら正常」 は漏れ容認思想で禁止。
    #   ✅: 完全成功 (= errors=0 / untaken=0 / 100%)
    #   ⚠️: 1 件でも error / 未対応 (= 即対応要)
    #   ❌: 系統的異常 (= scrape phase 全断 / step 失敗 / 急増ガード発火 = 大量誤判定疑い)
    if has_action_summary:
        # 仕入元在庫監視ステータス
        processed = (mon.get("processed", 0) or 0) if mon else 0
        errors = (mon.get("errors", 0) or 0) if mon else 0
        reasons_set = {it.get("reason", "") for it in (ar.get("items") or [])}
        scraper_burst = "newly_sold_burst_guard_holdout" in reasons_set
        sheet_write_anomaly = "reinclude_burst_guard_holdout" in reasons_set
        if scraper_burst:
            scrape_status = f"❌ 異常 (scraper 系急増ガード発火、 偽 OOS or 本物大量売切の判別要)"
        elif sheet_write_anomaly:
            scrape_status = f"❌ 異常 (スプシ書込系の系統的失敗疑い、 監視結果の反映不完全)"
        elif errors == 0:
            scrape_status = f"✅ 正常 ({processed} 件全件 scrape 成功)"
        else:
            # 1 件でも error あれば ⚠️ (= その行の在庫状況不明 → 売れたら履行不能 risk)
            err_rate = (errors / processed) if processed else 0
            scrape_status = f"⚠️ 要対応 ({processed} 件中 通信エラー {errors} 件 ({err_rate*100:.1f}%) — 該当 row の在庫状況不明、 次 cycle で再試行)"
        lines.append(f"仕入元在庫監視 : {scrape_status}")

        # eBay 在庫調整ステータス
        if newly_sold == 0 and action_count == 0:
            lines.append(f"eBay 在庫調整  : ✅ 対象なし (= 新規売切検知 0 件)")
        elif action_count > 0:
            lines.append(f"eBay 在庫調整  : ⚠️ 要対応 (売切検知 {newly_sold} → 完了 {completed} / 未取下げ {action_count})")
        else:
            lines.append(f"eBay 在庫調整  : ✅ 全件取下げ完了 (売切検知 {newly_sold} → 完了 {completed})")
    else:
        # 旧形式 cycle log (= action_required_summary 未投入): fallback
        lines.append(f"結果      : {status_jp}")

    lines.append(f"開始時刻   : {_fmt_ts(cycle_log.get('ts_start', ''))}")
    lines.append(f"終了時刻   : {_fmt_ts(cycle_log.get('ts_end', ''))}")
    lines.append(f"所要時間   : {_fmt_duration(cycle_log.get('ts_start', ''), cycle_log.get('ts_end', ''))}")
    lines.append(f"対象スプシ  : {_format_sheet_label(cycle_log)}")
    if cycle_log.get("test_mode"):
        lines.append("注意      : テストモード (本番運用ではない)")

    # 仕入元在庫監視で error/異常がある場合の対応手順 (= ユーザー指示 2026-06-10 load-bearing 化)
    if has_action_summary:
        scrape_issue = (mon.get("errors", 0) or 0) > 0
        # 急増ガード発火状況は scrape_status に含まれる
        if scrape_issue or "急増ガード" in (locals().get("scrape_status") or ""):
            lines.append("")
            lines.append(f"【★仕入元在庫監視 要対応】 該当行と対応手順")
            error_rows = (mon.get("error_rows") or [])
            if error_rows:
                lines.append(f"  エラー row 詳細 (上位 {min(len(error_rows), 10)} 件):")
                for er in error_rows[:10]:
                    short_err = (er.get("error") or "")[:80]
                    lines.append(f"  - {er.get('sheet','?')} row{er.get('row_index','?')} "
                                  f"iid={er.get('item_id') or '(空)'} sup={er.get('supplier','?')}")
                    lines.append(f"      url: {er.get('url','')[:100]}")
                    lines.append(f"      err: {short_err}")
                if (mon.get("errors", 0) or 0) > 10:
                    lines.append(f"  ... 他 {(mon.get('errors', 0) or 0) - 10} 件 (全件: logs/listings_<date>.log)")
                # 対応手順
                lines.append("")
                lines.append("  対応手順 (= 漏れ 0 最優先、 該当 row の在庫状況不明):")
                lines.append("  1. err 内容を確認:")
                lines.append("     - 'ConnectionError' / 'getaddrinfo failed' / 'Timeout' = transient → 次 cycle で auto retry、 待つで OK")
                lines.append("     - 'unsupported supplier' = URL 不正 → スプシ A 列 URL を手動修正")
                lines.append("     - '404' / 'page not found' = listing 削除済 → 仕入元側で確認、 必要なら手動 D=○ 化")
                lines.append("     - その他 = scraper 構造変更疑い → log 詳細 chk + 修正依頼")
                lines.append("  2. transient なら待つ。 持続的に同 row で error → 手動 chk")
                lines.append(f"  対応期限: 4 時間以内 (次 cycle 開始前)、 ただし 該当 row 売れたら履行不能 risk あり")
            else:
                # 急増ガード発火 or scrape phase 全断
                lines.append(f"  全断疑い (詳細 row 取得不能):")
                lines.append("  対応手順:")
                lines.append("  1. logs/listings_<date>.log の末尾を確認 → どこで詰まったか")
                lines.append("  2. chromedriver / Selenium UI 構造変更 / login 切れ を chk")
                lines.append("  3. 復旧後、 手動 cycle 再実行: `python run_cycle.py --sheet both`")
                lines.append(f"  対応期限: **即時** (= scrape 動作不能、 全 row 在庫不明)")

    # 未取下げ詳細を冒頭近くに (= 詳細はその後で OK の原則だが、 要対応は即明示)
    if action_count > 0:
        lines.append("")
        lines.append(f"【★要対応 — 未取下げ {action_count} 件】 (手動対処 or 次 cycle で auto retry)")
        # HQ 2026-06-10 confirm 指示 C: 手動 SLA 明記
        # 通常 reason → 次 cycle (4h 後) で auto retry されるので 「4h 以内」
        # reinclude_burst_guard_holdout → sheet 書込系異常疑い → 「即時」
        # newly_sold_burst_guard_holdout → scraper 系異常疑い (= 偽 OOS or 本物大量売切) → 「即時」
        # HQ Phase 1.6 affirm #1: burst HOLD は 「本物大量売切」 だと fail-OPEN なので 即時 release 経路 明示
        reasons_in_actions = {it.get("reason", "") for it in (ar.get("items") or [])}
        has_newly_sold_burst = "newly_sold_burst_guard_holdout" in reasons_in_actions
        has_reinclude_burst = "reinclude_burst_guard_holdout" in reasons_in_actions
        if has_newly_sold_burst or has_reinclude_burst:
            lines.append("  対応期限    : **即時** (= 急増ガード発火、 系統的異常 or 本物大量売切の判別要)")
            lines.append("  ★ load-bearing: HOLD のまま放置すると本物の売切時に fail-OPEN (= 出品継続→無在庫履行不能)")
            lines.append("  release 手順:")
            if has_newly_sold_burst:
                lines.append("    # 1. dry-run で対象一覧確認")
                lines.append("    python -m tools.release_holdouts --reason newly_sold_burst_guard_holdout")
                lines.append("    # 2. eBay 検索や scraper 個別確認で 本物 vs 偽 OOS 判別")
                lines.append("    # 3. 本物なら execute (= 取下げ実行 + verify)")
                lines.append("    python -m tools.release_holdouts --reason newly_sold_burst_guard_holdout --execute")
            if has_reinclude_burst:
                lines.append("    # sheet 書込系の系統的異常確認 (= DNS / Sheets API quota / 認証切れ)")
                lines.append("    python -m tools.release_holdouts --reason reinclude_burst_guard_holdout --execute")
        else:
            lines.append("  対応期限    : 4 時間以内 (= 次 cycle 開始前、 自然 retry も並行発火)")
        # reason 別 対応手順
        has_item_id_empty = "item_id_empty" in reasons_in_actions
        has_verify_giveup = "verify_qty_gt0_giveup" in reasons_in_actions
        if has_item_id_empty or has_verify_giveup:
            lines.append("  対応手順 (reason 別):")
            if has_item_id_empty:
                lines.append("    item_id_empty:")
                lines.append("      1. スプシ B 列 (itemID) を確認 → 空欄なら eBay で title 検索 → ID 引き直し → スプシ手動入力")
                lines.append("      2. 入力後、 次 cycle で auto 検知 + revise")
                lines.append("      3. eBay 出品がない場合 → スプシ B 列に「NONE」 記入 (= 監視除外)")
            if has_verify_giveup:
                lines.append("    verify_qty_gt0_giveup (= revise 後 in-cycle 65s で qty=0 反映確認できず):")
                lines.append("      1. 該当 itemID を手動で eBay 確認 → 既に qty=0 なら eventual consistency 由来 (false positive)")
                lines.append("      2. qty>0 残存なら release CLI で 再 revise:")
                lines.append("         python -m tools.release_holdouts --reason verify_qty_gt0_giveup --execute")
                lines.append("      3. 持続的に出る itemID → variation specifics の mismatch 疑い、 手動 chk 要")
        for it in (ar.get("items") or [])[:10]:
            iid = it.get("item_id") or "(item_id 空欄)"
            lines.append(f"  - {it.get('sheet','?')} row{it.get('row','?')} iid={iid} reason={it.get('reason','')}")
            t = it.get("title") or ""
            if t:
                lines.append(f"    \"{t}\"")
        if action_count > 10:
            lines.append(f"  ... 他 {action_count - 10} 件 (詳細: decision_log/action_required.jsonl)")
    lines.append("")

    phases = cycle_log.get("phases", {}) or {}

    # 在庫監視 (monitor) — 一番大事なところ
    mon = phases.get("monitor", {}) or {}
    if mon:
        lines.append("【在庫監視】(仕入元サイトのページを巡回)")
        processed = mon.get("processed", 0) or 0
        errors = mon.get("errors", 0) or 0
        lines.append(f"  チェック件数  : {processed} 件")
        lines.append(f"  新規売切検知  : {mon.get('newly_sold', '?')} 件 ← eBay から取下げ対象")
        lines.append(f"  在庫復活検知  : {mon.get('newly_in_stock', '?')} 件")
        rate = (errors / processed) if processed else 0
        if errors == 0:
            lines.append("  通信エラー    : 0 件")
        elif rate >= 0.5:
            lines.append(f"  通信エラー    : {errors} 件 / {processed} 件中 ({rate*100:.0f}%) ★★ 異常高率、scraper or anti-bot 要確認")
        elif rate >= 0.1:
            lines.append(f"  通信エラー    : {errors} 件 / {processed} 件中 ({rate*100:.0f}%) ★ やや多い、傾向監視")
        else:
            lines.append(f"  通信エラー    : {errors} 件 (一時的、次 cycle で再試行)")
        lines.append("")

    # eBay 取下げ (revise + upload)
    rc = phases.get("revise_csv", {}) or {}
    up = phases.get("upload", {}) or {}
    if rc or up:
        lines.append("【eBay 取下げ】")
        if rc.get("skipped"):
            lines.append("  取下げ対象   : なし (新規売切なし)")
        elif rc:
            candidates = rc.get("candidates", 0) or 0
            allowed = rc.get("allowed", 0) or 0
            mon_newly_sold = mon.get("newly_sold", 0) or 0 if mon else 0
            excluded = mon_newly_sold - candidates
            if excluded > 0:
                lines.append(f"  CSV 生成     : {allowed} 件 (売切 {mon_newly_sold} 件中、item_id 空欄等で {excluded} 件除外)")
            else:
                lines.append(f"  CSV 生成     : {allowed} 件 (条件 OK で対象化)")
            deferred = rc.get("deferred", 0) or 0
            if deferred:
                lines.append(f"  保留         : {deferred} 件 (条件未達、次 cycle 持越)")

        if up.get("skipped"):
            # rc 側で既に「対象なし」表示済みなら upload 行は省略
            if not rc.get("skipped"):
                lines.append("  upload      : スキップ (取下げ対象が無いため)")
        elif up:
            success = up.get("success")
            csv_lines = up.get("csv_lines", "?")
            err_text = up.get("error", "")
            submit_likely_ok = _is_submit_likely_succeeded(err_text)
            if success:
                summary = _summarize_result_text(up.get("result_text", ""))
                lines.append(f"  upload結果   : 成功 ({csv_lines} 件処理) → {summary}")
            elif submit_likely_ok:
                # Submit は届いている可能性大、結果取得だけ失敗
                lines.append(f"  upload結果   : Submit OK / 結果取得失敗 ({csv_lines} 件、要 eBay 履歴目視)")
                lines.append(f"  失敗内容     : {_translate_error(err_text)}")
                if up.get("page_url"):
                    lines.append(f"  確認 URL     : {up['page_url']}")
            else:
                lines.append(f"  upload結果   : 失敗 ({csv_lines} 件未送信)")
                lines.append(f"  失敗内容     : {_translate_error(err_text)}")
                if up.get("page_url"):
                    lines.append(f"  確認 URL     : {up['page_url']}")
                # upload phase 全断時の対応手順 (ユーザー指示 2026-06-10 load-bearing 化)
                lines.append(f"  対応手順 (= upload phase 全断、 取下げ送信ゼロ → 漏れ全件):")
                err_low = (err_text or "").lower()
                if "connectionerror" in err_low or "getaddrinfo" in err_low or "timeout" in err_low:
                    lines.append("    1. transient (DNS/Connection/Timeout) → 数分待つ + 次 cycle で auto retry 想定")
                    lines.append("    2. 連続失敗なら network 自体 chk: `Test-NetConnection api.ebay.com -Port 443`")
                elif "oauth" in err_low or "token" in err_low or "iaftoken" in err_low or "invalid" in err_low:
                    lines.append("    1. OAuth token 切れ疑い → ユーザー認証画面で再 OAuth 取得")
                    lines.append("    2. credentials/api_key.txt の token 更新 → 手動 cycle 再実行")
                else:
                    lines.append(f"    1. logs/cycle_<ts>.jsonl の upload phase 詳細を chk")
                    lines.append("    2. eBay Developer dashboard で API 障害情報 chk")
                    lines.append("    3. 復旧後、 手動 cycle 再実行: `python run_cycle.py --sheet both`")
                lines.append(f"    対応期限: **即時** (= 取下げ漏れ全件 → 全 BAN risk)")
        lines.append("")

    # ヘルス (upload_health)
    uh = phases.get("upload_health", {}) or {}
    if uh:
        lines.append("【ヘルス】(連続失敗の検知)")
        nl = uh.get("not_logged_in_streak", 0) or 0
        fl = uh.get("flaky_streak", 0) or 0
        gn = uh.get("generic_failure_streak", 0) or 0
        # 「汎用エラー」の中身を直近 error から推定して詳細表示
        last_err = uh.get("last_failure_error") or up.get("error") or ""
        gn_detail = ""
        if gn > 0 and last_err:
            low = last_err.lower()
            if "result_csv_download_failed" in low:
                gn_detail = " (= 結果 CSV 取得 503 が継続)"
            elif "chrome not reachable" in low:
                gn_detail = " (= Chrome 起動失敗が継続)"
            else:
                gn_detail = f" (= {_translate_error(last_err)[:40]})"
        lines.append(f"  ログイン切れ : 連続 {nl} 回 {'← 即時アラート対象' if nl > 0 else '(正常)'}")
        lines.append(f"  判定不安定   : 連続 {fl} 回 {'← 3回でアラート' if fl >= 3 else ''}")
        lines.append(f"  汎用エラー   : 連続 {gn} 回{gn_detail} {'← 2回でアラート' if gn >= 2 else ''}")
        if uh.get("alert_fired"):
            lines.append(f"  → アラート発火 ({uh.get('reason', '')})")
        lines.append("")

    # reverse_audit (HQ 2026-06-10 confirm 指示 B: 「再発しない」 の唯一の客観証拠)
    ra = phases.get("reverse_audit", {}) or {}
    if ra:
        lines.append("【reconciliation】(意図 D=○ vs 実 eBay qty>0 突合)")
        # ユーザー指示 「放置禁止」: phase 自体 error の場合は「乖離 0」 と誤表示しない
        # (= silent 化 risk、 嘘の安心)。 error key が立ってたら未実行を明示。
        if ra.get("error"):
            lines.append(f"  ❌ reverse_audit phase 失敗、 突合不能: {ra.get('error')[:120]}")
            lines.append("  ★ 注意: 取下げ漏れ最後の砦が動作不能、 「乖離 0」 表記なし = 嘘の安心 排除")
            lines.append("  対応期限: **即時** (= reconciliation 動かない = 漏れ検知不能)")
            lines.append("")
            ra = {}  # 以降の通常 path をスキップ
        else:
            pass  # 通常 path へ続く
    if ra:
        mc = ra.get("mismatch_count", 0) or 0
        if mc == -1:
            lines.append(f"  ★中断: {ra.get('error', '')}")
            lines.append(f"  対応期限: **即時** (= sheet 読込系の異常、 audit 機能停止中)")
        elif mc == 0:
            lines.append(f"  ✅ 乖離 0 件 (= 継続証跡を 1 件積上げ)")
        else:
            lines.append(f"  ⚠️ 乖離 {mc} 件検出 ← 取下げ漏れの直接証拠")
            by_sheet = ra.get("by_sheet", {}) or {}
            by_supplier = ra.get("by_supplier", {}) or {}
            if by_sheet:
                lines.append(f"     sheet 別: {by_sheet}")
            if by_supplier:
                lines.append(f"     supplier 別: {by_supplier}")
            lines.append(f"     log: {ra.get('log_path', '')}")
            lines.append(f"  注意: 初回 (= 5 週間分の既存乖離) は鳥瞰として正常 = audit 機能の証拠")
            lines.append(f"        当日内に件数を減らす目標は不要、 人手で順次潰す。 継続乖離なし状態 が「再発しない」 の証跡")
            lines.append(f"  対応期限: **24 時間以内** (= 翌日 09:30 cycle 前に乖離 -1 件以上の進捗)")
        lines.append("")

    # 補助情報 (折りたたみ的扱い)
    aux = []
    pp = phases.get("pytest_precheck", {}) or {}
    if pp:
        aux.append(f"テスト事前実行 : {pp.get('status', '?')} ({pp.get('elapsed_sec', '?')}秒)")
    bk = phases.get("backup", {}) or {}
    for label, info in bk.items():
        if isinstance(info, dict):
            b = info.get("backup", {}) or {}
            aux.append(f"スプシ backup : {label} → {b.get('row_count', '?')} 行")
    aud = phases.get("audit_sample", {}) or {}
    for label, a in aud.items():
        if isinstance(a, dict):
            aux.append(f"抜取監査     : {label} → {a.get('appended', '?')} 件 audit タブに追記")
    if aux:
        lines.append("【補助】")
        for x in aux:
            lines.append(f"  {x}")
        lines.append("")

    # cycle 全体の例外
    if cycle_log.get("error"):
        lines.append("【巡回中に例外発生】")
        lines.append(f"  {_translate_error(cycle_log['error'])}")
        tb = cycle_log.get("traceback", "")
        if tb:
            lines.append("--- traceback (debug 用) ---")
            lines.append(tb[:1500])
        lines.append("")

    lines.append("=" * 50)
    lines.append("（このメールは iMakInventory が自動送信しています）")
    return "\n".join(lines)


def _send_via_gmail(address: str, app_password: str, to: str,
                    subject: str, body: str,
                    smtp_host: str = "smtp.gmail.com",
                    smtp_port: int = 465,
                    timeout: int = 30) -> None:
    """Gmail SMTP で送信。失敗時は例外 raise (呼出側で握る)."""
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = address
    msg["To"] = to
    msg["Date"] = formatdate(localtime=True)

    with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=timeout) as smtp:
        smtp.login(address, app_password)
        smtp.send_message(msg)


def send_cycle_report(cycle_log: Dict[str, Any]) -> Dict[str, Any]:
    """cycle 完了レポートを Gmail SMTP で送信。

    opt-in: encrypted_gmail.dat 不在なら skip。
    fail-safe: 送信失敗しても raise しない (cycle 全体を止めない)。

    Returns:
        {"sent": bool, "skipped_reason": Optional[str], "error": Optional[str]}
    """
    # 遅延 import (auth/encrypted_gmail は pywin32 依存、テストで不要なら触らない)
    try:
        from auth.encrypted_gmail import load_gmail_config  # noqa: PLC0415
    except Exception as e:
        return {"sent": False, "skipped_reason": None,
                "error": f"import failed: {type(e).__name__}: {e}"}

    cfg = load_gmail_config()
    if cfg is None:
        return {"sent": False,
                "skipped_reason": "encrypted_gmail.dat 不在 (= opt-in 未有効化)",
                "error": None}

    address, app_password, to = cfg

    try:
        subject = _format_subject(cycle_log)
        body = _format_body(cycle_log)
        _send_via_gmail(address, app_password, to, subject, body)
        return {"sent": True, "skipped_reason": None, "error": None}
    except Exception as e:
        msg = f"send failed: {type(e).__name__}: {e}"
        # cycle を止めないため stderr に warning のみ
        print(f"  [!] email_notifier: {msg}", file=sys.stderr)
        return {"sent": False, "skipped_reason": None, "error": msg}


# ----------------------------------------------------------------------------
# CLI: 動作確認用 (tools/setup_email.py で credentials 保存後の smoke test)
# ----------------------------------------------------------------------------
def main():
    """CLI: ダミー cycle_log を 1 通送信 (smoke test 用)."""
    dummy_log = {
        "ts_start": "2026-05-09T12:34:56",
        "ts_end": "2026-05-09T13:00:00",
        "sheet": "both",
        "test_mode": True,
        "status": "success",
        "phases": {
            "monitor": {"processed": 100, "newly_sold": 1, "newly_in_stock": 0, "errors": 0},
            "revise_csv": {"candidates": 1, "allowed": 1, "deferred": 0, "reason": "OK"},
            "upload": {"success": True, "csv_lines": 1,
                       "result_text": "Warning 1 + safe Failure 0 + action-needed Failure 0",
                       "error": None},
            "upload_health": {"alert_fired": False, "reason": "",
                              "not_logged_in_streak": 0, "flaky_streak": 0,
                              "generic_failure_streak": 0},
        },
    }
    res = send_cycle_report(dummy_log)
    print(res)


if __name__ == "__main__":
    main()
