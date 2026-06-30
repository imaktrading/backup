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
# 現価格は funnel(生成25日前=実価格と大きく乖離)でも report(通貨混在)でもなく、
# **GetItem でライブ取得(USD換算)** する (2026-06-30 ユーザー指摘「eBay URLあるんだから自分で見ろ」)。
# non-US出品(AUD/EUR/GBP)も ConvertedCurrentPrice で USD 正規化 → V8(USD)と正しく比較。
CREDS_PATH = r"c:\dev\iMak\double-hold-421922-7c0d38d3f73d.json"
SHEET_IDS = ["19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk",   # HIGH
             "1jF9vggbfUCddjneROMO2GGN-jTAPRbq6Qe2cbgr37B0"]   # LOW
SHEET_GID = 851100680
COL_SUPPLY, COL_ITEMID, COL_SOLD, COL_COST, COL_CAT = 0, 1, 3, 13, 17   # A / B / D / N / R

# 判断ゲート: 利益率がこれ以上なら CUT_PP 削っても黒字 → 「値下」候補。未満は薄利で除外。
# (degressive利益率で一律%は不可。≥10%だけ拾えば5pp削っても≥5%残る=赤字なし。2026-06-30 ユーザー)
MARGIN_GATE_PCT = 10
CUT_PP = 5

COL_AL_FLAG = 37          # AL列(0-index37=38列目)。値下FLG。Q列(FLG)は重複くん使用中のため末尾に新設。
AL_FLAG_HEADER = "値下FLG"
AL_FLAG_VALUE = f"値下{CUT_PP}pp"

