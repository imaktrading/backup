"""gshock_revise_descriptions — 既存 live G-shock 出品の description を一括クリーン化する
FileExchange Revise CSV を生成する (2026-06-13・ユーザー依頼)。

背景: gshock_to_csv の旧 build_specs_html/trim_features バグで、過去にアップした
G-shock 出品の Description Specifications ブロックに **空欄項目の裸残り** と
**catalog 生 feature コード (alarms:_5 等)** が混入していた。generator は修正済 (新規は
クリーン) だが、既に live の出品は汚れたまま。本ツールでまとめて revise する。

方式 (fail-closed): eBay active listings レポート (ItemID + Title) を入力に、
  Title から型番抽出 → catalog ID-strict lookup → 修正済 build_description で
  **クリーンな description を再生成** → Revise CSV (Action=Revise, ItemID, *Description)。
  型番が catalog に confident に解決しない出品は **skip** (誤った内容で revise しない =
  出品の正確性原則)。Description 以外は一切変更しない (price/title/specs 不変)。

使い方:
  python gshock_revise_descriptions.py <active_listings_report.csv> [out.csv]
出力: revise CSV + skipped 一覧 (解決不能で未revise=要個別対応)。
"""
from __future__ import annotations
import csv
import os
import re
import sys
from datetime import datetime

sys.argv_backup = sys.argv
sys.stdout.reconfigure(encoding="utf-8")

_GSHOCK_DIR = r"C:/dev/iMak/iMakG-shock"
if _GSHOCK_DIR not in sys.path:
    sys.path.insert(0, _GSHOCK_DIR)

# gshock_to_csv は argparse を持つので暴発防止
_real_argv = sys.argv
sys.argv = ["gshock_to_csv.py"]
import gshock_to_csv as G  # noqa: E402
sys.argv = _real_argv

GSHOCK_TXT = os.path.join(_GSHOCK_DIR, "GSHOCK.txt")
ACTION_HDR = "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)"
OUT_DIR = r"C:/dev/iMak/iMakHQ/csv_output"


def _read_active(path):
    """eBay active listings レポートを読む (先頭 BOM 対応・列名 dict)。"""
    rows = list(csv.reader(open(path, encoding="utf-8-sig", errors="replace", newline="")))
    if not rows:
        return [], {}
    headers = {h.strip(): i for i, h in enumerate(rows[0])}
    return rows[1:], headers


def _is_gshock(title):
    return "g-shock" in title.lower() or "gshock" in title.lower()


def build_revise(report_path, out_path=None):
    if G._catalog_lookup is None:
        print("❌ catalog lookup 未ロード (C:/dev/iMak_catalog 不在?) — 中止")
        return 2
    base_html = open(GSHOCK_TXT, encoding="utf-8").read() if os.path.exists(GSHOCK_TXT) else None
    if not base_html:
        print(f"❌ GSHOCK.txt が読めない: {GSHOCK_TXT} — 中止")
        return 2

    data_rows, h = _read_active(report_path)
    def _hi(*names):
        for n in names:
            if n in h:
                return h[n]
        return None
    item_i = _hi("Item number", "ItemID", "Item ID")
    title_i = _hi("Title")
    site_i = _hi("Listing site")
    if item_i is None or title_i is None:
        print(f"❌ レポートに Item number / Title 列が無い: {list(h)[:8]}")
        return 2
    # Revise Action は SiteID=US。UK/AU/DE 等の他サイト出品は US Action で revise 不可なので
    # US サイトのみ対象 (site 列が無いレポートは全件=従来互換)。
    n_nonus = 0

    revise = []           # [ItemID, clean_desc]
    skipped = []          # (ItemID, title, reason)
    seen = set()
    n_gshock = 0
    for r in data_rows:
        if max(item_i, title_i) >= len(r):
            continue
        item_id = r[item_i].strip().strip('"')
        title = r[title_i].strip()
        if not _is_gshock(title):
            continue
        # US サイト出品のみ (Revise Action=SiteID=US のため)
        if site_i is not None and site_i < len(r) and r[site_i].strip().upper() not in ("US", ""):
            n_nonus += 1
            continue
        n_gshock += 1
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        model = G.extract_model_from_text(title)
        if not model:
            skipped.append((item_id, title, "型番抽出不能"))
            continue
        try:
            rec = G._catalog_lookup(model)
        except Exception as e:
            rec = None
            skipped.append((item_id, title, f"lookup例外:{type(e).__name__}"))
            continue
        if not rec:
            skipped.append((item_id, title, f"catalog未解決({model})"))
            continue
        data = G._catalog_record_to_scrape_dict(rec, model)
        desc = G.build_description(data, base_html)
        if not desc:
            skipped.append((item_id, title, "description生成失敗"))
            continue
        revise.append([item_id, desc])

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if out_path is None:
        out_path = os.path.join(OUT_DIR, f"gshock_revise_desc_{ts}.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        w.writerow([ACTION_HDR, "ItemID", "*Description"])
        for item_id, desc in revise:
            w.writerow(["Revise", item_id, desc])

    skip_path = out_path.replace(".csv", "_skipped.csv")
    with open(skip_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        w.writerow(["ItemID", "Title", "理由"])
        for row in skipped:
            w.writerow(list(row))

    print("=" * 64)
    print(f"G-shock description 一括 Revise CSV 生成")
    print(f"  入力レポート : {os.path.basename(report_path)}")
    print(f"  G-shock US出品: {n_gshock} 件 (他サイト除外 {n_nonus} 件=UK/AU/DE 等)")
    print(f"  ✅ revise 行 : {len(revise)} (クリーン description 再生成)")
    print(f"  ⏭️ skip      : {len(skipped)} (型番未解決=誤revise回避でfail-closed)")
    print(f"  出力CSV      : {out_path}")
    print(f"  skip一覧      : {skip_path}")
    print("=" * 64)
    # skip 理由の内訳
    from collections import Counter
    reasons = Counter(s[2].split("(")[0] for s in skipped)
    for reason, c in reasons.most_common():
        print(f"    skip理由: {reason} = {c}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python gshock_revise_descriptions.py <active_report.csv> [out.csv]")
        sys.exit(2)
    sys.exit(build_revise(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))
