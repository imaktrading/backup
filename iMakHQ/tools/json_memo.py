# -*- coding: utf-8 -*-
"""数え直しの1回の中で、同じ JSON ファイルを何度も読み直さない (2026-10-14)。

★ユーザー「神風の数えなおし、もっと早くできない？」: 補URL の数え (count_workload) が1回 6分13秒、
  そのうち約2分半が **同じファイルを 5,697回 読み直す** 時間だった (答えの記録 url_card_verdicts.json 等を
  候補1件ごとに開き直していた)。

数え直しのプロセス (console/counts.py が SHEET_READ_MEMO=1 で起動する) と、JSON_READ_MEMO=1 を立てた
プロセス (補URL ③ / 再仕入れ ① の main が立てる・2026-10-14) の中でだけ効く。
ファイルの更新時刻と大きさが変わったら読み直すので、途中で書き込まれても古い中身は返さない。
返すのは **読んだ物そのもの** (同じ物を返すので、呼び出し側の id() での使い回しも効く)。書き換えないこと。
"""
import json
import os

_MEMO = {}


def enabled():
    return os.environ.get("SHEET_READ_MEMO") == "1" or os.environ.get("JSON_READ_MEMO") == "1"


def load(path, default_factory=dict):
    """path の JSON を読む。数え直しの中では2回目以降は前に読んだ物を返す。読めなければ default_factory()。"""
    if not enabled():
        return _read(path, default_factory)
    try:
        st = os.stat(path)
        sig = (st.st_mtime_ns, st.st_size)
    except OSError:
        return default_factory()
    hit = _MEMO.get(path)
    if hit and hit[0] == sig:
        return hit[1]
    d = _read(path, default_factory)
    _MEMO[path] = (sig, d)
    return d


def _read(path, default_factory):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default_factory()
