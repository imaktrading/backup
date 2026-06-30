#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NO_CONVERT 値下げ余地 一覧 — 「クリック来るが売れない」を V8 で何%下げられるか可視化。

ユーザー設計 (2026-06-30):
  そのバケツ(NO_CONVERT)に対し、HIGH/LOW(商品管理スプシ2枚)の最新仕入値 + 在庫(売切=仕入可否)
  を取得し、現価格と「V8でどこまで値下げできるか」を一覧化 → 人が価格リバイス可否を判断する。

スコープ/安全:
  - 売切○(監視くん=公式在庫切れ=仕入不可)は **対象外**(値下げしても履行不能=BAN risk)。fail-closed。
  - 仕入値が空 or カテゴリ未対応(pricingに無い)は floor を出さず「要確認」表示(推測しない)。
  - 自動リバイスはしない。判断列を空で出し、人が「値下/様子見」を入れる。

値下げ余地の定義 (V8/V6 cost-plus):
  floor(プロモ据置)   = V8推奨価格 − 込み利益(profit_jpy)/FX … 利益ゼロ=損益分岐
  floor(プロモ外す)   = floor(据置) − 広告(ad_rate)×推奨   … Promoted Listings 広告分が浮く
  値下げ可能幅        = 現価格 − floor (現価格が推奨超なら余地大)

