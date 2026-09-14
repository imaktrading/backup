#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""売れた → 補充 の一覧 (2026-08-28 新設)。

なぜ必要か:
    補充系のボタンは全部**ファネル起点**で、「今日 売れた分」を入口にする道が無かった。
    実害 (2026-08-28): 8/27 の注文レポートに出ていた PSA 4枚は、売れて出品が閉じたため
    ファネルの RESTOCK に乗らず、`psa_resource_gate` の対象一覧に**1枚も入っていなかった**。
    窓口が手で突き合わせて初めて「4枚が補充されていない」と分かった。

対象カテゴリ (= 売れた後に **同じ物をもう一度仕入れられる** もの):
    PSA / G-Shock / 一番くじ。
    ★アパレル(UNIQLO/GU)は入れない: バリエーション出品で**出品は生きたまま**残り、
      落ちるのは売れたサイズの数量だけ。公式在庫が戻れば監視くんが復活させる
      (2026-08-28 ユーザー確定)。混ぜると生きている出品を二重に出す事故になる。
    ★PORTER中古・ビンテージ玩具も入れない: 代替の個体が事実上無い (1点もの)。

使い方:
    python sold_restock_worklist.py                 # デスクトップの最新 注文レポート
    python sold_restock_worklist.py <orders.csv>    # ファイル指定
    python sold_restock_worklist.py --no-stock      # 仕入元の生死を見ない (速い)
