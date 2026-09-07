#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仕入元が **別のカード** になっている出品を見つける (2026-09-08)。

■ なぜ要るか
2026-09-08、バイヤーの問い合わせで発覚した: 出品 820026248229 (ブラッキー SV8a-092) の
補URL に **別カードの安い出品** が入り、その値段が「今の最安 ¥10,900」としてシートに載って、
価格が cost-plus で決まる仕組みのまま **$155.98** で出ていた (正しくは $405.98)。
**見た目では分からない**。人が気づいたのは買い手に聞かれたからで、それ以外に検知は無かった。

■ 見つけ方 (2段)
  ① 値段の形で絞る  … 仕入値が「番号一致で見つかっている供給の最安」より大幅に安い行。
                     別カードが混ざると必ずこの形になる (安いから混ざったと気づかない)。
  ② 商品名で確かめる … ①の行の仕入元URLを開き、**商品名のカード番号が KEY と合うか**。
                     ここまでやらないと「本当に安かっただけ」と区別できない。

■ 実測 (2026-09-08 の初回)
  照合できた出品 316件 → ① で 14件 → ② で **別カードの混入は0件**。
  代わりに KEY の取り違えを1件見つけた (820065007711: 仕入元 OP07-033 が正で KEY=P-033 が誤り)。
  → ①だけでは判定できない。**②まで通した件数を出す**こと。

使い方:
  python supply_card_mismatch.py                 # ①だけ (無料・数秒)
  python supply_card_mismatch.py --verify        # ②まで (ブラウザで商品名を読む・数分)
  python supply_card_mismatch.py --verify --limit 10
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

# ★import した時に stdout を差し替えない (pytest の捕捉が壊れる)。実行時だけ整える。
if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                         # noqa: BLE001
        pass
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import psa_hoju_fill as hf                                    # noqa: E402

# 「安すぎる」の線。0.6 = 番号一致の最安の6割未満。2026-09-08 の実測でこの線で 316→14件。
CHEAP_RATIO = 0.6
OUT_PATH = os.path.join(HERE, "..", "review_logs", "supply_card_mismatch.json")


def _cell(row, i):
    return (row[i] if len(row) > i else "") or ""


def _num(s):
    d = re.sub(r"[^0-9]", "", str(s or ""))
    return int(d) if d else None


def known_prices(entry):
    """その出品の **番号一致で見つかった供給** の値段一覧 (純関数)。

    キャッシュに入るのはカード番号で検索して当たったものだけなので、
    ここに並ぶ値段は「そのカードの相場」と見てよい。
    """
    out = []
    m = (entry or {}).get("mercari") or {}
    for key in ("cands", "all_cands"):
        for row in (m.get(key) or []):
            if row and isinstance(row[0], (int, float)):
                out.append(float(row[0]))
    for lst in ((entry or {}).get("snkrdunk") or {}).get("psa10_listings") or []:
        try:
            out.append(float(lst.get("price")))
        except (TypeError, ValueError):
            pass
    return [p for p in out if p]


def find_suspects(vals, cache, ratio=CHEAP_RATIO):
    """① 値段の形で絞る (純関数)。戻り: (suspects, 照合できた件数)。"""
    suspects, checked = [], 0
    for r in vals[1:]:
        iid, cert = _cell(r, hf.B).strip(), _cell(r, hf.CERT).strip()
        if not iid or not cert or _cell(r, 3).strip():        # 出品中のみ / 売切は除く
            continue
        cost = _num(_cell(r, 13)) or _num(_cell(r, 12)) or _num(_cell(r, 5))
        prices = known_prices(cache.get(iid))
        if not cost or not prices:
            continue
        checked += 1
        cheapest = min(prices)
        if cost < cheapest * ratio:
            suspects.append({
                "itemID": iid, "cert": cert, "key": _cell(r, hf.KEY),
                "cost": cost, "cheapest": cheapest,
                "ratio": round(cost / cheapest, 3),
                "title": _cell(r, 2)[:60],
                "urls": [u for u in ([_cell(r, 0)]
                                     + [_cell(r, hf.AUX0 + k) for k in range(hf.AUXN)]) if u],
            })
    suspects.sort(key=lambda s: s["ratio"])
    return suspects, checked


