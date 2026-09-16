# -*- coding: utf-8 -*-
"""ファネル (funnel_output/funnel_YYYYMMDD.csv) の読み口 (2026-09-16)。

出品の **今の値段** と **出品サイト** はここにしか無い (商品管理シートには無い)。
読む所が増えたので1か所にまとめた:
  ・棚割りの金額        … control_panel (US の price を合計)
  ・売れた分を補充の件数 … sold_restock (US 以外 = ミラーは触らないので数えない)

ミラー (UK / AU / CA / DE) は親 (US) を写した別 itemID。**site で見分ける**
(グローバル CLAUDE.md「UK/AU/CA/DE は eBaymag のミラー — 直接 触るな」)。
"""
import csv
import glob
import io
import os

FUNNEL_DIR = r"C:/dev/iMak/iMakHQ/funnel_output"


def latest_funnel_path(funnel_dir=None):
    """直近のファネル (無ければ None)。"""
    hits = sorted(glob.glob(os.path.join(funnel_dir or FUNNEL_DIR, "funnel_*.csv")),
                  key=os.path.getmtime, reverse=True)
    return hits[0] if hits else None


def read_funnel_rows(path=None, funnel_dir=None):
    """ファネルの行 (読めなければ空)。"""
    p = path or latest_funnel_path(funnel_dir)
    if not p:
        return []
    try:
        with io.open(p, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def price_map_from_funnel_rows(rows):
    """行 → {itemID: US$}。US の行だけ (純関数)。"""
    out = {}
    for r in rows or []:
        if (r.get("site") or "").strip().upper() != "US":
            continue
        item_id = (r.get("item_id") or "").strip()
        if not item_id:
            continue
        try:
            usd = float(str(r.get("price") or "").replace("$", "").replace(",", "").strip() or 0)
        except ValueError:
            usd = 0.0
        if usd > 0:
            out[item_id] = usd
    return out


def site_map_from_funnel_rows(rows):
    """行 → {itemID: 出品サイト} (純関数)。"""
    out = {}
    for r in rows or []:
        item_id = (r.get("item_id") or "").strip()
        site = (r.get("site") or "").strip().upper()
        if item_id and site:
            out[item_id] = site
    return out


# eBay の日次スナップショット (出品サイトが入っている唯一の材料)。
# ★ファネルは US だけを載せているので、ミラーの判別には使えない (2026-09-16 実測: site は US のみ)。
SNAPSHOT_DIR = r"C:/dev/iMak_data/snapshots"


def non_us_from_snapshot_rows(rows):
    """スナップショットの行 → US 以外 (= ミラー) の itemID (純関数)。

    分からない物 (site 空) は入れない。ミラーを触らない判断は fail-closed 側に倒すが、
    **数えない** 判断なので、確実に US 以外と分かっている物だけを外す。
    """
    out = set()
    for r in rows or []:
        iid = (r.get("Item number") or r.get("item_id") or "").strip()
        site = (r.get("Listing site") or r.get("site") or "").strip()
        if iid and site and site.upper() not in ("US", "EBAY.COM"):
            out.add(iid)
    return out


def non_us_item_ids(rows=None, path=None, snapshot_dir=None):
    """US 以外 (= ミラー) と分かっている itemID。分からない物は入れない。"""
    if rows is not None:
        return non_us_from_snapshot_rows(rows) | {
            iid for iid, site in site_map_from_funnel_rows(rows).items() if site and site != "US"}
    hits = sorted(glob.glob(os.path.join(snapshot_dir or SNAPSHOT_DIR, "ebay_active_*.csv")),
                  key=os.path.getmtime, reverse=True)
    if not hits:
        return set()
    try:
        with io.open(hits[0], encoding="utf-8-sig", newline="") as f:
            return non_us_from_snapshot_rows(list(csv.DictReader(f)))
    except OSError:
        return set()


def latest_funnel_prices(funnel_dir=None):
    """直近のファネルから {itemID: US$} と その path。無ければ ({}, None)。"""
    p = latest_funnel_path(funnel_dir)
    if not p:
        return {}, None
    return price_map_from_funnel_rows(read_funnel_rows(p)), p
