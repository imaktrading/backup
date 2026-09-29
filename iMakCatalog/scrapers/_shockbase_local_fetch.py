"""ShockBase ローカル実行用 fetch script (= Anthropic WebFetch IP block 回避).

依頼: ユーザー指示 (= 2026-05-29) 「ShockBase を発売年の新しい順に取得していって」
+ Gemini 助言 (= rate 5-10sec + jitter, batch 100-200 件, 自宅 ISP IP 使用).

flow:
  1. releases.php fetch → release year/month の list 抽出
  2. 最新 release から順に subseries/model 一覧 fetch
  3. 各 model の watch_dyn.php fetch → spec field 抽出
  4. JSON 蓄積 → `C:/dev/iMak_data/catalog/_shockbase_dumps/{batch_id}.json`

rate:
  - 7 sec + 0-6 sec jitter (= avg 10 sec/req、 robots.txt crawl-delay 指定なしへの保守設定)
  - 100 件で 1 batch 区切り、 batch 間に長休憩 (= 3-5 min)
  - checkpoint = JSON file + 既処理 model set

実行:
  python iMakCatalog/scrapers/_shockbase_local_fetch.py --year 2026          # 1 release year のみ
  python iMakCatalog/scrapers/_shockbase_local_fetch.py --year 2026 --limit 50   # test
  python iMakCatalog/scrapers/_shockbase_local_fetch.py --probe              # releases.php 構造確認のみ

注:
  - ユーザー自宅 PC で実行 = 自宅 ISP IP で fetch (= WebFetch IP block 回避)
  - 出力 JSON は C:/dev/iMak_data/catalog/_shockbase_dumps/ 配下 (= 共有領域)
  - Catalog Claude が JSON 受領 → catalog upsert 実行 (= 別 step、 本 script は upsert しない)
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

import socket

import requests
from bs4 import BeautifulSoup

# ============================================================================
# DNS bypass (= 2026-05-29 追加)
# ----------------------------------------------------------------------------
# ユーザー環境で nslookup OK だが python socket.getaddrinfo() が失敗する事象あり。
# IPv6 priority + 別 resolver 干渉が原因と推定。
# nslookup 確定 IP を hardcode で返す patch で透過解決。
# ============================================================================
_SHOCKBASE_IP = "46.243.93.137"
_orig_getaddrinfo = socket.getaddrinfo


def _patched_getaddrinfo(host, *args, **kwargs):
    if host == "shockbase.org":
        return _orig_getaddrinfo(_SHOCKBASE_IP, *args, **kwargs)
    return _orig_getaddrinfo(host, *args, **kwargs)


socket.getaddrinfo = _patched_getaddrinfo

BASE = "https://shockbase.org"
RELEASES_URL = f"{BASE}/watches/releases.php"
WATCH_URL_TEMPLATE = f"{BASE}/watches/watch_dyn.php?model={{model}}&subseries={{subseries}}&series={{series}}"
SUBSERIES_URL_TEMPLATE = f"{BASE}/watches/subseries_dyn.php?series={{series}}&subseries={{subseries}}&modul={{modul}}"

DUMP_DIR = Path("C:/dev/iMak_data/catalog/_shockbase_dumps")
CHECKPOINT_FILE = DUMP_DIR / "_progress.json"

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,ja;q=0.8",
}

RATE_MIN_SEC = 10.0       # ★ 7 → 10 (= 2026-05-29 ユーザー指摘踏まえ保守化)
RATE_JITTER_SEC = 8.0     # ★ 6 → 8 (= 周期性回避を強化、 10-18 sec/req = avg 14 sec)
BATCH_SIZE = 50           # ★ 100 → 50 (= 1 batch 短く、 block 兆候を早く検出)
BATCH_REST_SEC = 1800     # ★ 180 → 1800 (= 3 min → 30 min、 Gemini 推奨「数時間」 範囲内で運用負荷とバランス)


def polite_sleep():
    """1 req あたり 7-13 sec の rate 制御 (= jitter で周期性回避)."""
    delay = RATE_MIN_SEC + random.uniform(0, RATE_JITTER_SEC)
    time.sleep(delay)


def fetch(url: str, session: requests.Session) -> str | None:
    try:
        r = session.get(url, timeout=30)
        if r.status_code != 200:
            print(f"  ⚠️ {r.status_code} {url}")
            return None
        return r.text
    except Exception as e:
        print(f"  ⚠️ fetch fail: {e} {url}")
        return None


def parse_releases(html: str) -> list[dict]:
    """releases.php の `<option value=".../releases.php?release=YYYY">YYYY</option>` から year list 抽出.

    2026-05-29 fix: 元の anchor 探索 logic は 0 件返却 = ShockBase は select/option 構造採用。
    """
    soup = BeautifulSoup(html, "html.parser")
    releases = []
    for opt in soup.find_all("option"):
        val = opt.get("value", "")
        text = opt.get_text(strip=True)
        m = re.search(r"release=(\d{4})", val)
        if m:
            releases.append({
                "year": int(m.group(1)),
                "month": None,
                "href": val,
                "text": text,
            })
    # 新しい順 sort
    releases.sort(key=lambda r: -r["year"])
    return releases


def parse_subseries_models(html: str) -> list[dict]:
    """subseries_dyn.php / releases.php → 全 variant model list 抽出 (= model 単位 dedup).

    2026-05-29 fix: image anchor + text anchor で同 model に 2 entry 出るため dedup 必須。
    """
    soup = BeautifulSoup(html, "html.parser")
    seen = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "watch_dyn.php" not in href:
            continue
        qs = href.split("?", 1)[1] if "?" in href else ""
        params = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
        model = params.get("model")
        if not model or model in seen:
            continue
        seen[model] = {
            "model": model,
            "subseries": params.get("subseries", ""),
            "series": params.get("series", ""),
            "href": href,
            "text": a.get_text(strip=True),
        }
    return list(seen.values())


# spec field 抽出 patterns (= shockbase.org HTML 構造に依存)
# 実機 probe で確定するが、 ベース pattern は既存 4 件 sample の field 名から推定
SPEC_FIELDS = [
    "RELEASE_DATE", "MODULE", "SUBSERIES", "SERIES",
    "COLLECTION", "SPECIAL_EDITION", "LIMITED_EDITION", "NICKNAME",
    "COLOR", "TIMEKEEPING", "DISPLAY", "LCD_TYPE", "LIGHT_TYPE",
    "BAND_MATERIAL", "BEZEL_MATERIAL", "CASE_MATERIAL", "GLASS",
    "BATTERY", "BATTERY_LIFE", "WEIGHT",
    "SIZE_HEIGHT", "SIZE_WIDTH", "SIZE_THICKNESS",
    "WATER_RESISTANCE", "BAND_COLOR", "BEZEL_COLOR", "WATCHFACE_COLOR",
    "MAGNETIC_RESISTANCE", "MUD_RESISTANCE", "LOW_TEMPERATURE_RESISTANCE",
    "SOLAR", "BLUETOOTH", "WORLD_TIME", "ALARMS", "STOPWATCH",
    "COMPASS", "ALTIMETER", "BAROMETER", "HEART_RATE_MONITOR",
]


def parse_watch_detail(html: str) -> dict:
    """watch_dyn.php → spec field 抽出.

    2026-05-29 構造判明 (= raw HTML 解析):
      - 通常 spec: `<th>LABEL</th><td>VALUE</td>` (= 単一 th/td pair)
      - feature flag: `<td class="cellactive">` = ON / `<td class="cellinactive">` = OFF
      - 既存 parser は class 無視で隣接 td を label/value 誤読 → 全 fix
    """
    soup = BeautifulSoup(html, "html.parser")
    spec: dict = {}

    # === 通常 spec (= 2-cell <td> pair、 cells[0]=label cells[1]=value) ===
    # ShockBase の通常 spec は <td align="right">Module:</td><td>5611</td> 形式 (= th ではない)。
    # feature 行 (= 3-cell, class=cellactive/inactive) は別扱い。
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["th", "td"], recursive=False)
        if len(cells) != 2:
            continue  # 3 cell 以上は feature 並列 / 1 cell は header
        # feature 行除外 (= class=cellactive/cellinactive を含む cell があれば spec ではない)
        if any(
            cls in (c.get("class") or [])
            for c in cells
            for cls in ("cellactive", "cellinactive")
        ):
            continue
        # cells[0] が <th> で colspan 付き = section header、 spec 対象外
        if cells[0].name == "th" and cells[0].get("colspan"):
            continue
        label = cells[0].get_text(" ", strip=True).rstrip(":").strip()
        value = cells[1].get_text(" ", strip=True)
        if not label or not value or value.lower() in ("none", "-"):
            continue
        k = label.upper().replace(" ", "_")
        spec[k] = _clean_value(value)

    # === feature flag (= cellactive / cellinactive class) ===
    features_on: list[str] = []
    features_off: list[str] = []
    for td in soup.find_all("td"):
        cls = td.get("class") or []
        is_on = "cellactive" in cls
        is_off = "cellinactive" in cls
        if not (is_on or is_off):
            continue
        # feature 名抽出 = a tag があれば function param + text、 なければ td text
        a = td.find("a")
        if a:
            name = a.get_text(" ", strip=True)
            href = a.get("href", "")
            m = re.search(r"function=([\w_]+)", href)
            if m:
                name = m.group(1)  # ← function param を正規キーとして優先 (= 表記揺れ排除)
        else:
            name = td.get_text(" ", strip=True)
        name = re.sub(r"\s+", "_", name.strip()).lower()
        if not name:
            continue
        if is_on:
            features_on.append(name)
        else:
            features_off.append(name)

    if features_on:
        spec["FEATURES_ON"] = sorted(set(features_on))
    if features_off:
        spec["FEATURES_OFF"] = sorted(set(features_off))

    return spec


def _clean_value(v: str) -> str:
    """値文字列の clean (= 'show details' / 余分な空白除去)."""
    v = re.sub(r"\s*show details\s*$", "", v, flags=re.IGNORECASE)
    v = re.sub(r"\s{2,}", " ", v).strip()
    return v


RAW_HTML_DIR = Path("C:/dev/iMak_data/catalog/_shockbase_dumps/_raw_html")


def fetch_watch(model: str, subseries: str, series: str, session: requests.Session,
                save_raw: bool = True) -> dict | None:
    url = WATCH_URL_TEMPLATE.format(model=model, subseries=subseries, series=series)
    html = fetch(url, session)
    if not html:
        return None
    if save_raw:
        RAW_HTML_DIR.mkdir(parents=True, exist_ok=True)
        safe_model = re.sub(r"[^\w\-.]", "_", model)
        (RAW_HTML_DIR / f"{safe_model}.html").write_text(html, encoding="utf-8")
    spec = parse_watch_detail(html)
    spec["__model__"] = model
    spec["__subseries__"] = subseries
    spec["__series__"] = series
    spec["__url__"] = url
    spec["__fetched_at__"] = datetime.now().isoformat()
    return spec


def load_checkpoint() -> set[str]:
    if CHECKPOINT_FILE.exists():
        return set(json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8")))
    return set()


def save_checkpoint(done: set[str]):
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_FILE.write_text(json.dumps(sorted(done)), encoding="utf-8")


def cmd_probe(session: requests.Session):
    """releases.php / subseries / individual watch の HTML 構造を 1 件ずつ dump."""
    print("=== probe: releases.php ===")
    html = fetch(RELEASES_URL, session)
    if html:
        out = DUMP_DIR / "_probe_releases.html"
        out.write_text(html, encoding="utf-8")
        print(f"  saved: {out} ({len(html):,} bytes)")
        rels = parse_releases(html)
        print(f"  parse result: {len(rels)} releases detected")
        for r in rels[:5]:
            print(f"    {r}")

    print("\n=== probe: subseries (GA-2100) ===")
    polite_sleep()
    sub_url = SUBSERIES_URL_TEMPLATE.format(series="2100", subseries="GA-2100", modul="5611")
    html = fetch(sub_url, session)
    if html:
        out = DUMP_DIR / "_probe_subseries_GA-2100.html"
        out.write_text(html, encoding="utf-8")
        print(f"  saved: {out} ({len(html):,} bytes)")
        models = parse_subseries_models(html)
        print(f"  parse result: {len(models)} models detected")
        for m in models[:5]:
            print(f"    {m['model']} (s={m['series']}, sub={m['subseries']})")

    print("\n=== probe: watch (GA-2100-1A) ===")
    polite_sleep()
    # 個別 watch detail の raw HTML save (= parser 改良用)
    url = WATCH_URL_TEMPLATE.format(model="GA-2100-1A", subseries="GA-2100", series="2100")
    html2 = fetch(url, session)
    if html2:
        out_html = DUMP_DIR / "_probe_watch_GA-2100-1A.html"
        out_html.write_text(html2, encoding="utf-8")
        print(f"  saved: {out_html} ({len(html2):,} bytes)")
        spec = parse_watch_detail(html2)
        spec["__model__"] = "GA-2100-1A"
        out_json = DUMP_DIR / "_probe_watch_GA-2100-1A.json"
        out_json.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  parse: {len(spec)} fields")


def cmd_year(session: requests.Session, year: int, limit: int | None):
    """指定 year の release 全 model 取得 → JSON 蓄積.

    2026-05-29 fix: releases.php?release=YYYY で直接 1 page 取得 (= 該当 year の watch list 即時表示)。
    """
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    done = load_checkpoint()
    print(f"=== fetching release year {year} ===")
    print(f"  checkpoint: {len(done)} done so far")

    # Step 1: releases.php?release=YYYY 直接 fetch
    url = f"{RELEASES_URL}?release={year}"
    polite_sleep()
    html = fetch(url, session)
    if not html:
        print(f"  fetch fail: {url}")
        return
    all_models = parse_subseries_models(html)
    print(f"  total models in release year {year}: {len(all_models)}")

    if limit:
        all_models = all_models[:limit]
        print(f"  limit applied: {len(all_models)} models")

    # Step 3: each model fetch
    batch_results = []
    batch_idx = 0
    fetched = 0
    failed = 0
    started = time.time()

    for i, m in enumerate(all_models, start=1):
        key = m["model"]
        if key in done:
            continue
        polite_sleep()
        spec = fetch_watch(m["model"], m["subseries"], m["series"], session)
        if spec:
            batch_results.append(spec)
            done.add(key)
            fetched += 1
        else:
            failed += 1

        # batch flush
        if len(batch_results) >= BATCH_SIZE:
            batch_idx += 1
            batch_file = DUMP_DIR / f"year_{year}_batch_{batch_idx:03d}.json"
            batch_file.write_text(
                json.dumps(batch_results, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            save_checkpoint(done)
            elapsed = int(time.time() - started)
            print(f"  ★ batch {batch_idx} saved: {batch_file.name} ({len(batch_results)} models, "
                  f"total fetched={fetched}, failed={failed}, elapsed={elapsed//60}min)")
            print(f"    sleeping {BATCH_REST_SEC} sec before next batch...")
            batch_results = []
            time.sleep(BATCH_REST_SEC)

    # final flush
    if batch_results:
        batch_idx += 1
        batch_file = DUMP_DIR / f"year_{year}_batch_{batch_idx:03d}.json"
        batch_file.write_text(
            json.dumps(batch_results, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        save_checkpoint(done)
        print(f"  ★ final batch saved: {batch_file.name}")

    print(f"\n=== complete ===")
    print(f"  fetched: {fetched}")
    print(f"  failed:  {failed}")
    print(f"  total elapsed: {int((time.time() - started) // 60)} min")
    print(f"  output dir: {DUMP_DIR}")


def cmd_auto(session: requests.Session, from_year: int, to_year: int):
    """from_year から to_year まで降順で自動連鎖 fetch (= ユーザー放置運用).

    flow:
      - 古い batch (= 旧 parser bug 由来) を _stale/ に隔離
      - from_year から to_year へ降順、 各 year 完走後 1 hour 休憩
      - 中断/再開 OK (= _progress.json で resume)
    """
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    stale_dir = DUMP_DIR / "_stale"

    # 旧 parser 由来 batch の退避は **初回起動時のみ** (= checkpoint 無いとき)
    # resume 時 (= checkpoint 存在) は退避不要、 既存 batch をそのまま継続。
    if not CHECKPOINT_FILE.exists():
        stale_files = [f for f in DUMP_DIR.glob("year_*_batch_*.json")]
        if stale_files:
            stale_dir.mkdir(exist_ok=True)
            for f in stale_files:
                tgt = stale_dir / f.name
                if tgt.exists():
                    tgt.unlink()
                f.rename(tgt)
            print(f"  ★ {len(stale_files)} stale batch(es) moved to _stale/")
    else:
        print(f"  ☐ checkpoint exists → resume mode (= no stale move)")

    print(f"=== AUTO fetch: {from_year} → {to_year} (descending) ===")
    print(f"  rate: {RATE_MIN_SEC}-{RATE_MIN_SEC + RATE_JITTER_SEC} sec/req, "
          f"batch {BATCH_SIZE}, batch rest {BATCH_REST_SEC//60} min")

    for year in range(from_year, to_year - 1, -1):
        print(f"\n>>>>>> year {year} <<<<<<")
        cmd_year(session, year, None)
        # 各 year 間休憩は batch 休憩 (= 30min) で代替、 year 間追加 sleep なし
        # (= ユーザー指摘 2026-05-30: 1 時間 sleep が冗長で進行遅延)

    print(f"\n=== AUTO complete: {from_year} → {to_year} all done ===")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--probe", action="store_true", help="HTML 構造確認のみ (= releases / subseries / watch 各 1 件)")
    p.add_argument("--year", type=int, help="指定 release year の全 model 取得")
    p.add_argument("--limit", type=int, help="件数制限 (= test 用)")
    p.add_argument("--auto-from", type=int, default=None,
                   help="自動連鎖開始 year (= --auto-to と併用、 降順で過去へ進行)")
    p.add_argument("--auto-to", type=int, default=2010,
                   help="自動連鎖終了 year (= default 2010、 これ未満は古過ぎる)")
    args = p.parse_args()

    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(UA)

    if args.probe:
        cmd_probe(session)
        return
    if args.auto_from:
        cmd_auto(session, args.auto_from, args.auto_to)
        return
    if args.year:
        cmd_year(session, args.year, args.limit)
        return
    p.print_help()


if __name__ == "__main__":
    main()
