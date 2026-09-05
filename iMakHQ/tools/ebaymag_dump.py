#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eBaymag の画面を **最後までスクロールして** テキストに落とす (2026-09-06).

なぜ:
    ポリシー一覧のように縦に長い画面は、手でスクロールしないとコピーが取れない。
    しかも途中で描画が差し替わる作りだと、一度に全部は選択できない。
    スクロールしながら見えた行を拾い集めて、重複を落として1本のテキストにする。

使い方:
    # 1回目だけ: ログインする (ブラウザが開くので手で入って Enter)
    python ebaymag_dump.py --login

    # 2回目以降: 見たい画面の URL を渡す
    python ebaymag_dump.py --url https://ebaymag.com/policies

    出力先は既定でデスクトップ (--out で変えられる):
        ebaymag_<画面名>_<日時>.txt   画面の文字 (これをコピーする)
        ebaymag_<画面名>_<日時>.html  後から拾い直す用の元データ

安全側の作り:
    - ログイン情報は **HQ 専用のプロファイル**に置く。監視くんの eBay ログイン
      プロファイル (iMakInventory 配下) は触らない。あれは巡回の生命線で、
      同時に開くと壊れる (memory: failclosed_must_skip_not_destructive)。
    - Chrome の version は **数値で固定しない** (全worktree横断ルール 2026-06-13)。
    - ログインしていない画面を黙って保存しない。その場で止めて理由を出す。
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import datetime

sys.path.insert(0, r"C:\dev\iMak\iMakeBayAPI")
try:
    import dns_cache  # noqa: F401  ★これが無いと getaddrinfo failed になる (この環境の作法)
except Exception:                                                 # noqa: BLE001
    pass

try:
    from chrome_util import detect_chrome_major, silence_chromedriver_console
except Exception:                                                 # noqa: BLE001
    def detect_chrome_major():
        return None

    def silence_chromedriver_console():
        return None

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE = os.path.join(HQ, "chrome_profile_ebaymag")
DESKTOP = os.path.join(os.path.expanduser("~"), "OneDrive", "デスクトップ")
HOME = "https://ebaymag.com/"


# ── 純関数 (test 可) ────────────────────────────────────────────────
def merge_seen(chunks):
    """スクロール中に拾った複数の画面テキスト → 重複を落として1本にする。

    同じ行が何度も出るのは、スクロールのたびに見出しや前の行が入るため。
    **順番は最初に出てきた位置を保つ** (並べ替えると一覧として読めなくなる)。
    """
    out, seen = [], set()
    for chunk in chunks:
        for line in (chunk or "").splitlines():
            s = line.strip()
            if not s or s in seen:
                continue
            seen.add(s)
            out.append(s)
    return out


def looks_logged_out(url, text):
    """ログイン前の画面か。保存してから気づくのを防ぐ。"""
    if re.search(r"/(login|signin|sign_in|auth)\b", url or "", re.I):
        return True
    t = (text or "")[:2000].lower()
    if not t.strip():
        return True
    return ("sign in" in t or "log in" in t or "ログイン" in t) and "policy" not in t


def out_name(url, when=None):
    """URL → 出力ファイル名の芯 (画面が分かる名前にする)。"""
    when = when or datetime.now()
    slug = re.sub(r"[^A-Za-z0-9]+", "_", re.sub(r"^https?://[^/]+/?", "", url or "")).strip("_")
    return "ebaymag_%s_%s" % (slug or "home", when.strftime("%Y%m%d_%H%M%S"))


# ── ブラウザ ────────────────────────────────────────────────────────
def open_browser(headless=False):
    import undetected_chromedriver as uc
    silence_chromedriver_console()
    os.makedirs(PROFILE, exist_ok=True)
    opts = uc.ChromeOptions()
    opts.add_argument("--user-data-dir=%s" % PROFILE)
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1400,1000")
    if headless:
        opts.add_argument("--headless=new")
    maj = detect_chrome_major()
    return uc.Chrome(options=opts, version_main=maj) if maj else uc.Chrome(options=opts)


