#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""取下再出品③書戻し: Add結果レポートの新ItemIDを元スプシB列に書き戻す。

フロー (2026-06-06 確定・3コマンドの最後):
  ① 取下げ  : relist_from_funnel → End CSV + 保留リスト
  ② 再出品  : gshock/mercari --relist → Add CSV + skumap(supply_url↔実sku)
  ③ 書戻し  : ここ。Add CSVアップで eBay が返す **結果レポート** の ItemID↔CustomLabel を
              skumap 経由で supply_url に変換 → 元スプシ A列一致行の B列に新ItemIDを上書き。

なぜ skumap が要るか: SKU規約はカテゴリ別 (gshock=ASIN / mercari=末尾12) で、保留リストの
best-effort sku と実listingの CustomLabel が食い違う (例 Daiwa pending'B08NP6PKZM' vs 実'p/B08NP6PKZM')。
②の出品くんが付けた実 CustomLabel を skumap に記録済 → それを権威に照合する。

B列は旧itemID(取下げ済)が残っているので **旧→新で上書き** (relistの正常動作)。

使い方:
  python relist_writeback.py --add-report <FileExchange結果.csv> [--add-report <別カテゴリ結果.csv>]
  # dry-run (既定)。--execute で実書込。--skumap 省略時は最新 relist_skumap_*.csv。
