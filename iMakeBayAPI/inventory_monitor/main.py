"""main - UNIQLO 在庫監視オーケストレーション (Phase 1).

設計原則:
  - 既存モジュール (psa_to_csv / control_panel / iMakeBayAPI 内 listing 系) を一切変更しない
  - 本ディレクトリ内 3 モジュール (uniqlo_scraper / ebay_sku_fetcher / sheet_updater) を組合せ
  - Phase 1 = 検知のみ (Level 1)、eBay qty 自動変更は行わない (Phase 4 で実装予定)

実行フロー:
  1. メインシートから FLG ≠ 1 かつ uniqlo.com の listing 行を抽出
  2. 各 listing に対し UNIQLO L2S API で SKU × 在庫 × 価格を取得
  3. SKU シートの既存行を読込 → eBay SKU ID + 旧 Qty を保持
  4. UNIQLO データと SKU シート行を listing_id × size × color でマッチング
  5. 対処要判定 (仕入元✕ × eBay Qty>0 → 要対処)
  6. SKU シートに update / append (batch)
  7. 要対処件数の前回比較 → 増えたらアラート (現状は console、Phase 1.5 でメール)

実行:
  python main.py                      # 全 UNIQLO listing
  python main.py --listing 357401200653  # 特定 listing のみ
  python main.py --dry-run            # スプシ書込なし、結果のみ console
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

# stdout/stderr を UTF-8 化 (Windows cp932 console で 絵文字 (▶/✅/◎/✕ 等) print
# 時の UnicodeEncodeError 連鎖を防ぐ。spreadsheet 書込用の ◎ ✕ はそのまま残す。)
for _stream_name in ("stdout", "stderr"):
    _s = getattr(sys, _stream_name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

# 同階層モジュール import
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from uniqlo_scraper import fetch_product_inventory as fetch_uniqlo  # noqa: E402
from montbell_scraper import fetch_product_inventory as fetch_montbell  # noqa: E402
from ebay_sku_fetcher import get_skus_for_listing   # noqa: E402
from sheet_updater import (                          # noqa: E402
    open_sheet,
    read_main_active_rows,
    read_sku_rows,
    update_sku_rows,
    determine_needs_action,
)

# Phase 3 (2026-05-14): iMakInventory の本番稼働中 amazon_scraper を流用
# (memory: reuse_existing_proven_solution.md = 既存実績流用主義)
# SCRIPT_DIR = .../iMakInventory_root/iMakeBayAPI/inventory_monitor
# → parent.parent = iMakInventory_root → / "iMakInventory/scrapers" = 既存 scraper dir
_amazon_scrapers_dir = SCRIPT_DIR.parent.parent / "iMakInventory" / "scrapers"
if _amazon_scrapers_dir.exists() and str(_amazon_scrapers_dir) not in sys.path:
    sys.path.insert(0, str(_amazon_scrapers_dir))
from amazon_scraper import fetch_product_inventory as fetch_amazon  # noqa: E402

LOG_DIR = SCRIPT_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
NEEDS_ACTION_STATE = SCRIPT_DIR / "logs" / "_last_needs_action_count.json"


# ============================================================================
# ロガー (シンプル file + stdout)
# ============================================================================
def _log_path() -> Path:
    return LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.log"


def log(msg: str):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line)
    with open(_log_path(), "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ============================================================================
# montbell カラー推測: listing title から color code 抽出
# ============================================================================
# 暫定マップ (実運用で発生したものから蓄積). 大文字比較.
# 2026-05-14 修正: サンダーパス系で title→code が montbell 実 code と乖離していた bug fix.
# montbell の実 color code は単純 2 文字でなく "RDBR" "NV/PB" "HN/MA" "GP/OC" のような
# 複合 code が混在する。Takaaki さん確認 (2026-05-14):
#   RED   → RDBR  (Red/Brown)
#   BLUE  → NV/PB (Navy/Powder Blue)
#   ORANGE→ HN/MA (Honey/Marine?)
#   BROWN → GP/OC (Grape/Ocher?)
MONTBELL_COLOR_MAP = {
    "RED": "RDBR", "BLUE": "NV/PB", "ORANGE": "HN/MA", "BROWN": "GP/OC",
    "BLACK": "BK", "NAVY": "NV", "YELLOW": "YL", "GREEN": "DGN",
    "TURQUOISE": "TQ", "WHITE": "WH",
    # 略号そのまま入ってる場合も
    "RD": "RD", "BL": "BL", "OG": "OG", "BR": "BR", "BK": "BK",
    "NV": "NV", "YL": "YL", "DGN": "DGN", "TQ": "TQ", "WH": "WH",
}


def guess_montbell_color(title: str) -> Optional[str]:
    """listing title からモンベルカラーコードを推測. ヒットなければ None.
    例: "サンダーパス Men's RED" → "RD"
    """
    t = (title or "").upper()
    # 単語境界で hit を探す
    for keyword, code in MONTBELL_COLOR_MAP.items():
        if re.search(rf"\b{re.escape(keyword)}\b", t):
            return code
    return None


# ============================================================================
# 仕入元 dispatch
# ============================================================================
def fetch_supplier_inventory(supplier: str, url: str, title: str) -> Optional[dict]:
    """supplier に応じて適切な scraper を呼ぶ."""
    if supplier == "uniqlo":
        return fetch_uniqlo(url)
    elif supplier == "montbell":
        color_hint = guess_montbell_color(title)
        return fetch_montbell(url, target_color_code=color_hint)
    elif supplier == "amazon":
        # Amazon は variation なし、listing 全体で 1 SKU 判定
        # use_selenium_fallback=False で軽量 (requests のみ)、unqualifiedBuyBox 検出時は
        # fail-closed (= in_stock=False) で安全側に倒す
        return fetch_amazon(url, use_selenium_fallback=False)
    else:
        raise ValueError(f"未対応 supplier: {supplier}")


# ============================================================================
# マッチング: 仕入元 scrape 結果 × SKU シート既存行
# ============================================================================
def _normalize_size(s: str) -> str:
    return (s or "").strip().upper().replace(" ", "")


def _normalize_color(c: str) -> str:
    return (c or "").strip().upper().replace(" ", "")


def match_supplier_skus_with_sheet(
    supplier_skus: list,
    sheet_skus: list,
    listing_default_color: str = "",
) -> list:
    """仕入元 scraper の SKU と SKU シート既存行を (size, color) compound key で match.

    color は SKU の color_code (montbell 由来) を最優先、なければ listing_default_color (UNIQLO).
    まず compound match を試み、失敗時は size-only fallback (旧シート行のため).
    """
    matched = []
    for sup in supplier_skus:
        u_size = _normalize_size(sup.get("size", ""))
        u_color = _normalize_color(sup.get("color_code") or listing_default_color)

        # compound match (size + color)
        existing = None
        for sh_sku in sheet_skus:
            if (_normalize_size(sh_sku.get("size", "")) == u_size
                    and _normalize_color(sh_sku.get("color", "")) == u_color):
                existing = sh_sku
                break
        # size-only fallback
        if existing is None:
            for sh_sku in sheet_skus:
                if _normalize_size(sh_sku.get("size", "")) == u_size:
                    existing = sh_sku
                    break

        matched.append({
            "row_index":         existing["row_index"] if existing else None,
            "sku_id":            existing["sku_id"] if existing else "",
            "size":              sup.get("size", ""),
            "color":             sup.get("color_code") or listing_default_color,
            "supplier_in_stock": sup.get("in_stock", False),
            "supplier_quantity": sup.get("quantity", 0),
            "supplier_price":    sup.get("price_jpy"),
            "ebay_qty":          existing["ebay_qty"] if existing else 0,
            "uniqlo_l2id":       sup.get("l2Id", ""),
            "uniqlo_communication_code": sup.get("communication_code", ""),
        })
    return matched


# 後方互換 (古い名前を残す)
def match_uniqlo_with_sheet(uniqlo_skus: list, sheet_skus: list) -> list:
    return match_supplier_skus_with_sheet(uniqlo_skus, sheet_skus, listing_default_color="")


# ============================================================================
# 1 listing 処理
# ============================================================================
def process_listing(sh, main_row: dict, dry_run: bool = False) -> dict:
    """1 listing 分の処理. Returns: {"updates": [...], "needs_action_count": N}"""
    listing_id = main_row["listing_id"]
    title = main_row["title"]
    url = main_row["url"]
    supplier = main_row.get("supplier", "uniqlo")

    log(f"  ▶ listing {listing_id} [{supplier}] ({title[:30]})")

    try:
        info = fetch_supplier_inventory(supplier, url, title)
    except Exception as e:
        log(f"    ⚠️ {supplier} scrape 失敗: {type(e).__name__}: {e}")
        return {"updates": [], "needs_action_count": 0, "error": str(e)}

    log(f"    {supplier}: {info['name'][:40]} / {info.get('color', '')} / {len(info['skus'])} skus")

    # SKU シート読込 (1回だけで全 listing の rows 持つ → 呼出側でキャッシュした方が効率的)
    all_sku_rows = read_sku_rows(sh)
    sheet_skus = get_skus_for_listing(listing_id, mode="stub_from_sheet", sheet_rows=all_sku_rows)

    listing_default_color = info.get("color", "") if info.get("color", "") not in ("ALL", "") else ""
    matched = match_supplier_skus_with_sheet(info["skus"], sheet_skus, listing_default_color)

    updates = []
    needs_action_count = 0
    auto_check_at = datetime.now().strftime("%Y/%m/%d %H:%M")
    for m in matched:
        needs_action = determine_needs_action(
            supplier_in_stock=m["supplier_in_stock"],
            ebay_qty=m["ebay_qty"],
        )
        # 偽陽性防止: eBay SKU ID が空欄 = 「人手で eBay SKU を紐付けるまで未確定」
        # シート未登録 (row_index is None) も同様に未確定。
        # 真の判定は「人手で sku_id 列を埋めた SKU」のみで行う。
        if m["row_index"] is None or not (m["sku_id"] or "").strip():
            needs_action = False
        if needs_action:
            needs_action_count += 1

        # sku_id は人手記入待ち = 空文字のまま (UNIQLO の自動補完はやめる、偽陽性源)
        sku_id = m["sku_id"]
        # color: SKU 個別 color_code (montbell) > listing default color (UNIQLO)
        color = m["color"] or listing_default_color

        updates.append({
            "row_index":            m["row_index"],
            "listing_id":           listing_id,
            "title":                title,
            "sku_id":               sku_id,
            "size":                 m["size"],
            "color":                color,
            "supplier_stock_mark":  "◎" if m["supplier_in_stock"] else "✕",
            "supplier_price":       m["supplier_price"],
            "ebay_qty":             m["ebay_qty"],
            "auto_check_at":        auto_check_at,
            "needs_action":         needs_action,
        })

    # 在庫サマリーログ
    in_stock_count = sum(1 for m in matched if m["supplier_in_stock"])
    log(f"    在庫: {in_stock_count}/{len(matched)} あり, 要対処: {needs_action_count}")

    return {"updates": updates, "needs_action_count": needs_action_count}


# ============================================================================
# アラート (Phase 1: console 出力のみ。1.5 でメール)
# ============================================================================
def _send_alert_email(subject: str, body: str) -> bool:
    """iMakInventory の既存 email_notifier を流用してアラートメール送信.

    既存実績流用主義 (memory: reuse_existing_proven_solution.md):
    - 同マシン内 `iMakInventory/email_notifier.py` (5/9 commit 90e7773 から本番稼働)
    - 同じ DPAPI 暗号化 Gmail credentials を流用
    - opt-in (encrypted_gmail.dat 不在なら送信 skip)、fail-safe (失敗しても止まらない)

    Returns: True=送信、False=skip/失敗
    """
    try:
        # iMakInventory 配下を sys.path に追加 (= 同 worktree 内)
        # SCRIPT_DIR = .../iMakInventory_root/iMakeBayAPI/inventory_monitor
        # → parent.parent = iMakInventory_root → / "iMakInventory" = 本体 dir
        inv_root = SCRIPT_DIR.parent.parent / "iMakInventory"
        if str(inv_root) not in sys.path:
            sys.path.insert(0, str(inv_root))
        from email_notifier import _send_via_gmail  # noqa: PLC0415
        from auth.encrypted_gmail import load_gmail_config  # noqa: PLC0415

        cfg = load_gmail_config()
        if cfg is None:
            return False  # opt-in 未有効化
        addr, pw, to = cfg
        _send_via_gmail(addr, pw, to, subject, body)
        return True
    except Exception as e:
        log(f"  [!] アラートメール送信失敗 (cycle 全体は続行): {type(e).__name__}: {e}")
        return False


def alert_if_increased(current: int, all_updates: Optional[list] = None) -> None:
    """前回比較で要対処件数が増えてればコンソール強調 + メール送信 (Phase 5)."""
    last = 0
    if NEEDS_ACTION_STATE.exists():
        try:
            last = json.loads(NEEDS_ACTION_STATE.read_text(encoding="utf-8")).get("count", 0)
        except Exception:
            last = 0

    if current > last:
        diff = current - last
        sku_url = f"https://docs.google.com/spreadsheets/d/{(__import__('sheet_updater').SPREADSHEET_ID)}/edit"
        log("=" * 60)
        log(f"⚠️ 要対処件数 増加: 前回 {last} → 今回 {current} (+{diff})")
        log(f"   SKU シート確認: {sku_url}")
        log("=" * 60)

        # Phase 5: メール送信 (= console alert と同時)
        subject = f"[ALERT] inventory_monitor: 要対処 +{diff} 件増加 (合計 {current} 件)"
        body_lines = [
            "=" * 50,
            "inventory_monitor アラート: 要対処 SKU 増加検知",
            "=" * 50,
            f"前回 (= 最後の実行): {last} 件",
            f"今回 (= 現在の実行): {current} 件",
            f"差分 (+ 新規追加): +{diff} 件",
            "",
            f"SKU シート: {sku_url}",
            "",
            f"検知時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]
        # 直近 update の要対処サンプル (= title + size + color + listing_id)
        if all_updates:
            needs_action_updates = [u for u in all_updates if u.get("needs_action")]
            if needs_action_updates:
                body_lines.append(f"【要対処サンプル (max 10 件、計 {len(needs_action_updates)} 件)】")
                for u in needs_action_updates[:10]:
                    body_lines.append(
                        f"  - listing {u.get('listing_id', '?')} "
                        f"{u.get('title', '')[:30]} "
                        f"size={u.get('size', '')} color={u.get('color', '')}"
                    )
                body_lines.append("")
        body_lines.append("=" * 50)
        body_lines.append("（このメールは inventory_monitor が自動送信）")
        body = "\n".join(body_lines)

        sent = _send_alert_email(subject, body)
        if sent:
            log(f"  [mail] アラートメール送信完了")
    else:
        log(f"  要対処件数: 前回 {last} → 今回 {current} (増加なし)")

    NEEDS_ACTION_STATE.write_text(
        json.dumps({"count": current, "checked_at": datetime.now().isoformat()}, ensure_ascii=False),
        encoding="utf-8",
    )


# ============================================================================
# main
# ============================================================================
def main():
    parser = argparse.ArgumentParser(description="仕入元在庫監視 (Phase 1+2: UNIQLO + montbell)")
    parser.add_argument("--listing", help="特定 listing ID のみ処理")
    parser.add_argument("--supplier", choices=["all", "uniqlo", "montbell", "amazon"], default="all",
                        help="特定仕入元のみ処理 (default: all)")
    parser.add_argument("--dry-run", action="store_true", help="スプシ書込なし")
    args = parser.parse_args()

    log("=" * 60)
    log(f"UNIQLO 在庫監視 開始 ({'DRY RUN' if args.dry_run else 'LIVE'})")
    log("=" * 60)

    try:
        sh = open_sheet()
        log(f"スプシ open: {sh.title}")
    except Exception as e:
        log(f"❌ スプシ認証失敗: {type(e).__name__}: {e}")
        log(traceback.format_exc())
        sys.exit(1)

    main_rows = read_main_active_rows(sh, supplier_filter=args.supplier)
    by_sup = {}
    for r in main_rows:
        by_sup[r["supplier"]] = by_sup.get(r["supplier"], 0) + 1
    log(f"メインシート active 行: {len(main_rows)} 件 ({by_sup})")

    if args.listing:
        main_rows = [r for r in main_rows if r["listing_id"] == args.listing]
        log(f"--listing {args.listing} で絞り込み → {len(main_rows)} 件")

    if not main_rows:
        log("対象 0 件、終了")
        return

    all_updates = []
    total_needs_action = 0
    errors = []
    for row in main_rows:
        try:
            result = process_listing(sh, row, dry_run=args.dry_run)
            all_updates.extend(result["updates"])
            total_needs_action += result["needs_action_count"]
            if result.get("error"):
                errors.append((row["listing_id"], result["error"]))
        except Exception as e:
            errors.append((row["listing_id"], f"{type(e).__name__}: {e}"))
            log(f"    ❌ listing {row['listing_id']} 例外: {e}")
            log(traceback.format_exc())

    log("")
    log(f"=== 集計 ===")
    log(f"  処理 listing: {len(main_rows)}")
    log(f"  生成 update : {len(all_updates)}")
    log(f"  要対処 SKU  : {total_needs_action}")
    log(f"  エラー       : {len(errors)}")
    for lid, msg in errors:
        log(f"    - {lid}: {msg}")

    if args.dry_run:
        log("\n[DRY RUN] スプシ書込スキップ")
        # サンプル表示
        for u in all_updates[:5]:
            log(f"  サンプル update: {u}")
    elif all_updates:
        log(f"\nスプシ書込中... ({len(all_updates)} 件)")
        try:
            r = update_sku_rows(sh, all_updates)
            log(f"  ✅ updated={r['updated']}, appended={r['appended']}")
        except Exception as e:
            log(f"  ❌ スプシ書込失敗: {type(e).__name__}: {e}")
            log(traceback.format_exc())
            sys.exit(1)

    alert_if_increased(total_needs_action, all_updates=all_updates)

    log("=" * 60)
    log("完了")


if __name__ == "__main__":
    main()
