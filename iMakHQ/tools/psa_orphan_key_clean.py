# -*- coding: utf-8 -*-
"""出品プールの orphan canonical KEY を掃除(歩留まり激減の恒久対策)。

バグ(2026-06-21 究明): canonical KEY は「カード認識時(生成/catalog照合/確認ゲート)」に書かれるが、
dedup はその KEY を「出品済」と解釈する。KEY が付くのは出品より**前**なので、認識されたが出品
されなかった在庫(dedup除外/アップロード失敗(Vaporeon型)/旧backlog)にも KEY が付き、dedup が
未出品を誤ブロック → 出品プールに溜まり毎回再scrape→除外で歩留まり激減(10件→1〜2件)。

このツールは「未出品(B列空)で、かつ同一カード(KEY)が一度も出品されてない(同KEYの B列埋め行が
無い)」行の AI列 KEY を消す → dedup が未出品を誤ブロックしなくなる。新規生成の前に毎回走らせて
orphan が溜まらないようにする(恒久運用)。

安全設計:
- 消すのは「同一カードが一度も出品されてない」orphan のみ。出品済カードの2枚目(別cert・B列空)は
  KEY を残す(= 2枚目は引き続き重複除外 = 設計通り)。
- seller snapshot(あれば)に痕跡がある cert は除外(出品済なのに B列 未記入だった場合の保険=
  同一certの二重出品を防ぐ)。
- AI列を読む build_key_map は B列空(itemID無)行を元々 skip → RESTOCK/需要マップに無影響。
- dedupe worktree / psa_to_csv(新規)は触らない。スプシ AI列のみ操作。
- 既定 dry-run、--execute で実消去。

find_orphans は純関数(test可)。I/O(スプシ読み書き)は clean。
"""
import csv
import glob
import os
import sys

# 商品管理シート HIGH / LOW(dedup の canonical KEY 元。両 worktree 共有)。
SHEETS = [
    ("HIGH", "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk"),
    ("LOW", "1jF9vggbfUCddjneROMO2GGN-jTAPRbq6Qe2cbgr37B0"),
]
SHEET_GID = 851100680
_SNAPSHOT_DIR = r"C:\dev\iMak_data\seller_hub"


def find_orphans(rows, snapshot_certs=None):
    """orphan(消す対象)を返す。純関数。

    rows: [{"sheet","row","cert","key","b"}, ...] (全 HIGH/LOW 行、header除外)。
    snapshot_certs: 実出品の疑いがある cert の集合(除外用)。None=除外なし。
    orphan = KEY有 + B列空 + そのKEYに B列埋め行が無い(=一度も出品されてないカード)。
            ただし cert が snapshot_certs にあれば除外(出品済の疑い)。
    戻り: [{"sheet","row","key","cert"}, ...]
    """
    snapshot_certs = snapshot_certs or set()
    listed_keys = {r["key"] for r in rows if r.get("key") and r.get("b")}
    out = []
    for r in rows:
        key, b, cert = r.get("key", ""), r.get("b", ""), r.get("cert", "")
        if key and not b and key not in listed_keys:
            if cert and cert in snapshot_certs:
                continue   # 実出品の疑い → 消さない(同cert二重出品防止)
            out.append({"sheet": r["sheet"], "row": r["row"], "key": key, "cert": cert})
    return out


def _load_snapshot_certs():
    """最新 seller snapshot の sku+title 全文を返す(cert 部分一致判定用)。無ければ ''。"""
    fs = sorted(glob.glob(os.path.join(_SNAPSHOT_DIR, "snapshot_active_all_*.csv")),
                key=os.path.getmtime)
    if not fs:
        return ""
    try:
        with open(fs[-1], encoding="utf-8-sig") as f:
            snap = list(csv.DictReader(f))
        return " ".join((x.get("sku", "") + " " + x.get("title", "")) for x in snap)
    except Exception:
        return ""


def clean(execute=False):
    """HIGH/LOW を読み orphan KEY を掃除(I/O)。戻り: stats dict。"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import gspread
    from google.oauth2.service_account import Credentials
    from sheet_io import CREDS_PATH, PRODUCT_COL_ITEMID, PRODUCT_COL_CERT, PRODUCT_COL_KEY

    creds = Credentials.from_service_account_file(
        CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)

    snaptext = _load_snapshot_certs()
    sheet_ws, rows = {}, []
    for name, sid in SHEETS:
        sh = gc.open_by_key(sid)
        ws = next((w for w in sh.worksheets() if w.id == SHEET_GID), sh.sheet1)
        sheet_ws[name] = ws
        for i, r in enumerate(ws.get_all_values()):
            if i == 0:
                continue
            rows.append({
                "sheet": name, "row": i + 1,
                "cert": (r[PRODUCT_COL_CERT].strip() if len(r) > PRODUCT_COL_CERT else ""),
                "key": (r[PRODUCT_COL_KEY].strip() if len(r) > PRODUCT_COL_KEY else ""),
                "b": (r[PRODUCT_COL_ITEMID].strip() if len(r) > PRODUCT_COL_ITEMID else ""),
            })

    # snapshot に痕跡がある cert を除外集合に(実出品の疑い)
    snap_certs = set()
    if snaptext:
        for r in rows:
            if r["cert"] and r["cert"] in snaptext:
                snap_certs.add(r["cert"])

    orphans = find_orphans(rows, snap_certs)
    col = "AI"  # PRODUCT_COL_KEY=34 → AI 列

    by_sheet = {}
    for o in orphans:
        by_sheet.setdefault(o["sheet"], []).append(o)

    print(f"orphan(未出品なのにKEY有=dedup誤ブロック): {len(orphans)} 件 "
          f"(snapshot除外cert {len(snap_certs)})")
    for name, lst in by_sheet.items():
        print(f"  {name}: {len(lst)} 件")

    if not execute:
        print("[DRY-RUN] 消去なし。--execute で AI列 KEY 消去。")
        return {"orphans": len(orphans), "cleared": 0, "executed": False}

    cleared = 0
    for name, lst in by_sheet.items():
        reqs = [{"range": f"{col}{o['row']}", "values": [[""]]} for o in lst]
        if reqs:
            sheet_ws[name].batch_update(reqs, value_input_option="RAW")
            cleared += len(reqs)
            print(f"  ✅ {name}: {len(reqs)} 件 の orphan KEY を消去")
    print(f"✅ 合計 {cleared} 件 → 同数のカードが出品対象に復活")
    return {"orphans": len(orphans), "cleared": cleared, "executed": True}


def main():
    import argparse
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="出品プールの orphan canonical KEY を掃除")
    ap.add_argument("--execute", action="store_true", help="実消去(既定は dry-run)")
    a = ap.parse_args()
    clean(execute=a.execute)


if __name__ == "__main__":
    main()