"""
import argparse
import csv
import glob
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REVISE_DIR = r"c:\dev\iMak_data\revise"
CREDS_PATH = r"c:\dev\iMak\double-hold-421922-7c0d38d3f73d.json"
DESK = r"C:\Users\imax2\OneDrive\デスクトップ"

# 管理スプシ (seller_hub_writeback.SHEETS と同一)。supply_url は どちらかに在る → 両方探索。
SHEETS = [
    {"id": "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk", "gid": 851100680,
     "label": "スプシ1 (Porter/TCG/Ichibankuji/UNIQLO UT/Other)"},
    {"id": "1jF9vggbfUCddjneROMO2GGN-jTAPRbq6Qe2cbgr37B0", "gid": 851100680,
     "label": "スプシ2 (G-Shock/Tomica/Reel/フィギュア/グッズ/etc)"},
]


def parse_add_report(path):
    """FileExchange Add結果レポート → [(custom_label, item_id), ...]。

    ItemID が入った行のみ採用 (Failure は ItemID 空)。Status は Success だけでなく
    Warning(例: Best Offer の IMMEDIATE_PAY 注意) も出品成功なので ItemID 有れば採用。
    """
    out = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            item_id = (row.get("ItemID") or "").strip()
            sku = (row.get("CustomLabel") or "").strip()
            if item_id and sku:
                out.append((sku, item_id))
    return out


def load_skumap(path):
    """relist_skumap_*.csv → {sku: supply_url}。"""
    out = {}
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            sku = (row.get("sku") or "").strip()
            url = (row.get("supply_url") or "").strip()
            if sku and url:
                out[sku] = url
    return out


def plan_writeback(add_pairs, skumap, supply_to_row):
    """純粋ロジック (network無し)。書戻し計画を返す。

    Args:
      add_pairs: [(sku, new_item_id), ...] (Add結果レポート由来)
      skumap: {sku: supply_url}
      supply_to_row: {supply_url: {"sheet": label, "row": idx, "current_b": str}}
    Returns:
      [{sku,new_item_id,supply_url,sheet,row,current_b,status}, ...]
      status: 'WRITE'(旧→新上書き) | 'SKIP_SAME'(既に新ID) | 'NO_SKUMAP' | 'NO_ROW'
    """
    plan = []
    for sku, new_id in add_pairs:
        supply_url = skumap.get(sku)
        if not supply_url:
            plan.append({"sku": sku, "new_item_id": new_id, "supply_url": "",
                         "sheet": "", "row": "", "current_b": "", "status": "NO_SKUMAP"})
            continue
        loc = supply_to_row.get(supply_url)
        if not loc:
            plan.append({"sku": sku, "new_item_id": new_id, "supply_url": supply_url,
                         "sheet": "", "row": "", "current_b": "", "status": "NO_ROW"})
            continue
        cur = (loc.get("current_b") or "").strip()
        status = "SKIP_SAME" if cur == new_id else "WRITE"
        plan.append({"sku": sku, "new_item_id": new_id, "supply_url": supply_url,
                     "sheet": loc["sheet"], "row": loc["row"], "current_b": cur,
                     "status": status})
    return plan


def _read_sheets(gc):
    """両スプシの A列(supply_url)→行 を読む。戻り: ({supply_url: loc}, {label: worksheet})。"""
    supply_to_row, ws_by_label = {}, {}
    for cfg in SHEETS:
        sh = gc.open_by_key(cfg["id"])
        ws = sh.get_worksheet_by_id(cfg["gid"])
        ws_by_label[cfg["label"]] = ws
        for i, row in enumerate(ws.get_all_values(), start=1):
            url = (row[0].strip() if row and row[0] else "")
            if not url or url in supply_to_row:
                continue  # 先勝ち (同 supply_url 重複は最初の行)
            supply_to_row[url] = {"sheet": cfg["label"], "row": i,
                                  "current_b": (row[1].strip() if len(row) > 1 else "")}
    return supply_to_row, ws_by_label


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--add-report", action="append", default=[],
                    help="FileExchange Add結果レポートCSV (複数カテゴリ分は複数指定可)")
    ap.add_argument("--auto", action="store_true",
                    help="デスクトップの Add結果レポートを自動検出 (skumap生成より新しい *_upload_*-*.csv)")
    ap.add_argument("--skumap", default="", help="relist_skumap CSV (省略時最新)")
    ap.add_argument("--execute", action="store_true", help="本書込 (既定: dry-run)")
    args = ap.parse_args()

    if not args.skumap:
        cands = sorted(glob.glob(os.path.join(REVISE_DIR, "relist_skumap_*.csv")))
        if not cands:
            sys.exit("relist_skumap_*.csv がありません (②再出品を先に実行)。")
        args.skumap = cands[-1]
    skumap = load_skumap(args.skumap)
    print(f"📂 skumap: {os.path.basename(args.skumap)} → {len(skumap)} sku")

    # --auto: デスクトップの Add結果レポートを自動検出 (skumap より新しい = 今バッチの分)
    if args.auto:
        sku_mtime = os.path.getmtime(args.skumap)
        # 結果レポートは末尾に -Mon-YYYY-... が付く。アップ元CSV(csv_output)と区別され、
        # End結果(relist_end_*)は *_upload_* に該当しないので自然に除外。
        found = [p for p in glob.glob(os.path.join(DESK, "*_upload_*-*.csv"))
                 if os.path.getmtime(p) > sku_mtime]
        found.sort(key=os.path.getmtime)
        if not found:
            sys.exit("デスクトップに skumap より新しい Add結果レポートが見つかりません。\n"
                     "  ②再出品→Add CSVアップ→結果レポートDL の順で実行してください。")
        print(f"🔍 --auto 検出: {len(found)} 件の結果レポート (skumap より新しい)")
        args.add_report = found

    if not args.add_report:
        sys.exit("--add-report も --auto も指定されていません。")

    add_pairs = []
    for p in args.add_report:
        if not os.path.exists(p):
            sys.exit(f"Add結果レポートが見つかりません: {p}")
        pairs = parse_add_report(p)
        print(f"📂 Add結果: {os.path.basename(p)} → {len(pairs)} 行 (ItemID有)")
        add_pairs.extend(pairs)

    print(f"\n=== モード: {'EXECUTE(本書込)' if args.execute else 'DRY-RUN'} ===")
    import gspread
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_file(
        CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)
    supply_to_row, ws_by_label = _read_sheets(gc)
    print(f"📊 スプシ2枚読込: A列 supply_url {len(supply_to_row)} 行")

    plan = plan_writeback(add_pairs, skumap, supply_to_row)

    summary = {"WRITE": 0, "SKIP_SAME": 0, "NO_SKUMAP": 0, "NO_ROW": 0}
    for e in plan:
        summary[e["status"]] += 1
        mark = {"WRITE": "✍", "SKIP_SAME": "=", "NO_SKUMAP": "⚠", "NO_ROW": "⚠"}[e["status"]]
        print(f"  {mark} {e['status']:9} sku={e['sku']:14} 旧B={e['current_b'] or '-':14} → 新={e['new_item_id']}"
              f"  {e['sheet'][:10]} row{e['row']}")

    if args.execute:
        wrote = 0
        for e in plan:
            if e["status"] != "WRITE":
                continue
            ws = ws_by_label.get(e["sheet"])
            if ws is None:
                continue
            ws.update_acell(f"B{e['row']}", e["new_item_id"])
            wrote += 1
        print(f"\n✅ {wrote} 件 B列書込完了 (旧→新)")
    else:
        print(f"\n[DRY-RUN] 実書込なし。--execute で {summary['WRITE']} 件を書込")

    print(f"\n=== サマリー === WRITE={summary['WRITE']} / SKIP_SAME={summary['SKIP_SAME']} "
          f"/ NO_SKUMAP={summary['NO_SKUMAP']} / NO_ROW={summary['NO_ROW']}")

    # 書込後はダッシュボードの済/未が変わるので「取下再出品」タブを即更新 (stale防止)
    if args.execute and summary["WRITE"] > 0:
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import relist_dashboard as rd
            rd.main()
            print("📋 「既存メンテ」取下再出品タブも更新 (済/未を最新化)")
        except Exception as _e:  # noqa: BLE001
            print(f"⚠ ダッシュボード更新スキップ: {type(_e).__name__}: {_e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