# 商品管理シート R列 ラベル → pricing_engine カテゴリ。未収載=floor出さず「要確認」(fail-closed)。
SHEET_CAT_TO_PRICING = {
    "G-shock": "G-SHOCK", "TCG": "TCG(PSA10)", "Tシャツ": "Tシャツ(UT)",
    "フィギュア": "フィギュア", "一番くじ": "一番くじ", "tomica": "トミカ",
    "カプセルトイ": "ガシャポン", "ヴィンテージ": "ヴィンテージ玩具", "リール": "リール",
    "バッグ": "バッグ(アネロ)",   # porter/yoshida も近似(同group B)
    "アウトドア・ジャケット": "Montbell(重)",
    "プライズフィギュア": "フィギュア",
    "グリグラ": "フィギュア",              # One Piece Glitter&Glamours = バンプレフィギュア
    "グッズ": "サンリオぬいぐるみ",         # 実体=サンリオ plush/キーホルダー(2026-06-30 実データ確認)
    "スニーカー": "スニーカー", "ゴルフ": "ゴルフ",
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


def write_al_flags(flagged_ids):
    """HIGH/LOW 商品管理シートの AL列(値下FLG)を **フル同期** で書く (I/O)。

    flagged_ids に居る itemID の行 → "値下{CUT_PP}pp"、それ以外の全行 → "" (clear)。
    = 売れた/薄利化/対象外になった品の flag を毎回掃除する(追加削除をフル同期で回す)。
    リバイス君はこの AL列を読んで apply_pricedown_override を適用する(2026-06-30)。
    戻り: {sheet: (set件数, clear件数)}。
    """
    import gspread
    from google.oauth2.service_account import Credentials
    gc = gspread.authorize(Credentials.from_service_account_file(
        CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"]))
    summary = {}
    for sid in SHEET_IDS:
        ws = gc.open_by_key(sid).get_worksheet_by_id(SHEET_GID)
        rows = ws.get_all_values()
        col = build_al_column(rows, flagged_ids)
        ws.update(range_name=f"AL1:AL{len(col)}", values=col, value_input_option="RAW")
        n_set = sum(1 for c in col[1:] if c[0] == AL_FLAG_VALUE)
        summary[sid[:8]] = (n_set, len(col) - 1 - n_set)
    return summary


def build_al_column(rows, flagged_ids):
    """AL列のフル同期値を構築 (純関数, test可)。行1=ヘッダー、以降 itemID が flagged なら値・他は空。"""
    col = [[AL_FLAG_HEADER]]
    for r in rows[1:]:
        iid = (r[COL_ITEMID] if len(r) > COL_ITEMID else "").strip()
        col.append([AL_FLAG_VALUE if (iid and iid in flagged_ids) else ""])
    return col


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
    """1商品の利益率(=値下げ余地)を算出 (純関数, test可)。

    値下げ余地 = V8が価格に織り込んだ利益率 = 込み利益 ÷ V8推奨価格。V8自身の出力をそのまま使う
    (自前の損益分岐近似は DDP/fee grossup を誤るため廃止。2026-06-30 ユーザー指摘)。
    margin_keep = 利益率(プロモ据置) / margin_drop = 広告(ad_rate)を外した分も上乗せ。
    戻り dict または {"error": 理由} (カテゴリ未対応/仕入値ゼロ)。cur_price は表示/乖離確認用。
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
    margin_keep = round(100 * profit_usd / v8, 1) if v8 else 0.0           # 利益率(プロモ据置)
    margin_drop = round(margin_keep + 100 * ad_rate, 1)                    # +広告分(プロモ外す)
    return {"pricing_cat": rec.get("category_resolved", base), "v8_rec": v8,
            "profit_usd": round(profit_usd, 2),
            "margin_keep_pct": margin_keep, "margin_drop_pct": margin_drop}


def main():
    import pricing_engine as pe
    from profit_params import _load as profit_load
    cache = profit_load()
    fx = _f(cache.get("exchange_rate") or cache.get("exchange_rate_usd") or 159.0)
    ad_rate = _f(cache.get("ad_rate") or 0.10)

    def compute_fn(cost_jpy, median, cat, title):
        # title_override(Porter等)を効かせる: 標準と同じカテゴリ解決にするため v6 を title付きで呼ぶ
        return pe.compute_listing_price_v6(cost_jpy, median or 0.0, cat, title=title or "")

    from ebay_getitem_images import fetch_listing_price

    nc = load_noconvert()
    print(f"NO_CONVERT = {len(nc)}件。商品管理スプシ(HIGH/LOW)読込中...", flush=True)
    idx = load_sheet_index()

    # 仕入可(売切でない)+結合済 のみ live 価格取得対象に絞る (GetItem 回数を最小化)
    targets = []
    n_oos = n_nomatch = 0
    for r in nc:
        d = idx.get((r.get("item_id") or "").strip())
        if not d:
            n_nomatch += 1
            continue
        if is_sold_out(d["sold"]):
            n_oos += 1
            continue            # 仕入不可=対象外 (fail-closed)
        targets.append((r, d))

    print(f"  仕入可 {len(targets)}件 → eBay GetItem で現価格(USD換算)をライブ取得中...", flush=True)
    out = [["利益率%(=値下げ余地・据置)", "判断(値下/様子見)", "カテゴリ", "商品名", "現価格$", "通貨", "最新仕入¥",
            "V8推奨$", "込み利益$", "利益率%(プロモ外)", "現価格÷V8(乖離)",
            "在庫", "仕入元URL", "eBay URL"]]
    rows_calc = []
    n_noprice = 0
    for i, (r, d) in enumerate(targets, 1):
        cur, ccy = fetch_listing_price(r.get("item_id"))
        if cur is None or cur <= 0:
            n_noprice += 1
            continue            # ライブ価格取れない(ended等)→ 除外 (fail-closed)
        res = compute_pricedown(cur, _f(d["cost"]), d["cat"], r.get("title", ""),
                                compute_fn=compute_fn, fx=fx, ad_rate=ad_rate)
        rows_calc.append((r, d, cur, ccy or "USD", res,
                          res["margin_keep_pct"] if "error" not in res else -999))
        if i % 25 == 0:
            print(f"    ...{i}/{len(targets)}", flush=True)

    rows_calc.sort(key=lambda x: -x[5])    # 利益率%(据置) 降順
    flagged_ids = set()                    # AL列フル同期用: 値下5pp 対象の itemID
    for r, d, cur, ccy, res, _ in rows_calc:
        if "error" in res:
            out.append(["", "", d["cat"], (r.get("title") or "")[:50], f"${cur:.0f}", ccy,
                        f"¥{_f(d['cost']):.0f}", "要確認", res["error"], "", "",
                        "仕入可", d.get("supply", ""), r.get("ebay_url", "")])
        else:
            gap = round(cur / res["v8_rec"], 2) if res["v8_rec"] else ""   # 現価格÷V8 (1.0=追従, <1=値上げ遅れ)
            # 判断 自動記入: 利益率≥10% は 5pp 削っても≥5%残る=赤字なし → 「値下5pp」候補。
            # 10%未満は薄利で除外(空欄)。閾値/削り幅は MARGIN_GATE/CUT_PP で調整可。
            judge = f"値下{CUT_PP}pp" if res["margin_keep_pct"] >= MARGIN_GATE_PCT else ""
            if judge:
                flagged_ids.add((r.get("item_id") or "").strip())
            out.append([res["margin_keep_pct"], judge, res["pricing_cat"], (r.get("title") or "")[:50], f"${cur:.0f}", ccy,
                        f"¥{_f(d['cost']):.0f}", f"${res['v8_rec']:.0f}", f"${res['profit_usd']:.1f}",
                        res["margin_drop_pct"], gap,
                        "仕入可", d.get("supply", ""), r.get("ebay_url", "")])

    calc_ok = sum(1 for x in rows_calc if "error" not in x[4])
    print(f"  結合 {len(targets)+n_oos}件 / 売切○(仕入不可=除外) {n_oos} / 未結合 {n_nomatch} / ライブ価格取得不可 {n_noprice}")
    print(f"  値下げ余地 算出 {calc_ok}件 / 要確認(カテゴリ未対応等) {len(rows_calc)-calc_ok}件")
    try:
        from sheet_io import write_rows_to_tab, MAINT_URL
        write_rows_to_tab("値下げ余地", out)
        print(f"💲 「値下げ余地」タブ更新: {len(out)-1}件 → {MAINT_URL}")
    except Exception as e:
        print(f"⚠ タブ更新失敗: {type(e).__name__}: {e}")
    # 商品管理シート AL列(値下FLG)をフル同期 → リバイス君が読む。NOCONVERT_NO_FLAG_WRITE=1 で抑止。
    if os.environ.get("NOCONVERT_NO_FLAG_WRITE") == "1":
        print(f"  ※ AL列書込skip (NOCONVERT_NO_FLAG_WRITE=1)。値下5pp対象 {len(flagged_ids)}件")
    else:
        try:
            s = write_al_flags(flagged_ids)
            print(f"🏷 AL列(値下FLG)フル同期: {dict(s)} (値下5pp={len(flagged_ids)}件・他はclear)")
        except Exception as e:
            print(f"⚠ AL列書込失敗: {type(e).__name__}: {e}")
    print("▶ リバイス君が AL列(値下FLG)を読み、apply_pricedown_override で週1反映(本実装依頼後)。")
    print("※ 売切○は仕入不可のため除外済。自動値下げはしない。")


if __name__ == "__main__":
    main()
