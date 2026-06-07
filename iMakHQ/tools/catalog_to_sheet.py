#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""カタログ (products.sqlite) をスプシに書き出す (2026-06-07)。

目的: 「何がどうデータ化されているか」を人が見て分かるようにする。
構造 (= ユーザー整理の2層モデル):
  A層 = 生の公式データ (name_jp / set_name / set_name_official / specs の *_ebay 以外)
  B層 = eBay向け派生 (name_en / set_name_ebay / specs の末尾 *_ebay) ← 公式に答えが無く事故源

シート構成:
  - 概要      : 2層モデル説明 + カテゴリ件数 + B層フィールドの空欄率 (= 抜けの可視化)
  - <category>: カテゴリ毎に全件。列は [front] [A層core] [B層core] [specs: B(*_ebay)→A]

再実行可能 (clear+update)。カタログ更新後に回せば最新が反映される。
"""
import collections
import json
import sqlite3
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB = r"C:\dev\iMak_data\catalog\products.sqlite"
CREDS_PATH = r"c:\dev\iMak\double-hold-421922-7c0d38d3f73d.json"
TARGET_SHEET_ID = "1U0P3gLMYzQMdxIrP2OE31XSGQOStdK0QPIfH2uC88vE"

# 列に展開すると重い/読みにくい長文 specs は除外 or 短縮
_LONG_KEYS = {"desc", "card_text", "effect", "card_characteristics", "ability", "flavor_text"}
_SKIP_TOP = {"specs", "images", "variants", "id"}
MAXCELL = 280  # セル文字数上限 (読みやすさ + payload 抑制)

# 表示順の先頭固定列 (top-level)
FRONT = ["product_id", "language", "source"]
A_CORE = ["name_jp", "set_name", "set_name_official"]
B_CORE = ["name_en", "name_en_source"]


def _trunc(v):
    if v is None:
        return ""
    if isinstance(v, (list, dict)):
        try:
            v = json.dumps(v, ensure_ascii=False)
        except Exception:
            v = str(v)
    s = str(v)
    return s[:MAXCELL] + "…" if len(s) > MAXCELL else s


def _is_b_specs(key):
    return key.endswith("_ebay") or key.endswith("_en")


def gather_category(con, cat):
    """カテゴリ全件取得 → (header, rows2d)。specs を列展開。"""
    rows = con.execute(
        "SELECT product_id,language,source,name,name_jp,set_name,set_name_official,"
        "name_en,name_en_source,specs,images FROM products WHERE category=? ORDER BY product_id",
        (cat,),
    ).fetchall()
    cols = [c[0] for c in con.execute("PRAGMA table_info(products)")]
    # specs キー union (出現頻度順)
    spec_counter = collections.Counter()
    parsed = []
    for r in rows:
        d = dict(zip(
            ["product_id", "language", "source", "name", "name_jp", "set_name",
             "set_name_official", "name_en", "name_en_source", "specs", "images"], r))
        try:
            sp = json.loads(d["specs"]) if d["specs"] else {}
        except Exception:
            sp = {}
        d["_specs"] = sp
        parsed.append(d)
        for k in sp:
            spec_counter[k] += 1
    # specs 列順: B層(*_ebay/_en) を先に、その後 A層。各 出現頻度順。長文keyは末尾。
    b_specs = [k for k, _ in spec_counter.most_common() if _is_b_specs(k) and k not in _LONG_KEYS]
    a_specs = [k for k, _ in spec_counter.most_common() if not _is_b_specs(k) and k not in _LONG_KEYS]
    long_specs = [k for k, _ in spec_counter.most_common() if k in _LONG_KEYS]

    header = (FRONT + A_CORE + B_CORE
              + [f"specsB:{k}" for k in b_specs]
              + [f"specsA:{k}" for k in a_specs]
              + [f"specsA:{k}" for k in long_specs])
    out = [header]
    for d in parsed:
        sp = d["_specs"]
        row = [_trunc(d.get(c)) for c in FRONT + A_CORE + B_CORE]
        row += [_trunc(sp.get(k)) for k in b_specs]
        row += [_trunc(sp.get(k)) for k in a_specs]
        row += [_trunc(sp.get(k)) for k in long_specs]
        out.append(row)
    return out, len(rows)


def build_overview(con):
    cats = [(c, n) for c, n in con.execute(
        "SELECT category,COUNT(*) FROM products GROUP BY category ORDER BY COUNT(*) DESC")]
    rows = [
        ["カタログ構造マップ (products.sqlite)"],
        [],
        ["■ 2層モデル"],
        ["A層 = 生の公式データ", "name_jp / set_name / set_name_official / specsA:* (= 公式サイトをそのまま保存)", "ほぼ事故なし"],
        ["B層 = eBay向け派生", "name_en / set_name_ebay / specsB:*_ebay (= 公式に答えが無い、人/機械が解釈して生成)", "事故はここで出る"],
        ["", "※ 列名 specsB: = B層 / specsA: = A層。末尾 _ebay と name_en が B層の目印。", ""],
        [],
        ["■ カテゴリ件数 + B層フィールド空欄率 (= 抜けの可視化)"],
        ["category", "件数", "set_name_ebay 空欄", "name_en 空欄", "空欄率(set_ebay)"],
    ]
    for cat, n in cats:
        se_blank = 0
        ne_blank = 0
        for (sp, ne) in con.execute(
                "SELECT specs,name_en FROM products WHERE category=?", (cat,)):
            try:
                d = json.loads(sp) if sp else {}
            except Exception:
                d = {}
            if not d.get("set_name_ebay"):
                se_blank += 1
            if not (ne or "").strip():
                ne_blank += 1
        rows.append([cat, n, se_blank, ne_blank, f"{se_blank/n*100:.0f}%" if n else "-"])
    rows += [
        [],
        ["■ 見方"],
        ["- 各カテゴリのシートに全件。1行=1商品。"],
        ["- specsB:set_name_ebay が空 = eBay側にまだ値が無い新弾 等 (fail-closed=空欄。推測で埋めない)。"],
        ["- 誤り(誤ったセット名等)は B層で発生する。A層(JP名)は基本正しい。"],
    ]
    return rows


def _auth():
    import gspread
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_file(
        CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    return gspread.authorize(creds)


def write_tab(sh, tab, rows2d, chunk=2000):
    """大量行対応: clear → resize → チャンク書込。"""
    import gspread
    ncols = max((len(r) for r in rows2d), default=4)
    nrows = len(rows2d)
    try:
        ws = sh.worksheet(tab)
        ws.clear()
        ws.resize(rows=max(nrows + 2, 2), cols=max(ncols, 1))
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab, rows=max(nrows + 2, 10), cols=max(ncols, 4))
    for i in range(0, nrows, chunk):
        part = rows2d[i:i + chunk]
        ws.update(range_name=f"A{i + 1}", values=part, value_input_option="RAW")
    return nrows


def main():
    con = sqlite3.connect(DB)
    gc = _auth()
    sh = gc.open_by_key(TARGET_SHEET_ID)

    print("▶ 概要シート")
    ov = build_overview(con)
    write_tab(sh, "概要", ov)
    print(f"  概要 {len(ov)}行")

    cats = [c for (c,) in con.execute(
        "SELECT category FROM products GROUP BY category ORDER BY COUNT(*) DESC")]
    for cat in cats:
        rows2d, n = gather_category(con, cat)
        write_tab(sh, cat, rows2d)
        print(f"  {cat:18} {n}件 ({len(rows2d[0])}列) 書込")

    print(f"\n✅ 完了: https://docs.google.com/spreadsheets/d/{TARGET_SHEET_ID}/edit")


if __name__ == "__main__":
    main()
