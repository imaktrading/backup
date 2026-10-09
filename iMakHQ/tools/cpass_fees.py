#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SpeedPAK (CPaSS / Orange Connex) の追跡番号ごとの送料 (2026-10-09)。注文 → 仕入れ の管理 (order_purchase_sync.py) が使う。

★ユーザー「追跡番号が EE から始まるのは Cpass なのね。そこから送料を取ってほしい」→「Gmail じゃないよ」。
  SpeedPAK セラーポータル (ebay-jp.orangeconnex.com) の「各注文番号の料金明細」を、いつもの Edge の拡張
  (tools/sellerhub_grab/cpass_fees.js) が読んで神風 (/api/cpass/fees) に渡す。ここはその控えを持つ。
  控えは貯めていく (ポータルの一覧は新しい順で、古い物はページの奥に行くため)。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import time

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
CACHE = r"C:/dev/iMak_data/hq/cpass_fees.json"
URL = "https://ebay-jp.orangeconnex.com/homePage#imak-ship"
WAIT_SEC = 120
TRACK = re.compile(r"^E[A-Z]\d{10,}[A-Z0-9]*$")


def is_cpass_tracking(t):
    """SpeedPAK (Orange Connex) の追跡番号か (純関数)。EE… (Economy) / EX… (FedEx) など E + 英字 + 数字。"""
    return bool(TRACK.match((t or "").strip()))


def load(path=None):
    try:
        with open(path or CACHE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"at": None, "fees": {}}


def save_from_extension(body, now=None, path=None):
    """拡張が送ってきた {追跡番号: {yen,…}} を控えに足す (I/O)。神風が呼ぶ。"""
    d = load(path)
    fees = d.get("fees") or {}
    new = 0
    for t, v in (body.get("fees") or {}).items():
        if is_cpass_tracking(t) and isinstance(v, dict) and v.get("yen") is not None:
            new += t not in fees
            fees[t] = v
    d = {"at": (now or dt.datetime.now()).isoformat(timespec="seconds"), "fees": fees}
    with open(path or CACHE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    return {"ok": True, "n": len(body.get("fees") or {}), "new": new, "total": len(fees)}


def fetch(wait=WAIT_SEC, opener=None, sleep=time.sleep, now=dt.datetime.now):
    """ポータルを Edge で開いて、拡張が控えを書くのを待つ (I/O)。戻り: {追跡番号: 円}。返事が無ければ例外。"""
    asked = now().replace(microsecond=0)
    if opener is None:
        import mercari_purchases as MP                         # 別窓で開いて画面の右下の端に寄せる (前に出さない)
        opener = lambda u: MP._open_quiet(u, ("Orange Connex", "SpeedPAK", "orangeconnex"))  # noqa: E731
    opener(URL)
    for _ in range(int(wait / 3)):
        sleep(3)
        d = load()
        if d.get("at") and dt.datetime.fromisoformat(d["at"]) >= asked:
            return {t: v["yen"] for t, v in d["fees"].items()}
    raise RuntimeError("SpeedPAK の送料が届きません (Edge でポータルにログインしているか・拡張 3.9 以上か)")