入力: ../funnel_output/funnel_*.csv (NO_CONVERT) + 商品管理スプシ HIGH/LOW (B=itemID/N=仕入/R=cat/D=売切)
出力: 「既存メンテ」スプシ「値下げ余地」タブ (値下げ可能%降順)
"""
import csv
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "iMakeBayAPI")))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
FUNNEL_DIR = os.path.normpath(os.path.join(_HERE, "..", "funnel_output"))
CREDS_PATH = r"c:\dev\iMak\double-hold-421922-7c0d38d3f73d.json"
SHEET_IDS = ["19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk",   # HIGH
             "1jF9vggbfUCddjneROMO2GGN-jTAPRbq6Qe2cbgr37B0"]   # LOW
SHEET_GID = 851100680
COL_SUPPLY, COL_ITEMID, COL_SOLD, COL_COST, COL_CAT = 0, 1, 3, 13, 17   # A / B / D / N / R

# 商品管理シート R列 ラベル → pricing_engine カテゴリ。未収載=floor出さず「要確認」(fail-closed)。
SHEET_CAT_TO_PRICING = {
    "G-shock": "G-SHOCK", "TCG": "TCG(PSA10)", "Tシャツ": "Tシャツ(UT)",
    "フィギュア": "フィギュア", "一番くじ": "一番くじ", "tomica": "トミカ",
    "カプセルトイ": "ガシャポン", "ヴィンテージ": "ヴィンテージ玩具", "リール": "リール",
    "バッグ": "バッグ(アネロ)",   # title_overrides で porter/yoshida は Porter に上書きされる
}


def _f(v):
    try:
        return float(str(v).replace(",", "").replace("$", "").replace("¥", "").strip())
    except (ValueError, TypeError):
        return 0.0


def is_sold_out(mark):
    return (mark or "").strip() in ("○", "〇")


def load_noconvert():
    fs = glob.glob(os.path.join(FUNNEL_DIR, "funnel_*.csv"))
    if not fs:
        sys.exit("funnel_*.csv がありません。先に『📊 ファネル分析』を実行してください。")
    rows = list(csv.DictReader(open(max(fs, key=os.path.getmtime), encoding="utf-8")))
    return [r for r in rows if "NO_CONVERT" in (r.get("flags") or "").split("|")]


def load_sheet_index():
    """HIGH/LOW 2枚 → {itemID: {cost, cat, sold}}。I/O。"""
    import gspread
    from google.oauth2.service_account import Credentials
    gc = gspread.authorize(Credentials.from_service_account_file(
        CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"]))
    idx = {}
    for sid in SHEET_IDS:
        for r in gc.open_by_key(sid).get_worksheet_by_id(SHEET_GID).get_all_values():
            iid = (r[COL_ITEMID] if len(r) > COL_ITEMID else "").strip()
            if not iid.isdigit():
                continue
            idx[iid] = {"cost": (r[COL_COST] if len(r) > COL_COST else "").strip(),
                        "cat": (r[COL_CAT] if len(r) > COL_CAT else "").strip(),
                        "sold": (r[COL_SOLD] if len(r) > COL_SOLD else "").strip(),
                        "supply": (r[COL_SUPPLY] if len(r) > COL_SUPPLY else "").strip()}
    return idx


def compute_pricedown(cur_price, cost_jpy, sheet_cat, title, *, compute_fn, fx, ad_rate):
    """1商品の値下げ余地を算出 (純関数, test可)。

    戻り dict: {pricing_cat, v8_rec, profit_usd, floor_keep, floor_drop, room_keep_pct, room_drop_pct}
    または {"error": 理由} (カテゴリ未対応/仕入値ゼロ)。
    """
    if cost_jpy <= 0:
        return {"error": "仕入値ゼロ"}
    base = SHEET_CAT_TO_PRICING.get(sheet_cat)
    if not base:
        return {"error": f"カテゴリ未対応({sheet_cat})"}
    try:
        rec = compute_fn(cost_jpy, cur_price or None, base, title)
    except Exception as e:
        return {"error": f"V8計算失敗({type(e).__name__})"}
    v8 = _f(rec.get("price"))
    profit_usd = _f(rec.get("profit_jpy")) / fx if fx else 0.0
    floor_keep = round(v8 - profit_usd, 2)                       # 損益分岐(プロモ据置)
    floor_drop = round(floor_keep - ad_rate * v8, 2)            # 広告分も削る(プロモ外す)
    room_keep = cur_price - floor_keep                          # 現価格からの値下げ可能幅
    room_drop = cur_price - floor_drop
    return {"pricing_cat": rec.get("category_resolved", base), "v8_rec": v8,
            "profit_usd": round(profit_usd, 2), "floor_keep": floor_keep, "floor_drop": floor_drop,
            "room_keep_pct": round(100 * room_keep / cur_price, 1) if cur_price else 0.0,
            "room_drop_pct": round(100 * room_drop / cur_price, 1) if cur_price else 0.0}


def main():
    import pricing_engine as pe
    from profit_params import _load as profit_load
    cache = profit_load()
    fx = _f(cache.get("exchange_rate") or cache.get("exchange_rate_usd") or 159.0)
    ad_rate = _f(cache.get("ad_rate") or 0.10)

    def compute_fn(cost_jpy, median, cat, title):
        return pe.compute_listing_price(cost_jpy=cost_jpy, median_usd=median or 0.0, category=cat)

    nc = load_noconvert()
    print(f"NO_CONVERT = {len(nc)}件。商品管理スプシ(HIGH/LOW)読込中...", flush=True)
    idx = load_sheet_index()

    out = [["値下げ余地%(据置)", "判断(値下/様子見)", "カテゴリ", "商品名", "現価格", "最新仕入¥", "V8推奨",
            "込み利益$", "下限(プロモ据置)", "下限(プロモ外)", "値下げ余地%(外)",
            "在庫", "仕入元URL", "eBay URL"]]
    rows_calc = []
    n_oos = n_nomatch = 0
    for r in nc:
        iid = (r.get("item_id") or "").strip()
        d = idx.get(iid)
        if not d:
            n_nomatch += 1
            continue
        if is_sold_out(d["sold"]):
            n_oos += 1
            continue            # 仕入不可=対象外 (fail-closed)
        cur = _f(r.get("price"))
        res = compute_pricedown(cur, _f(d["cost"]), d["cat"], r.get("title", ""),
                                compute_fn=compute_fn, fx=fx, ad_rate=ad_rate)
        if "error" in res:
            rows_calc.append((r, d, cur, res, -1))
            continue
        rows_calc.append((r, d, cur, res, res["room_keep_pct"]))

    rows_calc.sort(key=lambda x: -x[4])    # 値下げ余地%(据置) 降順
    for r, d, cur, res, _ in rows_calc:
        if "error" in res:
            out.append(["", "", d["cat"], (r.get("title") or "")[:50], f"${cur:.0f}",
                        f"¥{_f(d['cost']):.0f}", "要確認", res["error"], "", "", "",
                        "仕入可", d.get("supply", ""), r.get("ebay_url", "")])
        else:
            out.append([res["room_keep_pct"], "", res["pricing_cat"], (r.get("title") or "")[:50], f"${cur:.0f}",
                        f"¥{_f(d['cost']):.0f}", f"${res['v8_rec']:.0f}", f"${res['profit_usd']:.1f}",
                        f"${res['floor_keep']:.0f}", f"${res['floor_drop']:.0f}", f"{res['room_drop_pct']:.0f}%",
                        "仕入可", d.get("supply", ""), r.get("ebay_url", "")])

    calc_ok = sum(1 for x in rows_calc if "error" not in x[3])
    print(f"  結合 {len(rows_calc)+n_oos}件 / 売切○(仕入不可=除外) {n_oos} / 未結合 {n_nomatch}")
    print(f"  値下げ余地 算出 {calc_ok}件 / 要確認(カテゴリ未対応等) {len(rows_calc)-calc_ok}件")
    try:
        from sheet_io import write_rows_to_tab, MAINT_URL
        write_rows_to_tab("値下げ余地", out)
        print(f"💲 「値下げ余地」タブ更新: {len(out)-1}件 → {MAINT_URL}")
    except Exception as e:
        print(f"⚠ タブ更新失敗: {type(e).__name__}: {e}")
    print("▶ 各行の値下げ余地%を見て、判断列に「値下/様子見」を記入 → リバイス君が利益率上書きで反映(別途依頼)。")
    print("※ 売切○は仕入不可のため除外済。自動値下げはしない。")


if __name__ == "__main__":
    main()
