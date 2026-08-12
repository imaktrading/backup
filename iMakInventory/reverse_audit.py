"""reverse_audit — 意図状態 (sheet D=○) vs 実 eBay 状態 (qty>0) の reconciliation.

HQ 2026-06-10 FINAL 指示 D + confirm 指示 B 準拠:
- 「取下げ義務 persist」 の最後の砦
- 「再発しないこと」 の唯一の客観証拠 (= 継続乖離 0 件)
- 初回実行は 「乖離 0 件」 を目標にしない (= 5 週間分の既存乖離を全列挙して鳥瞰、 fail-OPEN 隠ぺい禁止)
- read-only 突合 + critical alert のみ。 auto-fix は Phase 2 で別検討。

統合先: run_cycle.py の `--sheet both` cycle (毎日 09:30) 末尾の phase として呼出。
4h cycle (--sheet-label SHEET 単一 mode) では skip (= API quota / 実行時間考慮、 日次で十分)。

出力:
- `decision_log/reverse_audit_<ts>.jsonl`: 不整合 entry の機械可読 log
- 返り値: {"mismatch_count": N, "by_sheet": {...}, "by_supplier": {...}, "items": [...]}

★ HQ Phase 1.6 affirm #2 backstop 機能:
- newly_sold burst HOLD (= 6/3 偽 OOS 95 件型対策) は閾値 30 件で発火、 22-29 件帯は通過
- このとき burst guard が発火しなかった場合 (= 通過した取下げ漏れ) も、 sheet D は newly_sold で
  ○ マーク済 → 取下げ未送なら eBay qty>0 が残る → **次 09:30 cycle の reverse_audit で必ず catch**
- = burst guard (予防) + reverse_audit (検知) の 2 段防御で隙間を埋める設計
- burst HOLD された entry (= 取下げ実行されず action_required.jsonl 残存) も同様に backstop:
  sheet D=○ 維持、 eBay qty>0 残存 → reverse_audit が検出 → email alert で人手 release 誘導
- 「予防が空振りした」 失敗モードも 「検知が catch」 する relationship を sheet+eBay 突合で物理担保
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sheet_updater import (  # noqa: E402
    HIGH_SHEET_ID,
    LOW_SHEET_ID,
    open_sheet_by_id,
    get_listings_worksheet,
    read_listings_rows,
)

DECISION_LOG_DIR = ROOT_DIR / "decision_log"
SOLD_MARKERS = ("○", "〇")


def _detect_supplier(url: str) -> str:
    u = (url or "").lower()
    if "mercari" in u:
        return "mercari"
    if "amazon" in u:
        return "amazon"
    if "fril" in u:
        return "fril"
    if "snkrdunk" in u:
        return "snkrdunk"
    return "other"


def _fetch_ebay_qty_map() -> dict:
    """eBay GetSellerList で active listing 全件取得 → {item_id: qty} map.

    iMakeBayAPI/inventory_monitor/ebay_active_listing_via_trading_api の
    download_active_listing_via_trading_api() を流用 (= CSV 出力 + 互換 column)。
    """
    monitor_path = ROOT_DIR.parent / "iMakeBayAPI" / "inventory_monitor"
    if str(monitor_path) not in sys.path:
        sys.path.insert(0, str(monitor_path))
    from ebay_active_listing_via_trading_api import (  # noqa: PLC0415
        download_active_listing_via_trading_api,
    )
    import csv as _csv  # noqa: PLC0415

    csv_path = download_active_listing_via_trading_api()
    qty_map = {}
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = _csv.DictReader(f)
        for row in reader:
            iid = (row.get("Item number") or "").strip()
            if not iid:
                continue
            try:
                qty = int(row.get("Available quantity") or 0)
            except (TypeError, ValueError):
                qty = 0
            # variation listing は同 item_id で複数行、 合計 qty で集計
            qty_map[iid] = qty_map.get(iid, 0) + qty
    return qty_map


def run_reverse_audit(
    high_sheet_id: Optional[str] = None,
    low_sheet_id: Optional[str] = None,
    write_log: bool = True,
    qty_map: Optional[dict] = None,
) -> dict:
    """逆方向 reconciliation 実行 (= sheet D=○ + eBay active qty>0 検出).

    Returns: {
        "ts": "...",
        "mismatch_count": N,
        "by_sheet":    {"HIGH": ..., "LOW": ...},
        "by_supplier": {"mercari": ..., "amazon": ..., ...},
        "items": [
            {"sheet": "HIGH", "row_index": 25, "item_id": "...",
             "ebay_qty": 1, "supplier": "mercari", "url": "...", "title": "..."},
            ...
        ],
        "elapsed_sec": float,
        "log_path": str | None,
    }
    """
    t0 = time.time()
    h_id = high_sheet_id or HIGH_SHEET_ID
    l_id = low_sheet_id or LOW_SHEET_ID

    print("  [reverse_audit] Step 1: eBay active listing 全件取得...", flush=True)
    if qty_map is None:
        qty_map = _fetch_ebay_qty_map()
    print(f"  [reverse_audit] eBay active: {len(qty_map)} 件 ({time.time()-t0:.0f}s)", flush=True)

    # 安全弁 (2026-06-11 追加): active map 空 = eBay 取得失敗 (DNS/API障害) → fail-closed。
    # ガードが無いと、 空 map のまま突合して全 D=○ 行が「乖離なし」= 偽の mismatch 0 件
    # (= fail-OPEN) になり、 取下げ漏れを見逃したまま「✅ 乖離0件」を継続証跡に積んでしまう。
    # (2026-06-11 09:30 cycle で DNS flaky 時に elapsed 4.3s / mismatch 0 = 偽0 を実観測)。
    # sibling run_ebay_down_sheet_active_audit と同じ防御。 この口座は常時 active 多数のため
    # 空 = 取得失敗で確定 (真に 0 listing になることはない)。
    if not qty_map:
        print("  [!] [reverse_audit] active map 空 = eBay 取得失敗、 fail-closed 中断", flush=True)
        return {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "mismatch_count": -1,
            "error": "ebay_active_map_empty",
            "by_sheet": {}, "by_supplier": {}, "items": [],
            "elapsed_sec": time.time() - t0,
            "log_path": None,
        }

    print("  [reverse_audit] Step 2: HIGH/LOW スプシ D 列読込...", flush=True)
    all_rows = []
    for label, sid in [("HIGH", h_id), ("LOW", l_id)]:
        try:
            sh = open_sheet_by_id(sid)
            ws = get_listings_worksheet(sh)
            rows = read_listings_rows(ws, only_with_url=False)
            for r in rows:
                all_rows.append({"sheet": label, **r})
            print(f"  [reverse_audit] {label}: {len(rows)} 行", flush=True)
        except Exception as e:
            print(f"  [!] [reverse_audit] {label} 読込失敗: {type(e).__name__}: {e}", flush=True)
            # sheet 読込失敗 = fail-CLOSED で audit 中断 (= 部分結果を出すと「ゼロ件」 と誤読される)
            return {
                "ts": datetime.now().isoformat(timespec="seconds"),
                "mismatch_count": -1,
                "error": f"sheet_read_failed: {label} {type(e).__name__}",
                "elapsed_sec": time.time() - t0,
                "log_path": None,
            }

    print("  [reverse_audit] Step 3: 乖離検出 (D=○ + eBay qty>0)...", flush=True)
    # ★ 2026-08-13: 同一 item_id が複数行 (仕入元違い) で管理されることがある。
    #   片方の仕入元が売切 (D=○) でも、**別行の仕入元にまだ在庫がある**なら eBay が active
    #   なのは正しく、fail-OPEN ではない。これを乖離に数えていたため、3 件が 5 日連続で
    #   MISMATCH として鳴り続けていた (08-09〜08-13、誰も対処できない = 無視される alert)。
    #   在庫のある行は URL を持つものに限る (URL 空 + D 空欄 は「未設定」であって在庫ではない)。
    alive_ids = {
        (r.get("item_id") or "").strip()
        for r in all_rows
        if (r.get("item_id") or "").strip()
        and (r.get("url") or "").strip()
        and (r.get("current_sold") or "").strip() not in SOLD_MARKERS
    }

    items, suppressed = [], []
    for r in all_rows:
        iid = (r.get("item_id") or "").strip()
        d_col = (r.get("current_sold") or "").strip()
        if not iid:
            continue
        if d_col not in SOLD_MARKERS:
            continue
        qty = qty_map.get(iid)
        if qty is not None and qty > 0:
            entry = {
                "sheet":      r["sheet"],
                "row_index":  r.get("row_index", -1),
                "item_id":    iid,
                "ebay_qty":   qty,
                "supplier":   _detect_supplier(r.get("url", "")),
                "url":        r.get("url", "")[:200],
                "title":      (r.get("title") or "")[:80],
            }
            if iid in alive_ids:
                # silent drop 禁止: 数えないが log には残す (後から検証できる形にする)
                suppressed.append({**entry, "suppressed_reason": "other_row_in_stock"})
            else:
                items.append(entry)
    if suppressed:
        print(f"  [reverse_audit] 別行に在庫あり = 乖離ではない: {len(suppressed)} 件 "
              f"(item_id {sorted({s['item_id'] for s in suppressed})})", flush=True)

    from collections import Counter  # noqa: PLC0415
    result = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "mismatch_count": len(items),
        "by_sheet":    dict(Counter(it["sheet"] for it in items)),
        "by_supplier": dict(Counter(it["supplier"] for it in items)),
        "items":       items,
        "suppressed":  suppressed,
        "elapsed_sec": time.time() - t0,
        "log_path":    None,
    }

    # decision_log への書込 (= 機械可読 + 履歴保全)
    if write_log:
        DECISION_LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = DECISION_LOG_DIR / f"reverse_audit_{ts}.jsonl"
        with open(log_path, "w", encoding="utf-8") as f:
            # ヘッダ entry: 集計
            f.write(json.dumps({
                "kind": "summary",
                "ts": result["ts"],
                "mismatch_count": result["mismatch_count"],
                "by_sheet": result["by_sheet"],
                "by_supplier": result["by_supplier"],
                "suppressed_count": len(suppressed),
                "elapsed_sec": result["elapsed_sec"],
            }, ensure_ascii=False) + "\n")
            # 各 entry
            for it in items:
                f.write(json.dumps({"kind": "mismatch", **it},
                                    ensure_ascii=False) + "\n")
            for it in suppressed:
                f.write(json.dumps({"kind": "suppressed", **it},
                                    ensure_ascii=False) + "\n")
        result["log_path"] = str(log_path)

    print(f"  [reverse_audit] 乖離: {result['mismatch_count']} 件 "
          f"sheet 別 {result['by_sheet']} supplier 別 {result['by_supplier']}", flush=True)
    return result


# ============================================================================
# 逆方向 #2 (2026-06-10 user 指示): eBay qty=0/ended だが sheet 未売切 (D 空欄)
#   → 「在庫あり・eBay取下げ済」 レビュー用シートに書き出す。
#   背景: eBay が勝手に取下げ / ユーザー手動取下げ で eBay は qty=0 or ended だが
#         スプシ D 列は未更新 (= まだ active 扱い) のものを、 人手レビュー用に列挙。
#   方向: reverse_audit (D=○ + qty>0) の鏡像 (D 空欄 + qty=0/不在)。
#   安全弁: active map が空 = eBay 取得失敗 → fail-closed (全件を誤って ended 扱いしない)。
#   D 列は触らない (= 自動売切化しない、 user 指示で 「書き出すだけ」)。
# ============================================================================
ORPHAN_SHEET_TITLE = "在庫あり・eBay取下げ済"
ORPHAN_HEADER = ["itemID", "eBay URL", "仕入元URL", "タイトル",
                 "eBay状態", "sheet", "row", "検出日時"]


def _get_or_create_worksheet(sh, title: str):
    """worksheet を取得、 無ければ作成 (gspread)."""
    try:
        return sh.worksheet(title)
    except Exception:  # gspread.WorksheetNotFound 等
        return sh.add_worksheet(title=title, rows=200, cols=len(ORPHAN_HEADER))


def _write_orphan_sheet(sh, label: str, items: list, ts_str: str) -> int:
    """label (HIGH/LOW) の orphan items を当該 spreadsheet の review tab に上書き."""
    ws = _get_or_create_worksheet(sh, ORPHAN_SHEET_TITLE)
    data = [ORPHAN_HEADER]
    for it in items:
        ebay_url = f"https://www.ebay.com/itm/{it['item_id']}" if it["item_id"] else ""
        data.append([
            it["item_id"], ebay_url, it.get("url", ""), it.get("title", ""),
            it["ebay_state"], it["sheet"], it["row_index"], ts_str,
        ])
    ws.clear()
    last_col = chr(ord("A") + len(ORPHAN_HEADER) - 1)
    ws.batch_update(
        [{"range": f"A1:{last_col}{len(data)}", "values": data}],
        value_input_option="USER_ENTERED",
    )
    return len(items)


def run_ebay_down_sheet_active_audit(
    high_sheet_id: Optional[str] = None,
    low_sheet_id: Optional[str] = None,
    write_sheet: bool = True,
    write_log: bool = True,
    qty_map: Optional[dict] = None,
) -> dict:
    """eBay qty=0/ended × sheet D 空欄 (未売切) を検出 → review シート出力.

    Returns: {
        "ts", "orphan_count", "by_sheet", "by_state" (qty0 / ended),
        "active_total", "coverage" (D空欄 item の active map ヒット率),
        "items": [...], "elapsed_sec", "log_path", "error" (任意),
    }
    """
    t0 = time.time()
    h_id = high_sheet_id or HIGH_SHEET_ID
    l_id = low_sheet_id or LOW_SHEET_ID

    print("  [ebay_down_audit] Step 1: eBay active listing 全件取得...", flush=True)
    if qty_map is None:
        qty_map = _fetch_ebay_qty_map()
    print(f"  [ebay_down_audit] eBay active: {len(qty_map)} 件 ({time.time()-t0:.0f}s)", flush=True)

    # 安全弁: active map が空 = eBay 取得失敗。 全 sheet 行を 「ended」 と誤判定して
    # review シートを汚染するのを防ぐ → fail-closed で中断。
    if not qty_map:
        print("  [!] [ebay_down_audit] active map 空 = eBay 取得失敗、 fail-closed 中断", flush=True)
        return {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "orphan_count": -1,
            "error": "ebay_active_map_empty",
            "elapsed_sec": time.time() - t0,
            "log_path": None,
        }

    print("  [ebay_down_audit] Step 2: HIGH/LOW スプシ読込...", flush=True)
    sheets = {}
    all_rows = []
    for label, sid in [("HIGH", h_id), ("LOW", l_id)]:
        try:
            sh = open_sheet_by_id(sid)
            ws = get_listings_worksheet(sh)
            rows = read_listings_rows(ws, only_with_url=False)
            sheets[label] = sh
            for r in rows:
                all_rows.append({"sheet": label, **r})
            print(f"  [ebay_down_audit] {label}: {len(rows)} 行", flush=True)
        except Exception as e:
            print(f"  [!] [ebay_down_audit] {label} 読込失敗: {type(e).__name__}: {e}", flush=True)
            return {
                "ts": datetime.now().isoformat(timespec="seconds"),
                "orphan_count": -1,
                "error": f"sheet_read_failed: {label} {type(e).__name__}",
                "elapsed_sec": time.time() - t0,
                "log_path": None,
            }

    print("  [ebay_down_audit] Step 3: 検出 (D空欄 + eBay qty=0/不在)...", flush=True)
    items = []
    d_empty_with_id = 0
    found_in_active = 0
    for r in all_rows:
        iid = (r.get("item_id") or "").strip()
        d_col = (r.get("current_sold") or "").strip()
        if not iid:
            continue            # item_id 空欄 = 未出品 (Req1)、 対象外
        if d_col in SOLD_MARKERS:
            continue            # 既に売切マーク済 = 対象外 (reverse_audit が別途扱う)
        d_empty_with_id += 1
        qty = qty_map.get(iid)
        if qty is None:
            ebay_state = "ended/未active(要確認)"   # active 一覧に不在 = 終了/削除
        elif qty == 0:
            found_in_active += 1
            ebay_state = "qty=0"
        else:
            found_in_active += 1
            continue            # qty>0 = eBay も active = 正常 (= orphan でない)
        items.append({
            "sheet":      r["sheet"],
            "row_index":  r.get("row_index", -1),
            "item_id":    iid,
            "ebay_state": ebay_state,
            "supplier":   _detect_supplier(r.get("url", "")),
            "url":        r.get("url", "")[:200],
            "title":      (r.get("title") or "")[:80],
        })

    from collections import Counter  # noqa: PLC0415
    coverage = round(found_in_active / d_empty_with_id, 3) if d_empty_with_id else None
    result = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "orphan_count": len(items),
        "by_sheet":    dict(Counter(it["sheet"] for it in items)),
        "by_state":    dict(Counter(it["ebay_state"] for it in items)),
        "active_total": len(qty_map),
        "coverage":    coverage,
        "items":       items,
        "elapsed_sec": time.time() - t0,
        "log_path":    None,
        "sheet_writes": {},
    }

    # review シート書込 (= HIGH/LOW それぞれの spreadsheet 内 tab に上書き)
    if write_sheet:
        ts_str = result["ts"]
        for label, sh in sheets.items():
            label_items = [it for it in items if it["sheet"] == label]
            try:
                n = _write_orphan_sheet(sh, label, label_items, ts_str)
                result["sheet_writes"][label] = n
                print(f"  [ebay_down_audit] {label} review シート書込: {n} 件", flush=True)
            except Exception as e:
                print(f"  [!] [ebay_down_audit] {label} シート書込失敗: {type(e).__name__}: {e}", flush=True)
                result["sheet_writes"][label] = f"write_failed: {type(e).__name__}"

    # jsonl log (機械可読 + 履歴)
    if write_log:
        DECISION_LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = DECISION_LOG_DIR / f"ebay_down_audit_{ts}.jsonl"
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "kind": "summary", "ts": result["ts"],
                "orphan_count": result["orphan_count"],
                "by_sheet": result["by_sheet"], "by_state": result["by_state"],
                "active_total": result["active_total"], "coverage": coverage,
                "elapsed_sec": result["elapsed_sec"],
            }, ensure_ascii=False) + "\n")
            for it in items:
                f.write(json.dumps({"kind": "orphan", **it}, ensure_ascii=False) + "\n")
        result["log_path"] = str(log_path)

    print(f"  [ebay_down_audit] orphan: {result['orphan_count']} 件 "
          f"sheet 別 {result['by_sheet']} state 別 {result['by_state']} "
          f"(active {result['active_total']} 件, coverage {coverage})", flush=True)
    return result


# ============================================================================
# daily 専用エントリ (2026-06-25): 06-16 のスケジュール再編で run_cycle の
#   `--sheet both` cycle が消滅 → Phase 5 reverse_audit が自動実行されなくなった。
#   安全原則「定期 reconciliation で乖離ゼロを継続証跡」が本体側で途切れたため、
#   専用 daily cron (iMakInventory_ReverseAudit_Daily 09:30) でこの関数を直接呼ぶ。
#   reverse + ebay_down を 1 回の eBay active map で両方走らせ、 取下げ漏れ (reverse
#   mismatch>0) / audit 不能 (mismatch==-1) を **多チャネルで非-silent に** 通知する。
# ============================================================================
HEARTBEAT_LOG = DECISION_LOG_DIR / "reverse_audit_daily.log"
ALERT_LOG = DECISION_LOG_DIR / "AUDIT_ALERT.log"

# 承認済み既知偽陽性 allowlist (2026-06-27 新設):
#   url 空で源 scrape 不能なまま eBay live = reverse_audit が毎日同じ乖離を出し続け、
#   critical alert が常時鳴る → 本物の取下げ漏れ alert が埋もれる (alert 疲労)。
#   人手で「取下げ漏れではない」と確認済の item_id をここに登録すると、 当該乖離は
#   **alert (toast/email) を抑制** するが **heartbeat には毎回記録** する (= silent drop 禁止、
#   安全原則準拠)。 fail-closed: ここに無い item_id は従来通り必ず alert。
#   登録は git 追跡ファイルで人手レビュー可能 (= 不可視な握り潰しにしない)。
ACK_FILE = ROOT_DIR / "reverse_audit_acknowledged.json"


def _load_acknowledged() -> dict:
    """承認済み item_id → entry の dict を返す (ファイル不在/壊れていれば空 = fail-closed で全件 alert)."""
    try:
        if not ACK_FILE.exists():
            return {}
        data = json.loads(ACK_FILE.read_text(encoding="utf-8"))
        out = {}
        for e in data.get("acknowledged", []):
            iid = str(e.get("item_id", "")).strip()
            if iid:
                out[iid] = e
        return out
    except Exception as e:
        print(f"  [!] [daily_audit] ack allowlist 読込失敗 (= 全件 alert に倒す): "
              f"{type(e).__name__}: {e}", flush=True)
        return {}


def _toast(title: str, body: str) -> None:
    """Windows toast (win10toast 不在 / 失敗時は黙って skip)."""
    try:
        from win10toast import ToastNotifier  # noqa: PLC0415
        ToastNotifier().show_toast(title, body[:200], duration=15, threaded=True)
    except Exception:
        pass


def _email_alert(subject: str, body: str) -> bool:
    """Gmail SMTP で alert 送信 (opt-in: encrypted_gmail.dat 不在なら skip)。失敗しても raise しない."""
    try:
        from auth.encrypted_gmail import load_gmail_config  # noqa: PLC0415
        from email_notifier import _send_via_gmail  # noqa: PLC0415
        cfg = load_gmail_config()
        if cfg is None:
            return False
        address, app_password, to = cfg
        _send_via_gmail(address, app_password, to, subject, body)
        return True
    except Exception as e:
        print(f"  [!] email alert 送信失敗: {type(e).__name__}: {e}", flush=True)
        return False


def _emit_crash_alert(err: str, tb_str: str = "") -> None:
    """daily_audit が最外周で想定外クラッシュした時に非-silent 記録 (heartbeat AUDIT_CRASH + alert)。

    pythonw cron では stderr が破棄され、 _run_daily_audit より外の例外は heartbeat/alert に
    到達せず silent crash する (2026-06-30 10:00 実観測)。 audit が走らなかったこと自体を
    非-silent にするための最後の砦。
    """
    ts = datetime.now().isoformat(timespec="seconds")
    try:
        DECISION_LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(HEARTBEAT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": ts, "status": "AUDIT_CRASH", "error": err},
                               ensure_ascii=False) + "\n")
        subj = "[iMakInventory] ⚠️ reverse_audit daily cron クラッシュ (audit 未完了)"
        body = (f"reverse_audit --mode all が想定外の例外で中断 = 当日の reconciliation 未実行。\n"
                f"error: {err}\n\n{tb_str}\n"
                f"= 乖離ゼロを証明できていない。 次 cron で自動再試行されるが継続するなら要調査。\n")
        with open(ALERT_LOG, "a", encoding="utf-8") as f:
            f.write(f"{ts}\t{subj}\n{body}\n{'-'*60}\n")
        _toast(subj, body)
        _email_alert(subj, body)
    finally:
        print(f"  [NG] daily_audit クラッシュ (非-silent 記録済): {err}", flush=True)


def _run_daily_audit() -> dict:
    """daily cron 用: reverse + ebay_down を共有 qty_map で両方実行 + 非-silent 通知 + 継続証跡."""
    ts = datetime.now().isoformat(timespec="seconds")
    DECISION_LOG_DIR.mkdir(parents=True, exist_ok=True)

    # eBay active map を 1 回だけ取得 → 両 audit で共有 (二重 DL 回避)。
    # 取得失敗時は None で続行 → 各 audit が自前 fetch → 空なら fail-closed (mismatch/orphan=-1)。
    shared_qty_map = None
    try:
        shared_qty_map = _fetch_ebay_qty_map()
        print(f"  [daily_audit] eBay active map: {len(shared_qty_map)} 件 (両 audit 共有)", flush=True)
    except Exception as e:
        print(f"  [!] [daily_audit] eBay active map 取得失敗、 各 audit 自前 fetch に fallback: "
              f"{type(e).__name__}: {e}", flush=True)
        shared_qty_map = None

    rev = run_reverse_audit(write_log=True, qty_map=shared_qty_map)
    edn = run_ebay_down_sheet_active_audit(write_sheet=True, write_log=True, qty_map=shared_qty_map)

    mc = rev.get("mismatch_count", 0)
    oc = edn.get("orphan_count", 0)

    # 承認済み既知偽陽性を分離 (alert は unack のみ、 ack は heartbeat に必ず記録 = silent drop 禁止)。
    ack = _load_acknowledged()
    all_items = rev.get("items", []) or []
    ack_items = [it for it in all_items if str(it.get("item_id", "")).strip() in ack]
    unack_items = [it for it in all_items if str(it.get("item_id", "")).strip() not in ack]
    unack_count = len(unack_items)
    ack_ids = [str(it.get("item_id", "")).strip() for it in ack_items]

    # 継続証跡 heartbeat (= 乖離 0 でも「実行した」証跡。 pythonw でも残る。 安全原則: 継続 reconciliation)
    #   status は **未承認** 乖離で判定 (= 承認済みだけなら OK 扱いだが、 ack 内訳は必ず残す)。
    if mc == -1:
        status = "AUDIT_ERROR"
    elif unack_count > 0:
        status = "MISMATCH"
    elif ack_items:
        status = "OK_ACK_ONLY"   # 乖離はあるが全て承認済み既知偽陽性
    else:
        status = "OK"
    with open(HEARTBEAT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": ts, "status": status,
            "reverse_mismatch": mc, "reverse_by_sheet": rev.get("by_sheet"),
            "reverse_unack": unack_count, "reverse_ack": len(ack_items),
            "acknowledged_ids": ack_ids,
            "reverse_error": rev.get("error"),
            "ebay_down_orphan": oc, "ebay_down_error": edn.get("error"),
            "reverse_log": rev.get("log_path"), "ebay_down_log": edn.get("log_path"),
        }, ensure_ascii=False) + "\n")

    if ack_items:
        print(f"  [info] 承認済み既知偽陽性 {len(ack_items)} 件は alert 抑制 (heartbeat 記録済): "
              f"{ack_ids}", flush=True)

    # 非-silent アラート判定:
    #   unack_count > 0  = 未承認の取下げ漏れ疑い (D=○ なのに eBay qty>0) = fail-OPEN 最有力 → critical
    #   mc == -1 = audit 不能 (eBay 取得失敗 / sheet 読込失敗) = 検出網が動かなかった → critical
    #   ebay_down orphan は review シートに書出済 = 自動で害なし → heartbeat のみ (alert しない)
    #   承認済みのみ (unack=0) → critical alert は出さない (= 既知ノイズで本物を埋もれさせない)
    if unack_count > 0 or mc == -1:
        if unack_count > 0:
            from collections import Counter  # noqa: PLC0415
            by_sheet = dict(Counter(it["sheet"] for it in unack_items))
            by_supplier = dict(Counter(it.get("supplier", "?") for it in unack_items))
            subj = f"[iMakInventory] ⚠️ reverse_audit 乖離 {unack_count} 件 (取下げ漏れ疑い)"
            body = (f"reverse_audit が D=○ × eBay qty>0 の未承認乖離を {unack_count} 件検出。\n"
                    f"sheet 別: {by_sheet}\nsupplier 別: {by_supplier}\n"
                    f"= 売切マーク済なのに eBay で買える状態 = 無在庫履行不能 → 要対応。\n"
                    + (f"(別途 承認済み既知偽陽性 {len(ack_items)} 件 {ack_ids} は抑制)\n" if ack_items else "")
                    + f"log: {rev.get('log_path')}\n")
        else:
            subj = "[iMakInventory] ⚠️ reverse_audit 実行不能 (検出網が動かなかった)"
            body = (f"reverse_audit が fail-closed で中断 (= 乖離ゼロを証明できていない)。\n"
                    f"error: {rev.get('error')}\n"
                    f"eBay 取得失敗 / sheet 読込失敗の可能性。 次 cron で自動再試行されるが継続するなら要調査。\n")
        # 多重防御: alert ログ (永続) + toast + email、 各 best-effort
        with open(ALERT_LOG, "a", encoding="utf-8") as f:
            f.write(f"{ts}\t{subj}\n{body}\n{'-'*60}\n")
        _toast(subj, body)
        emailed = _email_alert(subj, body)
        print(f"  [★critical] {subj} (alert_log + toast + email={'sent' if emailed else 'skip/fail'})",
              flush=True)
    elif ack_items:
        print(f"  ✓ reverse_audit 未承認乖離 0 件 (承認済み {len(ack_items)} 件のみ = 既知偽陽性、 "
              f"継続証跡を 1 件積上げ)", flush=True)
    else:
        print(f"  ✓ reverse_audit 乖離 0 件 (= 継続証跡を 1 件積上げ)", flush=True)

    return {"ts": ts, "status": status, "reverse": rev, "ebay_down": edn,
            "unack_count": unack_count, "ack_count": len(ack_items), "ack_ids": ack_ids}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="reverse_audit / ebay_down_audit")
    ap.add_argument("--mode", choices=["reverse", "ebay_down", "all"], default="reverse",
                    help="reverse = D=○+qty>0 (取下げ漏れ) / ebay_down = D空欄+qty=0/ended / "
                         "all = 両方 + 非-silent alert (daily cron 用)")
    ap.add_argument("--no-sheet-write", action="store_true",
                    help="ebay_down mode で review シート書込を skip (dry)")
    args = ap.parse_args()

    if args.mode == "all":
        # daily cron は pythonw 起動で stdout/stderr が破棄される。 _run_daily_audit の
        # 内部 try は run_reverse_audit 等の個別失敗は握るが、 想定外の例外がそこより外で
        # 起きると heartbeat/alert に到達せず **silent crash** する (2026-06-30 10:00 で実観測:
        # exit 1 + heartbeat 無記録)。 audit が走らなかったこと自体を非-silent にするため、
        # 最外周で捕捉して AUDIT_ERROR heartbeat + alert を必ず残す (安全原則: audit 不能は非-silent)。
        try:
            res = _run_daily_audit()
            print(f"\n=== daily_audit 結果 ({res['status']}) ===")
            print(f"  reverse 乖離: {res['reverse'].get('mismatch_count')} 件 "
                  f"(未承認 {res.get('unack_count')} / 承認済 {res.get('ack_count')} {res.get('ack_ids')}) / "
                  f"ebay_down orphan: {res['ebay_down'].get('orphan_count')} 件")
            print(f"  heartbeat: {HEARTBEAT_LOG}")
        except Exception as e:
            import traceback as _tb  # noqa: PLC0415
            _emit_crash_alert(f"{type(e).__name__}: {e}", _tb.format_exc())
            sys.exit(1)
    elif args.mode == "ebay_down":
        res = run_ebay_down_sheet_active_audit(write_sheet=not args.no_sheet_write)
        print(f"\n=== ebay_down_audit 結果 ===")
        print(f"  orphan (D空欄+eBay取下げ済): {res.get('orphan_count')} 件")
        print(f"  by_sheet: {res.get('by_sheet')}")
        print(f"  by_state: {res.get('by_state')}")
        print(f"  active_total: {res.get('active_total')} / coverage: {res.get('coverage')}")
        print(f"  sheet_writes: {res.get('sheet_writes')}")
        print(f"  log: {res.get('log_path')}")
        if res.get("error"):
            print(f"  [!] error: {res['error']}")
    else:
        res = run_reverse_audit()
        print(f"\n=== reverse_audit 結果 ===")
        print(f"  乖離: {res['mismatch_count']} 件")
        print(f"  by_sheet: {res['by_sheet']}")
        print(f"  by_supplier: {res['by_supplier']}")
        print(f"  log: {res.get('log_path')}")
        print(f"  elapsed: {res.get('elapsed_sec', 0):.1f}s")
