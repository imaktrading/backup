# -*- coding: utf-8 -*-
"""補URLが1本も無い出品を **1枚のタブにまとめる** (2026-08-17)。

■ なぜ要るか
ユーザー「42件はどこにあるの?」→ 商品管理シートの行として散っており、
R列=TCG / B列あり / D列空 / AC-AG が全部空、を自分で絞らないと見えなかった。
「1つのシートにまとめてくれた方が分かりやすい」との指示。

■ 何を書くか
`既存メンテ` スプシの **補URL丸腰** タブに、1行1出品で:
  行 / itemID / cert / タイトル / 状態 / 理由 / 補URL本数 / 更新日
状態は3つだけ (ボタンのラベルと同じ語彙 = `split_blocked` が SSOT):
  - 目視できる     … 🩹 を押せば候補が出る
  - 市場に版が無い … 探しても出てこない。**待つしかない**
  - 手が打てる     … 未検索・番号が取れない等、こちら側で動かせる

■ 書き込むのはこのタブだけ
商品管理シート(本番)には一切触らない。毎晩の巡回で作り直す。
"""
from __future__ import annotations

import argparse
import collections
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import psa_hoju_fill as H                              # noqa: E402
import sheet_io                                        # noqa: E402

TAB = "補URL丸腰"
HEADER = ["状態", "理由", "行", "itemID", "cert", "タイトル", "補URL本数", "更新日"]
READY, WAIT, ACT = "目視できる", "市場に版が無い(待ち)", "手が打てる"
_ORDER = {READY: 0, ACT: 1, WAIT: 2}


def classify(why, has_cands, unjudged):
    """1件の止まり方 → (状態, 理由) (純関数)。

    語彙は `split_blocked` と揃える (ボタンのラベルと同じ言葉にする)。
    """
    if has_cands:
        return READY, ("絵柄が未判定 (押すと判定)" if unjudged else "候補あり")
    ja = H._REASON_JA.get(why, why or "不明")
    if why in H.WAIT_REASONS:
        return WAIT, ja
    if why in H.ACT_REASONS:
        return ACT, ja
    return ACT, ja                       # no_ref 等は こちらで直せる側に寄せる


def build_rows(targets, survivors, today):
    """[(target, cands, why, unjudged)] → シートに書く2次元配列 (純関数)。"""
    rows = []
    for t, cands, why, unjudged in survivors:
        st, ja = classify(why, bool(cands), unjudged)
        rows.append([st, ja, t.get("row", ""), t.get("itemID", ""), t.get("cert", ""),
                     (t.get("title") or "")[:60], t.get("n_backups", 0), today])
    rows.sort(key=lambda r: (_ORDER.get(r[0], 9), r[1]))
    return [HEADER] + rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    import mercari_psa_resource as mp                   # noqa: F401  (build_search_query 用)
    import psa_art_match as art
    import psa_resource_confirm as prc

    today = datetime.date.today().isoformat()
    vals = H._read_high()
    targets = H.select_backfill_targets(vals)
    cache = H._load_cache()
    ctx = H.build_confirm_context(vals, cache, today)
    acache = art.load_cache()
    stats = collections.Counter()
    unknown_ref = set()

    def _ref_of(t):
        if not prc.ref_image_known(t["itemID"]):
            unknown_ref.add(t["itemID"])
        return (prc.ebay_listing_image(t["itemID"], allow_fetch=False)
                or prc.psa_image_for_cert(t.get("cert") or None))

    def _art_of(ref, cands, t):
        if t["itemID"] in unknown_ref:
            return [dict(c, _art_unjudged=True) for c in cands], []
        keep, dropped = [], []
        for c in cands:
            hit = art.cached_verdict(ref, c.get("image") or c.get("url") or "",
                                     c.get("name") or "", acache)
            if hit is None:
                keep.append(dict(c, _art_unjudged=True))
            elif art.drop_reason(hit):
                dropped.append(c)
            else:
                keep.append(c)
        return keep, dropped

    survivors = []
    for t in targets:
        cands, _ref, why, _ = H.confirm_survivors(
            t, vals, cache, ctx, today, ref_of=_ref_of, art_of=_art_of, stats=stats)
        survivors.append((t, cands, why, any(c.get("_art_unjudged") for c in cands)))

    rows = build_rows(targets, survivors, today)
    n = collections.Counter(r[0] for r in rows[1:])
    print(f"▶ 補URLが1本も無い出品: {len(rows) - 1}件")
    for k in (READY, ACT, WAIT):
        if n.get(k):
            print(f"   {k}: {n[k]}件")
    if a.dry_run:
        print("🧪 DRY-RUN: 書込なし")
        for r in rows[1:6]:
            print("   ", r[:6])
        return
    sheet_io.write_rows_to_tab(TAB, rows)
    print(f"✅ 『{TAB}』タブに {len(rows) - 1}件 書きました → {sheet_io.MAINT_URL}")


if __name__ == "__main__":
    main()