_SCROLLER_JS = """
// 一番よくスクロールする要素を選ぶ (ページ全体が動かない作りへの対策)
let best = document.scrollingElement || document.body, gap = 0;
for (const el of document.querySelectorAll('*')) {
  const g = el.scrollHeight - el.clientHeight;
  if (g > gap && el.clientHeight > 200) { gap = g; best = el; }
}
return [best === (document.scrollingElement || document.body) ? 'page' : 'inner',
        best.scrollHeight, best.clientHeight];
"""

_SCROLL_STEP_JS = """
let best = document.scrollingElement || document.body, gap = 0;
for (const el of document.querySelectorAll('*')) {
  const g = el.scrollHeight - el.clientHeight;
  if (g > gap && el.clientHeight > 200) { gap = g; best = el; }
}
best.scrollTop = best.scrollTop + Math.floor(best.clientHeight * 0.8);
return [best.scrollTop, best.scrollHeight];
"""


def scroll_and_collect(driver, pause=0.7, max_steps=400):
    """最後まで送りながら、その都度 見えている文字を集める。

    途中で描画が差し替わる作り (仮想スクロール) でも取りこぼさないよう、
    **1画面ごとに拾って** 最後にまとめる。
    """
    chunks, last_top, stuck = [], -1, 0
    kind, h, ch = driver.execute_script(_SCROLLER_JS)
    print("[INFO] スクロール対象=%s  高さ=%s / 画面=%s" % (kind, h, ch))
    for i in range(max_steps):
        chunks.append(driver.execute_script("return document.body.innerText;"))
        top, height = driver.execute_script(_SCROLL_STEP_JS)
        time.sleep(pause)
        if top == last_top:
            stuck += 1
            if stuck >= 3:                       # 3回動かなければ最後まで来た
                break
        else:
            stuck = 0
        last_top = top
        if i and i % 20 == 0:
            print("   … %d画面ぶん (位置 %s / %s)" % (i, top, height))
    chunks.append(driver.execute_script("return document.body.innerText;"))
    return chunks


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                             # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="", help="落としたい画面の URL")
    ap.add_argument("--login", action="store_true",
                    help="ログインだけする (ブラウザが開くので手で入って Enter)")
    ap.add_argument("--out", default=DESKTOP, help="出力先フォルダ (既定: デスクトップ)")
    ap.add_argument("--wait", type=float, default=6.0, help="開いてから待つ秒数")
    ap.add_argument("--pause", type=float, default=0.7, help="1スクロールごとの待ち秒")
    ap.add_argument("--headless", action="store_true", help="窓を出さずに走らせる")
    a = ap.parse_args()

    if not a.login and not a.url:
        print("URL を渡してください。初回は先に --login でログインを。")
        return 2

    driver = open_browser(headless=a.headless and not a.login)
    try:
        if a.login:
            driver.get(HOME)
            print("ブラウザで eBaymag にログインしてください。")
            print("済んだらこの画面で Enter を押す (ログインはこの端末に残ります)")
            try:
                input()
            except EOFError:
                print("※ 対話できない環境です。窓が開いている間に入ってください (60秒待ちます)")
                time.sleep(60)
            print("[OK] プロファイル: %s" % PROFILE)
            if not a.url:
                return 0

        driver.get(a.url)
        time.sleep(a.wait)
        head = driver.execute_script("return document.body.innerText;")
        if looks_logged_out(driver.current_url, head):
            print("⚠️ ログインしていない画面に見えます (%s)" % driver.current_url)
            print("   先に `python ebaymag_dump.py --login` を実行してください。")
            print("   ※ 中身は保存していません (ログイン画面を保存しても意味がないため)")
            return 1

        chunks = scroll_and_collect(driver, pause=a.pause)
        lines = merge_seen(chunks)
        html = driver.page_source

        os.makedirs(a.out, exist_ok=True)
        stem = out_name(a.url)
        txt_p = os.path.join(a.out, stem + ".txt")
        html_p = os.path.join(a.out, stem + ".html")
        with open(txt_p, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        with open(html_p, "w", encoding="utf-8") as f:
            f.write(html)
        print("\n[OK] %d行 取れました" % len(lines))
        print("  文字   : %s" % txt_p)
        print("  元データ: %s" % html_p)
        return 0
    finally:
        try:
            driver.quit()
        except Exception:                                         # noqa: BLE001
            pass


if __name__ == "__main__":
    raise SystemExit(main())