"""
from __future__ import annotations

import csv
import glob
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sheet_io as S  # noqa: E402

DESK = os.path.join(os.path.expanduser("~"), "OneDrive", "デスクトップ")
# ★2026-09-14 レポートはファネル用と同じ置き場 (日付フォルダ) に置く運用。デスクトップだけ見ていたので、
#   9/14 に DL した注文レポートを拾えず「押しても0件」のままだった。
REPORTS = r"C:\dev\iMak_data\seller_hub\reports"
ORDER_PATTERNS = ("ebay-all-orders-report-*.csv", "eBay-OrdersReport-*.csv")
AUX = S.PRODUCT_COL_AUX_START

# ---------------------------------------------------------------- 純関数
_RE_PSA = re.compile(r"^PSA\s*10\b")
_RE_GSHOCK = re.compile(r"G-Shock|G-SHOCK|CASIO", re.I)
_RE_KUJI = re.compile(r"Ichiban\s*Kuji|Ichibankuji", re.I)
# 補充対象外 (監視くん所管 / 代替個体が無い)
_RE_APPAREL = re.compile(r"UNIQLO|GU |AIRism|Graphic Tee|Sukajan", re.I)


def category_of(title):
    """出品タイトル → 補充カテゴリ (純関数, test 可)。対象外は ""。

    ★アパレルを先に判定する。UNIQLO の Pokemon コラボ Tシャツ等が
      PSA/一番くじ の語に当たって紛れ込むのを防ぐ (fail-closed)。
    """
    t = title or ""
    if _RE_APPAREL.search(t):
        return ""
    if _RE_PSA.match(t.strip()):
        return "PSA"
    if _RE_GSHOCK.search(t):
        return "G-Shock"
    if _RE_KUJI.search(t):
        return "一番くじ"
    return ""


def read_orders(path):
    """eBay の注文レポート → 注文行 (I/O)。1行目はダミーでヘッダは2行目。"""
    raw = io.open(path, encoding="utf-8-sig", newline="").read().splitlines()
    if not raw:
        return []
    start = 1 if not raw[0].strip(", ") else 0
    return [r for r in csv.DictReader(raw[start:])
            if (r.get("Item Number") or "").strip()]


def classify(row, item_col=S.PRODUCT_COL_ITEMID, live=None):
    """台帳の1行 → (状態, 補URL list) (純関数, test 可)。

    B列が空 → 未補充。補URL(AC-AG) は次に買える個体の候補。
    live (出品一覧 {itemID: {avail,...}}) を渡すと **eBay の在庫で** 判定する:
      B列の出品が在庫1以上 → 補充済 / 在庫0 → 在庫0 (その出品の数量を戻す) /
      一覧に無い → 出品なし (判らないので触らない)
    ★2026-09-14: B列に番号があるだけで「補充済」にしていたため、売れて在庫0のまま残った
      4件 (監視くんは仕入元が売切→在庫ありに戻った時しか数量を戻さない) が
      一覧にもボタンの件数にも出ず、押しても何もしなかった。
    live を渡さない時は従来どおり (B列に番号 = 補充済)。
    """
    b = (row[item_col] or "").strip() if len(row) > item_col else ""
    aux = [(row[i] or "").strip() for i in range(AUX, AUX + S.PRODUCT_AUX_MAX)
           if len(row) > i and (row[i] or "").strip()]
    if not b:
        return "未補充", aux
    if live is None:
        return "補充済", aux
    v = live.get(b)
    if v is None:
        return "出品なし", aux
    return ("補充済" if int(v.get("avail") or 0) > 0 else "在庫0"), aux


def load_live():
    """出品一覧キャッシュ (取下げ候補づくりと共用・eBay は呼ばない)。読めなければ None。"""
    try:
        import json as _json
        import itemid_writeback_audit as _A
        if _A.CACHE.exists():
            d = _json.loads(_A.CACHE.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) and d else None
    except Exception:                                              # noqa: BLE001
        return None
    return None


def find_row(sheets, sku, item_id):
    """SKU / 旧itemID から台帳の行を引く (純関数, test 可)。"""
    for label, rows in sheets:
        for n, r in enumerate(rows[1:], 2):
            a = (r[0] or "").strip() if r else ""
            b = (r[S.PRODUCT_COL_ITEMID] or "").strip() if len(r) > 1 else ""
            if item_id and b == item_id:
                return label, n, r
            if sku and len(sku) >= 6:
                cert = (re.sub(r"\D", "", r[S.PRODUCT_COL_CERT] or "")
                        if len(r) > S.PRODUCT_COL_CERT else "")
                if sku in a or (cert and sku.replace("PSA10-", "") == cert):
                    return label, n, r
    return None, None, None


def report_day(path):
    """ファイル名の日付 (純関数)。'...-2026-09-13-...' / 'OrdersReport-Sep-13-2026-...'。読めなければ None。"""
    import datetime as _dt
    b = os.path.basename(path)
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", b)
    if m:
        return _dt.date(int(m[1]), int(m[2]), int(m[3]))
    m = re.search(r"([A-Z][a-z]{2})-(\d{2})-(\d{4})", b)
    if m:
        try:
            return _dt.datetime.strptime(f"{m[1]}-{m[2]}-{m[3]}", "%b-%d-%Y").date()
        except ValueError:
            return None
    return None


def _find_desk_report(roots=None):
    """注文レポート: レポート置き場 (日付フォルダの中も) とデスクトップから、ファイル名の日付が一番新しい1本。"""
    import datetime as _dt
    roots = roots if roots is not None else [(REPORTS, True), (DESK, False)]
    fs = []
    for root, deep in roots:
        for pat in ORDER_PATTERNS:
            fs += glob.glob(os.path.join(root, "**", pat) if deep else os.path.join(root, pat), recursive=deep)
    if not fs:
        return ""
    return max(fs, key=lambda p: (report_day(p) or _dt.date.min, os.path.getmtime(p)))


def _sheets():
    """商品管理シート2枚 (I/O)。[(ラベル, 2d rows)]。"""
    import gspread
    from google.oauth2.service_account import Credentials
    from relist_writeback import SHEETS
    cr = Credentials.from_service_account_file(
        S.CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(cr)
    out = []
    for cfg in SHEETS:
        ws = gc.open_by_key(cfg["id"]).get_worksheet_by_id(S.PRODUCT_GID)
        out.append((cfg["label"], ws.get_all_values()))
    return out


def main():
    argv = sys.argv[1:]
    no_stock = "--no-stock" in argv
    paths = [a for a in argv if not a.startswith("--")]
    src = paths[0] if paths else _find_desk_report()
    if not src or not os.path.isfile(src):
        print("注文レポートが見つかりません "
              f"({REPORTS} の日付フォルダに ebay-all-orders-report-*.csv を置いてください)")
        return 2
    print(f"対象: {os.path.basename(src)}")

    pairs = [(o, category_of(o.get("Item Title") or "")) for o in read_orders(src)]
    want = [(o, c) for o, c in pairs if c]
    if not want:
        print("補充対象カテゴリ (PSA / G-Shock / 一番くじ) の売上はありません")
        return 0

    sheets = _sheets()
    live = load_live()
    if live is None:
        print("  ⚠ 出品一覧を読めず、B列に番号がある行は補充済として扱います (eBay の在庫は見ていません)")
    todo, done, orphan = [], 0, []
    for o, cat in want:
        sku = (o.get("Custom Label") or "").strip()
        iid = (o.get("Item Number") or "").strip()
        label, n, r = find_row(sheets, sku, iid)
        if r is None:
            orphan.append((o.get("Sale Date"), cat, o.get("Item Title") or ""))
            continue
        state, aux = classify(r, live=live)
        if state == "補充済":
            done += 1
            continue
        todo.append({"date": o.get("Sale Date"), "cat": cat, "sheet": label, "row": n,
                     "title": o.get("Item Title") or "", "supply": r[0] if r else "",
                     "aux": aux, "state": state,
                     "item": (r[S.PRODUCT_COL_ITEMID] or "").strip() if len(r) > S.PRODUCT_COL_ITEMID else ""})

    print(f"\n売れた {len(want)}件 (PSA/G-Shock/一番くじ) → "
          f"補充済 {done} / **未補充 {len(todo)}** / 台帳に行が無い {len(orphan)}")

    stock = {}
    if todo and not no_stock:
        urls = sorted({u for t in todo for u in t["aux"]})
        if urls:
            print(f"  仕入元の生死を確認中 ({len(urls)}本)...")
            try:
                import csv_drop_sold_rows as D
                stock = D.live_stock(urls)
            except Exception as e:                                 # noqa: BLE001
                # 取れなかった = 在庫なしに倒さない (fail-closed)。一覧は必ず出す。
                print(f"  ⚠ 在庫を確認できず、一覧だけ出します: {type(e).__name__}")

    for t in todo:
        alive = [u for u in t["aux"] if stock.get(u) == "in_stock"]
        if alive:
            mark = f"買える補URL {len(alive)}本"
        elif t["aux"]:
            mark = f"補URL {len(t['aux'])}本 (生死不明)"
        else:
            mark = "補URL なし = 個体探しから"
        if t.get("state") == "在庫0":
            mark = f"出品 {t['item']} が在庫0 (数量を戻せば売れる) / " + mark
        elif t.get("state") == "出品なし":
            mark = f"出品 {t['item']} が出品一覧に無い / " + mark
        print(f"\n{t['date']} [{t['cat']}] {t['sheet'][:6]} row{t['row']} — {mark}")
        print(f"   {t['title'][:88]}")
        print(f"   売れた時の仕入元: {t['supply'][:70]}")
        for u in t["aux"]:
            print(f"   {stock.get(u, '-'):9s} {u[:72]}")

    if orphan:
        print(f"\n■ 台帳に行が無い {len(orphan)}件 (補充するなら行を作るところから)")
        for d, c, t in orphan:
            print(f"   {d} [{c}] {t[:76]}")

    print("\n→ 補URL が生きているものは そのまま補充できます。"
          "補URL が無いものは 🃏 PSA再仕入れ照合 / 🛒 在庫切れ再仕入れ で個体を探してください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
