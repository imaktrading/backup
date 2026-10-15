# -*- coding: utf-8 -*-
"""読むためだけのページ (CPaSS の送料・メルカリの購入履歴) を、Edge の拡張に「前に出さない窓」で開いてもらう (2026-10-15)。

★ユーザー「Cpass の窓の件、分からないように開けて閉じれないの？」: 数え直しのたびに、プログラムが Edge に直接
  開かせていたので、新しい窓が一瞬前に出て作業中の窓が切り替わっていた (その後で右下の端へ動かしていた)。
  → 開いてほしい URL をここに置く → 神風 (/api/ext/open) 経由で拡張が30秒以内に拾い、focused:false の窓を
    最初から画面の右下の端に開く。読み終えたら拡張が閉じる (CPaSS は3分で必ず閉じる)。
  最小化はしない: 最小化した窓ではページが一覧を描かず0件になる (メルカリの購入履歴で実測)。
  拡張が拾わない時 (古い版・Edge が閉じている) は、今までの開き方 (fallback) に戻す。
"""
import datetime as dt
import json
import os
import time

REQ = r"C:/dev/iMak_data/hq/ext_open_requests.json"
TAKE_WAIT_SEC = 45          # 拡張は30秒おきに見に来る
STALE_SEC = 180             # これより古い頼みは拾わせない (開きっぱなしにしない)


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def _save(rows, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def ask(url, fallback=None, path=REQ, wait=TAKE_WAIT_SEC, sleep=time.sleep, now=dt.datetime.now):
    """拡張に開いてもらう (I/O)。拾われたら "ext"、拾われなければ fallback(url) を呼んで "fallback"。"""
    rid = now().strftime("%Y%m%d%H%M%S%f")
    rows = [r for r in _load(path) if not _stale(r, now())] + [{"id": rid, "url": url, "at": now().isoformat(), "taken": ""}]
    _save(rows, path)
    for _ in range(int(wait / 3)):
        sleep(3)
        if any(r.get("id") == rid and r.get("taken") for r in _load(path)):
            print(f"  🪟 拡張が前に出さない窓で開きました: {url[:60]}", flush=True)
            return "ext"
    _save([r for r in _load(path) if r.get("id") != rid], path)      # 拾われなかった頼みは消す
    print(f"  🪟 拡張が拾わなかった ({wait}秒) → 今までの開き方で開きます: {url[:60]}", flush=True)
    if fallback:
        fallback(url)
    return "fallback"


def _stale(r, now):
    try:
        return (now - dt.datetime.fromisoformat(r.get("at") or "")).total_seconds() > STALE_SEC
    except ValueError:
        return True


def take(path=REQ, now=dt.datetime.now):
    """神風 (/api/ext/open) が呼ぶ: まだ拾われていない新しい頼みの URL を返し、拾った印を付ける (I/O)。"""
    t = now()
    rows = [r for r in _load(path) if not _stale(r, t)]
    urls = [r["url"] for r in rows if not r.get("taken")]
    if urls:
        for r in rows:
            r["taken"] = r.get("taken") or t.isoformat(timespec="seconds")
        _save(rows, path)
    return urls
