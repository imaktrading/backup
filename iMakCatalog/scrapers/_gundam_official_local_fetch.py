"""Gundam 公式 gundam-gcg.com cardlist ローカル fetch.

依頼: ユーザー指示 (2026-05-30) 「Gundam 公式 全 series 網羅」

flow:
  1. Selenium で各 series page 開く (= JS render 待ち)
  2. list page の全 card 構造抽出 (= modal 系 or list+detail 系を自動判別)
  3. JSON 出力

実行:
  python iMakCatalog/scrapers/_gundam_official_local_fetch.py --probe
  python iMakCatalog/scrapers/_gundam_official_local_fetch.py
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

from bs4 import BeautifulSoup

BASE = "https://www.gundam-gcg.com"
LIST_URL = f"{BASE}/jp/cards/"

DUMP_DIR = Path("C:/dev/iMak_data/catalog/_gundam_official_dumps")
CHECKPOINT_FILE = DUMP_DIR / "_progress.json"
RAW_HTML_DIR = DUMP_DIR / "_raw_html"

RATE_MIN_SEC = 6.0
RATE_JITTER_SEC = 4.0

# series ID list (= 公式 HTML data-val より、 2026-05-30 現在)
SERIES_LIST = [
    ("615101", "Newtype Rising [GD01]"),
    ("615102", "Dual Impact [GD02]"),
    ("615103", "Steel Requiem [GD03]"),
    ("615104", "Phantom Aria [GD04]"),
    ("615001", "Heroic Beginnings [ST01]"),
    ("615002", "Wings of Advance [ST02]"),
    ("615003", "Zeon's Rush [ST03]"),
    ("615004", "SEED Strike [ST04]"),
    ("615005", "Iron Bloom [ST05]"),
    ("615006", "Clan Unity [ST06]"),
    ("615007", "Celestial Drive [ST07]"),
    ("615008", "Flash of Radiance [ST08]"),
    ("615009", "Destiny Ignition [ST09]"),
    # 2026-07-23 新弾追加 (公式 cardlist data-val 実機確認)
    ("615010", "Generation Pulse [ST10]"),
    ("615201", "Eternal Nexus [EB01]"),
    ("615105", "Freedom Ascension [GD05]"),
    ("615301", "カスタムデッキボックス Freedom Ascension [SC01]"),
    ("615701", "限定商品収録カード"),
    ("615000", "リミテッドBOX Ver.β"),
    ("615801", "基本カード"),
    ("615901", "プロモーションカード"),
]


def polite_sleep():
    time.sleep(RATE_MIN_SEC + random.uniform(0, RATE_JITTER_SEC))


def _start_driver():
    import undetected_chromedriver as uc
    opts = uc.ChromeOptions()
    opts.add_argument("--lang=ja-JP")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-blink-features=AutomationControlled")
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


def fetch_list_html(driver, series_id: str, save_raw: bool = True) -> str | None:
    """series page の 動的 render 後 HTML 取得.

    Gundam 公式は URL `?series=` を JS が読まないため、
    page 開いてから収録弾ボタン click → render 待ちが必要。
    """
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.by import By

    # 1. cardlist top page を開く (= initial render 終わるまで待つ)
    driver.get(LIST_URL)
    try:
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a.js-selectBtn-package"))
        )
    except Exception:
        print(f"  ⚠️ initial page render timeout")
        html = driver.page_source
        if save_raw:
            RAW_HTML_DIR.mkdir(parents=True, exist_ok=True)
            (RAW_HTML_DIR / f"series_{series_id}_init.html").write_text(html, encoding="utf-8")
        return html
    time.sleep(2)

    # 2. 該当 series ボタンを JS で click (= スクロール不要)
    try:
        driver.execute_script(
            "document.querySelector('a.js-selectBtn-package[data-val=\"' + arguments[0] + '\"]').click();",
            series_id,
        )
        print(f"  → clicked series {series_id}")
    except Exception as e:
        print(f"  ⚠️ click fail: {e}")
        return None

    # 3. card 要素 render 待ち
    candidates = ["li.cardItem", "dl.modalCol", ".card-item", ".cardCol",
                  ".result-card", ".searchResult .card"]
    found = False
    for sel in candidates:
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, sel))
            )
            print(f"  ✓ render detected via {sel}")
            found = True
            break
        except Exception:
            continue
    if not found:
        print(f"  ⚠️ {series_id}: no card element after click (tried {len(candidates)} selectors)")
    time.sleep(3)
    html = driver.page_source
    if save_raw:
        RAW_HTML_DIR.mkdir(parents=True, exist_ok=True)
        (RAW_HTML_DIR / f"series_{series_id}.html").write_text(html, encoding="utf-8")
    return html


def parse_cards(html: str, series_id: str) -> list[dict]:
    """list HTML から各 card 抽出 (= 複数 selector 試行で自動判別)."""
    soup = BeautifulSoup(html, "html.parser")
    cards: list[dict] = []

    # Try 1: OPCG 系 modal (dl.modalCol)
    for dl in soup.select("dl.modalCol"):
        cid = dl.get("id") or ""
        if not cid:
            continue
        out = {"card_id": cid, "series_id": series_id, "_parser": "modalCol"}
        info = dl.select_one(".infoCol")
        if info:
            spans = [s.get_text(strip=True) for s in info.find_all("span")]
            if spans:
                out["card_number"] = spans[0] if len(spans) >= 1 else ""
                out["rarity"] = spans[1] if len(spans) >= 2 else ""
                out["type"] = spans[2] if len(spans) >= 3 else ""
        name = dl.select_one(".cardName")
        if name:
            out["name_jp"] = name.get_text(strip=True)
        img = dl.select_one(".frontCol img.lazy") or dl.select_one("img.lazy")
        if img:
            src = img.get("data-src") or img.get("src") or ""
            if src.startswith("../"):
                src = BASE + "/jp/cards/" + src.replace("../../", "")
            elif src.startswith("/"):
                src = BASE + src
            out["image_url"] = src.split("?")[0]
        for cls in ("cost", "power", "counter", "color", "block", "feature", "text",
                    "level", "ap", "hp", "linkCondition"):
            div = dl.select_one(f".{cls}")
            if div:
                h3 = div.find("h3")
                if h3:
                    h3.extract()
                val = div.get_text(" ", strip=True)
                if val:
                    out[cls] = val
        cards.append(out)

    if cards:
        return cards

    # Try 2: DBFW/Gundam 系 (li.cardItem with detail link)
    # DBFW pattern: data-src="detail.php?card_no=FB10-001"
    # Gundam pattern: data-src="detail.php?detailSearch=GD01-001"
    seen_ids = set()
    for li in soup.select("li.cardItem"):
        a = li.find("a", attrs={"data-src": True}) or li.find("a", href=True)
        if not a:
            continue
        ds = a.get("data-src", "") or a.get("href", "")
        m = re.search(r"(?:card_no|detailSearch)=([\w-]+)(?:&p=(_p\d+))?", ds)
        if not m:
            continue
        cid = m.group(1)
        if m.lastindex and m.lastindex >= 2 and m.group(2):
            cid = f"{cid}{m.group(2)}"
        if cid in seen_ids:
            continue
        seen_ids.add(cid)
        img = li.find("img")
        out = {"card_id": cid, "series_id": series_id, "_parser": "cardItem"}
        if img:
            src = img.get("data-src") or img.get("src") or ""
            if src.startswith("../"):
                src = BASE + "/jp/cards/" + src.replace("../../", "")
            elif src.startswith("/"):
                src = BASE + src
            out["image_url"] = src.split("?")[0]
            out["name_jp"] = img.get("alt", "")
        cards.append(out)

    return cards


def fetch_detail(session, card_id: str, save_raw: bool = True) -> dict:
    """detail.php from card_id → spec 抽出.

    Gundam: detail.php?detailSearch=GD01-001
    """
    import requests
    base_url = f"{BASE}/jp/cards/detail.php?detailSearch={card_id}"
    try:
        r = session.get(base_url, timeout=20)
        if r.status_code != 200:
            return {}
    except Exception:
        return {}
    if save_raw:
        det_dir = DUMP_DIR / "_raw_detail_html"
        det_dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w\-]", "_", card_id)
        (det_dir / f"{safe}.html").write_text(r.text, encoding="utf-8")
    soup = BeautifulSoup(r.text, "html.parser")
    out: dict = {"url": base_url}
    # dl/dt/dd
    for dl in soup.find_all("dl"):
        for dt, dd in zip(dl.find_all("dt"), dl.find_all("dd")):
            k = dt.get_text(" ", strip=True).rstrip(":").strip()
            v = dd.get_text(" ", strip=True)
            if k and v:
                out[k] = v
    # table tr (= th/td)
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["th", "td"], recursive=False)
        if len(cells) == 2 and cells[0].name == "th":
            k = cells[0].get_text(" ", strip=True).rstrip(":").strip()
            v = cells[1].get_text(" ", strip=True)
            if k and v:
                out[k] = v
    return out


def cmd_series_one(driver, series_id: str, series_name: str, fetch_detail_too: bool = True):
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    polite_sleep()
    print(f"=== {series_id} ({series_name}) ===")
    html = fetch_list_html(driver, series_id)
    if not html:
        return None
    cards = parse_cards(html, series_id)
    parser_kind = cards[0].get("_parser", "?") if cards else "?"
    print(f"  ✓ list: {len(cards)} cards (parser={parser_kind})")

    # cardItem parser の場合 detail.php fetch で spec 補完
    if fetch_detail_too and parser_kind == "cardItem" and cards:
        import requests
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "ja,en;q=0.8",
        })
        for i, c in enumerate(cards, 1):
            polite_sleep()
            d = fetch_detail(session, c["card_id"])
            if d:
                c.update(d)
            if i % 20 == 0:
                print(f"  ... detail {i}/{len(cards)}")

    out_file = DUMP_DIR / f"series_{series_id}.json"
    out_file.write_text(
        json.dumps({"series_id": series_id, "series_name": series_name, "cards": cards},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  ✓ saved {out_file.name}")
    return {"series_id": series_id, "count": len(cards), "parser": parser_kind}


def load_checkpoint() -> set[str]:
    if CHECKPOINT_FILE.exists():
        return set(json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8")))
    return set()


def save_checkpoint(done: set[str]):
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_FILE.write_text(json.dumps(sorted(done)), encoding="utf-8")


def cmd_all(resume: bool = True):
    """各 series ごとに driver 再起動 (= long-running session 切断対策).

    2026-05-30 fix: 2 series 完走後 driver session 切断問題 → 各 series 独立 driver。
    """
    done = load_checkpoint() if resume else set()
    print(f"=== Gundam 公式 全 series fetch ({len(SERIES_LIST)} series, "
          f"checkpoint={len(done)} done) ===")
    for sid, sname in SERIES_LIST:
        if sid in done:
            print(f"  ☐ {sid} ({sname}): skip")
            continue
        driver = None
        try:
            driver = _start_driver()
            res = cmd_series_one(driver, sid, sname)
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
        sid = args.series or "615101"
        sname = next((n for s, n in SERIES_LIST if s == sid), sid)
        driver = _start_driver()
        try:
            cmd_series_one(driver, sid, sname)
        finally:
            driver.quit()
        return
    cmd_all(resume=not args.no_resume)


if __name__ == "__main__":
    main()
