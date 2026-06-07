#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""④ タイトル改修対象 (NO_CLICK ∩ watcher有) を手 revise 用に CSV 出力。

NO_CLICK = 表示はされてるが CTR 低い = タイトル/サムネが弱い。
うち **watcher有** は取下再出品すると watcher を失う → in-place 編集(eBay Revise)が必須。
だが in-place の自動配線は リバイスくん側で未稼働なので、当面は本リストで **手 revise**。

出力に「どれが対象か」+「なぜ弱いか(語数/写真数)」+ eBay URL を載せ、1件ずつ開いて直せるように。
改修案の自動生成はしない (推測KW注入=誤タイトルのリスク。語を盛るのは人が判断)。

入力: ../funnel_output/funnel_*.csv (NO_CLICK flag + watch + keywords + photos + ctr)
出力: デスクトップ タイトル改修対象_YYYYMMDD.csv (watcher有→価格 の順)
"""
import csv
import datetime
import glob
import importlib.util
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
FUNNEL_DIR = os.path.normpath(os.path.join(_HERE, "..", "funnel_output"))
DESK = r"C:\Users\imax2\OneDrive\デスクトップ"

_spec = importlib.util.spec_from_file_location("demand_winners", os.path.join(_HERE, "demand_winners.py"))
dw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dw)

MIN_KEYWORDS = 10   # LQR 推奨水準の目安。これ未満=語数不足
MIN_PHOTOS = 8      # eBay 推奨枚数の目安


def _f(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0


def fix_hint(keywords, photos):
    """なぜ弱いか → 何を直すかの短いメモ (語数/写真の不足を優先指摘)。"""
    hints = []
    if 0 < keywords < MIN_KEYWORDS:
        hints.append(f"タイトル語数{int(keywords)}=少→上位検索語を前方に追加")
    if 0 < photos < MIN_PHOTOS:
        hints.append(f"写真{int(photos)}枚=少→追加")
    if not hints:
        hints.append("語順/サムネ見直し(impr有CTR低=見られたが押されてない)")
    return " / ".join(hints)


def select(rows):
    """NO_CLICK 全件を価格(利益額)降順。"""
    out = [r for r in rows if "NO_CLICK" in (r.get("flags") or "").split("|")]
    out.sort(key=lambda r: -_f(r.get("price")))
    return out


def fix_method(watch):
    """relist で watcher を失うか否かで対応を示す。"""
    return "in-place(watcher保持)" if watch > 0 else "relist可 or in-place"


def main():
    fs = glob.glob(os.path.join(FUNNEL_DIR, "funnel_*.csv"))
    if not fs:
        sys.exit("funnel_*.csv がありません。先に『📊 ファネル分析』を実行してください。")
    rows = list(csv.DictReader(open(max(fs, key=os.path.getmtime), encoding="utf-8")))
    targets = select(rows)
    n_all_noclick = sum(1 for r in rows if "NO_CLICK" in (r.get("flags") or "").split("|"))

    # スプシ「タイトル改修」タブに集約 (デスクトップCSV廃止 2026-06-07)
    out_rows = [["済", "系統", "商品名", "watch", "対応", "CTR", "語数", "写真",
                 "価格", "改修ヒント", "eBay URL"]]
    for r in targets:
        kw, ph = _f(r.get("keywords")), _f(r.get("photos"))
        watch = int(_f(r.get("watch")))
        ctr_disp = r.get("ctr_total") or r.get("ctr", "")   # 判定基盤(organic+PL累計)優先
        out_rows.append(["", dw.vein_of(r.get("title") or ""), r.get("title", ""),
                         watch, fix_method(watch), ctr_disp, int(kw) if kw else "",
                         int(ph) if ph else "", f"${_f(r.get('price')):.0f}",
                         fix_hint(kw, ph), r.get("ebay_url", "")])
    try:
        from sheet_io import write_rows_to_tab, MAINT_URL
        write_rows_to_tab("タイトル改修", out_rows)
        print(f"✏️ 「タイトル改修」タブ更新: {len(out_rows)-1}件 → {MAINT_URL}")
    except Exception as _e:
        print(f"⚠ 「タイトル改修」タブ更新失敗: {type(_e).__name__}: {_e}")

    n_w = sum(1 for r in targets if _f(r.get("watch")) > 0)
    print(f"タイトル改修対象 (NO_CLICK 全件) = {len(targets)}件 (価格高い順)")
    print(f"  対応の目安: watcher無 {len(targets)-n_w}件=取下再出品でも可(ブースト+再生成) / watcher有 {n_w}件=in-place推奨(watcher保持)")
    print("▶ relistで一括ブースト＋再生成 か、個別に in-place で考えたタイトルに直すか。watcher有はin-place推奨。")
    print("※ 本気のCTR改善は出品くんのタイトル生成改善(別PDCA)。本リストはその対象把握も兼ねる。")


if __name__ == "__main__":
    main()
