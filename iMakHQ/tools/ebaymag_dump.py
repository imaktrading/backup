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
# ★2026-09-06 ユーザー指摘「何回もログインボタン押さなあかん」。
#   eBaymag のログイン cookie は **セッション限り** (has_expires=0) なので、
#   Chrome を閉じた瞬間に消える。プロファイルを共有しても残らない。
#   閉じる前に自分で書き出し、開いた後に流し込む。共有領域に置く (鍵と同じ扱い)。
COOKIE_FILE = r"C:\dev\iMak_data\credentials\ebaymag_cookies.json"


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


def merge_rows(batches):
    """スクロール中に拾った行 (セルのリスト) → 重複を落として1本にする。

    ★行ごと丸ごとで重複を見る (2026-09-06)。1行1行を文字として畳むと、
      「7」「いいえ」のような **どの行にも出る値が消えて列が壊れる**
      (実際、最初の版で 180件のポリシーの時間と返品可が全部落ちた)。
    """
    out, seen = [], set()
    for batch in batches or []:
        for row in batch or []:
            cells = [str(c).replace("\n", " ").strip() for c in row]
            if not any(cells):
                continue
            key = "\t".join(cells)
            if key in seen:
                continue
            seen.add(key)
            out.append(cells)
    return out


def looks_logged_out(url, text):
    """ログイン前の画面か。保存してから気づくのを防ぐ。

    ★2026-09-06: **eBaymag に居ること**を先に見る。以前は文字だけで見ていたので、
      Google のパスワード画面を「入れた」と誤判定した (そこでは何も取れない)。
    """
    u = url or ""
    if not re.match(r"https?://(www\.)?ebaymag\.com(/|$)", u, re.I):
        return True                       # 認証の途中 / 別サイト = まだ
    if re.search(r"/(login|signin|sign_in|auth)\b", u, re.I):
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


def save_cookies(driver, path=COOKIE_FILE):
    """セッション限りの cookie も含めて書き出す (CDP は expires 無しも返す)。"""
    import json
    try:
        ck = driver.execute_cdp_cmd("Network.getAllCookies", {}).get("cookies", [])
        ck = [c for c in ck if "ebaymag" in (c.get("domain") or "")]
        if not ck:
            return 0
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(ck, f, ensure_ascii=False)
        return len(ck)
    except Exception as e:                                        # noqa: BLE001
        print("(cookie の保存に失敗: %s)" % type(e).__name__)
        return 0


def load_cookies(driver, path=COOKIE_FILE):
    """前回の cookie を流し込む。無ければ何もしない (ログインを求められるだけ)。"""
    import json
    if not os.path.exists(path):
        return 0
    try:
        with open(path, encoding="utf-8") as f:
            ck = json.load(f)
    except Exception:                                             # noqa: BLE001
        return 0
    n = 0
    for c in ck:
        d = {k: c[k] for k in ("name", "value", "domain", "path") if k in c}
        for k in ("secure", "httpOnly", "sameSite"):
            if c.get(k) not in (None, ""):
                d[k] = c[k]
        # セッション限りだったものは **期限を付けて**保存し直す (閉じても消えないように)
        d["expires"] = c.get("expires") or (time.time() + 60 * 60 * 24 * 14)
        try:
            driver.execute_cdp_cmd("Network.setCookie", d)
            n += 1
        except Exception:                                         # noqa: BLE001
            pass
    return n


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


# 表の行 (role=row / セルは role=cell)。eBaymag のポリシー一覧はこの作り。
_ROWS_JS = """
return Array.from(document.querySelectorAll('[role="row"]')).map(r => {
  const cells = r.querySelectorAll('[role="cell"],[role="gridcell"],[role="columnheader"]');
  return Array.from(cells.length ? cells : r.children).map(c => (c.innerText||'').trim());
});
"""


def wait_until_loaded(driver, seconds=60, poll=2.0):
    """一覧が出るまで待つ。**決め打ちの秒数で諦めない** (2026-09-06)。

    eBaymag は開いた直後「配送ポリシーを読み込んでいます...」だけを出す。
    そこで拾うと 0行のファイルができて、取れたのか失敗したのか分からない。
    """
    end = time.time() + seconds
    while time.time() < end:
        n = len(driver.execute_script(_ROWS_JS) or [])
        if n > 1:
            return n
        time.sleep(poll)
    return 0


def scroll_and_collect(driver, pause=0.7, max_steps=400):
    """最後まで送りながら、その都度 見えている中身を集める。

    途中で描画が差し替わる作り (仮想スクロール = 見えている行しか無い) なので、
    **1画面ごとに拾って** 最後にまとめる。
    表があれば行として、無ければ文字として拾う。
    戻り: (行のかたまり[], 文字のかたまり[])
    """
    batches, chunks, last_top, stuck = [], [], -1, 0
    kind, h, ch = driver.execute_script(_SCROLLER_JS)
    print("[INFO] スクロール対象=%s  高さ=%s / 画面=%s" % (kind, h, ch))
    for i in range(max_steps):
        batches.append(driver.execute_script(_ROWS_JS))
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
            print("   … %d画面ぶん (位置 %s / %s / ここまで %d行)"
                  % (i, top, height, len(merge_rows(batches))))
    batches.append(driver.execute_script(_ROWS_JS))
    chunks.append(driver.execute_script("return document.body.innerText;"))
    return batches, chunks


