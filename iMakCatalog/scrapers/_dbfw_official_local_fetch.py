"""DBFW 公式 dbs-cardgame.com/fw cardlist ローカル fetch.

依頼: ユーザー指示 (2026-05-30) 「公式 source 全 TCG 網羅」
+ DBFW 公式 = JS 動的 render → Selenium で list page、 detail.php は requests。

flow:
  1. series ID list (= 25 series) で各 list page を Selenium 走査
  2. 各 card_id を抽出 (= `<li class="cardItem">` の data-src から)
  3. 各 card_id で detail.php fetch (= requests)
  4. spec 抽出 (= dl/dt/dd) + JSON 出力

実行:
  python iMakCatalog/scrapers/_dbfw_official_local_fetch.py --probe         # 1 series 試行
  python iMakCatalog/scrapers/_dbfw_official_local_fetch.py                  # 全 series 連鎖
  python iMakCatalog/scrapers/_dbfw_official_local_fetch.py --series 584010  # FB10 のみ

必要 install:
  pip install undetected-chromedriver selenium beautifulsoup4 requests
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import requests
from bs4 import BeautifulSoup

BASE = "https://www.dbs-cardgame.com"
LIST_URL = f"{BASE}/fw/jp/cardlist/"
DETAIL_URL = f"{BASE}/fw/jp/cardlist/detail.php?card_no={{card_no}}"

DUMP_DIR = Path("C:/dev/iMak_data/catalog/_dbfw_official_dumps")
CHECKPOINT_FILE = DUMP_DIR / "_progress.json"
RAW_DETAIL_DIR = DUMP_DIR / "_raw_detail_html"

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.8",
}

RATE_MIN_SEC = 6.0
RATE_JITTER_SEC = 4.0

# series ID list (= 公式 HTML data-val より、 2026-05-30 現在)
SERIES_LIST = [
    ("584010", "ブースターパック CROSS FORCE [FB10]"),
    ("584009", "ブースターパック DUAL EVOLUTION [FB09]"),
    ("584008", "ブースターパック 誇り高き戦闘民族 [FB08]"),
    ("584007", "ブースターパック 神龍への願い [FB07]"),
    ("584006", "ブースターパック 迫り来る脅威 [FB06]"),
    ("584005", "ブースターパック 未知なる冒険 [FB05]"),
    ("584004", "ブースターパック 限界を超えし者 [FB04]"),
    ("584003", "ブースターパック 怒りの咆哮 [FB03]"),
    ("584002", "ブースターパック 烈火の闘気 [FB02]"),
    ("584001", "ブースターパック 覚醒の鼓動 [FB01]"),
    ("584201", "MANGA BOOSTER 01 [SB01]"),
    ("584202", "MANGA BOOSTER 02 [SB02]"),
    ("584112", "スタートデッキEX 気の躍動 [FS12]"),
    ("584111", "スタートデッキEX 進化の境地 [FS11]"),
    ("584110", "スタートデッキEX ジブレット [FS10]"),
    ("584109", "スタートデッキEX シャロット [FS09]"),
    ("584108", "スタートデッキ ベジータ(ミニ) 超サイヤ人3 [FS08]"),
    ("584107", "スタートデッキ ベジータ(ミニ) [FS07]"),
    ("584106", "スタートデッキ 孫悟空(ミニ) [FS06]"),
    ("584105", "スタートデッキ バーダック [FS05]"),
    ("584104", "スタートデッキ フリーザ [FS04]"),
    ("584103", "スタートデッキ ブロリー [FS03]"),
    ("584102", "スタートデッキ ベジータ [FS02]"),
    ("584101", "スタートデッキ 孫悟空 [FS01]"),
    ("584901", "プロモーションカード"),
]


def polite_sleep():
    time.sleep(RATE_MIN_SEC + random.uniform(0, RATE_JITTER_SEC))


def _start_driver():
    """undetected_chromedriver 起動 (= Chrome 148 を明示)."""
    import undetected_chromedriver as uc
    opts = uc.ChromeOptions()
    opts.add_argument("--lang=ja-JP")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    # version_main を Chrome 148 に固定 (= driver 149 と installed 148 の mismatch fix)
    # 2026-06-14: version_main を実機 Chrome 自動検出 (旧 148 固定。Chrome更新で mismatch→orphan回避)。
    try:
        import os as _os, sys as _sys
        _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
        from _chrome_version import installed_chrome_major as _icm
        _vm = _icm(148)
    except Exception:
        _vm = 148
    drv = uc.Chrome(options=opts, version_main=_vm)

    drv.set_page_load_timeout(60)
    return drv


def fetch_list_card_ids(driver, series_id: str) -> list[str]:
    """Selenium で list page から card_id 一覧抽出.

    2026-05-30 fix: ?series= URL は JS で読まれず無視されていた。
    正しい URL: `?search=true&category[0]=NNN` (= meta og:url 経由判明)。
    """
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.by import By

    # URL filter 試行
    url = f"{LIST_URL}?search=true&category%5B0%5D={series_id}"
    driver.get(url)
    try:
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "li.cardItem"))
        )
    except Exception:
        print(f"  ⚠️ {series_id}: list render timeout")
        return []
    time.sleep(3)
    # render 後の URL 確認 = filter 効いてるなら category[0]=NNN が残る
    cur_url = driver.current_url
    # 念のため JS click でも filter 実行 (= URL では効かない site 対策)
    try:
        driver.execute_script(
            "var a=document.querySelector('a[data-val=\"' + arguments[0] + '\"]');"
            "if(a) a.click();",
            series_id,
        )
        time.sleep(5)  # filter render 待ち
    except Exception:
        pass

    soup = BeautifulSoup(driver.page_source, "html.parser")
    card_ids: list[str] = []
    seen = set()
    for li in soup.select("li.cardItem"):
        a = li.find("a", href=True) or li.find("a", attrs={"data-src": True})
        if not a:
            continue
        ds = a.get("data-src", "") or a.get("href", "")
        m = re.search(r"card_no=([\w-]+)(?:&p=(_p\d+))?", ds)
        if not m:
            continue
        cid = m.group(1)
        if m.group(2):
            cid = f"{cid}{m.group(2)}"  # 例 FB10-001_p1
        if cid in seen:
            continue
        seen.add(cid)
        card_ids.append(cid)
    return card_ids


def fetch_detail(session: requests.Session, card_id: str, save_raw: bool = True) -> dict | None:
    """detail.php from card_id → spec 抽出."""
    # card_id に _pN suffix あれば &p= で分離
    m = re.match(r"^(\w+-\d+)(_p\d+)?$", card_id)
    if not m:
        return None
    base = m.group(1)
    p = m.group(2) or ""
    url = DETAIL_URL.format(card_no=base) + (f"&p={p}" if p else "")
    try:
        r = session.get(url, timeout=20)
        if r.status_code != 200:
            return None
    except Exception:
        return None
    if save_raw:
        RAW_DETAIL_DIR.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w\-]", "_", card_id)
        (RAW_DETAIL_DIR / f"{safe}.html").write_text(r.text, encoding="utf-8")
    return parse_detail_html(r.text, card_id, url)


def parse_detail_html(html: str, card_id: str, url: str = "") -> dict:
    """DBFW detail HTML → spec dict (= h6 label + div.data value pair)."""
    soup = BeautifulSoup(html, "html.parser")
    out: dict = {"card_id": card_id, "url": url}
    # h6 label + 同階層の次 div.data を value とする
    for h6 in soup.find_all("h6"):
        label = h6.get_text(" ", strip=True).rstrip(":").strip()
        if not label:
            continue
        # 直後の sibling から div.data を順に探索
        sib = h6.find_next_sibling()
        values: list[str] = []
        while sib and sib.name not in ("h6",):
            if sib.name == "div" and "data" in (sib.get("class") or []):
                t = sib.get_text(" ", strip=True)
                # is-back (= 裏面) は別扱い、 表/裏で値違う場合 "FRONT / BACK" 形式で連結
                cls = sib.get("class") or []
                if "is-back" in cls:
                    values.append(f"(裏){t}")
                elif "is-front" in cls:
                    values.append(t)
                else:
                    values.append(t)
            sib = sib.find_next_sibling()
        if values:
            out[label] = " / ".join(v for v in values if v) if len(values) > 1 else values[0]
    # 画像
    img = soup.select_one("img.lazy[data-src*='/cards/card/']") or soup.find(
        "img", src=re.compile(r"/cards/card/")
    )
    if img:
        src = img.get("data-src") or img.get("src") or ""
        if src.startswith("../"):
            # 2026-06-23 サイトリニューアルで画像パスから /jp が除去された
            # (旧 /fw/jp/images/... → 新 /fw/images/...)。先頭の ../ を全て剥がして
            # /fw/ 配下に組む(末尾 .../images/cards/card/jp/XXX.webp はそのまま)。
            rel = re.sub(r"^(\.\./)+", "", src)
            src = BASE + "/fw/" + rel
        elif src.startswith("/"):
            src = BASE + src
        out["image_url"] = src.split("?")[0]
    name = soup.select_one("h1, .cardName, .name")
    if name:
        out["name"] = name.get_text(" ", strip=True)
    return out


def load_checkpoint() -> set[str]:
    if CHECKPOINT_FILE.exists():
        return set(json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8")))
    return set()


def save_checkpoint(done: set[str]):
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_FILE.write_text(json.dumps(sorted(done)), encoding="utf-8")


def cmd_series_one(driver, session, series_id, series_name):
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    polite_sleep()
    print(f"=== {series_id} ({series_name}) ===")
    card_ids = fetch_list_card_ids(driver, series_id)
    print(f"  list cards: {len(card_ids)}")
    if not card_ids:
        return None
    cards = []
    for i, cid in enumerate(card_ids, 1):
        polite_sleep()
        d = fetch_detail(session, cid)
        if d:
            d["series_id"] = series_id
            cards.append(d)
        if i % 20 == 0:
            print(f"  ... {i}/{len(card_ids)}")
    out_file = DUMP_DIR / f"series_{series_id}.json"
    out_file.write_text(
        json.dumps({"series_id": series_id, "series_name": series_name, "cards": cards},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  ✓ {len(cards)} cards saved")
    return {"series_id": series_id, "count": len(cards)}


def cmd_all(resume: bool = True):
    """各 series ごとに driver 再起動 (= long-running session 切断対策).

    2026-05-30 fix: 2 series 完走後 driver session 切断問題 → 各 series 独立 driver。
    """
    done = load_checkpoint() if resume else set()
    session = requests.Session()
    session.headers.update(UA)
    print(f"=== DBFW 公式 全 series fetch ({len(SERIES_LIST)} series, "
          f"checkpoint={len(done)} done) ===")
    for sid, sname in SERIES_LIST:
        if sid in done:
            print(f"  ☐ {sid} ({sname}): skip")
            continue
        # 各 series で driver 再起動 (= 安定性優先、 起動コスト ~5sec)
        driver = None
        try:
            driver = _start_driver()
            res = cmd_series_one(driver, session, sid, sname)
            if res:
                done.add(sid)
                save_checkpoint(done)
        except Exception as e:
            print(f"  ⚠️ {sid} fail: {e}")
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--probe", action="store_true")
    p.add_argument("--series", type=str)
    p.add_argument("--no-resume", action="store_true")
    args = p.parse_args()
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    if args.probe or args.series:
        sid = args.series or "584010"
        sname = next((n for s, n in SERIES_LIST if s == sid), sid)
        driver = _start_driver()
        session = requests.Session()
        session.headers.update(UA)
        try:
            cmd_series_one(driver, session, sid, sname)
        finally:
            driver.quit()
        return
    cmd_all(resume=not args.no_resume)


if __name__ == "__main__":
    main()
