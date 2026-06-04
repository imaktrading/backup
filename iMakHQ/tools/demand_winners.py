#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""需要・新規強化リスト — 実売(orders)ベースで「次に何を出すか」を出す。

【設計思想】(2026-06-04 全面刷新)
需要は SOLD だけでなく **SOLD(実証) + WATCH(潜在) + impression(露出)** を合算して見る。
SOLD のみだと「売れてないが超 watch=潜在需要」(例 PORTER Tanker) を取りこぼす。

需要シグナル: funnel CSV (sold/watch/impr を 4サイト合算・商品単位) の合算スコア
  需要スコア = 実売*100 + watch*8 + impr*0.05   (信頼度: 実売 >> watch > impr)
$ 文脈      : orders レポート(去年+今年) から vein 別の売上/AOV を併用

種別:
  - 伸ばす(実証) : 需要シグナルが立つ主要系統。同系の未出品を出す本命
  - 入る(未開拓) : 体系化してないが需要が出た untapped (Tomica/POP MART/ブリキ/ガシャポン等)
  - 避ける(薄利) : AOV が低く量を追っても薄利な系統 ← 注意喚起

入力: funnel CSV (../funnel_output/funnel_*.csv = 先に『ファネル分析』を実行) + *orders*.csv
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
DESK = r"C:\Users\imax2\OneDrive\デスクトップ"

# AOV がこれ未満の系統 = 薄利。量を追わない (避ける)
TH_LOW_AOV = 30

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-]*")
_CARD_RE = re.compile(r"\b([A-Z]{1,3}\d{2}-\d{2,3}|P-\d{2,4}|EB\d{2}-\d{2,3}|LV-N?\d{2,4}[a-z]?)\b")
_MODEL_RE = re.compile(r"\b([A-Z]{2,4}-?[A-Z]?\d{2,4}[A-Z]{0,4}(?:-\d{1,2}[A-Z]{0,4})?)\b")
_STOP = {"the", "and", "with", "for", "of", "a", "an", "in", "by", "to", "new", "used", "japan",
         "japanese", "pre-owned", "pre", "owned", "mens", "men", "women", "womens", "size",
         "us", "jp", "digital", "watch", "card", "game", "tcg", "psa", "10", "gem", "mt", "vol",
         "set", "full", "limited", "edition", "casio", "uniqlo", "ut", "sanrio", "yoshida",
         "porter", "montbell", "tomica", "bag", "shirt", "t-shirt", "plush", "figure"}


def _f(v):
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return 0.0


def _open_w(path):
    """書込オープン。Excel等でロック中なら _2,_3... に退避して落ちない。"""
    base, ext = os.path.splitext(path)
    for i in range(0, 20):
        p = path if i == 0 else f"{base}_{i+1}{ext}"
        try:
            return open(p, "w", newline="", encoding="utf-8-sig"), p
        except PermissionError:
            continue
    raise PermissionError(f"書込先がすべてロック中: {path}")


def load_orders():
    """*orders*.csv 全ファイル(去年+今年)を結合。row0空/row1ヘッダ/row2+データ。Order Number で重複除去。"""
    out, seen = [], set()
    for p in sorted(glob.glob(os.path.join(REPORTS_DIR, "*orders*.csv"))):
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


# vein(系統) 判定 = 仕入れ単位。untapped も明示的に拾う。
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
    if "tin " in t or "wind-up" in t or "pop pop" in t or "buriki" in t:
        return "ブリキ玩具"
    if "gashapon" in t or "gacha" in t or "capsule" in t:
        return "ガシャポン"
    if "onitsuka" in t:
        return "Onitsuka Tiger"
    if "anello" in t:
        return "Anello"
    if "reel" in t or "shimano" in t or "daiwa" in t:
        return "Reel"
    if any(k in t for k in ("sanrio", "kuromi", "hello kitty", "cinnamoroll", "pochacco", "my melody")):
        return "Sanrio"
    if "figuarts" in t or "figurizma" in t or "figure" in t or "statue" in t:
        return "Figure"
    if "uniqlo" in t or " ut " in t or t.startswith("ut ") or "t-shirt" in t or "airism" in t or "pufftech" in t:
        return "UNIQLO/UT"
    return "other"


