#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""需要・新規強化リスト (B版) — 「実証系統で、まだ出していない商品(=売れそう)」を出す。

【設計思想】(2026-06-04 B版)
過去ランキング(売れた/watch多い羅列)ではなく、**新規未出品で売れそうな商品**を出す。
= 実証系統(需要シグナルが立つ系統) × その系統で catalog にあるが未出品の商品。

需要シグナル(系統の実証度): funnel CSV (sold + watch + impr を4サイト合算)
  需要スコア = 実売*100 + watch*8 + impr*0.05  (信頼度: 実売 >> watch > impr)
$ 文脈                  : orders(去年+今年) の vein 別 AOV
未出品の母集団           : catalog − active

【B が deterministic に出せる範囲 (2026-06-04 時点)】
  - G-SHOCK : catalog 型番 = active タイトルの型番でマッチ成立 → casio_finder の
              unlisted_from_catalog_*.csv を母集団に使う。◎ 即可。
  - Montbell: catalog 型番(数字)が active タイトルに無い物が多く型番マッチ不成立 → 名前マッチ要(未対応)
  - UNIQLO/UT: catalog 未完 → 除外
  - TCG/PSA : set code マッチ可だが variant 煩雑(未対応)
  - PORTER/Tomica/POP MART: catalog 無し → AI/手動候補
  誤マッチで嘘の「未出品」を出さない(精度原則)。確実な G-SHOCK のみ候補化し、他は明示。

入力: ../funnel_output/funnel_*.csv + *orders*.csv + iMakG-shock/casio_finder/unlisted_from_catalog_*.csv
出力: デスクトップ 新規強化リスト_YYYYMMDD.csv (1行=1候補) + コンソール要約

