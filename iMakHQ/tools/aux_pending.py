#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""補URL の **目視待ち**。機械が勝手にシートへ書かず、ここに積む (2026-09-08 ユーザー指示)。

■ なぜ
2026-09-08 に「補URLが別のカードで、そのぶん安く出品されていた」事故が3件出た
(820026248229 $155.98/正 $405.98・820049712142 $202.98/正 $648.98・358908083352)。
3件ともバイヤーの問い合わせやオファーで発覚。どこから入ったかログから特定できず、
ユーザー判断:

    「勝手に補に追加するルートは閉じて、必ず目視を通る様にして」

■ 何が危ないのか (自動経路が悪意なく間違う仕組み)
自動の2経路は **KEY (版まで含んだ product_id) が一致する行**から URL を配る。理屈は正しいが、
**元の行の KEY が誤っていれば、誤った版の URL をそのまま配る**。KEY の取り違えは実在した
(2026-09-07: `P-033` と `OP07-033_p2`)。しかも同じ番号の別版は、商品名では見分けが付かない
(ST10-006 は版が8つあり全部 SR)。だから機械の一致だけで書き込ませない。

■ 使い方
書きたかった内容を `queue()` で積み、人が目視で採否を決める。
    python aux_pending.py            # 溜まっている件数と中身