# untapped = 体系化してない (= 新規参入の空白)
_UNTAPPED = {"POP MART", "Tomica", "ブリキ玩具", "ガシャポン", "Onitsuka Tiger", "Anello"}

# 仕入れ適性 (近しい商品をタイムリーに調達できるか) と pipeline
_FEAS = {
    "G-SHOCK": ("◎", "gshock_to_csv"), "Montbell": ("◎", "montbell_listing"),
    "UNIQLO/UT": ("◎", "tshirt_listing"), "PORTER": ("△", "-"), "PSA card": ("△", "-"),
    "一番くじ": ("△", "ichibankuji_to_csv"), "Sanrio": ("◎", "メルカリ"), "Figure": ("△", "メルカリ"),
    "Reel": ("△", "daiwa_jp/shimano_jp"), "POP MART": ("◎", "メルカリ"), "Tomica": ("◎", "メルカリ"),
    "ブリキ玩具": ("◎", "メルカリ"), "ガシャポン": ("◎", "メルカリ"), "Onitsuka Tiger": ("△", "メルカリ"),
    "Anello": ("△", "メルカリ"), "other": ("?", "-"),
}

# メルカリ検索を Japanese 寄りにできる vein はシード語を持つ
_MERCARI_SEED = {"ブリキ玩具": "ブリキ おもちゃ 昭和", "ガシャポン": "ガシャポン", "一番くじ": "一番くじ"}


def search_key(title, vein):
    """コピペ検索キー = vein + 型番/カード番号、無ければ vein + タイトル識別語3つ。"""
    pre = re.sub(r"[/×]", " ", vein).strip()
    pre_toks = pre.split()
    mc = _CARD_RE.search(title) or _MODEL_RE.search(title)
    if mc:
        code = mc.group(1)
        kept = [t for t in pre_toks if not code.upper().startswith(t.upper())]
        return " ".join(kept + [code]).strip()
    pre_low = {t.lower() for t in pre_toks}
    toks, seen = [], set()
    for tok in _TOKEN_RE.findall(title):
        low = tok.lower()
        if low in seen or low in _STOP or low in pre_low or low.isdigit() or len(low) < 2:
            continue
        seen.add(low)
        toks.append(tok)
        if len(toks) >= 3:
            break
    return " ".join(pre_toks + toks).strip()


def mercari_url(key, vein):
    seed = _MERCARI_SEED.get(vein)
    kw = seed if seed else key
    return "https://jp.mercari.com/search?keyword=" + urllib.parse.quote(kw) + "&status=on_sale"


def load_funnel():
    """funnel CSV (sold/watch/impr を持つ商品母集団)。商品単位(title)に 4サイト合算。"""
    fs = glob.glob(os.path.join(FUNNEL_DIR, "funnel_*.csv"))
    if not fs:
        sys.exit("funnel_*.csv がありません。先に『ファネル分析』を実行してください。")
    rows = list(csv.DictReader(open(max(fs, key=os.path.getmtime), encoding="utf-8")))
    prod = {}
    for r in rows:
        k = (r.get("title") or "").strip()
        if not k:
            continue
        p = prod.setdefault(k.lower(), {"title": k, "sold": 0.0, "watch": 0.0, "impr": 0.0, "price": 0.0})
        p["sold"] += _f(r.get("sold_qty")) + _f(r.get("sales90"))
        p["watch"] += _f(r.get("watch"))
        p["impr"] += _f(r.get("impr"))
        p["price"] = _f(r.get("price")) or p["price"]
    return list(prod.values())


def demand_score(p):
    """需要 = 実売*100 + watch*8 + impr*0.05 (信頼度: 実売 >> watch > impr)。"""
    return p["sold"] * 100 + p["watch"] * 8 + p["impr"] * 0.05


