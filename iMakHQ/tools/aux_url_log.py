#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""補URL が **誰に・いつ** 入れられたかを残す台帳 (2026-09-08)。

■ なぜ要るか
2026-09-08 に「補URLが別のカードで、そのぶん安く出品されていた」事故が **3件** 出た
(820026248229 / 820049712142 / 358908083352)。3件ともバイヤーの問い合わせ・オファーで発覚。
直した後にユーザーから「補が入れられたルートは? 勝手に入るルートない?」と聞かれ、
**866本のログを探しても分からなかった**。補URLを書く経路は4つあり、
そのうち3つは URL をログに出していない (件数・本数だけ) ため。

  目視 (補URL③)          … 件数だけ
  2枚目の自動追記        … URL を出す
  捨てた候補の転記 (夜間) … 本数だけ
  新規出品行の作成       … 出さない

門をどこに置くかは「どこから入ったか」が分からないと決められない。だから先にここを作る。

■ 作り
書込は全経路が `sheet_io.write_aux_urls()` を通るので、**そこ1か所**で記録する。
経路名は呼び手が `AUX_SOURCE` 環境変数か `set_source()` で名乗る。名乗らなければ "不明"。
JSONL で追記のみ (壊れても過去は残る)。
"""
from __future__ import annotations

import datetime
import json
import os
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(HERE, "..", "review_logs", "aux_url_log.jsonl")
_LOCK = threading.Lock()
_SOURCE = {"name": ""}


def set_source(name):
    """この走行が名乗る経路名。呼ばないと環境変数 → "不明" の順で決まる。"""
    _SOURCE["name"] = (name or "").strip()


def current_source():
    return _SOURCE["name"] or os.environ.get("AUX_SOURCE", "").strip() or "不明"


def norm(url):
    """突合キー。dup_guard と同じ正規化 (無ければ素朴に)。"""
    u = (url or "").strip()
    if not u:
        return ""
    try:
        import sys
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import dup_guard
        return dup_guard.norm_url(u) or ""
    except Exception:                                          # noqa: BLE001
        return u.split("?")[0].rstrip("/").lower()


def build_records(row_to_urls, source, today=None, item_of=None):
    """書込内容 → 台帳に足す行 (純関数)。

    item_of: {行番号: itemID} を渡せば itemID も残す (後から出品単位で引けるようにする)。
    """
    today = today or datetime.date.today().isoformat()
    out = []
    for row, urls in (row_to_urls or {}).items():
        for u in (urls or []):
            u = (u or "").strip()
            if not u:
                continue
            out.append({"date": today, "source": source, "row": row,
                        "itemID": (item_of or {}).get(row, ""), "url": u, "n": norm(u)})
    return out


def record(row_to_urls, source=None, item_of=None, path=None):
    """台帳に追記 (I/O)。★失敗しても書込そのものは止めない (記録は本業ではない)。"""
    recs = build_records(row_to_urls, source or current_source(), item_of=item_of)
    if not recs:
        return 0
    p = path or LOG_PATH
    try:
        with _LOCK:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                for r in recs:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
    except Exception:                                          # noqa: BLE001
        return 0
    return len(recs)


def load(path=None):
    """台帳を読む (I/O)。壊れた行は飛ばす。"""
    p = path or LOG_PATH
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


def source_of(url, records=None):
    """その補URLを **最後に入れた経路** (無ければ None)。純関数 (records を渡した時)。"""
    n = norm(url)
    if not n:
        return None
    hit = None
    for r in (records if records is not None else load()):
        if r.get("n") == n:
            hit = r
    return hit


def summary(records=None):
    """経路ごとの本数 (純関数)。どこから入っているかを一目で見るため。"""
    import collections
    c = collections.Counter(r.get("source") or "不明"
                            for r in (records if records is not None else load()))
    return dict(c.most_common())


if __name__ == "__main__":
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    recs = load()
    print(f"補URL の記録: {len(recs)}本")
    for k, v in summary(recs).items():
        print(f"  {k}: {v}本")
    if len(sys.argv) > 1:
        hit = source_of(sys.argv[1], recs)
        print(f"\n{sys.argv[1]}\n  → {hit or '記録なし (台帳を作る前に入った分)'}")
