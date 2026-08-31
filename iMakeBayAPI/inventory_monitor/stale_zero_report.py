"""stale_zero_report — 「在庫0が続いている公式出品」を棚卸用にまとめる (2026-09-01).

なぜ要るか:
    公式ブランド (UNIQLO / GU 等) は売り切れても再入荷することがあるので、在庫0でも
    出品は残しておく。ただし**企画物のシーズンが終わった商品は二度と戻らない**ので、
    いつまでも置くと出品手数料だけ払い続ける。どこで見切るかの判断材料が無く、
    ユーザーは棚卸のたびに保留していた。

物差し (毎回この場のログから計算する。固定値を書かない):
    「在庫0 → 復活」の実績を集計して、何日で戻るのが普通かを出す。
    実測 (2026-06〜08、291回): 97% が 7日以内に復活、最長 35日。
    → 2週間を超えたものは、まず戻らない。

やること:
    1. 巡回ログから listing ごとの在庫推移を作る
    2. 今 在庫0 が続いているものを、経過日数の長い順に並べる
    3. 復活実績の統計を添えて CSV + メールで出す

取り下げ (End) は週次の自動実行で行う (2026-09-01 ユーザー指示)。
何を・いつ・なぜ終了したかは logs/ended_listings.jsonl に必ず残す (仕入元URL付き = 再出品可能)。
★ End すると itemID が消え、**自動復活の対象から外れる** (再出品は新しい itemID になり、
  商品管理シートの差し替えが要る)。だから既定は「報告だけ」。

使い方:
    python stale_zero_report.py                      # 報告のみ (CSV + メール)
    python stale_zero_report.py --days 30            # 30日以上だけ一覧
    python stale_zero_report.py --end-days 30 --execute   # 30日以上を取り下げ
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

LOG_DIR = SCRIPT_DIR / "logs"
OUT_DIR = SCRIPT_DIR / "logs" / "reports"

#: 「まず戻らない」と見なす日数の既定 (物差しの実測 最長 39日 に対する安全側)。
DEFAULT_STALE_DAYS = 30

#: 取り下げた出品の履歴 (何を・いつ・なぜ終了したか。後から再出品できるように仕入元URLも残す)
ENDED_LEDGER = LOG_DIR / "ended_listings.jsonl"

#: 1 回の自動実行で取り下げる上限。超えたら 1 件も取り下げずに人へ回す。
#: 大量に出る = 巡回側の異常 (全件を誤って在庫0と判定した等) の疑いがあり、
#: 誤って一括終了すると itemID が消えて元に戻せない (再出品は別 itemID)。
MAX_AUTO_END = 30

_LISTING_RE = re.compile(r"▶ listing (\d+) \[(\w+)\]")
_STOCK_RE = re.compile(r"在庫: (\d+)/(\d+) あり")


def _days_between(a: str, b: str) -> int:
    ay, am, ad = map(int, a.split("-"))
    by, bm, bd = map(int, b.split("-"))
    return (date(by, bm, bd) - date(ay, am, ad)).days


def build_series(log_dir: Path = LOG_DIR) -> tuple:
    """巡回ログ → ({item_id: [(日付, 在庫ありサイズ数)]}, {item_id: ブランド})."""
    series, brand = defaultdict(list), {}
    for f in sorted(glob.glob(str(log_dir / "20??-??-??.log"))):
        day = Path(f).stem
        cur = None
        try:
            text = Path(f).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            m = _LISTING_RE.search(line)
            if m:
                cur = m.group(1)
                brand[cur] = m.group(2)
                continue
            m2 = _STOCK_RE.search(line)
            if m2 and cur:
                series[cur].append((day, int(m2.group(1))))
                cur = None
    return series, brand


def recovery_stats(series: dict) -> dict:
    """「0 になってから復活するまで」の実績 (= 見切りの物差し)."""
    lens = []
    for rows in series.values():
        zero_at = None
        for day, n in rows:
            if n == 0 and zero_at is None:
                zero_at = day
            elif n > 0 and zero_at is not None:
                lens.append(_days_between(zero_at, day))
                zero_at = None
    lens.sort()
    if not lens:
        return {"n": 0}
    return {
        "n": len(lens),
        "median": lens[len(lens) // 2],
        "max": lens[-1],
        "within_7d": sum(1 for x in lens if x <= 7),
        "within_14d": sum(1 for x in lens if x <= 14),
    }


def stuck_at_zero(series: dict, brand: dict) -> list:
    """今 在庫0 が続いているもの (経過日数の長い順)."""
    out = []
    for iid, rows in series.items():
        if not rows:
            continue
        zero_at = None
        for day, n in rows:
            if n == 0 and zero_at is None:
                zero_at = day
            elif n > 0:
                zero_at = None
        if zero_at is not None:
            out.append({"item_id": iid, "brand": brand.get(iid, "?"),
                        "zero_since": zero_at,
                        "days": _days_between(zero_at, rows[-1][0])})
    out.sort(key=lambda r: -r["days"])
    return out


def attach_titles(rows: list) -> None:
    """商品名をシートから補う (取れなければ空のまま = 落とさない)."""
    try:
        import sheet_updater as su  # noqa: PLC0415
        sheet = su.open_sheet().worksheets()[0].get_all_values()
        title = {r[2]: r[1] for r in sheet[1:] if len(r) > 2 and r[2]}
        url = {r[2]: (r[5] if len(r) > 5 else "") for r in sheet[1:] if len(r) > 2 and r[2]}
    except Exception as e:
        print(f"  [!] 商品名の取得を skip ({type(e).__name__}: {str(e)[:60]})", flush=True)
        return
    for r in rows:
        r["title"] = title.get(r["item_id"], "")
        r["url"] = url.get(r["item_id"], "")      # 再出品する時の仕入元


def format_report(rows: list, stats: dict, stale_days: int) -> str:
    buckets = [("30日以上", 30, 10 ** 6), ("14〜29日", 14, 29),
               ("7〜13日", 7, 13), ("6日以内", 0, 6)]
    lines = [f"在庫0が続いている公式出品: {len(rows)} 件", ""]
    for label, lo, hi in buckets:
        n = sum(1 for r in rows if lo <= r["days"] <= hi)
        lines.append(f"  {label:<8}: {n:>3} 件")
    if stats.get("n"):
        lines += ["", f"[物差し] 過去に在庫0から復活した {stats['n']} 回の実績:",
                  f"  {stats['within_7d']}/{stats['n']} 回 ({stats['within_7d'] / stats['n']:.0%}) が 7日以内に復活",
                  f"  最長 {stats['max']}日 / 中央値 {stats['median']}日",
                  f"  → {stale_days}日を超えたものは、まず戻りません"]
    stale = [r for r in rows if r["days"] >= stale_days]
    if stale:
        lines += ["", f"■ {stale_days}日以上 ({len(stale)} 件) = 取り下げ候補"]
        for r in stale[:30]:
            lines.append(f"  {r['item_id']} {r['brand']:<8} {r['days']:>3}日 "
                         f"({r['zero_since']}〜) {r.get('title', '')[:34]}")
        if len(stale) > 30:
            lines.append(f"  ... 他 {len(stale) - 30} 件 (CSV 参照)")
    lines += ["", "※ 取り下げ (End) すると itemID が消え、自動復活の対象から外れます。",
              "   在庫0のまま置いておけば、再入荷時に巡回が自動で在庫を戻します。"]
    return "\n".join(lines)


def _append_history(entry: dict) -> None:
    """取り下げた記録を残す (後から追えるように。silent に消さない)."""
    try:
        ENDED_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with open(ENDED_LEDGER, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"  [!] 履歴に書けませんでした ({type(e).__name__}: {str(e)[:60]})", flush=True)


def _mark_excluded(item_ids: set) -> int:
    """終了した listing の行を FLG=1 (巡回対象外) にする。行は消さない.

    終了済みの出品を巡回し続けると、毎回「eBay に無い」を検出してノイズになる。
    再出品する時は HQ が新しい itemID を入れて FLG を戻す。
    """
    if not item_ids:
        return 0
    try:
        import sheet_updater as su  # noqa: PLC0415
        ws = su.open_sheet().worksheets()[0]
        values = ws.get_all_values()
        updated = 0
        for idx, row in enumerate(values[1:], start=2):
            iid = (row[su.MAIN_COL_LISTING_ID - 1] if len(row) >= su.MAIN_COL_LISTING_ID else "").strip()
            flg = (row[su.MAIN_COL_FLG - 1] if len(row) >= su.MAIN_COL_FLG else "").strip()
            if iid in item_ids and flg != "1":
                ws.update(range_name=f"A{idx}", values=[["1"]])
                updated += 1
        return updated
    except Exception as e:
        print(f"  [!] シートの FLG 更新を skip ({type(e).__name__}: {str(e)[:60]})", flush=True)
        return 0


def end_listings(rows: list, stale_days: int, max_auto: int = MAX_AUTO_END) -> dict:
    """取り下げ候補を実際に End する (送った後に状態を確認し、履歴を残す)."""
    inv_root = SCRIPT_DIR.parent.parent / "iMakInventory"
    if str(inv_root) not in sys.path:
        sys.path.insert(0, str(inv_root))
    from ebay_actions.trading_api_client import (  # noqa: PLC0415
        end_fixed_price_item, _call_trading,
    )

    targets = [r for r in rows if r["days"] >= stale_days]
    # 急増ガード: 一度に大量終了は「巡回が全件を誤判定した」疑いの方が高い。
    # 取り下げは元に戻せない (itemID が消える) ので、多い時は 1 件も触らない。
    if len(targets) > max_auto:
        print(f"  [★HOLD] 対象が {len(targets)} 件 (上限 {max_auto}) → 1 件も取り下げません。"
              f"巡回側の異常が無いか確認してください", flush=True)
        return {"ended": [], "failed": [], "targets": len(targets), "held": True}

    def _get_item(iid: str) -> tuple:
        """(site, listing 状態) を返す。取れなければ (None, None)."""
        body = ("<?xml version='1.0' encoding='utf-8'?>"
                "<GetItemRequest xmlns='urn:ebay:apis:eBLBaseComponents'>"
                f"<ItemID>{iid}</ItemID><DetailLevel>ReturnAll</DetailLevel></GetItemRequest>")
        xml = (_call_trading("GetItem", body, raw_xml_cap=None).get("raw_xml") or "")
        site = re.search(r"<Site>([^<]+)</Site>", xml)
        st = re.search(r"<ListingStatus>(\w+)</ListingStatus>", xml)
        return (site.group(1) if site else None), (st.group(1) if st else None)

    done, failed, skipped = [], [], []
    for r in targets:
        iid = r["item_id"]
        # ★ ミラーを終了しない (2026-08-24 の全社ルール)。UK/AU/CA/DE は eBaymag が
        #   US の親から自動生成したもので、こちらの持ち物ではない。親 (US) を操作すれば
        #   ミラーは付いてくる。site が読めない時も触らない (fail-closed)。
        site, before = _get_item(iid)
        if site != "US":
            skipped.append(iid)
            print(f"  {iid}: site={site} → 触りません (US 以外 / 不明はミラーの可能性)", flush=True)
            continue
        if before in ("Completed", "Ended"):
            skipped.append(iid)
            print(f"  {iid}: 既に終了済 ({before}) → 何もしません", flush=True)
            continue

        res = end_fixed_price_item(iid)
        _, status = _get_item(iid)
        status = status or "?"
        ok = status in ("Completed", "Ended")
        _append_history({
            "ended_at": datetime.now().isoformat(timespec="seconds"),
            "item_id": iid, "brand": r.get("brand", ""), "title": r.get("title", ""),
            "zero_since": r.get("zero_since"), "days_at_zero": r.get("days"),
            "source_url": r.get("url", ""),          # 再出品する時の仕入元
            "reason": f"在庫0が {r.get('days')} 日継続 (基準 {stale_days} 日)",
            "verified_status": status, "verified_ok": ok,
            "error_code": res.get("error_code"),
        })
        if ok:
            done.append(iid)
            print(f"  {iid}: 取り下げ完了 ({status})", flush=True)
        else:
            failed.append(iid)
            print(f"  {iid}: ★終了を確認できず (status={status} / "
                  f"err={res.get('error_code')})", flush=True)

    excluded = _mark_excluded(set(done))
    if excluded:
        print(f"  シートの {excluded} 行を巡回対象外 (FLG=1) にしました", flush=True)
    if skipped:
        print(f"  触らなかったもの: {len(skipped)} 件 (US 以外 / 既に終了済)", flush=True)
    return {"ended": done, "failed": failed, "targets": len(targets),
            "held": False, "excluded_rows": excluded, "skipped": skipped}


def main() -> int:
    ap = argparse.ArgumentParser(description="在庫0が続いている公式出品の棚卸レポート")
    ap.add_argument("--days", type=int, default=DEFAULT_STALE_DAYS,
                    help=f"取り下げ候補とみなす経過日数 (既定 {DEFAULT_STALE_DAYS})")
    ap.add_argument("--end-days", type=int, default=None,
                    help="この日数以上を取り下げ対象にする (--execute と併用)")
    ap.add_argument("--execute", action="store_true", help="実際に取り下げる (既定は報告のみ)")
    ap.add_argument("--no-mail", action="store_true", help="メールを送らない")
    args = ap.parse_args()

    series, brand = build_series()
    if not series:
        print("[NG] 巡回ログが読めませんでした (logs/YYYY-MM-DD.log)", file=sys.stderr)
        return 2

    rows = stuck_at_zero(series, brand)
    attach_titles(rows)
    stats = recovery_stats(series)
    report = format_report(rows, stats, args.days)
    print(report, flush=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d")
    csv_path = OUT_DIR / f"stale_zero_{stamp}.csv"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["item_id", "brand", "zero_since", "days", "title"])
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in w.fieldnames})
    print(f"\nCSV: {csv_path}", flush=True)

    ended = None
    if args.end_days is not None and args.execute:
        print(f"\n=== {args.end_days}日以上を取り下げます ===", flush=True)
        ended = end_listings(rows, args.end_days)
        report += (f"\n\n■ 取り下げ実行: 対象 {ended['targets']} 件 / "
                   f"完了 {len(ended['ended'])} 件 / 未完了 {len(ended['failed'])} 件")
    elif args.end_days is not None:
        print(f"\n(--execute が無いので取り下げは実行していません)", flush=True)

    if not args.no_mail:
        try:
            from run_daily import _send_report_email  # noqa: PLC0415
            subject = f"[公式在庫] 棚卸レポート: 在庫0継続 {len(rows)} 件 " \
                      f"(うち{args.days}日以上 {sum(1 for r in rows if r['days'] >= args.days)} 件)"
            _send_report_email(subject, report + f"\n\nCSV: {csv_path}\n")
        except Exception as e:
            print(f"  [!] メール送信 skip ({type(e).__name__}: {str(e)[:60]})", flush=True)

    return 1 if (ended and ended["failed"]) else 0


if __name__ == "__main__":
    sys.exit(main())