def main():
    products = load_funnel()           # 需要シグナル源 (sold+watch+impr)
    orders = load_orders()             # $ 文脈 (vein別 売上/AOV)

    # vein別の $ 文脈 (orders)
    vrev = defaultdict(lambda: {"n": 0, "rev": 0.0})
    for o in orders:
        t = o.get("Item Title", "")
        if not t.strip():
            continue
        d = vrev[vein_of(t)]
        d["n"] += 1
        d["rev"] += _f(o.get("Sold For"))

    def aov(v):
        d = vrev.get(v)
        return d["rev"] / max(d["n"], 1) if d and d["n"] else 0.0

    # 商品を vein に束ね、需要スコアで評価
    veins = defaultdict(list)
    for p in products:
        p["score"] = demand_score(p)
        p["vein"] = vein_of(p["title"])
        if p["score"] > 0:
            veins[p["vein"]].append(p)

    def kind(v):
        if v in _UNTAPPED:
            return "入る(未開拓)"
        if 0 < aov(v) < TH_LOW_AOV:
            return "避ける(薄利)"
        return "伸ばす(実証)"

    # vein を 合計需要スコアで並べ
    ordered = sorted(veins.items(), key=lambda kv: -sum(p["score"] for p in kv[1]))

    # ---- CSV (1行=1候補) ----
    f, path = _open_w(os.path.join(DESK, f"新規強化リスト_{datetime.date.today():%Y%m%d}.csv"))
    with f:
        w = csv.writer(f)
        w.writerow(["種別", "系統", "コピペ検索キー", "需要スコア", "実売", "watch", "impr",
                    "系統AOV", "仕入適性", "pipeline", "メルカリ検索URL"])
        for v, ps in ordered:
            if v == "other":
                continue
            k = kind(v)
            mark, pipe = _FEAS.get(v, ("?", "-"))
            a = aov(v)
            if k == "避ける(薄利)":
                tot = sum(p["score"] for p in ps)
                w.writerow([k, v, "(量を追わない・薄利)", f"{tot:.0f}", int(sum(p['sold'] for p in ps)),
                            int(sum(p['watch'] for p in ps)), int(sum(p['impr'] for p in ps)),
                            f"${a:.0f}", mark, pipe, ""])
                continue
            # 需要スコア順に商品(=コピペ検索キー)を出す。同一キーは集約
            agg = defaultdict(lambda: {"score": 0.0, "sold": 0.0, "watch": 0.0, "impr": 0.0})
            for p in ps:
                key = search_key(p["title"], v)
                ad = agg[key]
                ad["score"] += p["score"]; ad["sold"] += p["sold"]
                ad["watch"] += p["watch"]; ad["impr"] += p["impr"]
            for key, ad in sorted(agg.items(), key=lambda x: -x[1]["score"]):
                w.writerow([k, v, key, f"{ad['score']:.0f}", int(ad['sold']), int(ad['watch']),
                            int(ad['impr']), f"${a:.0f}", mark, pipe, mercari_url(key, v)])

    # ---- コンソール要約 ----
    print(f"需要シグナル: funnel {len(products)}商品 / 実売文脈: orders {len(orders)}件")
    print(f"\n{'種別':<12}{'系統':<14}{'需要計':>7}{'実売':>5}{'watch':>6}{'AOV':>6}  適性")
    for v, ps in ordered:
        if v == "other":
            continue
        tot = sum(p["score"] for p in ps)
        print(f"{kind(v):<12}{v:<14}{tot:>7.0f}{int(sum(p['sold'] for p in ps)):>5}"
              f"{int(sum(p['watch'] for p in ps)):>6}{'$'+format(aov(v),'.0f'):>6}  {_FEAS.get(v,('?',''))[0]}")
    print(f"\n▼ 伸ばす/入る の具体候補 (需要スコア順 = 実売+watch+impr 合算)")
    for v, ps in ordered:
        if v == "other" or kind(v) == "避ける(薄利)":
            continue
        agg = defaultdict(lambda: {"score": 0.0, "sold": 0.0, "watch": 0.0})
        for p in ps:
            key = search_key(p["title"], v)
            agg[key]["score"] += p["score"]; agg[key]["sold"] += p["sold"]; agg[key]["watch"] += p["watch"]
        top = sorted(agg.items(), key=lambda x: -x[1]["score"])[:4]
        print(f"  ▼ {v} [{kind(v)}]")
        for key, ad in top:
            print(f"      {key:<38} 需要{ad['score']:.0f}(実売{int(ad['sold'])}/W{int(ad['watch'])})")
    print(f"\nCSV出力: {path}")
    print("▶ 需要スコア = 実売*100 + watch*8 + impr*0.05。SOLD だけでなく潜在(watch)も込み。")
    print("▶ 伸ばす=実証系統の未出品 / 入る=未開拓だが需要あり / 避ける=薄利で量を追わない")


if __name__ == "__main__":
    main()
