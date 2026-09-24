#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""メルカリの「購入した商品」を読む (2026-09-24)。注文 → 仕入れ の管理 (order_purchase_sync.py) が使う。

★ユーザー (2026-09-24):「メルカリは mypage/purchases から URL とれないかな」「自分の購入履歴ならいいと思う」。
  仕入れアカウントでログインした **専用の Chrome (PROFILE)** で読む。ログインは人が1回だけ手でした。
  他の道具が使う匿名の Chrome (ログインしない) とは別物。混ぜない。

読むのは1ページ目だけ (直近 約40件)。完了済みの古い取引はリンクが無いものがあり、それは取れない。
"""
from __future__ import annotations

import datetime as dt
import html as _html
import re
import time

PROFILE = r"C:\Users\imax2\local_data\iMakHQ\mercari_buyer_profile"
URL = "https://jp.mercari.com/mypage/purchases"
_DATE = re.compile(r"(\d{4})/(\d{2})/(\d{2}) (\d{2}):(\d{2})")


def parse_purchases(src):
    """購入履歴の HTML → [{"id", "url", "title", "at"(datetime or None)}] (純関数)。"""
    parts = re.split(r'href="/transaction/(m\d+)"', src or "")
    out = []
    for k in range(1, len(parts), 2):
        body = re.sub(r"<svg.*?</svg>", "", parts[k + 1][:6000], flags=re.S)
        texts = [_html.unescape(x.split(">", 1)[-1]).strip() for x in body.split("<")]
        texts = [x for x in texts if x]
        m = next((_DATE.search(x) for x in texts if _DATE.search(x)), None)
        # 表に入れるのは取引画面 (発送状況・取引メッセージが見られる)。ユーザー 2026-09-24「こっちの URL の方がよくない？」
        out.append({"id": parts[k], "url": "https://jp.mercari.com/transaction/" + parts[k],
                    "title": texts[0] if texts else "",
                    "at": dt.datetime(*map(int, m.groups())) if m else None})
    return out


def fetch_purchases():
    """ログイン済みの専用 Chrome (窓なし) で読む (I/O)。ログインが切れていたら例外。"""
    import undetected_chromedriver as uc
    from mercari_psa_resource import _chrome_major, _quiet_chromedriver
    _quiet_chromedriver()
    o = uc.ChromeOptions()
    for a in (f"--user-data-dir={PROFILE}", "--headless=new", "--lang=ja-JP", "--window-size=1280,1400"):
        o.add_argument(a)
    maj = _chrome_major()
    d = uc.Chrome(options=o, version_main=maj) if maj else uc.Chrome(options=o)
    try:
        d.get(URL)
        for _ in range(20):
            time.sleep(2)
            if "/transaction/" in d.page_source:
                break
        if "/mypage/purchases" not in d.current_url:
            raise RuntimeError("メルカリのログインが切れています (%s)" % d.current_url)
        return parse_purchases(d.page_source)
    finally:
        d.quit()


def login():
    """ログインが切れた時に人が1回ログインする窓を開く (I/O)。購入履歴が出たら閉じる (最大15分)。

        python mercari_purchases.py --login
    """
    import undetected_chromedriver as uc
    from mercari_psa_resource import _chrome_major, _quiet_chromedriver
    _quiet_chromedriver()
    o = uc.ChromeOptions()
    for a in (f"--user-data-dir={PROFILE}", "--lang=ja-JP", "--window-size=1280,1400"):
        o.add_argument(a)
    maj = _chrome_major()
    d = uc.Chrome(options=o, version_main=maj) if maj else uc.Chrome(options=o)
    try:
        d.get(URL)
        for _ in range(90):
            time.sleep(10)
            if "/mypage/purchases" in d.current_url and "/transaction/" in d.page_source:
                print("ログインできました")
                return True
        print("15分でログインが終わりませんでした")
        return False
    finally:
        d.quit()


def match(orders, purchases):
    """注文の行と購入を結ぶ (純関数)。

    orders   : [(行番号, 注文日 date, {候補のメルカリ id})]
    purchases: parse_purchases の結果
    返り値   : {行番号: 購入}。1つの購入は1つの注文にだけ。注文日より前の購入は結ばない。
    古い注文から順に、候補にある **いちばん早い購入** を当てる
    (同じカードが2回売れた時 = 9/19 と 9/23 のヤドン、を取り違えないため)。
    """
    used, out = set(), {}
    buys = sorted((p for p in purchases if p.get("at")), key=lambda p: p["at"])
    for row, day, cands in sorted(orders, key=lambda o: (o[1], o[0])):
        for p in buys:
            if p["id"] in cands and p["id"] not in used and p["at"].date() >= day:
                out[row] = p
                used.add(p["id"])
                break
    return out


def mercari_id(url):
    m = re.search(r"/item/(m\d+)", url or "")
    return m.group(1) if m else ""


if __name__ == "__main__":
    import sys
    if "--login" in sys.argv:
        sys.exit(0 if login() else 1)
    for p in fetch_purchases():
        print(p["at"], p["url"], p["title"][:40])
