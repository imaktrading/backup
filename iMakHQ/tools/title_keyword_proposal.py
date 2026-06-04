#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""④ NO_SEARCH listing のタイトル改修案を生成 (iMakKeywords PDF 準拠)。

ルール (CLAUDE.md): タイトルは iMakKeywords PDF の上位検索語を最優先。推測で代替しない。
本ツールは各 NO_SEARCH listing について、該当カテゴリ PDF の上位語のうち
「商品に当てはまる高検索語」を抽出し、front-load した改修案を出す。
最終調整・実 revise は Revise worktree が担当 (本ツールは案の生成のみ)。

入力: funnel CSV (NO_SEARCH) + iMakKeywords PDF (pdftotext -layout)
出力: デスクトップ 04_タイトル改修案_YYYYMMDD.csv (現タイトル / 適用上位語 / 改修案 / 文字数)
"""
import csv
import datetime
import glob
import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DESK = r"C:\Users\imax2\OneDrive\デスクトップ"
KW_DIR = r"C:\Users\imax2\OneDrive\デスクトップ\iMak_workspace\iMakKeywords"
FUNNEL_CSV = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "funnel_output"))

# LQR category → iMakKeywords PDF
CAT_PDF = {
    "Wristwatches": "Jewelry_Watches_2026Q1.pdf",
    "Action Figures": "Collectibles_2026Q1.pdf",
    "Other Animation Merchandise": "Collectibles_2026Q1.pdf",
    "Figures & Statues": "Collectibles_2026Q1.pdf",
    "T-Shirts": "Clothing_Shoes_Accessories_2026Q1.pdf",
    "Coats, Jackets & Vests": "Clothing_Shoes_Accessories_2026Q1.pdf",
    "Women's Bags & Handbags": "Clothing_Shoes_Accessories_2026Q1.pdf",
}
# eBay タイトル上限
MAXLEN = 80
STOP = {"the", "a", "and", "for", "with", "in", "of", "japan", "japanese", "new", "men", "mens",
        "men's", "women", "size", "us", "jp"}


def parse_pdf_keywords(pdf_path, top=40):
    """PDF の "Rank Prev Diff keyword" 表から上位 top 件の keyword を順位付きで返す。"""
    try:
        txt = subprocess.run(["pdftotext", "-layout", pdf_path, "-"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace").stdout
    except FileNotFoundError:
        sys.exit("pdftotext が見つかりません (Git Bash 環境で実行してください)。")
    kws = []
    for line in txt.splitlines():
        m = re.match(r"^\s*(\d{1,3})\s+(?:\d{1,3}|NEW)\s+(?:-|\d{1,3}|NEW)\s+(.+?)\s*$", line)
        if m:
            kw = re.sub(r"\s{2,}.*$", "", m.group(2)).strip().lower()  # 末尾の Volume/GMV 列を除去
            kw = re.sub(r"[0-9,]+$", "", kw).strip()
            if kw and len(kw) > 2 and "my orders" not in kw:
                kws.append((int(m.group(1)), kw))
        if len(kws) >= top:
            break
    return kws


def applicable_keywords(title, kws):
    """商品に「真に当てはまる」高検索語のみ返す。

    精度原則 (CLAUDE.md): 虚偽キーワードは絶対NG。よって PDF 上位語のうち、
    その**全ての有意語が現タイトルに既出**のものだけ採用する (= 商品の真の属性の
    別表現/サブセット。新たな虚偽ブランド・キャラ名は足さない)。
    例: Kuromi 商品に "pokemon plush"/"hello kitty"、Casio に "rolex" は採用しない。
    """
    title_tokens = set(re.findall(r"[a-z0-9]+", title.lower()))
    out = []
    for rank, kw in kws:
        ktoks = [t for t in re.findall(r"[a-z0-9]+", kw) if t not in STOP]
        if not ktoks:
            continue
        if all(t in title_tokens for t in ktoks):  # 全有意語が既出 = 真に当てはまる
            phrase = " ".join(w.title() for w in kw.split())
            at_front = title.lower().startswith(kw.split()[0])
            out.append((rank, phrase, at_front))
    return out


def main():
    fcsv = max(glob.glob(os.path.join(FUNNEL_CSV, "funnel_*.csv")), key=os.path.getmtime)
    rows = [r for r in csv.DictReader(open(fcsv, encoding="utf-8")) if "NO_SEARCH" in (r.get("flags") or "").split("|")]
    pdf_cache = {}
    out = []
    for r in rows:
        cat = r.get("category", "")
        pdf = CAT_PDF.get(cat)
        if not pdf:
            continue
        if pdf not in pdf_cache:
            pdf_cache[pdf] = parse_pdf_keywords(os.path.join(KW_DIR, pdf))
        app = applicable_keywords(r["title"], pdf_cache[pdf])  # (rank, phrase, at_front)
        # front-load 推奨 = 真に当てはまる高検索語のうち、先頭に無い最上位のもの
        to_front = [ph for rk, ph, at_front in app if not at_front]
        demand_limited = (len(app) == 0)
        out.append({
            "category": cat, "price": r["price"],
            "current_title": r["title"], "len_cur": len(r["title"]),
            "true_applicable_kw": " / ".join(f"#{rk}:{ph}" for rk, ph, _ in app[:5]),
            "frontload_suggest": to_front[0] if to_front else "",
            "demand_limited": "YES" if demand_limited else "",
            "note": ("需要語なし=タイトル改修では救えない(低需要商品/新規出品の可能性。撤退or別軸検討)"
                     if demand_limited else "真の高検索語を先頭へ移動 (虚偽語は足さない)"),
            "ebay_url": r.get("ebay_url", ""),
        })

    path = os.path.join(DESK, f"04_タイトル改修案_{datetime.date.today():%Y%m%d}.csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)

    from collections import Counter
    cc = Counter(o["category"] for o in out)
    frontload = [o for o in out if o["frontload_suggest"]]
    limited = [o for o in out if o["demand_limited"]]
    print(f"NO_SEARCH 対象: {len(out)}件  カテゴリ別={dict(cc)}")
    print(f"真の高検索語を先頭へ移動で改善見込み: {len(frontload)}件")
    print(f"需要語なし=タイトルでは救えない(低需要/新規): {len(limited)}件")
    print("\n--- front-load 改善サンプル (虚偽語を足さず順序のみ) ---")
    for o in frontload[:10]:
        print(f"  [{o['category'][:12]}] 先頭へ→ {o['frontload_suggest']}  (該当語: {o['true_applicable_kw']})")
        print(f"    現: {o['current_title']}")
    print(f"\nCSV出力: {path}")


if __name__ == "__main__":
    main()