※ 送料無料は DDP 複雑で不採用(既定方針)。露出より「何を売るか」に寄せる前提。
"""
import csv
import datetime
import glob
import os
import re
import sys
import urllib.parse
from collections import defaultdict

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPORTS_DIR = r"C:\dev\iMak_data\seller_hub\reports"
FUNNEL_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "funnel_output"))
CASIO_UNLISTED_DIR = r"C:\dev\iMak\iMakG-shock\casio_finder"
DESK = r"C:\Users\imax2\OneDrive\デスクトップ"

# catalog 由来の deterministic B が出せる vein → 母集団ソース種別
_B_READY = {"G-SHOCK": "casio_unlisted"}
# vein 別 仕入れ適性マーク
_FEAS_MARK = {"G-SHOCK": "◎", "Montbell": "◎", "UNIQLO/UT": "◎", "Sanrio": "◎", "Tomica": "◎",
              "POP MART": "◎", "ブリキ玩具": "◎", "ガシャポン": "◎", "PORTER": "△", "PSA card": "△",
              "一番くじ": "△", "Figure": "△", "Reel": "△"}
# catalog 保有だが未対応(理由)
_B_PENDING = {
    "Montbell": "catalog型番がactiveタイトルに無い物多→名前(JP↔EN)マッチ要",
    "UNIQLO/UT": "catalog未完",
    "PSA card": "set codeマッチ可だがvariant煩雑(未対応)",
    "一番くじ": "catalog無(弾ごと)→AI/手動",
    "PORTER": "catalog無→AI/手動", "Tomica": "catalog無→AI/手動",
    "POP MART": "catalog無→AI/手動", "ブリキ玩具": "catalog無→AI/手動",
    "ガシャポン": "catalog無→AI/手動", "Sanrio": "catalog無→AI/手動",
    "Figure": "catalog無→AI/手動", "Reel": "catalog無→AI/手動",
}


def _f(v):
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return 0.0


def _open_w(path):
    base, ext = os.path.splitext(path)
    for i in range(0, 20):
        p = path if i == 0 else f"{base}_{i+1}{ext}"
        try:
            return open(p, "w", newline="", encoding="utf-8-sig"), p
        except PermissionError:
            continue
    raise PermissionError(f"書込先がすべてロック中: {path}")


def vein_of(title):
    t = (title or "").lower()
    if "g-shock" in t or "casio" in t:
        return "G-SHOCK"
    if "porter" in t or "tanker" in t:
        return "PORTER"
    if "montbell" in t or "mont-bell" in t:
        return "Montbell"
    if "psa 10" in t or "psa10" in t:
        return "PSA card"
    if "ichiban" in t:
        return "一番くじ"
    if "pop mart" in t or "popmart" in t:
        return "POP MART"
    if "tomica" in t:
        return "Tomica"
    if "tin " in t or "wind-up" in t or "pop pop" in t:
        return "ブリキ玩具"
    if "gashapon" in t or "gacha" in t or "capsule" in t:
        return "ガシャポン"
    if "reel" in t or "shimano" in t or "daiwa" in t:
        return "Reel"
    if any(k in t for k in ("sanrio", "kuromi", "hello kitty", "cinnamoroll", "pochacco", "my melody")):
        return "Sanrio"
    if "figuarts" in t or "figurizma" in t or "figure" in t or "statue" in t:
        return "Figure"
    if "uniqlo" in t or " ut " in t or t.startswith("ut ") or "t-shirt" in t or "airism" in t:
        return "UNIQLO/UT"
    return "other"


def series_of(s):
    """型番から系統prefix。'DW-6900UMS-1JF' → 'DW-6900' / 'GA-2100SB-1AJF' → 'GA-2100'。"""
    m = re.search(r"\b([A-Z]{2,4})-?(\d{3,4})", s or "")
    return f"{m.group(1)}-{m.group(2)}" if m else None


def mercari_url(kw):
    return "https://jp.mercari.com/search?keyword=" + urllib.parse.quote(kw) + "&status=on_sale"


# ---- facet 分解用の語彙 (需要を サブ系統/タイプ/ライン/サイズ/色 で割る。advisory用途) ----
_FRANCHISE = ["One Piece", "Pokemon", "Pok mon", "Dragon Ball", "Yu-Gi-Oh", "Yugioh", "Gundam",
              "Weiss", "Digimon", "Demon Slayer", "Jujutsu", "Naruto", "Evangelion", "KAWS",
              "Kenshi Yonezu", "Mamoru Hosoda", "Mario", "Hello Kitty", "Peanuts", "Chainsaw",
              "Hatsune Miku", "Mickey", "Snoopy", "Sanrio"]
_CHARS = {
    "One Piece": ["Luffy", "Zoro", "Nami", "Nico Robin", "Robin", "Sanji", "Chopper", "Yamato",
                  "Uta", "Shanks", "Ace", "Law", "Kid", "Boa", "Nico"],
    "Pokemon": ["Pikachu", "Eevee", "Charizard", "Umbreon", "Mewtwo", "Mew", "Lugia", "Rayquaza",
                "Gengar", "Snorlax", "Greninja", "Slowpoke", "Sylveon", "Glaceon"],
    "Dragon Ball": ["Goku", "Vegeta", "Gohan", "Frieza", "Broly", "Piccolo"],
}
_PORTER_TYPE = ["2Way", "2-Way", "2-Wege", "Shoulder", "Tote", "Waist", "Body", "Briefcase",
                "Helmet", "Backpack", "Wallet", "Boston", "Daypack", "Pouch"]
_MONTBELL_LINE = ["Wind Blast", "Versalite", "Thunder Pass", "Storm Cruiser", "EX Light", "Plasma",
                  "Permafrost", "Tachyon", "Rain Trekker", "Peak Shell", "Cosmic", "Torrent Flyer",
                  "Light Shell", "Rain Dancer", "Tensilite", "Mountain Parka"]
_SANRIO_CHAR = ["Kuromi", "Pochacco", "Cinnamoroll", "My Melody", "Hello Kitty", "Pompompurin",
                "Keroppi", "Badtz", "Tuxedosam"]
_REEL_BRAND = ["Shimano", "Daiwa", "Abu", "Stradic", "Stella", "Vanford", "Twin Power"]
_COLORS = ["Black", "White", "Red", "Blue", "Green", "Yellow", "Navy", "Gray", "Grey", "Pink",
           "Purple", "Orange", "Brown", "Olive", "Beige", "Gold", "Silver", "Khaki"]


# 色語を含むが「商品の色」ではない固有名詞 (フランチャイズ/キャラ)。color_of の前に除去。
_COLOR_NOISE = ["Blue Lock", "Blue Period", "Black Clover", "Black Butler", "Black Lagoon",
                "Red Hair", "Red-Haired", "Red Comet", "White Album", "Green Ranger",
                "Pink Panther", "Orange Range", "Golden Kamuy", "Silver Fang", "Blue Exorcist"]


def _first(t, kws):
    for k in kws:
        if k.lower() in t:
            return k
    return None


def color_of(title):
    # フランチャイズ名の色語 (Blue Lock 等) を除去してから、タイトル中で最初に出る色を採る。
    t = title
    for ph in _COLOR_NOISE:
        t = re.sub(re.escape(ph), " ", t, flags=re.I)
    best, pos = None, None
    for c in _COLORS:
        m = re.search(r"\b" + c + r"\b", t, re.I)
        if m and (pos is None or m.start() < pos):
            pos, best = m.start(), ("Gray" if c == "Grey" else c)
    return best


def size_of(title):
    # eBay バイヤーが検索するのは US サイズ。"US L (JP XL)" で JP(XL)を拾わないよう US 優先。
    m = re.search(r"\bUS\s*(?:Size\s*)?\(?\s*(XXS|XS|3XL|2XL|XXL|XL|S|M|L)\b", title, re.I)
    if m:
        return m.group(1).upper()
    # US 表記が無い (Montbell 旧型/PORTER 等) → 単独サイズ語。多文字を先に評価。
    m = re.search(r"\b(3XL|2XL|XXL|XL|XXS|XS)\b", title)
    if m:
        return m.group(1).upper()
    m = re.search(r"\b(?:Size|size)\s*\(?\s*(S|M|L)\b", title)
    return m.group(1).upper() if m else None


def facets(vein, title):
    """vein 別に title を facet 分解 → [(観点, 値, mercari種), ...]。mercari種が None なら検索URL無し。"""
    t = title.lower()
    out = []
    if vein == "PSA card":
        fr = _first(t, _FRANCHISE)
        sub = fr or "?"
        if fr in _CHARS:
            ch = _first(t, _CHARS[fr])
            if ch:
                sub = f"{fr} {ch}"
        out.append(("サブ", f"PSA {sub}", f"PSA10 {sub}"))
    elif vein == "UNIQLO/UT":
        out.append(("サブ", "UT " + (_first(t, _FRANCHISE) or "他"), "UNIQLO UT " + (_first(t, _FRANCHISE) or "")))
        sz = size_of(title)
        if sz:
            out.append(("サイズ", f"US {sz}", None))
        col = color_of(title)
        if col:
            out.append(("色", col, None))
    elif vein == "PORTER":
        typ = _first(t, _PORTER_TYPE) or "他"
        out.append(("タイプ", f"PORTER {typ}", f"PORTER タンカー {typ}"))
        col = color_of(title)
        if col:
            out.append(("色", col, None))
    elif vein == "Montbell":
        ln = _first(t, _MONTBELL_LINE) or "他"
        out.append(("ライン", f"Montbell {ln}", f"モンベル {ln}"))
        sz = size_of(title)
        if sz:
            out.append(("サイズ", f"US {sz}", None))
        col = color_of(title)
        if col:
            out.append(("色", col, None))
    elif vein == "一番くじ":
        fr = _first(t, _FRANCHISE) or "他"
        out.append(("サブ", f"一番くじ {fr}", f"一番くじ {fr}"))
    elif vein == "Sanrio":
        ch = _first(t, _SANRIO_CHAR) or "他"
        out.append(("サブ", f"Sanrio {ch}", ch))
    elif vein == "Figure":
        fr = _first(t, _FRANCHISE) or "他"
        out.append(("サブ", f"Figure {fr}", fr))
    elif vein == "Reel":
        br = _first(t, _REEL_BRAND) or "他"
        out.append(("サブ", f"Reel {br}", br))
    return out


def load_orders():
    out, seen = [], set()
    # ★2026-08-25: レポートは日付フォルダに入れて溜める運用。直下しか見ていないと
    #   1件も拾えない (ファネルの鮮度表示が更新されなかったのと同じ原因)。
    for p in sorted(glob.glob(os.path.join(REPORTS_DIR, "**", "*orders*.csv"),
                              recursive=True)):
        rows = list(csv.reader(open(p, encoding="utf-8-sig", errors="replace")))
        if len(rows) < 2:
            continue
        hdr = rows[1]
        for r in rows[2:]:
            if len(r) < 30 or not r[0].strip():
                continue
            rec = {hdr[j]: (r[j] if j < len(r) else "") for j in range(len(hdr))}
            on = (rec.get("Order Number") or "").strip()
            if on and on in seen:
                continue
            if on:
                seen.add(on)
            out.append(rec)
    return out


def load_funnel():
    fs = glob.glob(os.path.join(FUNNEL_DIR, "funnel_*.csv"))
    if not fs:
        sys.exit("funnel_*.csv がありません。先に『ファネル分析』を実行してください。")
    rows = list(csv.DictReader(open(max(fs, key=os.path.getmtime), encoding="utf-8")))
    prod = {}
    for r in rows:
        k = (r.get("title") or "").strip()
        if not k:
            continue
        p = prod.setdefault(k.lower(), {"title": k, "sold": 0.0, "watch": 0.0, "impr": 0.0})
        p["sold"] += _f(r.get("sold_qty")) + _f(r.get("sales90"))
        p["watch"] += _f(r.get("watch"))
        p["impr"] += _f(r.get("impr"))
    return list(prod.values())


def load_unlisted_gshock():
    """casio_finder の未出品catalog (catalog − active) を読む。"""
    fs = glob.glob(os.path.join(CASIO_UNLISTED_DIR, "unlisted_from_catalog_*.csv"))
    if not fs:
        return None, []
    p = max(fs, key=os.path.getmtime)
    rows = list(csv.DictReader(open(p, encoding="utf-8-sig", errors="replace")))
    return p, [r.get("product_id", "").strip() for r in rows if r.get("product_id", "").strip()]


def demand_score(p):
    return p["sold"] * 100 + p["watch"] * 8 + p["impr"] * 0.05


def main():
    products = load_funnel()
    orders = load_orders()

    # vein別 AOV ($文脈)
    vrev = defaultdict(lambda: {"n": 0, "rev": 0.0})
    for o in orders:
        t = o.get("Item Title", "")
        if t.strip():
            d = vrev[vein_of(t)]
            d["n"] += 1
            d["rev"] += _f(o.get("Sold For"))

    def aov(v):
        d = vrev.get(v)
        return d["rev"] / max(d["n"], 1) if d and d["n"] else 0.0

    # vein別 需要、G-SHOCK は系統別需要も、他 vein は facet(サブ/タイプ/ライン/サイズ/色)分解
    vein_dem = defaultdict(lambda: {"score": 0.0, "sold": 0.0, "watch": 0.0})
    gs_series = defaultdict(lambda: {"score": 0.0, "sold": 0.0, "watch": 0.0})
    # facet[vein][dim][value] = {score, sold, watch, seed}
    facet = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {"score": 0.0, "sold": 0.0, "watch": 0.0, "seed": None})))
    for p in products:
        v = vein_of(p["title"])
        sc = demand_score(p)
        vein_dem[v]["score"] += sc
        vein_dem[v]["sold"] += p["sold"]
        vein_dem[v]["watch"] += p["watch"]
        if sc <= 0:
            continue
        if v == "G-SHOCK":
            s = series_of(p["title"])
            if s:
                gs_series[s]["score"] += sc
                gs_series[s]["sold"] += p["sold"]
                gs_series[s]["watch"] += p["watch"]
        else:
            for dim, val, seed in facets(v, p["title"]):
                fd = facet[v][dim][val]
                fd["score"] += sc
                fd["sold"] += p["sold"]
                fd["watch"] += p["watch"]
                if seed:
                    fd["seed"] = seed

    # G-SHOCK B候補 = 未出品catalog × 実証系統(需要>0)
    upath, unlisted = load_unlisted_gshock()
    proven = {s for s, d in gs_series.items() if d["score"] > 0}
    gs_candidates = defaultdict(list)  # series -> [model_id]
    for mid in unlisted:
        s = series_of(mid)
        if s and s in proven:
            gs_candidates[s].append(mid)
    # series を需要順
    series_ranked = sorted(gs_candidates.keys(), key=lambda s: -gs_series[s]["score"])

    # ---- スプシ「需要・新規強化」タブに集約 (デスクトップCSV廃止 2026-06-07) ----
    out_rows = [["種別", "系統", "観点", "値(コピペ検索)", "需要スコア", "実売",
                 "watch", "系統AOV", "仕入適性", "メルカリ検索URL", "備考"]]
    # G-SHOCK 未出品候補 (deterministic = 実在の未出品型番)
    a = aov("G-SHOCK")
    for s in series_ranked:
        d = gs_series[s]
        for mid in sorted(gs_candidates[s]):
            out_rows.append(["新規候補(B)", f"G-SHOCK {s}", "未出品型番", f"G-SHOCK {mid}",
                             f"{d['score']:.0f}", int(d["sold"]), int(d["watch"]), f"${a:.0f}", "◎",
                             mercari_url(mid), "catalogにあり未出品=出せば売れそう"])
    # 他の実証 vein = facet 別 需要分解 (どのサブ/サイズ/色に需要があるか)
    for v, d in sorted(vein_dem.items(), key=lambda kv: -kv[1]["score"]):
        if v in ("other", "G-SHOCK") or d["score"] <= 0 or v not in facet:
            continue
        av = aov(v)
        for dim in ("サブ", "タイプ", "ライン", "サイズ", "色"):
            if dim not in facet[v]:
                continue
            top = sorted(facet[v][dim].items(), key=lambda x: -x[1]["score"])[:6]
            for val, fd in top:
                url = mercari_url(fd["seed"]) if fd["seed"] else ""
                out_rows.append(["需要分解", v, dim, val, f"{fd['score']:.0f}", int(fd["sold"]),
                                 int(fd["watch"]), f"${av:.0f}", _FEAS_MARK.get(v, "?"), url,
                                 _B_PENDING.get(v, "")])
    try:
        from sheet_io import write_rows_to_tab, MAINT_URL
        write_rows_to_tab("需要・新規強化", out_rows)
        print(f"📈 「需要・新規強化」タブ更新: {len(out_rows)-1}件 → {MAINT_URL}")
    except Exception as _e:
        print(f"⚠ 「需要・新規強化」タブ更新失敗: {type(_e).__name__}: {_e}")

    # ---- コンソール ----
    ncand = sum(len(v) for v in gs_candidates.values())
    print(f"需要: funnel {len(products)}商品 / orders {len(orders)}件")
    print(f"\n★ G-SHOCK 新規候補(B) = 実証系統 × 未出品 = {ncand}件")
    if upath:
        print(f"  (未出品母集団: {os.path.basename(upath)} = catalog − active)")
    print(f"  {'系統':<10}{'未出品数':>6}{'系統需要':>8}{'実売':>5}{'watch':>6}")
    for s in series_ranked:
        d = gs_series[s]
        print(f"  {s:<10}{len(gs_candidates[s]):>6}{d['score']:>8.0f}{int(d['sold']):>5}{int(d['watch']):>6}")
    print(f"\n  ▼ 上位系統の未出品型番(例)")
    for s in series_ranked[:6]:
        print(f"    {s} ({len(gs_candidates[s])}件): " + ", ".join(sorted(gs_candidates[s])[:6]))
    print(f"\n他の実証 vein = facet 別 需要分解 (どのサブ/ライン/サイズ/色に需要があるか):")
    for v, d in sorted(vein_dem.items(), key=lambda kv: -kv[1]["score"]):
        if v in ("other", "G-SHOCK") or d["score"] <= 0 or v not in facet:
            continue
        print(f"  ▼ {v} (需要{d['score']:.0f}/実売{int(d['sold'])}/W{int(d['watch'])})")
        for dim in ("サブ", "タイプ", "ライン", "サイズ", "色"):
            if dim not in facet[v]:
                continue
            top = sorted(facet[v][dim].items(), key=lambda x: -x[1]["score"])[:5]
            print(f"      {dim}: " + " / ".join(f"{val}({d2['score']:.0f})" for val, d2 in top))
    # 出力はスプシ「需要・新規強化」タブ (上で更新済)
    print("▶ B = 実証系統で catalog にあるが未出品 = 出せば売れそうな新規候補 (G-SHOCK)。")
    print("▶ 他 vein は facet 別需要分解 (サブ/ライン/サイズ/色) → その属性で仕入れ先を探す。")
    if not upath:
        print("⚠ 未出品catalogが無い。先に『G-SHOCK 未出品モデル(catalog)』ボタンを実行してください。")


if __name__ == "__main__":
    main()