def wait_for_login(driver, seconds=300, poll=3.0):
    """ログインが済むまで待つ。**Enter を押させない** (2026-09-06)。

    以前は input() で待っていたが、こちらから走らせると入力が届かず
    決め打ちの秒数で待つしかなかった。画面を見て、入れた瞬間に進む。
    戻り: 入れたか (bool)
    """
    end = time.time() + seconds
    while time.time() < end:
        try:
            txt = driver.execute_script("return document.body.innerText;")
            if not looks_logged_out(driver.current_url, txt):
                return True
        except Exception:                                         # noqa: BLE001
            pass
        left = int(end - time.time())
        print("   ログイン待ち… あと %d秒 (%s)" % (left, driver.current_url[:60]))
        time.sleep(poll)
    return False


def collect_links(driver):
    """画面内のリンク [(文字, URL)]。どの画面を落とせばいいか探す用。"""
    try:
        pairs = driver.execute_script(
            "return Array.from(document.querySelectorAll('a[href]'))"
            ".map(a => [ (a.innerText||'').trim(), a.href ]);")
    except Exception:                                             # noqa: BLE001
        return []
    out, seen = [], set()
    for t, u in pairs or []:
        if not u or u in seen:
            continue
        seen.add(u)
        out.append((t, u))
    return out


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                             # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="", help="落としたい画面の URL")
    ap.add_argument("--login", action="store_true",
                    help="ブラウザを開いてログインを待つ (入れたら自動で進む)")
    ap.add_argument("--login-seconds", type=int, default=300,
                    help="ログインを待つ秒数 (既定 300)")
    ap.add_argument("--out", default=DESKTOP, help="出力先フォルダ (既定: デスクトップ)")
    ap.add_argument("--wait", type=float, default=6.0, help="開いてから待つ秒数")
    ap.add_argument("--load-seconds", type=int, default=60,
                    help="一覧が出るまで待つ秒数 (既定 60)")
    ap.add_argument("--pause", type=float, default=0.7, help="1スクロールごとの待ち秒")
    ap.add_argument("--headless", action="store_true", help="窓を出さずに走らせる")
    a = ap.parse_args()

    if not a.login and not a.url:
        print("URL を渡してください。初回は先に --login でログインを。")
        return 2

    driver = open_browser(headless=a.headless and not a.login)
    try:
        # 前回の cookie を先に流し込む (これが無いと毎回ログインを聞かれる)
        driver.get(HOME)
        n_ck = load_cookies(driver)
        if n_ck:
            print("[INFO] 前回の cookie を %d本 復元しました" % n_ck)
            driver.get(HOME)
            time.sleep(3)

        if a.login or looks_logged_out(
                driver.current_url, driver.execute_script("return document.body.innerText;")):
            print("ブラウザで eBaymag にログインしてください (次回からは聞かれません)")
            print("入れたら自動で先へ進みます。Enter は要りません。")
            if not wait_for_login(driver, a.login_seconds):
                print("⚠️ 時間内にログインを確認できませんでした (%s)" % driver.current_url)
                print("   --login-seconds を伸ばして、もう一度やってみてください。")
                return 1
            print("[OK] ログインを確認しました (cookie %d本 保存)" % save_cookies(driver))
            if not a.url:
                a.url = driver.current_url        # 入った先の画面をそのまま落とす

        driver.get(a.url)
        time.sleep(a.wait)
        head = driver.execute_script("return document.body.innerText;")
        if looks_logged_out(driver.current_url, head):
            print("⚠️ ログインしていない画面に見えます (%s)" % driver.current_url)
            print("   ※ 中身は保存していません (ログイン画面を保存しても意味がないため)")
            return 1
        save_cookies(driver)                      # 使えた cookie を最新にしておく

        n0 = wait_until_loaded(driver, a.load_seconds)
        print("[INFO] 一覧の初期行数: %d" % n0)
        batches, chunks = scroll_and_collect(driver, pause=a.pause)
        rows = merge_rows(batches)
        lines = merge_seen(chunks)
        html = driver.page_source
        links = collect_links(driver)

        os.makedirs(a.out, exist_ok=True)
        stem = out_name(a.url)
        txt_p = os.path.join(a.out, stem + ".txt")
        html_p = os.path.join(a.out, stem + ".html")
        links_p = os.path.join(a.out, stem + ".links.txt")
        with open(txt_p, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        with open(html_p, "w", encoding="utf-8") as f:
            f.write(html)
        with open(links_p, "w", encoding="utf-8") as f:
            f.write("\n".join("%s\t%s" % (t.replace("\n", " "), u) for t, u in links))
        print("\n[OK] 文字 %d行 / リンク %d本" % (len(lines), len(links)))
        print("  文字   : %s" % txt_p)
        print("  リンク : %s" % links_p)
        print("  元データ: %s" % html_p)
        if rows:
            csv_p = os.path.join(a.out, stem + ".csv")
            import csv as _csv
            width = max(len(r) for r in rows)
            with open(csv_p, "w", newline="", encoding="utf-8-sig") as f:
                w = _csv.writer(f)
                for r in rows:
                    w.writerow(r + [""] * (width - len(r)))
            print("  表     : %s  (%d行 × %d列)" % (csv_p, len(rows), width))
        else:
            print("  ※ 表の行が見つからなかったので CSV は出していません")
        return 0
    finally:
        try:
            driver.quit()
        except Exception:                                         # noqa: BLE001
            pass


if __name__ == "__main__":
    raise SystemExit(main())