"""
from __future__ import annotations

import datetime
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "..", "review_logs", "aux_url_pending.jsonl")


def build_rows(row_to_urls, source, existing_by_row=None, item_of=None, today=None,
               already=None, price_of=None):
    """積む行を作る (純関数)。**既にシートに在る URL は積まない** (二度見せない)。

    ★2026-09-12 追加 `already`: **既に待ち行列に居る (行, URL) も積まない**。
      これが無かったので、毎晩 同じ物が積み直されていた
      (実測 2026-09-13: 951本 のうち 実質ユニークは 439本 = 512本 が積み直し)。
      人が見るまで消えない待ち行列なので、書く側が冪等でないと際限なく膨らむ。
    """
    today = today or datetime.date.today().isoformat()
    seen = set(already or ())
    out = []
    for row, urls in (row_to_urls or {}).items():
        have = {(u or "").strip() for u in (existing_by_row or {}).get(row, []) if u}
        for u in (urls or []):
            u = (u or "").strip()
            if not u or u in have or (row, u) in seen:
                continue
            seen.add((row, u))
            out.append({"date": today, "source": source, "row": row,
                        "itemID": (item_of or {}).get(row, ""), "url": u,
                        # ★2026-09-19: **積んだ時の値段を一緒に残す**。
                        #   以前は値段を持たず、画面で「今の検索キャッシュ」から引いていた。
                        #   数日前に積んだ物はキャッシュに居ないので **値段が空のまま**
                        #   目視に出ていた (実測: 目視待ち455本のうち257本が空)。
                        "price": (price_of or {}).get(u)})
    return out


# ★2026-10-10 ユーザー「入口と出口の無駄をなくして、正しいカードが補に追加されるようにして」。
#   実測: 待ち列 1,724本のうち、出品が消えた 346 / 既に主・補に入っている 241 / 買えない URL 176 は
#   見る意味が無いのに残り続け、毎回読み直して「既知 1,296・高い 1,698 を除外」して 3〜7件しか出ていなかった。
#   入口 (積む時) と出口 (補URL③の始め) で同じ門を通す。待ち列は「新規出品候補」タブと検索の控えから
#   作る写しなので、ここから外しても元の記録 (カード単位の仕入元) は消えない。外した物は理由つきで残す。
DROPPED_PATH = os.path.join(HERE, "..", "review_logs", "aux_url_pending_dropped.jsonl")
_A, _B, _AUX0, _AUXN, _KEY = 0, 1, 28, 5, 34


def _norm(u):
    return (u or "").strip().split("?", 1)[0].split("#", 1)[0].rstrip("/")


def junk_reason(url, sheet_row, not_buyable=(), verdicts=None):
    """待ち列に置く意味が無い理由。置く意味があれば "" (純関数)。

    sheet_row: その出品の商品管理シートの行 (None = 出品が消えた)
    not_buyable: 買えない URL (正規化済みの集合) / verdicts: url_card_verdicts (「違う」だけ見る)
    """
    if sheet_row is None:
        return "出品が消えた"
    n = _norm(url)
    have = {_norm(sheet_row[i]) for i in [_A] + list(range(_AUX0, _AUX0 + _AUXN))
            if i < len(sheet_row) and sheet_row[i]}
    if n in have:
        return "既に主URL/補URLに入っている"
    if n in not_buyable:
        return "買えない URL"
    pid = (sheet_row[_KEY] if len(sheet_row) > _KEY else "").split(":")[-1].strip()
    if pid and ((verdicts or {}).get(n) or {}).get(pid, {}).get("v") == "diff":
        return "このカードと「違う」と答えた URL"
    return ""


def load_context(vals):
    """門に要る物を揃える (I/O)。戻り: (itemID→行, 買えない URL, 判定の記録)。読めない物は空 (外す方に倒さない)。"""
    by_iid = {}
    for r in (vals or [])[1:]:
        iid = (r[_B] if len(r) > _B else "").strip()
        if iid:
            by_iid[iid] = r
    try:
        import mercari_psa_resource as _mp
        nb = {_norm(u) for u in (_mp.load_not_buyable() or {})}
    except Exception:                                          # noqa: BLE001
        nb = set()
    try:
        import psa_label_learned as _pl
        uv = _pl.load(_pl.URL_PATH)
    except Exception:                                          # noqa: BLE001
        uv = {}
    return by_iid, nb, uv


def sweep(vals, path=None, dropped_path=None, ctx=None):
    """待ち列から見る意味の無い物を外す (I/O)。外した物は理由つきで別ファイルに残す。戻り: {理由: 本数}。

    シートが読めていない (vals が空) 時は何もしない (全部「出品が消えた」にしないため)。
    """
    import collections
    if not vals or len(vals) < 2:
        return {}
    p = path or PATH
    rows = load(p)
    by_iid, nb, uv = ctx or load_context(vals)
    keep, drop, why = [], [], collections.Counter()
    today = datetime.date.today().isoformat()
    for r in rows:
        iid = (r.get("itemID") or "").strip()
        if not iid:
            keep.append(r)                 # 誰の候補か分からない古い行は画面側が出さない。ここでは触らない
            continue
        reason = junk_reason(r.get("url"), by_iid.get(iid), nb, uv)
        if reason:
            why[reason] += 1
            drop.append(dict(r, dropped=today, reason=reason))
        else:
            keep.append(r)
    if drop:
        with open(dropped_path or DROPPED_PATH, "a", encoding="utf-8") as f:
            for r in drop:
                f.write(json.dumps(r, ensure_ascii=False) + chr(10))
        with open(p, "w", encoding="utf-8") as f:
            for r in keep:
                f.write(json.dumps(r, ensure_ascii=False) + chr(10))
    return dict(why)


def queued_pairs(path=None):
    """今 待ち行列に居る (行, URL) の集合 (I/O)。"""
    return {(r.get("row"), (r.get("url") or "").strip()) for r in load(path)}


def queue(row_to_urls, source, existing_by_row=None, item_of=None, path=None, price_of=None, vals=None):
    """目視待ちに積む (I/O)。戻り: 積んだ本数。既に居る分は積み直さない。

    vals (商品管理シート) を渡すと、見る意味の無い物 (junk_reason) は積まない (★2026-10-10 入口の門)。
    """
    rows = build_rows(row_to_urls, source, existing_by_row, item_of,
                      already=queued_pairs(path), price_of=price_of)
    if vals and len(vals) > 1 and rows:
        import collections
        by_iid, nb, uv = load_context(vals)
        why = collections.Counter()
        kept = []
        for r in rows:
            reason = junk_reason(r.get("url"), by_iid.get((r.get("itemID") or "").strip()), nb, uv)
            if reason:
                why[reason] += 1
            else:
                kept.append(r)
        print(f"  🚪 目視待ちの入口で外した: {sum(why.values())}本 / 積もうとした {len(rows)}本 "
              f"{dict(why) if why else ''}")
        rows = kept
    if not rows:
        return 0
    p = path or PATH
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(rows)


def load(path=None):
    p = path or PATH
    out = []
    if not os.path.exists(p):
        return out
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:                                  # noqa: BLE001
                continue
    return out


def dedupe(path=None):
    """同じ (行, URL) が何度も積まれた分を1本にまとめる (I/O)。戻り: 消した本数。

    ★2026-09-13: 積む側が冪等でなかった間に貯まった分の後片付け。一番古い1本を残す
      (いつから待っているかが分かる方が役に立つ)。
    """
    p = path or PATH
    rows = load(p)
    seen, keep = set(), []
    for r in rows:
        k = (r.get("row"), (r.get("url") or "").strip())
        if k in seen:
            continue
        seen.add(k)
        keep.append(r)
    n = len(rows) - len(keep)
    if n:
        with open(p, "w", encoding="utf-8") as f:
            for r in keep:
                f.write(json.dumps(r, ensure_ascii=False) + chr(10))
    return n


def consume(pairs, path=None):
    """人に見せ終わった分を待ち行列から外す (I/O)。戻り: 外した本数。

    ★見せた時点で結論は出ている (チェックを残す=採用 / 外す=理由つきで台帳へ)。
      外さないと毎回同じものが並び、「押しても減らない画面」になる。
    """
    p = path or PATH
    rows = load(p)
    if not rows:
        return 0
    gone = {(str(i or "").strip(), (u or "").strip()) for i, u in (pairs or [])}
    keep = [r for r in rows
            if (str(r.get("itemID") or "").strip(), (r.get("url") or "").strip()) not in gone]
    n = len(rows) - len(keep)
    if not n:
        return 0
    with open(p, "w", encoding="utf-8") as f:
        for r in keep:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return n


if __name__ == "__main__":
    import collections
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    if "--dedupe" in sys.argv:
        print(f"積み直しの重複を {dedupe()}本 まとめました")
    rows = load()
    print(f"補URL 目視待ち: {len(rows)}本")
    for src, n in collections.Counter(r.get("source") for r in rows).most_common():
        print(f"  {src}: {n}本")
    for r in rows[-10:]:
        print(f"  {r.get('date')} row{r.get('row')} {r.get('itemID')} {r.get('url')[:60]}")
