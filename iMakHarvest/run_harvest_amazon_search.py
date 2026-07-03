"""run_harvest_amazon_search — Amazon.co.jp 検索 page 起点で G-shock 全件 収集.

依頼書: harvest/requests/2026-06-01_amazon_gshock_full_scrape.md
       harvest/requests/2026-06-11_amazon_gshock_two_birds_confirmation.md
回答  : catalog/requests/2026-06-11_amazon_gshock_two_birds_confirmation_response.md

出力 2 系統 (= 一石二鳥案):
  1. JSON dump (= Catalog Claude が catalog merge 用)
     `C:/dev/iMak_data/catalog/_amazon_jp_dumps/amazon_gshock_<ts>.json`
  2. 中間スプシ append (= iMakG-shock listing が読んで eBay 出品候補化)
     `amazon_gshock` タブ (= mercari_seller / mercari_shops と同 staging sheet)

実行例:
  python run_harvest_amazon_search.py --preset gshock-all   # メンズ + レディース 両 path
  python run_harvest_amazon_search.py --preset gshock-mens  # メンズ腕時計のみ
  python run_harvest_amazon_search.py --url "https://www.amazon.co.jp/s?k=G-Shock&rh=n%3A337470011"
  python run_harvest_amazon_search.py --preset gshock-all --max-per-session 100  # captcha 安全

注意:
  - rate limit: page 間 5-10s, detail 間 5-10s (= ユーザー「速度気を付けて」 反映)
  - hard cap per session: 100 件 detail (= default、 安全マージン)
  - captcha 出たら中断 → user 突破後 resume (= 既存 URL list を再 fetch せず未取得分のみ)
  - seller=Amazon.co.jp のみ採用 (= 第三者出品者 物理 除外)
  - 型番は **生 (verbatim) で記録**, 正規化は catalog 側 (Q3 回答準拠)
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from scrapers import amazon_search, amazon_search_http
from scrapers.amazon_item_detail import fetch_detail_full
from scrapers.amazon_wishlist import CHROME_VERSION_MAIN, create_driver
from sheet_writer_amazon import append_amazon_search_items


def attach_to_existing_chrome(port: int = 9222):
    """既存 chrome (= remote-debugging-port=9222) に接続して driver 取得.

    user が --launch-attach-chrome で起動した chrome に接続、
    user 操作で開いた URL + 拡張機能効果反映済の DOM をそのまま取得可能。
    """
    import undetected_chromedriver as uc  # noqa: PLC0415

    from scrapers._chrome_util import detect_chrome_major  # noqa: PLC0415

    options = uc.ChromeOptions()
    options.add_experimental_option("debuggerAddress", f"localhost:{port}")
    return uc.Chrome(options=options,
                     version_main=detect_chrome_major() or CHROME_VERSION_MAIN)


def _create_driver_with_retry(headless: bool, retries: int = 3):
    """create_driver を DNS/network 一過性失敗に強くする。

    2026-07-03: HTTP prefilter (Phase B) を 758件完走 keep=5 まで到達した後、
    Phase 2 の create_driver が getaddrinfo blip で落ち、 append 前にクラッシュ
    (= 50分の Phase B が無駄に)。 一過性 blip は backoff リトライで回復する。
    """
    last = None
    for att in range(1, retries + 1):
        try:
            return create_driver(headless=headless)
        except Exception as e:  # noqa: BLE001 (uc/urllib の DNS 失敗は多様な型)
            last = e
            _log(f"create_driver 失敗 (attempt {att}/{retries}): {e!r} → backoff")
            time.sleep(8 * att)
    raise last


# ============================================================================
# G-shock brand 判定 (= 6/11 5 件 sample で CITIZEN 混入課題対応)
# ============================================================================
# 検索結果に Amazon 関連商品表示 / 広告枠で他ブランド (= CITIZEN 等) が混じるため、
# seller=Amazon.co.jp + brand filter の AND で G-shock 商品のみ catalog 投入対象に絞る。

# brand text 内に G-SHOCK 表記 (= 直接 hit)
_GSHOCK_BRAND_DIRECT_RE = re.compile(
    r"(G[-\s]?SHOCK|Gショック|ジーショック)", re.IGNORECASE,
)
# brand text 内に CASIO 表記 (= G-shock 親ブランド)
_CASIO_BRAND_RE = re.compile(r"(CASIO|カシオ)", re.IGNORECASE)
# title 内に G-SHOCK 表記 (= CASIO brand 商品で Baby-G / Edifice 等 除外用)
_GSHOCK_TITLE_INDICATOR_RE = re.compile(
    r"(G[-\s]?SHOCK|Gショック|ジーショック)", re.IGNORECASE,
)
# title 内 G-shock 型番 regex (= brand 空時 fallback)
_GSHOCK_MODEL_IN_TITLE_RE = re.compile(
    r"\b([A-Z]{1,5}-[A-Z0-9]+-[A-Z0-9]+(?:[A-Z]{1,5})?)\b"
)


def is_gshock_item(brand: str, title: str) -> bool:
    """brand + title から G-shock 商品か判定 (= 他ブランド除外用、 fail-closed).

    判定 cascade:
      1. brand に "G-SHOCK" 直接表記 → True
      2. brand に "CASIO" / "カシオ" + title に G-shock indicator → True
         (= Baby-G / Edifice / Pro Trek 等の CASIO 別 series 除外)
      3. brand 空 + title に G-shock indicator + 型番 regex 両方 hit → True (= fallback)
      4. それ以外 → False (= reject)
    """
    b = brand or ""
    t = title or ""
    if _GSHOCK_BRAND_DIRECT_RE.search(b):
        return True
    if _CASIO_BRAND_RE.search(b) and _GSHOCK_TITLE_INDICATOR_RE.search(t):
        return True
    if not b.strip():
        if _GSHOCK_TITLE_INDICATOR_RE.search(t) and _GSHOCK_MODEL_IN_TITLE_RE.search(t.upper()):
            return True
    return False

# 出力先
DUMP_DIR = Path(r"C:\dev\iMak_data\catalog\_amazon_jp_dumps")

# preset 検索 URL (= 6/11 sniff で確認、 メンズ 200-300 弱 / レディース 推定 100 弱)
# URL filter `&rh=p_6%3AAN1VRQENFRJN5` = Amazon.co.jp 販売者絞込
# (= 6/11 ユーザー指示、 拡張機能 selenium 環境で効かない代替策)
# 各 preset に「新着sortパス」(-new) を併設する (2026-07-03)。
# 理由: 広い "G-Shock" 既定sort検索は Amazon の表示上限 (~400-500件) で頭打ちになり、
#   新作 (例 DW-6900CMG-3JF) が圏外に埋もれて取りこぼす。 s=date-desc-rank で新着順に
#   別途走査し、 新規到着分を回収する。 新着パスは merchantId URL フィルタ (p_6) を外す
#   (= search段のmerchantId絞込は直販でも稀に落とすため。 直販判定は Phase B の per-ASIN
#   merchantId検証に委ねる)。 ASIN dedup で既定sortパスとの重複は自動吸収。
PRESETS = {
    "gshock-all": [
        ("mens", "https://www.amazon.co.jp/s?k=G-Shock&rh=n%3A337470011&rh=p_6%3AAN1VRQENFRJN5"),
        ("mens-new", "https://www.amazon.co.jp/s?k=G-Shock&rh=n%3A337470011&s=date-desc-rank"),
        ("ladies", "https://www.amazon.co.jp/s?k=G-Shock&rh=n%3A338087011&rh=p_6%3AAN1VRQENFRJN5"),
        ("ladies-new", "https://www.amazon.co.jp/s?k=G-Shock&rh=n%3A338087011&s=date-desc-rank"),
    ],
    "gshock-mens": [
        ("mens", "https://www.amazon.co.jp/s?k=G-Shock&rh=n%3A337470011&rh=p_6%3AAN1VRQENFRJN5"),
        ("mens-new", "https://www.amazon.co.jp/s?k=G-Shock&rh=n%3A337470011&s=date-desc-rank"),
    ],
    "gshock-ladies": [
        ("ladies", "https://www.amazon.co.jp/s?k=G-Shock&rh=n%3A338087011&rh=p_6%3AAN1VRQENFRJN5"),
        ("ladies-new", "https://www.amazon.co.jp/s?k=G-Shock&rh=n%3A338087011&s=date-desc-rank"),
    ],
}

# rate limit defaults (= user 「気を付けて」 反映、 既存 mercari_seller 5-10s と同調)
DEFAULT_DETAIL_RATE_MIN = 5.0
DEFAULT_DETAIL_RATE_MAX = 10.0
DEFAULT_MAX_PER_SESSION = 100  # detail 取得 hard cap (= captcha 抑制)

# 拡張機能: Amazon 3rd Party Seller Filter (= 検索 page で第三者出品を非表示)
# Chrome Web Store URL
EXTENSION_INSTALL_URL = (
    "https://chromewebstore.google.com/detail/amazon-3rd-party-seller-f/"
    "gmfbegokkdolaokghlfnohddllgbbohd"
)


def launch_attach_chrome_mode() -> int:
    """普通の chrome (= selenium 起動でない) を 9222 port で起動して user 操作可能にする.

    抽出くん python は chrome 起動コマンドを実行して即終了 (= chrome は detached process)。
    以降 `--attach-port 9222` で接続することで user 操作 chrome の DOM を使える。
    """
    import os as _os  # noqa: PLC0415
    import subprocess  # noqa: PLC0415

    profile_dir = (
        r"C:\Users\imax2\local_data\iMakHarvest\chrome_profile_amazon_attach"
    )
    _os.makedirs(profile_dir, exist_ok=True)
    chrome_candidates = (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    )
    chrome_exe = None
    for c in chrome_candidates:
        if _os.path.isfile(c):
            chrome_exe = c
            break
    if not chrome_exe:
        _log("ERROR: chrome.exe 見つかりません (= " + ", ".join(chrome_candidates) + ")")
        return 1

    args = [
        chrome_exe,
        "--remote-debugging-port=9222",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        EXTENSION_INSTALL_URL,
    ]
    _log(f"chrome 起動 (= 新 profile = {profile_dir})")
    _log(f"args: {args}")
    flags = 0
    if _os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0,
        )
    subprocess.Popen(args, creationflags=flags, close_fds=True)
    _log("chrome 起動完了 (= detached、 python は即終了)")
    _log("---")
    _log("次のステップ (user 操作):")
    _log("  1. 起動した chrome で「Chrome に追加」 で拡張機能 install")
    _log("  2. Amazon 検索 URL filter を新タブで開く:")
    _log("     https://www.amazon.co.jp/s?k=G-Shock&rh=n%3A337470011%2Cp_6%3AAN1VRQENFRJN5")
    _log("  3. 画面に第三者除外 + Amazon 直販のみ表示 を確認")
    _log("  4. user 操作完了したら 抽出くんに「準備 OK」 と通知")
    _log("  5. 抽出くん: --preset gshock-mens --attach-port 9222 --skip-existing-tab gshock")
    return 0


def setup_extension_mode(headless: bool = False) -> int:
    """拡張機能 install setup mode (= 6/11 ユーザー提案、 mercari_seller setup_anonymous 同パターン).

    1. chrome 起動 (= chrome_profile_amazon 永続 profile)
    2. Chrome Web Store の Amazon 3rd Party Seller Filter ページに遷移
    3. user が「Chrome に追加」 click + install 確認
    4. 任意ページ navigate で profile 永続化確認
    5. user が close で完了 (= profile に拡張機能永続化)

    以降の通常 run 時、 拡張機能は自動 enable される。
    """
    _log("=== setup-extension mode ===")
    _log(f"chrome 起動 + 拡張機能 install URL navigate: {EXTENSION_INSTALL_URL}")
    driver = _create_driver_with_retry(headless)
    try:
        driver.get(EXTENSION_INSTALL_URL)
        _log("ブラウザで「Chrome に追加」 ボタン押下 + install 確認してください")
        _log("install 後、 Amazon 検索結果ページで動作確認推奨:")
        _log("  https://www.amazon.co.jp/s?k=G-Shock&rh=n%3A337470011")
        _log("install + 動作確認 完了したら 抽出くんに「install 完了」 と通知してください")
        _log("chrome は最大 30 分間 開きっぱなしです (= user 通知で TaskStop)")
        time.sleep(1800)  # 30 分 sleep (= user 操作余裕)
        _log("timeout (= 30 分) で close")
        return 0
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def _log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def _collect_urls_for_paths(driver, paths: list[tuple[str, str]]) -> dict:
    """各 search path を順次走査、 URL 統合.

    Returns: {
        "by_path": {label: {"urls": [...], "captcha_hit": bool, "pages_scanned": int, ...}},
        "all_urls": [...],         # 全 path union (= ASIN dedup 済)
        "captcha_hit": bool,
    }
    """
    by_path: dict[str, dict] = {}
    seen_asin: set[str] = set()
    all_urls: list[str] = []
    captcha_global = False
    for label, url in paths:
        _log(f"--- 検索 path: {label} ({url}) ---")
        r = amazon_search.collect_search_listing_urls(
            search_url=url,
            driver=driver,
            progress_callback=lambda i, n, m: _log(f"  {m}"),
        )
        by_path[label] = {
            "urls": r["urls"],
            "captcha_hit": r["captcha_hit"],
            "pages_scanned": r["pages_scanned"],
            "total_seen": r["total_seen"],
        }
        _log(
            f"  {label}: total={r['total_seen']} pages={r['pages_scanned']} "
            f"captcha={r['captcha_hit']}"
        )
        for u in r["urls"]:
            asin = amazon_search.parse_asin_from_url(u)
            if asin and asin not in seen_asin:
                seen_asin.add(asin)
                all_urls.append(u)
        if r["captcha_hit"]:
            captcha_global = True
            _log("  ⚠️ captcha 検出 → URL 収集中断")
            break
    return {
        "by_path": by_path,
        "all_urls": all_urls,
        "captcha_hit": captcha_global,
    }


def _http_prefilter_keep_asins(
    paths: list[tuple[str, str]],
    pre_visited_asins: set[str],
    max_pages: int = 15,
    rate_min: float = 3.0,
    rate_max: float = 5.0,
) -> dict:
    """HTTP で全 ASIN 取得 + seller=Amazon + brand=G-shock filter (= 2026-06-11 改善).

    Returns: {
        "url_keep_urls": list[str],    # keep ASIN を /dp/<ASIN> URL に変換した list
        "url_collected_count": int,    # HTTP で取得した全 ASIN 数 (= 重複除外後)
        "kept_asin_count": int,        # filter 通過 ASIN 数
        "rejected_asin_count": int,
        "skipped_pre_visited": int,
        "captcha_hit": bool,
        "session_obj": Session,         # 後段で keep_alive 流用
    }
    """
    session = amazon_search_http.create_session()
    all_asins: list[str] = []
    seen: set[str] = set(pre_visited_asins)
    captcha_url = False
    for label, base_url in paths:
        _log(f"[http-prefilter] URL 収集 path={label}: {base_url}")
        r = amazon_search_http.collect_search_asins(
            session=session, base_url=base_url, max_pages=max_pages,
            rate_min=rate_min, rate_max=rate_max,
            progress_callback=lambda i, n, m: _log(f"  {m}"),
        )
        if r["captcha_hit"]:
            captcha_url = True
            break
        for a in r["asins"]:
            if a not in seen:
                seen.add(a)
                all_asins.append(a)
    _log(f"[http-prefilter] URL 収集完了: {len(all_asins)} 件 (pre_visited skip={len(pre_visited_asins)})")

    # Phase B: seller/brand filter
    keep_asins: list[str] = []
    rejected = 0
    captcha_detail = False
    queue = list(all_asins)
    queued_set: set[str] = set(all_asins)
    processed = 0
    while queue:
        asin = queue.pop(0)
        processed += 1
        if processed % 20 == 0:
            _log(f"[http-prefilter] detail {processed}/{len(queued_set)} (keep={len(keep_asins)} reject={rejected})")
        r = amazon_search_http.evaluate_detail_for_keep(session, asin)
        if r["captcha_hit"]:
            captcha_detail = True
            _log("[http-prefilter] CAPTCHA detected, abort")
            break
        if not r["fetch_ok"]:
            rejected += 1
        elif r["should_keep"]:
            keep_asins.append(asin)
            # variant 子 ASIN を queue に追加
            for v in r["variant_asins"]:
                if v and v not in seen:
                    seen.add(v)
                    if v not in queued_set:
                        queued_set.add(v)
                        queue.append(v)
        else:
            rejected += 1
        time.sleep(random.uniform(rate_min, rate_max))

    _log(f"[http-prefilter] filter 完了: keep={len(keep_asins)} reject={rejected} captcha={captcha_detail}")
    return {
        "url_keep_urls": [f"https://www.amazon.co.jp/dp/{a}" for a in keep_asins],
        "url_collected_count": len(queued_set),
        "kept_asin_count": len(keep_asins),
        "rejected_asin_count": rejected,
        "skipped_pre_visited": len(pre_visited_asins),
        "captcha_hit": captcha_url or captcha_detail,
    }


def _http_variant_supplement(
    seed_asins: list[str],
    pre_visited_asins: set[str],
    rate_min: float = 3.0,
    rate_max: float = 5.0,
) -> dict:
    """seed ASIN を起点に variant 子 ASIN を HTTP で集めて seller=Amazon.co.jp filter.

    既存 keep ASIN の color variant 取りこぼし補完用 (= 2026-06-11 user 指示)。
    Amazon US (= merchantId 違い) は自動除外。

    Returns: {
        "url_keep_urls": list[str],   # 新規 keep ASIN を /dp/<ASIN> URL に
        "supplement_seed_count": int,
        "variant_candidates": int,    # variant 子 ASIN 候補 (= dedup 済)
        "kept_count": int,
        "rejected_count": int,
        "captcha_hit": bool,
    }
    """
    session = amazon_search_http.create_session()
    # Phase A: seed ASIN を HTTP detail で variant 子 ASIN 抽出
    variant_candidates: list[str] = []
    seen: set[str] = set(pre_visited_asins) | set(seed_asins)
    captcha_seed = False
    for i, asin in enumerate(seed_asins, start=1):
        if i % 20 == 0:
            _log(f"[variant-supplement] seed {i}/{len(seed_asins)} (candidates={len(variant_candidates)})")
        text, captcha = amazon_search_http.fetch_detail_page(session, asin)
        if captcha:
            captcha_seed = True
            break
        if not text:
            continue
        v_asins = amazon_search_http.extract_variant_asins_http(text)
        for v in v_asins:
            if v not in seen:
                seen.add(v)
                variant_candidates.append(v)
        time.sleep(random.uniform(rate_min, rate_max))
    _log(f"[variant-supplement] seed 完了: variant 子 ASIN 候補 {len(variant_candidates)} 件")

    # Phase B: variant 候補を HTTP detail で seller=Amazon.co.jp + brand=G-shock filter
    keep_asins: list[str] = []
    rejected = 0
    captcha_detail = False
    for i, asin in enumerate(variant_candidates, start=1):
        if i % 20 == 0:
            _log(f"[variant-supplement] filter {i}/{len(variant_candidates)} (keep={len(keep_asins)} reject={rejected})")
        r = amazon_search_http.evaluate_detail_for_keep(session, asin)
        if r["captcha_hit"]:
            captcha_detail = True
            break
        if not r["fetch_ok"]:
            rejected += 1
        elif r["should_keep"]:
            keep_asins.append(asin)
        else:
            rejected += 1
        time.sleep(random.uniform(rate_min, rate_max))
    _log(f"[variant-supplement] filter 完了: keep={len(keep_asins)} reject={rejected}")

    return {
        "url_keep_urls": [f"https://www.amazon.co.jp/dp/{a}" for a in keep_asins],
        "supplement_seed_count": len(seed_asins),
        "variant_candidates": len(variant_candidates),
        "kept_count": len(keep_asins),
        "rejected_count": rejected,
        "captcha_hit": captcha_seed or captcha_detail,
    }


def _load_existing_asins_from_tab(label: str) -> set[str]:
    """中間スプシ既存タブから ASIN set 読込 (= 重複 fetch 防止 pre-load 用).

    読込失敗を silent に空扱いすると skip=0 で全件再 fetch (無駄 + captcha リスク) に
    なるため、 DNS blip 等の一過性失敗は backoff リトライし、 尽きたら fail-fast で raise。
    タブ未作成 (= 初回) は正当な空として set() を返す (2026-07-03 DNS flapping 対策)。
    """
    import gspread  # noqa: PLC0415
    from sheet_writer_amazon import build_amazon_tab_name  # noqa: PLC0415
    from sheet_writer_mercari_seller import open_seller_staging_sheet  # noqa: PLC0415

    tab_name = build_amazon_tab_name(label)
    last = None
    for att in range(1, 4):
        try:
            sh = open_seller_staging_sheet()
            try:
                ws = sh.worksheet(tab_name)
            except gspread.exceptions.WorksheetNotFound:
                return set()  # タブ未作成 = 正当な空
            asins: set[str] = set()
            for row in ws.get_all_values()[1:]:
                if not row:
                    continue
                asin = amazon_search.parse_asin_from_url((row[0] or "").strip())
                if asin:
                    asins.add(asin)
            return asins
        except Exception as e:  # noqa: BLE001 (DNS/接続 blip は多様な型)
            last = e
            _log(f"skip-existing タブ読込 失敗 (attempt {att}/3): {e!r} → backoff")
            time.sleep(6 * att)
    raise RuntimeError(
        f"skip-existing タブ '{tab_name}' 読込に失敗 (DNS blip?): {last!r}。 "
        f"silent skip=0 は全件再fetchになるため中断。 DNS 安定後に再実行を。"
    )


def _fetch_details(
    driver,
    urls: list[str],
    max_per_session: int,
    rate_min: float,
    rate_max: float,
    pre_visited_asins: set[str] | None = None,
) -> dict:
    """各 URL の detail fetch (= 14 field + variant 子 ASIN 展開).

    variant 商品 (= color variation あり) は 子 ASIN を fetch queue に追加し、
    全色違いを個別 detail fetch する (= dedup 済)。
    seller=Amazon.co.jp + brand=G-shock のみ items_kept に追加。

    max_per_session は **total fetch 回数** cap (= parent + variant 全部合算)。
    """
    items_kept: list[dict] = []
    items_rejected: list[dict] = []
    captcha_hit = False
    # pre_visited_asins = 既存 タブ ASIN (= skip 対象)、 init で visited に注入
    visited_asins: set[str] = set(pre_visited_asins or [])
    # initial queue (= 検索結果 URL を順序保持で dequeue)、 既知 ASIN は除外
    queue: list[str] = []
    queued_set: set[str] = set(visited_asins)  # 既知 ASIN は queue 追加禁止
    skipped_pre = 0
    for u in urls:
        a = amazon_search.parse_asin_from_url(u)
        if not a:
            continue
        if a in visited_asins:
            skipped_pre += 1
            continue
        if a not in queued_set:
            queue.append(u)
            queued_set.add(a)
    if skipped_pre > 0:
        _log(f"  pre-visited ASIN {skipped_pre} 件 skip (= 既存タブ重複 fetch 回避)")

    fetched = 0
    while queue and fetched < max_per_session:
        url = queue.pop(0)
        asin = amazon_search.parse_asin_from_url(url) or ""
        if asin and asin in visited_asins:
            continue
        if asin:
            visited_asins.add(asin)
        fetched += 1
        _log(f"detail {fetched}/{max_per_session} (queue {len(queue)}): {url}")
        detail = fetch_detail_full(driver, url)
        if detail is None:
            _log("  WARN fetch_detail_full 返却 None -> skip")
            if fetched < max_per_session and queue:
                time.sleep(random.uniform(rate_min, rate_max))
            continue
        if detail.get("status") == "CAPTCHA":
            _log("  WARN CAPTCHA 検出 -> 中断")
            captcha_hit = True
            break

        # variant 子 ASIN を queue 追加 (= 未訪問 + queued でないもののみ)
        v_asins = detail.get("variant_asins") or []
        v_total = detail.get("variant_total") or 0
        if v_asins:
            new_added = 0
            for v_asin in v_asins:
                if v_asin and v_asin not in visited_asins and v_asin not in queued_set:
                    queue.append(f"https://www.amazon.co.jp/dp/{v_asin}")
                    queued_set.add(v_asin)
                    new_added += 1
            if new_added > 0:
                _log(f"  + variant: {v_total} 色中 {new_added} 件 queue 追加")

        seller = (detail.get("seller") or "").strip()
        brand = (detail.get("brand") or "").strip()
        title = detail.get("title", "")
        if seller != "Amazon.co.jp":
            items_rejected.append({
                "url": url,
                "asin": asin,
                "seller": seller,
                "brand": brand,
                "title": title[:80],
                "reason": "seller_not_amazon_jp",
            })
            _log(f"  REJECT seller={seller!r}")
        elif not is_gshock_item(brand, title):
            items_rejected.append({
                "url": url,
                "asin": asin,
                "seller": seller,
                "brand": brand,
                "title": title[:80],
                "reason": "brand_not_gshock",
            })
            _log(f"  REJECT brand={brand!r} (not G-shock)")
        elif amazon_search_http.is_ladies_only(title):
            items_rejected.append({
                "url": url,
                "asin": asin,
                "seller": seller,
                "brand": brand,
                "title": title[:80],
                "reason": "ladies_only",
            })
            _log(f"  REJECT ladies-only title")
        elif amazon_search_http.is_accessory_part(title):
            items_rejected.append({
                "url": url,
                "asin": asin,
                "seller": seller,
                "brand": brand,
                "title": title[:80],
                "reason": "accessory_part",
            })
            _log(f"  REJECT accessory/part (not watch body)")
        else:
            merged = {
                "asin": asin,
                **detail,
                "url": url,  # 中間スプシ用 (= sheet_writer_amazon._build_row が読む key)
                "fetched_at": datetime.now().isoformat(),
            }
            items_kept.append(merged)
        if fetched < max_per_session and queue:
            time.sleep(random.uniform(rate_min, rate_max))
    return {
        "items_kept": items_kept,
        "items_rejected": items_rejected,
        "captcha_hit": captcha_hit,
        "scanned": fetched,
        "input_urls": len(urls),
        "queue_remaining": len(queue),
    }


def harvest_amazon_search(
    paths: list[tuple[str, str]],
    label: str = "gshock",
    max_per_session: int = DEFAULT_MAX_PER_SESSION,
    rate_min: float = DEFAULT_DETAIL_RATE_MIN,
    rate_max: float = DEFAULT_DETAIL_RATE_MAX,
    headless: bool = False,
    skip_sheet: bool = False,
    skip_existing_tab: str | None = None,
    attach_port: int | None = None,
    use_http_prefilter: bool = False,
    supplement_variants_from_tab: str | None = None,
) -> dict:
    """1 session 内で URL 収集 + detail fetch + 2 出力 (= JSON dump + 中間スプシ append).

    Returns: {
        "summary": {...},
        "json_dump_path": str,
        "sheet_result": dict | None,
    }
    """
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    pre_visited: set[str] = set()
    if skip_existing_tab:
        pre_visited = _load_existing_asins_from_tab(skip_existing_tab)
        _log(
            f"[skip-existing] tab='{skip_existing_tab}' から既存 ASIN "
            f"{len(pre_visited)} 件 pre-load (= 重複 fetch skip)"
        )
    # HTTP pre-filter (= 2026-06-11 改善、 Gemini 助言 + merchantId 100% 精度実証)
    # selenium で URL 収集 + seller filter する代わりに、 HTTP で 100% 精度 filter
    # → keep ASIN list のみ selenium で 14 field detail fetch (= 効率最大化)
    http_filter_result: dict | None = None
    if use_http_prefilter:
        _log("=== Phase 0: HTTP pre-filter (= URL 収集 + seller/brand filter) ===")
        http_filter_result = _http_prefilter_keep_asins(
            paths=paths,
            pre_visited_asins=pre_visited,
            max_pages=15,
            rate_min=3.0,
            rate_max=5.0,
        )
        if not http_filter_result["url_keep_urls"]:
            _log("[http-prefilter] keep ASIN 0 件、 abort")
            return {
                "summary": {"label": label, "http_prefilter": http_filter_result},
                "json_dump_path": None, "sheet_result": None,
            }
        _log(
            f"[http-prefilter] selenium detail fetch 対象: "
            f"{len(http_filter_result['url_keep_urls'])} 件"
        )

    # variant supplement (= 2026-06-11 user 指示: 既存 keep ASIN の color variant 補完)
    variant_sup_result: dict | None = None
    if supplement_variants_from_tab:
        _log(
            f"=== Phase 0v: variant supplement seed='{supplement_variants_from_tab}' ==="
        )
        seed_asins = sorted(_load_existing_asins_from_tab(supplement_variants_from_tab))
        if not seed_asins:
            _log(f"[variant-supplement] seed タブ {supplement_variants_from_tab!r} 空、 abort")
            return {
                "summary": {"label": label, "variant_supplement": "seed empty"},
                "json_dump_path": None, "sheet_result": None,
            }
        _log(f"[variant-supplement] seed ASIN {len(seed_asins)} 件")
        variant_sup_result = _http_variant_supplement(
            seed_asins=seed_asins,
            pre_visited_asins=pre_visited,
            rate_min=3.0,
            rate_max=5.0,
        )
        if not variant_sup_result["url_keep_urls"]:
            _log("[variant-supplement] 新規 keep 子 ASIN 0 件、 abort")
            return {
                "summary": {"label": label, "variant_supplement": variant_sup_result},
                "json_dump_path": None, "sheet_result": None,
            }
        _log(
            f"[variant-supplement] selenium detail fetch 対象: "
            f"{len(variant_sup_result['url_keep_urls'])} 件"
        )

    if attach_port:
        _log(f"[attach] localhost:{attach_port} の既存 chrome に接続")
        driver = attach_to_existing_chrome(port=attach_port)
    else:
        driver = _create_driver_with_retry(headless)
    try:
        if supplement_variants_from_tab and variant_sup_result:
            all_urls = variant_sup_result["url_keep_urls"]
            _log(f"=== Phase 1: variant supplement keep URL = {len(all_urls)} 件 ===")
            url_result = {
                "by_path": {"variant_supplement": variant_sup_result},
                "all_urls": all_urls,
                "captcha_hit": variant_sup_result["captcha_hit"],
            }
        elif use_http_prefilter and http_filter_result:
            all_urls = http_filter_result["url_keep_urls"]
            _log(f"=== Phase 1: HTTP-prefilter 済 keep URL = {len(all_urls)} 件 ===")
            url_result = {
                "by_path": {"http_prefilter": http_filter_result},
                "all_urls": all_urls,
                "captcha_hit": http_filter_result["captcha_hit"],
            }
        else:
            _log(f"=== Phase 1: URL 収集 ({len(paths)} path) ===")
            url_result = _collect_urls_for_paths(driver, paths)
            all_urls = url_result["all_urls"]
            _log(f"URL union total: {len(all_urls)} 件")

        _log(f"=== Phase 2: detail fetch (= seller filter) ===")
        detail_result = _fetch_details(
            driver, all_urls, max_per_session, rate_min, rate_max,
            pre_visited_asins=pre_visited,
        )
        items_kept = detail_result["items_kept"]
        _log(
            f"kept={len(items_kept)} rejected={len(detail_result['items_rejected'])} "
            f"captcha={detail_result['captcha_hit']}"
        )

        # JSON dump (= catalog 投入用)
        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        dump_path = DUMP_DIR / f"amazon_{label}_{ts}.json"
        summary = {
            "label": label,
            "paths": [{"label": l, **url_result["by_path"].get(l, {})} for l, _ in paths],
            "all_urls_count": len(all_urls),
            "scanned_detail": detail_result["scanned"],
            "items_kept_count": len(items_kept),
            "items_rejected_count": len(detail_result["items_rejected"]),
            "captcha_hit": url_result["captcha_hit"] or detail_result["captcha_hit"],
            "max_per_session": max_per_session,
            "rate_min_max": [rate_min, rate_max],
            "completed_at": datetime.now().isoformat(),
        }
        dump = {
            "summary": summary,
            "items_rejected": detail_result["items_rejected"],
            "items": items_kept,
        }
        dump_path.write_text(json.dumps(dump, ensure_ascii=False, indent=2), encoding="utf-8")
        _log(f"[FILE] JSON dump: {dump_path}")

        # 中間スプシ append
        sheet_result = None
        if skip_sheet:
            _log("[SKIP] 中間スプシ append skip (= --skip-sheet)")
        elif not items_kept:
            _log("[SKIP] 中間スプシ append skip (= items_kept 0 件)")
        else:
            _log(f"=== Phase 3: 中間スプシ append ({len(items_kept)} 件) ===")
            sheet_result = append_amazon_search_items(items_kept, label=label)
            _log(f"[SHEET] {sheet_result}")

        return {
            "summary": summary,
            "json_dump_path": str(dump_path),
            "sheet_result": sheet_result,
        }
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--preset", choices=list(PRESETS.keys()), default="gshock-all",
        help="検索 path preset (default: gshock-all)",
    )
    ap.add_argument(
        "--url", action="append", default=[],
        help="個別 検索 URL (= --preset の代替、 複数指定可)",
    )
    ap.add_argument("--label", default="gshock", help="JSON dump + tab suffix")
    ap.add_argument(
        "--max-per-session", type=int, default=DEFAULT_MAX_PER_SESSION,
        help=f"1 session 内 detail fetch 上限 (default {DEFAULT_MAX_PER_SESSION})",
    )
    ap.add_argument(
        "--rate-min", type=float, default=DEFAULT_DETAIL_RATE_MIN,
        help=f"detail 間 sleep min sec (default {DEFAULT_DETAIL_RATE_MIN})",
    )
    ap.add_argument(
        "--rate-max", type=float, default=DEFAULT_DETAIL_RATE_MAX,
        help=f"detail 間 sleep max sec (default {DEFAULT_DETAIL_RATE_MAX})",
    )
    ap.add_argument("--headless", action="store_true", help="ヘッドレスモード")
    ap.add_argument("--skip-sheet", action="store_true", help="中間スプシ append を skip (JSON dump のみ)")
    ap.add_argument(
        "--skip-existing-tab", default=None,
        help="指定 label の既存タブ ASIN を pre-load して fetch から除外 (= 重複 fetch 防止)",
    )
    ap.add_argument(
        "--setup-extension", action="store_true",
        help="Amazon 3rd Party Seller Filter 拡張機能 install setup mode",
    )
    ap.add_argument(
        "--launch-attach-chrome", action="store_true",
        help="普通の chrome を 9222 port で起動 (= user 操作 + attach 用、 新 profile)",
    )
    ap.add_argument(
        "--attach-port", type=int, default=None,
        help="既存 chrome (= --launch-attach-chrome 起動分) の port に接続して fetch",
    )
    ap.add_argument(
        "--use-http-prefilter", action="store_true",
        help="HTTP で URL 収集 + seller/brand filter (= 100% 精度、 selenium fetch 最小化)",
    )
    ap.add_argument(
        "--supplement-variants-from-tab", default=None,
        help="指定タブ既存 ASIN を seed に variant 子 ASIN を補完 fetch (= Amazon US 自動除外)",
    )
    args = ap.parse_args(argv)

    if args.setup_extension:
        return setup_extension_mode(headless=args.headless)
    if args.launch_attach_chrome:
        return launch_attach_chrome_mode()

    if args.url:
        paths = [(f"custom_{i+1}", u) for i, u in enumerate(args.url)]
    else:
        paths = PRESETS[args.preset]

    _log(f"開始: preset={args.preset} paths={len(paths)} label={args.label!r}")
    _log(f"  max_per_session={args.max_per_session} rate={args.rate_min}-{args.rate_max}s")

    result = harvest_amazon_search(
        paths=paths,
        label=args.label,
        max_per_session=args.max_per_session,
        rate_min=args.rate_min,
        rate_max=args.rate_max,
        headless=args.headless,
        skip_sheet=args.skip_sheet,
        skip_existing_tab=args.skip_existing_tab,
        attach_port=args.attach_port,
        use_http_prefilter=args.use_http_prefilter,
        supplement_variants_from_tab=args.supplement_variants_from_tab,
    )
    _log("=== summary ===")
    _log(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    _log(f"JSON: {result['json_dump_path']}")
    _log(f"Sheet: {result['sheet_result']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
