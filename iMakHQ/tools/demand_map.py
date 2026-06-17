#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""需要マップ (合算ビュー) — eBay実績需要 と 国内OOS(仕入元切れ=国内実需proxy) を
1シートに **並走表示** (足し算はしない=別カラム)。値をパッと見える化するのが目的。

設計メモ: oos_demand_harvest_design.md
  - 需要・新規強化(demand_winners) は据え置き。本ツールは別タブ「需要マップ」に出力。
  - eBay需要(売る市場の実績) と 国内OOS(別市場のproxy) は混ぜると薄まる → 別カラムで横並び。
  - 4象限の狙い: eBay低×国内OOS高 = 「eBayで未実証だが国内で動く」= 新規開拓候補(本丸)。

国内OOS(=仕入元切れ) の解釈:
  funnel の qty(Available quantity)=0 は、無在庫運用で仕入元が切れた時に在庫0化される
  ため「仕入元OOS≒国内で売れた」の proxy。完全ではない(取下げ/期限切れ/1点もの) ため
  集計(回数)で見る。impr 併記で「露出されたのに売れない(死筋)」と「未露出(機会不足)」を区別。

入力: ../funnel_output/funnel_*.csv (最新)
出力: 「既存メンテ」スプシ 「需要マップ」タブ + コンソール要約
ブレスト版 (2026-06-09)。判定ロジックは最小、まず値の見える化を優先。
"""
import csv
import glob
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import demand_winners as dw  # vein_of / facets / _f を再利用 (ロジック重複を避ける)

# === demand_map 独自の追加 facet (demand_winners は無改変) ===
# G-SHOCK 型番系統: GA-2100SB-1AJF→GA-2100 / GW-B5600HR-1JF→GW-B5600 / GX-56MF→GX-56
_GS_SERIES_RE = re.compile(r"\b([A-Z]{1,4}-[A-Z]?\d{2,4})")
# PSA カード番号: #OP13-004 / #P-041 / #072 / #ST07-008 → カッコ内
_PSA_NUM_RE = re.compile(r"#\s*([A-Za-z]{0,3}\d{1,3}(?:-\d{1,4})?(?:/\d{1,4})?)")
# キャラ抽出: カード番号の後ろ ~ stopword 手前まで (heuristic。完全ではない=要catalog化が本筋)
_CHAR_STOP = {
    "card", "cards", "alternate", "alt", "art", "premium", "booster", "box", "gift",
    "collection", "gx", "ex", "v", "vmax", "vstar", "sr", "sar", "ar", "ur", "hr", "rr",
    "rrr", "ssr", "sec", "bandai", "game", "tcg", "promo", "manga", "rare", "parallel",
    "full", "special", "leader", "character", "stage", "anime", "japanese", "holo",
    "reverse", "the", "pokemon", "tag", "team", "&",
    "gem", "mt", "mint", "graded", "psa", "common", "uncommon", "bgs",
}


def _gs_series(title):
    m = _GS_SERIES_RE.search(title or "")
    return m.group(1) if m else None


def _psa_cardnum(title):
    m = _PSA_NUM_RE.search(title or "")
    return m.group(1).upper() if m else None


def _psa_char(title):
    """カード番号の後ろから stopword 手前までを character とみなす (best-effort)。"""
    m = _PSA_NUM_RE.search(title or "")
    if not m:
        return None
    toks = []
    for w in title[m.end():].split():
        wl = re.sub(r"[^A-Za-z]", "", w).lower()
        if not wl:
            continue
        if wl in _CHAR_STOP:
            break
        toks.append(w)
        if len(toks) >= 3:
            break
    name = " ".join(toks).strip(" .&-")
    return name or None


def _ebay_item_id(url):
    """ebay_url → itemID (mercari_psa_resource と同ロジック・KEY join 用)。"""
    try:
        import mercari_psa_resource as _mp
        return _mp._ebay_item_id(url)
    except Exception:
        m = re.search(r"/(\d{10,})", url or "")
        return m.group(1) if m else None


def _name_jp_for_key(key, _cache={}):
    """canonical KEY → catalog name_jp (demand_map キャラ軸用)。失敗時 None。"""
    if key in _cache:
        return _cache[key]
    nj = None
    try:
        import mercari_psa_resource as _mp
        meta = _mp.card_meta_for_key(key)
        nj = meta.get("name_jp") if meta else None
    except Exception:
        nj = None
    _cache[key] = nj
    return nj


def extra_facets(vein, title, key=None):
    """demand_winners.facets() に無い軸を補う。G-SHOCK型番系統 / PSAカード番号・キャラ。

    Step6 P4: PSA card は **canonical KEY(商品管理シート itemID join)** が解決できれば
    番号regex/キャラheuristic でなく **canonical product_id + catalog name_jp** で集計
    (番号衝突・heuristic誤りを排除 = コードTODO「要catalog化が本筋」を実行)。
    KEY 未解決(管理外行)→ 従来の regex/heuristic に fallback(後方互換)。
    """
    out = []
    if vein == "G-SHOCK":
        s = _gs_series(title)
        if s:
            out.append(("型番系統", s))
    elif vein == "PSA card":
        if key:
            out.append(("KEY", key))             # canonical product_id (一意・番号衝突なし)
            nj = _name_jp_for_key(key)
            if nj:
                out.append(("キャラ", nj))        # catalog 正名 (heuristic でない)
        else:
            c = _psa_char(title)
            if c:
                out.append(("キャラ", c))
            n = _psa_cardnum(title)
            if n:
                out.append(("カード番号", n))
    return out

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FUNNEL_DIR = dw.FUNNEL_DIR


def _f(v):
    return dw._f(v)


def _i(v):
    try:
        return int(float(str(v).replace(",", "").strip() or 0))
    except (ValueError, TypeError):
        return 0


def _blank_cell():
    return {"score": 0.0, "sold": 0.0, "watch": 0.0, "impr": 0.0,
            "listings": 0, "oos": 0, "restock": 0, "cull": 0}


def _ingest(cell, score, sold, watch, impr, is_oos, flags):
    cell["score"] += score
    cell["sold"] += sold
    cell["watch"] += watch
    cell["impr"] += impr
    cell["listings"] += 1
    if is_oos:
        cell["oos"] += 1
    if "RESTOCK" in flags:
        cell["restock"] += 1
    if "CULL" in flags:
        cell["cull"] += 1


def aggregate(rows):
    """funnel 行を vein別 と facet別(観点,値) に集計。eBay需要と国内OOSを同じcellに別フィールドで持つ。"""
    vein_agg = defaultdict(_blank_cell)
    facet_agg = defaultdict(_blank_cell)
    # Step6 P4: itemID→canonical KEY map を1回読む(PSA card facet を KEY集計に)。失敗時 fallback。
    keymap = {}
    try:
        from sheet_io import product_index
        keymap, _, _ = product_index()
    except Exception:
        keymap = {}
    keyed = total_psa = 0
    for r in rows:
        title = (r.get("title") or "").strip()
        if not title:
            continue
        vein = dw.vein_of(title)
        key = None
        if keymap and vein == "PSA card":
            total_psa += 1
            iid = _ebay_item_id(r.get("ebay_url", "") or "")
            key = keymap.get(iid) if iid else None
            if key:
                keyed += 1
        sold = _f(r.get("sold_qty")) + _f(r.get("sales90"))
        watch = _f(r.get("watch"))
        impr = _f(r.get("impr_total")) or _f(r.get("impr"))  # 累計(広告込)=真の露出。organicのみは過小
        score = sold * 100 + watch * 8 + impr * 0.05  # demand_winners 同式だが impr は累計を採用
        is_oos = _i(r.get("qty")) == 0                 # 仕入元切れ proxy
        flags = (r.get("flags") or "").split("|")
        _ingest(vein_agg[vein], score, sold, watch, impr, is_oos, flags)
        for kan, val, _m in dw.facets(vein, title):
            _ingest(facet_agg[(kan, val)], score, sold, watch, impr, is_oos, flags)
        for kan, val in extra_facets(vein, title, key):   # G-SHOCK型番系統 / PSA: KEY+catalog名 or fallback
            _ingest(facet_agg[(kan, val)], score, sold, watch, impr, is_oos, flags)
    if total_psa:
        print(f"[demand_map] PSA canonical KEY 集計: {keyed}/{total_psa} 行 "
              f"(残 {total_psa-keyed} は番号regex fallback)", flush=True)
    return vein_agg, facet_agg


# --- 判定マーク (3アクションに対応) + 背景色 ---
# 🟢 再仕入/鉄板 = eBayで実際に売れた実績あり → 維持/仕入れ直す
# 🔴 死筋:出さない = 売れてない & 露出十分(impr高) → もう出さない/畳む
# 🔵 新規開拓:出す = 売れてない & 国内OOS高 & 未露出(impr低) → 出してみる候補
MARK_GREEN = "🟢売れ筋/再仕入"
MARK_YELLOW = "⚠改善(露出多/実売弱)"
MARK_RED = "🔴死筋:出さない"
MARK_BLUE = "🔵国内実需:再仕入/増やす"
RGB_GREEN = {"red": 0.85, "green": 0.94, "blue": 0.83}
RGB_YELLOW = {"red": 1.0, "green": 0.96, "blue": 0.80}
RGB_RED = {"red": 0.97, "green": 0.84, "blue": 0.84}
RGB_BLUE = {"red": 0.82, "green": 0.89, "blue": 0.97}
_MARK_RGB = {MARK_GREEN: RGB_GREEN, MARK_YELLOW: RGB_YELLOW,
             MARK_RED: RGB_RED, MARK_BLUE: RGB_BLUE}

# 「国内で動く」とみなす絶対バー (OOS率)。これ以上は国内実需=死筋にしない。相対(中央値)だと
# PSA単カードのようにほぼ全部OOSな系統で boundary 事故が出るため絶対値で固定 (調整可)。
OOS_MOVES_BAR = 0.20


def classify(c, med_impr_pl, med_oos_rate, med_sold_pl):
    """per-listing 比率で4分類 (規模差を吸収)。
    重要: OOS品は買えない=eBay実売0は不人気の証拠にならない。国内OOS高=国内で動く=死筋でない。
    売れてる→売れ筋(🟢)/露出多いが弱い→改善(⚠)/無売&国内OOS≥20%→国内実需(🔵)/
    無売&国内でもほぼ動かず&露出済→死筋(🔴)。"""
    lst = c["listings"] or 1
    oos_rate = c["oos"] / lst
    impr_pl = c["impr"] / lst
    sold_pl = c["sold"] / lst
    if c["sold"] > 0:
        if sold_pl >= med_sold_pl:
            return MARK_GREEN                 # eBayで中央値以上に売れてる
        if impr_pl >= med_impr_pl:
            return MARK_YELLOW                # 売れてるが露出割に弱い → title/価格
        return ""
    # 実売0 — ただし OOS品は買えないので「売れない」を不人気と見なさない
    if oos_rate >= OOS_MOVES_BAR:              # 国内で動いてる(絶対バー) → 死筋でない。再仕入/増やす
        return MARK_BLUE
    if impr_pl >= med_impr_pl:                 # 国内でもほぼ動かず & eBay露出十分なのに無売 → 死筋
        return MARK_RED
    return ""


def _medians(cells):
    import statistics
    impr_pls = [c["impr"] / (c["listings"] or 1) for c in cells if c["listings"]]
    oos_rates = [c["oos"] / (c["listings"] or 1) for c in cells if c["listings"]]
    sold_pls = [c["sold"] / (c["listings"] or 1) for c in cells if c["listings"] and c["sold"] > 0]
    mi = statistics.median(impr_pls) if impr_pls else 0
    mo = statistics.median(oos_rates) if oos_rates else 0
    ms = statistics.median(sold_pls) if sold_pls else 0
    return mi, mo, ms


def _row_vals_vein(name, c, mark):
    return [name, mark, c["listings"], round(c["score"], 1), int(c["sold"]),
            int(c["watch"]), int(c["impr"]), c["oos"], c["restock"], c["cull"]]


def _row_vals_facet(kan, val, c, mark):
    return [kan, val, mark, c["listings"], round(c["score"], 1), int(c["sold"]),
            int(c["watch"]), int(c["impr"]), c["oos"], c["restock"], c["cull"]]


def build_sheet(vein_agg, facet_agg, src_name):
    """data2d と、色付け対象 [(sheet_row_1based, rgb), ...] を返す。"""
    import datetime
    mi_v, mo_v, ms_v = _medians(list(vein_agg.values()))
    mi_f, mo_f, ms_f = _medians(list(facet_agg.values()))
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    data = [[f"需要マップ (eBay実績 ∥ 国内OOS proxy を並走・足し算なし)  |  元funnel: {src_name}  |  更新 {now}"]]
    data.append(["凡例: 🟢売れ筋/再仕入=実売が中央値以上 / ⚠改善=売れてるが露出割に弱い(title/価格) / "
                 "🔵国内実需:再仕入/増やす=国内OOS高(国内で動く) / 🔴死筋:出さない=国内でも動かず露出済なのに無売 "
                 "※国内OOS=qty0=仕入元切れproxy=国内で売れた / OOS品は買えないので実売0を不人気と見なさない / 判定はper-listing比率"])
    data.append([""])
    colors = []
    data.append(["【系統サマリー】"])
    data.append(["系統", "判定", "出品数", "eBay需要スコア", "実売", "watch", "impr",
                 "国内OOS数", "RESTOCK", "CULL"])
    for name, c in sorted(vein_agg.items(), key=lambda kv: (-kv[1]["oos"], -kv[1]["score"])):
        mark = classify(c, mi_v, mo_v, ms_v)
        data.append(_row_vals_vein(name, c, mark))
        if mark in _MARK_RGB:
            colors.append((len(data), _MARK_RGB[mark]))  # len(data)=この行の1-based行番号
    data.append([""])
    data.append(["【属性別詳細 (サブ/タイプ/ライン/サイズ/色)】"])
    data.append(["観点", "値", "判定", "出品数", "eBay需要スコア", "実売", "watch", "impr",
                 "国内OOS数", "RESTOCK", "CULL"])
    for (kan, val), c in sorted(facet_agg.items(), key=lambda kv: (-kv[1]["oos"], -kv[1]["score"])):
        mark = classify(c, mi_f, mo_f, ms_f)
        data.append(_row_vals_facet(kan, val, c, mark))
        if mark in _MARK_RGB:
            colors.append((len(data), _MARK_RGB[mark]))
    return data, colors


def _apply_colors(colors):
    """行ごとに背景色を当てる (batch_format)。失敗は非致命。"""
    if not colors:
        return
    import gspread
    from google.oauth2.service_account import Credentials
    from sheet_io import CREDS_PATH, MAINT_SHEET_ID
    creds = Credentials.from_service_account_file(
        CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(MAINT_SHEET_ID).worksheet("需要マップ")
    reqs = [{"range": f"A{r}:K{r}", "format": {"backgroundColor": rgb}} for r, rgb in colors]
    ws.batch_format(reqs)


def main():
    fs = glob.glob(os.path.join(FUNNEL_DIR, "funnel_*.csv"))
    if not fs:
        sys.exit("funnel_*.csv がありません。先に『📊 ファネル分析』を実行してください。")
    src = max(fs, key=os.path.getmtime)
    rows = list(csv.DictReader(open(src, encoding="utf-8")))
    print(f"対象 funnel: {os.path.basename(src)} ({len(rows)}行)")

    vein_agg, facet_agg = aggregate(rows)
    data, colors = build_sheet(vein_agg, facet_agg, os.path.basename(src))
    mi_v, mo_v, ms_v = _medians(list(vein_agg.values()))

    # コンソール: 系統サマリー (判定マーク付き)
    print("\n=== 系統サマリー (国内OOS降順) ===")
    print(f"  {'系統':<12}{'判定':<22}{'出品':>5}{'eBay需要':>9}{'実売':>5}{'impr':>7}{'OOS':>5}{'CULL':>6}")
    for name, c in sorted(vein_agg.items(), key=lambda kv: (-kv[1]["oos"], -kv[1]["score"])):
        mark = classify(c, mi_v, mo_v, ms_v)
        print(f"  {name:<12}{mark:<22}{c['listings']:>5}{c['score']:>9.0f}{int(c['sold']):>5}"
              f"{int(c['impr']):>7}{c['oos']:>5}{c['cull']:>6}")

    try:
        from sheet_io import write_rows_to_tab, MAINT_URL
        write_rows_to_tab("需要マップ", data)
        _apply_colors(colors)
        print(f"\n📊 「需要マップ」タブ更新: {len(data)}行 / 色付 {len(colors)}行 → {MAINT_URL}")
    except Exception as _e:  # noqa: BLE001
        print(f"\n⚠ 「需要マップ」タブ更新失敗 (コンソールには出力済): {type(_e).__name__}: {_e}")


if __name__ == "__main__":
    main()
