#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""需要・新規強化リスト — 実売(orders)ベースで「次に何を出すか」を出す。

【設計思想】(2026-06-04 全面刷新)
旧版は自店 listing の view/watch を並べるだけ＝既に出してる物の再掲で「新規強化」にならなかった。
新版は **orders レポート(=実際に売れた取引・去年+今年の全ファイル)** を真実データとし、
売れた商品を vein(系統) ごとに集約して「コピペ検索キー＋実売実績＋メルカリURL」で出す。

種別:
  - 伸ばす(実証) : 実売した主要系統。同系の未出品を出す本命 (高単価優先)
  - 入る(未開拓) : 体系化してないが実売が出た untapped (Tomica/POP MART/ブリキ/ガシャポン等)
  - 避ける(薄利) : AOV が低く量を追っても薄利な系統 (UT/Sanrio 等) ← 注意喚起

入力: C:/dev/iMak_data/seller_hub/reports/*orders*.csv (全ファイル結合・Order Number 重複除去)
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


def main():
    orders = load_orders()
    if not orders:
        sys.exit(f"orders レポートが {REPORTS_DIR} にありません。Seller Hub から DL してください。")

    # vein -> {n, rev, keys{key:{n,rev,title}}}
    veins = defaultdict(lambda: {"n": 0, "rev": 0.0, "keys": defaultdict(lambda: {"n": 0, "rev": 0.0, "title": ""})})
    for o in orders:
        title = o.get("Item Title", "")
        if not title.strip():
            continue
        v = vein_of(title)
        sf = _f(o.get("Sold For"))
        d = veins[v]
        d["n"] += 1
        d["rev"] += sf
        k = search_key(title, v)
        kd = d["keys"][k]
        kd["n"] += 1
        kd["rev"] += sf
        kd["title"] = title

    # vein を 件数優先で並べ、種別判定
    def kind(v, d):
        if v in _UNTAPPED:
            return "入る(未開拓)"
        aov = d["rev"] / max(d["n"], 1)
        if aov < TH_LOW_AOV:
            return "避ける(薄利)"
        return "伸ばす(実証)"

    ordered = sorted(veins.items(), key=lambda kv: -kv[1]["n"])

    # ---- CSV (1行=1候補) ----
    f, path = _open_w(os.path.join(DESK, f"新規強化リスト_{datetime.date.today():%Y%m%d}.csv"))
    with f:
        w = csv.writer(f)
        w.writerow(["種別", "系統", "コピペ検索キー", "実売件数", "売上", "系統AOV", "仕入適性",
                    "pipeline", "メルカリ検索URL"])
        for v, d in ordered:
            if v == "other":
                continue
            k = kind(v, d)
            mark, pipe = _FEAS.get(v, ("?", "-"))
            aov = d["rev"] / max(d["n"], 1)
            if k == "避ける(薄利)":
                # 薄利は注意喚起の1行だけ (個別キーは出さない)
                w.writerow([k, v, "(量を追わない・薄利)", d["n"], f"${d['rev']:.0f}", f"${aov:.0f}", mark, pipe, ""])
                continue
            # 伸ばす / 入る = 売れたキーを実売件数→売上で
            for key, kd in sorted(d["keys"].items(), key=lambda x: (-x[1]["n"], -x[1]["rev"])):
                w.writerow([k, v, key, kd["n"], f"${kd['rev']:.0f}", f"${aov:.0f}", mark, pipe,
                            mercari_url(key, v)])

    # ---- コンソール要約 ----
    print(f"実売取引: {len(orders)}件 (orders 全ファイル結合) → vein {len(veins)} 系統")
    print(f"\n{'種別':<12}{'系統':<14}{'件数':>4}{'売上':>8}{'AOV':>6}  適性")
    for v, d in ordered:
        if v == "other":
            continue
        aov = d["rev"] / max(d["n"], 1)
        mark, _ = _FEAS.get(v, ("?", "-"))
        print(f"{kind(v,d):<12}{v:<14}{d['n']:>4}{'$'+format(d['rev'],'.0f'):>8}{'$'+format(aov,'.0f'):>6}  {mark}")
    print(f"\n▼ 伸ばす/入る の具体候補 (コピペ検索キー・実売順)")
    for v, d in ordered:
        if v == "other" or kind(v, d) == "避ける(薄利)":
            continue
        top = sorted(d["keys"].items(), key=lambda x: (-x[1]["n"], -x[1]["rev"]))[:4]
        print(f"  ▼ {v} [{kind(v,d)}]")
        for key, kd in top:
            print(f"      {key:<38} 実売{kd['n']}/{'$'+format(kd['rev'],'.0f')}")
    print(f"\nCSV出力: {path}")
    print("▶ 伸ばす=実証系統の未出品を出す / 入る=未開拓だが実売あり / 避ける=薄利で量を追わない")
    print("※ 売上の$0は DE/UK の外貨取引(未換算)。件数は正。")


if __name__ == "__main__":
    main()
