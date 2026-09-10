#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""取下げ (CULL) 候補を **出品中の一覧から毎晩作る** (Seller Hub レポート不要)。

★2026-09-10 ユーザー「数日 青にならない。毎日 候補が追加されるはず」。
  夜の処理 (run_hoju_search.bat) は毎晩 listing_funnel を回しているが、元の Seller Hub
  レポートは **人が手で落として置く**しかなく、4日以上古いと funnel は自分で中断する
  (9/9・9/10 の夜は中断)。結果、取下げの候補は 9/8 の funnel のまま増えなかった。

  CULL の材料 (在庫0 / 売れた数 / ウォッチ / 出品日 / タイトル) は出品一覧 API で全部取れる。
  足りないのは **表示回数** だけで、これは「戻す担当がいる」行 (PSA10 / 一番くじ) の判定にしか
  使わない。その行は **最新 funnel に表示回数がある時だけ**判定し、無ければ候補にしない
  (判らないものを落とす側に倒さない)。戻す担当がいない行は表示回数を見ずに CULL
  (listing_funnel.classify と同じ。2026-08-25 ユーザー確定)。

判定は **listing_funnel.classify をそのまま呼ぶ** (条件を書き直さない = ズレない)。
取り下げはしない。候補ファイルを書くだけ。落とすのは従来どおり 🗑 ボタン
(押した時に1件ずつ eBay の実状態を見てから落とす)。

入力 : 出品一覧 (itemid_writeback_audit._fetch_live = 2時間キャッシュ共用。API は ~20回)
       最新 funnel_*.csv (表示回数を借りるだけ)
出力 : ../funnel_output/cull_live_YYYYMMDD.csv (funnel と同じ列名。cull_end が読む)
"""
import csv
import datetime
import glob
import html
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "..", "iMakeBayAPI")))
FUNNEL_DIR = os.path.normpath(os.path.join(_HERE, "..", "funnel_output"))
OUT_PREFIX = "cull_live_"
FIELDS = ["item_id", "title", "site", "category", "price", "qty", "sold_qty", "sales90",
          "watch", "impr", "impr_total", "age_days", "flags"]


def _age_days(start_time, today):
    """StartTime ('2026-07-10T11:18:21.000Z') → 経過日数。読めなければ 0 (= 不明。cull_end が落とす)。"""
    try:
        d = datetime.datetime.strptime((start_time or "")[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return 0
    return max((today - d).days, 0)


def rows_from_live(live, today=None):
    """出品一覧 (itemid_writeback_audit のキャッシュ形式) → funnel と同じ形の行 (純関数)。"""
    today = today or datetime.datetime.utcnow()
    out = []
    for iid, it in (live or {}).items():
        if not isinstance(it, dict) or "sold" not in it:
            continue                       # 旧形式のキャッシュ = 売れた数が判らない → 作らない
        out.append({
            "item_id": str(iid), "title": html.unescape(it.get("title") or ""),
            "site": it.get("site") or "", "category": "",
            "price": float(it.get("usd") or it.get("price") or 0.0),
            "qty": int(it.get("avail") or 0), "sold_qty": int(it.get("sold") or 0),
            "sales90": 0, "watch": int(it.get("watch") or 0),
            "impr": 0.0, "impr_total": 0.0, "trend_price": 0.0,
            "age_days": _age_days(it.get("start_time"), today)})
    return out


def build_cull(live_rows, funnel_rows):
    """CULL 行と内訳を返す (純関数, test 可)。

    戻り: (cull 行 list, {"oos": 在庫0のUS行, "held": 表示回数が無く判定を保留した行数})
    """
    import listing_funnel as LF
    us, _n_mirror, _n_gained = LF.absorb_mirror_demand([dict(r) for r in live_rows])
    oos = [r for r in us if r["qty"] == 0]
    by_id = {str(r.get("item_id")): r for r in (funnel_rows or [])}
    judged, held = [], 0
    for r in oos:
        if LF.restock_owner(r):
            f = by_id.get(r["item_id"])
            if f is None:
                held += 1                  # 表示回数が判らない = 戻す担当の判定ができない → 候補にしない
                continue
            r["impr"] = LF._f(f.get("impr"))
            r["impr_total"] = LF._f(f.get("impr_total"))
            r["sales90"] = LF._i(f.get("sales90"))
        judged.append(r)
    cull = LF.classify(judged)["CULL"] if judged else []
    for r in cull:
        r["flags"] = "OUT_OF_STOCK|CULL"
    return cull, {"oos": len(oos), "held": held}


def latest_funnel_rows():
    fs = glob.glob(os.path.join(FUNNEL_DIR, "funnel_*.csv"))
    if not fs:
        return [], ""
    src = max(fs, key=os.path.getmtime)
    with open(src, encoding="utf-8") as f:
        return list(csv.DictReader(f)), os.path.basename(src)


def write_csv(rows, path):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    os.replace(tmp, path)                  # 途中で落ちても半端なファイルを残さない


def main():
    import itemid_writeback_audit as A
    try:
        live = A._fetch_live(use_cache=True)
    except Exception as e:                                         # noqa: BLE001
        # 取り切れなかった一覧で判定しない (欠けた分が「在庫0」に見えることはないが、
        # 件数を正常と誤報告しない)。前回の候補ファイルはそのまま残る。
        sys.exit(f"⚠ 出品一覧を取り切れませんでした → 今回は候補を作りません: {e}")
    live_rows = rows_from_live(live)
    if not live_rows:
        # キャッシュが旧形式 (売れた数を持たない) だった → 取り直す
        live = A._fetch_live(use_cache=False)
        live_rows = rows_from_live(live)
    if not live_rows:
        sys.exit("⚠ 出品一覧が空です → 候補を作りません")
    funnel_rows, fsrc = latest_funnel_rows()
    cull, info = build_cull(live_rows, funnel_rows)
    os.makedirs(FUNNEL_DIR, exist_ok=True)
    path = os.path.join(FUNNEL_DIR, f"{OUT_PREFIX}{datetime.date.today():%Y%m%d}.csv")
    write_csv(cull, path)
    n_us = sum(1 for r in live_rows if r["site"] == "US")
    print(f"出品中 {len(live_rows)}件 (US {n_us}) / US の在庫0 {info['oos']}件")
    print(f"取下げ候補 (CULL) {len(cull)}件 → {os.path.basename(path)}")
    if info["held"]:
        print(f"  ※ 保留 {info['held']}件 — PSA10/一番くじで、表示回数が最新 funnel ({fsrc or 'なし'}) に無い。"
              f"判らないので候補にしていません (ファネル分析が回れば判定されます)")


if __name__ == "__main__":
    main()
