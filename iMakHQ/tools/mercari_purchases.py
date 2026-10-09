#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""メルカリの「購入した商品」を読む (2026-09-24)。注文 → 仕入れ の管理 (order_purchase_sync.py) が使う。

★ユーザー (2026-09-24):「メルカリは mypage/purchases から URL とれないかな」「自分の購入履歴ならいいと思う」。
  ★2026-10-09 から **いつも使っている Edge の拡張** (tools/sellerhub_grab/mercari_buys.js) が一覧を読んで神風に渡す。
    専用の Chrome (ログインを1回だけ手でした物) は1日ほどでログインが切れたのでやめた (save_from_extension)。
  値段は商品ページ (ログインしない Chrome) で読む (item_prices)。

読むのは1ページ目だけ (直近 約40件)。完了済みの古い取引はリンクが無いものがあり、それは取れない。
"""
from __future__ import annotations

import datetime as dt
import html as _html
import re
import time

try:                                     # 後片付けで uc が quit を2回呼び「ハンドルが無効」を出す (結果には無害)。
    import undetected_chromedriver as _uc   # こちらは必ず明示的に quit するので、GC 時の quit は止める
    _uc.Chrome.__del__ = lambda self: None
except Exception:                        # noqa: BLE001
    pass

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


EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
CACHE = r"C:/dev/iMak_data/hq/mercari_purchases_cache.json"
FRESH_MIN = 30                    # これより新しい控えがあれば Edge を開かない
WAIT_SEC = 90                     # Edge の拡張が控えを書くのを待つ


def save_from_extension(body, now=None, path=None):
    """Edge の拡張 (sellerhub_grab/mercari_buys.js) が送ってきた購入履歴を控えに書く (I/O)。神風が呼ぶ。

    ★2026-10-09 ユーザー「メルカリ購入履歴_ログインし直す.bat を押すって、アナログ過ぎない？」→「単純に購入履歴を読み取ればいい」。
      専用の Chrome で読むと、メルカリから別の端末に見えて1日ほどでログインが切れた (9/25・10/6 に直して2回とも切れた)。
      いつも使っている Edge (ログインしたまま) の拡張が一覧の HTML を渡し、ここで読む。
    """
    import json
    now = now or dt.datetime.now()
    if body.get("login_required"):
        d = {"at": now.isoformat(timespec="seconds"), "login_required": True, "items": []}
    else:
        items = parse_purchases(body.get("html") or "")
        # 読み方を直す時のために、最後に届いたページをそのまま残す
        with open((path or CACHE).replace(".json", "_last.html"), "w", encoding="utf-8") as f:
            f.write(body.get("html") or "")
        d = {"at": now.isoformat(timespec="seconds"), "login_required": False,
             "items": [{**p, "at": p["at"].isoformat() if p["at"] else None} for p in items]}
    with open(path or CACHE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    return {"ok": True, "n": len(d["items"]), "login_required": d["login_required"]}


def load_cache(path=None):
    """控え → (書いた時刻, ログインが要るか, 購入 list)。無ければ (None, False, [])。"""
    import json
    try:
        with open(path or CACHE, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None, False, []
    items = [{**p, "at": dt.datetime.fromisoformat(p["at"]) if p.get("at") else None} for p in d.get("items") or []]
    return dt.datetime.fromisoformat(d["at"]), bool(d.get("login_required")), items


def cache_state(at, login_required, now, since=None):
    """控えをどう扱うか (純関数): "use" / "login" / "stale"。

    since: Edge に頼んだ時刻。それより後に書かれた物だけを今回の返事として扱う。
    """
    if at is None or (since is not None and at < since):
        return "stale"
    if login_required:
        return "login"
    return "use" if (now - at).total_seconds() <= FRESH_MIN * 60 else "stale"


def _open_quiet(url):
    """Edge の **別の窓** で開いて、すぐ画面の右下の端へ動かす (I/O)。

    ★2026-10-09 ユーザー「メルカリ購入履歴を確認する (ブラウザが) 立ち上がる」: 数え直しのたびに、作業中の窓の上に
      購入履歴のタブが出ていた。別の窓にして、出たら画面の右下の端へ動かす (読み終えたら拡張が閉じる)。
    """
    import ctypes
    import subprocess
    from ctypes import wintypes
    subprocess.Popen([EDGE, "--new-window", url])
    u32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(h, _l):
        n = u32.GetWindowTextLengthW(h)
        if n and u32.IsWindowVisible(h):
            b = ctypes.create_unicode_buffer(n + 1)
            u32.GetWindowTextW(h, b, n + 1)
            if "メルカリ" in b.value or "mercari" in b.value.lower():
                found.append(h)
        return True
    for _ in range(40):                                        # 最大 10秒、窓が出るのを待つ
        time.sleep(0.25)
        found.clear()
        u32.EnumWindows(_cb, 0)
        if found:
            for h in found:
                # 最小化・画面の外だと「見えていない窓」として一覧を描かず 0件で返る (実測)。
                # 画面の右下に 8px だけ見える位置へ (見えている扱いのまま・前にも出さない)
                sw, sh = u32.GetSystemMetrics(0), u32.GetSystemMetrics(1)
                u32.SetWindowPos(h, 0, sw - 8, sh - 8, 1280, 1400, 0x0010 | 0x0004)   # NOACTIVATE | NOZORDER
            return


def fetch_purchases(wait=WAIT_SEC, opener=None, sleep=time.sleep, now=dt.datetime.now):
    """購入履歴 (I/O)。新しい控えがあればそれを、無ければ Edge で開いて拡張の返事を待つ。

    ログインが要る時・返事が無い時は例外 (呼び側が神風の注文の枠に出す)。
    """
    at, login, items = load_cache()
    if cache_state(at, login, now()) == "use" and items:
        return items
    asked = now().replace(microsecond=0)
    (opener or _open_quiet)(URL + "#imak-buys")
    for _ in range(int(wait / 3)):
        sleep(3)
        at, login, items = load_cache()
        st = cache_state(at, login, now(), since=asked)
        if st == "use":
            if not items:                                      # 一覧が描かれる前に渡した = 読めていない
                raise RuntimeError("Edge から購入履歴が0件で届きました (一覧が描かれる前)")
            return items
        if st == "login":
            raise RuntimeError("メルカリのログインが要ります (Edge で開いたタブでログインしてください)")
    raise RuntimeError("Edge の拡張から購入履歴が届きません (Edge の拡張「Seller Hub レポート取り」3.4 以上と神風が動いているか)")


_PRICE = re.compile(r'data-testid="price"[^>]*>\s*<span[^>]*>[¥￥]</span>\s*<span>([\d,]+)</span>')


def parse_item_price(src):
    """商品ページの HTML → 値段 (円, 送料込み)。読めなければ None (純関数)。"""
    m = _PRICE.search(src or "")
    return int(m.group(1).replace(",", "")) if m else None


def item_prices(ids):
    """買った商品の値段 {id: 円} (I/O)。★ログインしない Chrome で商品ページを読む。

    ユーザー (2026-09-24)「メルカリも仕入値入るの？」→「うん」。購入履歴の一覧には値段が無く、
    取引画面はより強い本人確認を求めてログインが切れた。商品ページは売り切れ後も値段が残る。
    入るのは出品価格 (送料込み)。ポイント・クーポンで引いた分は反映されない。
    """
    if not ids:
        return {}
    import undetected_chromedriver as uc
    from mercari_psa_resource import _chrome_major, _quiet_chromedriver
    _quiet_chromedriver()
    o = uc.ChromeOptions()
    for a in ("--headless=new", "--lang=ja-JP", "--window-size=1280,1400"):
        o.add_argument(a)
    maj = _chrome_major()
    d = uc.Chrome(options=o, version_main=maj) if maj else uc.Chrome(options=o)
    out = {}
    try:
        for mid in ids:
            d.get("https://jp.mercari.com/item/" + mid)
            for _ in range(10):
                time.sleep(1.5)
                v = parse_item_price(d.page_source)
                if v:
                    out[mid] = v
                    break
    finally:
        d.quit()
    return out


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
    for p in fetch_purchases():
        print(p["at"], p["url"], p["title"][:40])