def number_matches(key, card_no):
    """KEY と 商品名から取れた番号が同じカードか (純関数)。

    ポケモンは商品名が `090/071` のような通し番号で、KEY は `SV2P-090`。
    ここを見ないと **一致しているものを不一致と読む** (2026-09-08 に4件 誤判定した)。
    """
    if not card_no:
        return None                                           # 番号が読めない = 判定しない
    base = (key or "").split(":")[-1].split("_")[0].upper()
    no = card_no.upper()
    if no == base:
        return True
    m = re.match(r"^(\d{1,3})/\d{1,3}$", no)                  # 090/071 → 末尾 090
    if m and base.endswith("-" + m.group(1)):
        return True
    return False


def verify(suspects, limit=0, verbose=True):
    """② 仕入元の商品名を読んで、カード番号が KEY と合うか確かめる (I/O)。"""
    import time
    import mercari_psa_resource as mp
    import newcand_confirm as nc
    todo = suspects[:limit] if limit else suspects
    try:
        drv = mp.new_scrape_driver()
    except Exception as e:                                    # noqa: BLE001
        print(f"⚠ ブラウザを起こせない ({type(e).__name__}) → ②は skip")
        return suspects
    try:
        for s in todo:
            s["checked"] = []
            for u in s["urls"]:
                if "snkrdunk" in u:
                    s["checked"].append({"url": u, "verdict": "skip(スニダンは構造が別)"})
                    continue
                try:
                    drv.get(u)
                    time.sleep(2.5)
                    t = re.search(r"<title>(.*?)</title>", drv.page_source, re.S)
                    title = re.sub(r"\s*-\s*メルカリ.*$", "", (t.group(1) if t else "")).strip()
                except Exception as e:                        # noqa: BLE001
                    s["checked"].append({"url": u, "verdict": f"開けず({type(e).__name__})"})
                    continue
                no = nc.extract_card_no(title) or ""
                ok = number_matches(s["key"], no)
                s["checked"].append({"url": u, "title": title[:60], "no": no,
                                     "verdict": {True: "一致", False: "★不一致",
                                                 None: "番号なし"}[ok]})
            s["mismatch"] = sum(1 for c in s["checked"] if c["verdict"] == "★不一致")
            if verbose:
                mark = "★別カードの疑い" if s["mismatch"] else "シロ"
                print(f"  {s['itemID']}  {mark}  仕入¥{s['cost']:,.0f} / 最安¥{s['cheapest']:,.0f}"
                      f"  {s['title'][:30]}")
                for c in s["checked"]:
                    if c["verdict"] == "★不一致":
                        print(f"      {c['url'][-16:]} 番号={c['no']} ≠ KEY={s['key']}"
                              f"  {c.get('title','')[:36]}")
    finally:
        try:
            drv.quit()
        except Exception:                                     # noqa: BLE001
            pass
    return suspects


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="仕入元の商品名まで読んで確かめる")
    ap.add_argument("--limit", type=int, default=0, help="②で見る件数の上限")
    ap.add_argument("--ratio", type=float, default=CHEAP_RATIO)
    a = ap.parse_args()

    vals = hf._read_high()
    cache = {}
    if os.path.exists(hf.CACHE_PATH):
        with open(hf.CACHE_PATH, encoding="utf-8") as f:
            cache = json.load(f)
    suspects, checked = find_suspects(vals, cache, a.ratio)
    print(f"仕入元が別カードでないかの検査: 照合できた出品 {checked}件 / "
          f"① 値段が安すぎる {len(suspects)}件 (最安の{a.ratio*100:.0f}%未満)")
    if not suspects:
        print("  ① で0件。②は不要。")
    for s in suspects[:20]:
        print(f"  {s['itemID']}  仕入¥{s['cost']:>8,.0f} / 番号一致の最安¥{s['cheapest']:>8,.0f}"
              f" ({s['ratio']*100:3.0f}%)  {s['title'][:34]}")
    if a.verify and suspects:
        print("\n② 仕入元の商品名を読んで確かめます (ブラウザ)")
        suspects = verify(suspects, a.limit)
        bad = [s for s in suspects if s.get("mismatch")]
        print(f"\n★別カードの疑い {len(bad)}件 / 見た {sum(1 for s in suspects if 'checked' in s)}件")
        if not bad:
            print("  ②まで通して0件 = 安いのは本物。①の件数だけで騒がないこと。")
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump({"checked": checked, "ratio": a.ratio, "verified": bool(a.verify),
                   "suspects": suspects}, f, ensure_ascii=False, indent=1)
    print(f"\n記録: {os.path.normpath(OUT_PATH)}")


if __name__ == "__main__":
    main()
