#!/usr/bin/env python3
"""Pokemon TCG (Japanese) scraper — pokemon-card.com 経由で全カードを iMakCatalog DB に投入.

データ源:
  - https://www.pokemon-card.com/card-search/resultAPI.php (list, JSON)
  - https://www.pokemon-card.com/card-search/details.php/card/{cardID} (detail, HTML)

設計:
  - resultAPI.php をページングで全件取得 (~5245 カード × 39/page ≈ 135 page)
  - 各カード詳細は disk cache (db/cache/pokemon_tcg/) に保存
  - product_id = "{set_code}_{cardID}" (set_code は image_url から抽出、cardID は global 5桁)
    例: 'M2a_50000' (メガゲンガーex), 'M4_50085' (ビードル ニンジャスピナー)
  - One Piece/Gundam/DBSCG とは構造的に異なる (各 TCG 固有スキーマ)

CLI:
  python scrapers/pokemon_tcg.py --full              # 全件 (~5300 件、~2.5 時間)
  python scrapers/pokemon_tcg.py --update            # 差分のみ
  python scrapers/pokemon_tcg.py --card 50000        # 単一 cardID
  python scrapers/pokemon_tcg.py --limit 50          # 先頭 N 件 (動作確認用)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

# Allow `from api import ...` when run as script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import api  # noqa: E402

# ============================================================================
# 定数
# ============================================================================
LIST_API = "https://www.pokemon-card.com/card-search/resultAPI.php"
DETAIL_BASE = "https://www.pokemon-card.com/card-search/details.php/card"
CATEGORY = "pokemon_tcg"
SOURCE = "pokemon_card_jp"
PAGE_SIZE = 39   # site default
SLEEP_BETWEEN_CALLS = 1.5

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

CACHE_DIR = Path(__file__).resolve().parent.parent / "db" / "cache" / CATEGORY
CACHE_DIR.mkdir(parents=True, exist_ok=True)

_session = requests.Session()
_session.headers.update({
    "User-Agent": USER_AGENT,
    "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.8",
    "Referer": "https://www.pokemon-card.com/card-search/",
    "X-Requested-With": "XMLHttpRequest",   # AJAX endpoint 完全版を返してもらうため必須
})

# JA → EN type 変換 (TCG 内部 type、必要なら eBay フィルタ用)
JP_TYPE_TO_EN = {
    "草": "Grass", "炎": "Fire", "水": "Water", "雷": "Lightning",
    "超": "Psychic", "闘": "Fighting", "悪": "Darkness", "鋼": "Metal",
    "フェアリー": "Fairy", "ドラゴン": "Dragon", "無色": "Colorless",
}


# ============================================================================
# HTTP
# ============================================================================
def _get(url: str, params: dict | None = None, retries: int = 5) -> requests.Response:
    """Polite GET with backoff."""
    backoff = [8, 16, 32, 60, 60]
    last_err = None
    for attempt in range(retries):
        try:
            r = _session.get(url, params=params, timeout=30)
            if r.status_code == 200:
                return r
            if r.status_code in (429, 403) or r.status_code >= 500:
                wait = backoff[min(attempt, len(backoff) - 1)]
                print(f"    ⚠️ HTTP {r.status_code} on {url} → wait {wait}s "
                      f"(attempt {attempt + 1}/{retries})", flush=True)
                last_err = f"HTTP {r.status_code}"
                time.sleep(wait)
                continue
            return r
        except (requests.ConnectionError, requests.Timeout) as e:
            wait = backoff[min(attempt, len(backoff) - 1)]
            print(f"    ⚠️ network error: {e} → wait {wait}s "
                  f"(attempt {attempt + 1}/{retries})", flush=True)
            last_err = str(e)
            time.sleep(wait)
    raise RuntimeError(f"GET {url} failed after {retries} retries: {last_err}")


# ============================================================================
# List endpoint (resultAPI.php)
# ============================================================================
def list_all_cards(all_regulations: bool = True) -> list[dict]:
    """resultAPI.php を全ページ取得.

    Args:
        all_regulations: True = 旧弾も含む全カード (`regulation_sidebar_form=all`)、
                         False = 現行レギュレーションのみ
    """
    # 注: pagination param は 'page' (NOT 'pg'). 'pg' は別の form フィールド (id=38 cards).
    base_params = {}
    if all_regulations:
        base_params["regulation_sidebar_form"] = "all"

    all_cards: list[dict] = []
    r = _get(LIST_API, params={**base_params, "page": 1})
    data = r.json()
    max_page = int(data.get("maxPage", 1))
    hit_cnt = int(data.get("hitCnt", 0))
    print(f"  pokemon-card.com total: {hit_cnt} cards / {max_page} pages "
          f"(all_regulations={all_regulations})")
    all_cards.extend(data.get("cardList", []) or [])
    time.sleep(SLEEP_BETWEEN_CALLS)

    for page in range(2, max_page + 1):
        r = _get(LIST_API, params={**base_params, "page": page})
        data = r.json()
        all_cards.extend(data.get("cardList", []) or [])
        if page % 20 == 0:
            print(f"  ... list page {page}/{max_page} (cards so far: {len(all_cards)})", flush=True)
        time.sleep(SLEEP_BETWEEN_CALLS)
    return all_cards


# ============================================================================
# Detail endpoint (HTML parsing)
# ============================================================================
def get_detail(card_id: int | str) -> dict | None:
    """カード詳細を取得 (キャッシュ付). HTML を parse して dict 化."""
    cache_path = CACHE_DIR / f"detail_{card_id}.json"
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cache_path.unlink()

    r = _get(f"{DETAIL_BASE}/{card_id}")
    if r.status_code != 200 or not r.text:
        return None
    parsed = _parse_detail_html(r.text, card_id)
    if parsed:
        cache_path.write_text(json.dumps(parsed, ensure_ascii=False), encoding="utf-8")
    time.sleep(SLEEP_BETWEEN_CALLS)
    return parsed


def _parse_detail_html(html: str, card_id: int | str) -> dict | None:
    """detail.php HTML から構造化 dict を抽出 (HTML 構造を直接使う)."""
    # Search page placeholder = カード不在
    if "<title>カード検索" in html and "/card_images/large/" not in html:
        return None

    # &nbsp; を通常空白に変換 (entity decoding は後でも良いが card_number には必須)
    import html as html_mod
    html_decoded = html_mod.unescape(html)

    out: dict = {"cardID": str(card_id)}

    # Card name (h1)
    m = re.search(r"<h1[^>]*>([^<]+)</h1>", html_decoded)
    if m:
        out["name"] = m.group(1).strip()

    # Image URL → set_code, padded_id
    m = re.search(r'src="(/assets/images/card_images/large/([^/]+)/(\d+)_[^"]+)"', html_decoded)
    if m:
        out["image_url"] = "https://www.pokemon-card.com" + m.group(1)
        out["set_code"] = m.group(2)
        out["padded_id"] = m.group(3)

    # 印刷 card_number 抽出.
    #   Booster: <img regulation_logo/M2a.gif/> 240/193        (digits/digits)
    #   Promo:   <img regulation_logo/SM-P.gif/> 001/SM-P      (digits/promo-code)
    # 両方を 1 つの regex でカバー.
    m = re.search(
        r'regulation_logo_\d+/([^"./]+)\.gif"\s+class="[^"]+"\s+alt="[^"]+"\s*/?>\s*'
        r'([0-9A-Z\s/／-]+)',  # 数字 + 全角/半角スラッシュ + 英数字 (promo set code)
        html_decoded,
    )
    if m:
        out["regulation_set"] = m.group(1)
        num_text = re.sub(r"\s+", "", m.group(2)).strip("/")
        out["card_number_text"] = num_text
        # Booster 形式: '240/193'
        m2 = re.match(r"^(\d+)/(\d+)$", num_text)
        if m2:
            out["card_number"] = m2.group(1)
            out["card_number_total"] = m2.group(2)
        else:
            # Promo 形式: '001/SM-P', '047/S-P', '012/XY-P' 等
            m3 = re.match(r"^(\d+)/([A-Z][A-Z0-9-]+)$", num_text)
            if m3:
                out["card_number"] = m3.group(1)
                out["card_number_promo_code"] = m3.group(2)  # 'SM-P' 等

    # Rarity (from rarity image filename: ic_rare_sar.gif → "SAR" / ic_rare_c_c.gif → "C")
    # Pokemon rarity image format: ic_rare_{rarity}[_{type_marker}].gif
    #   sar / rr / rrr / ur / hr / ma / mur → そのまま
    #   c_c / u_c / r_c → アンダースコア前まで (rarity 部分のみ)
    m = re.search(r'rarity/ic_rare_(\w+)\.gif', html_decoded)
    if m:
        raw = m.group(1)
        # アンダースコアあり → 先頭部分を rarity とする
        rarity_part = raw.split("_")[0].upper()
        out["rarity"] = rarity_part

    # Plain-text body for free-form fields
    text_only = re.sub(r"<script[^>]*>.*?</script>", "", html_decoded, flags=re.DOTALL | re.IGNORECASE)
    text_only = re.sub(r"<style[^>]*>.*?</style>", "", text_only, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text_only)
    text = re.sub(r"\s+", " ", text).strip()

    # HP
    m = re.search(r"HP\s+(\d+)", text)
    if m:
        out["hp"] = m.group(1)

    # Stage (進化段階) — text 順序で一番近いものを優先
    m = re.search(r"(2\s*進化|1\s*進化|たね|基本|MEGA|VMAX|VSTAR|ex\s*進化)", text)
    if m:
        out["stage"] = re.sub(r"\s+", "", m.group(1)).strip()

    # Type icon — 2 形式対応:
    #   旧 (BW/XY/SM 系): alt="炎" 等
    #   新 (SV 系):       class="icon-psychic icon"
    type_imgs = re.findall(r'alt="(草|炎|水|雷|超|闘|悪|鋼|フェアリー|ドラゴン|無色)"', html_decoded)
    if type_imgs:
        out["type_jp"] = type_imgs[0]
        out["type_en"] = JP_TYPE_TO_EN.get(type_imgs[0], type_imgs[0])
    else:
        icon_class = re.search(
            r'class="icon-(grass|fire|water|lightning|psychic|fighting|darkness|metal|fairy|dragon|colorless)\s+icon"',
            html_decoded,
            re.IGNORECASE,
        )
        if icon_class:
            en_type = icon_class.group(1).lower()
            _EN_TYPE_NAMES = {
                "grass": "Grass", "fire": "Fire", "water": "Water",
                "lightning": "Lightning", "psychic": "Psychic",
                "fighting": "Fighting", "darkness": "Darkness",
                "metal": "Metal", "fairy": "Fairy", "dragon": "Dragon",
                "colorless": "Colorless",
            }
            _EN_TO_JP = {v: k for k, v in JP_TYPE_TO_EN.items()}
            out["type_en"] = _EN_TYPE_NAMES.get(en_type, en_type.capitalize())
            out["type_jp"] = _EN_TO_JP.get(out["type_en"], "")

    # Set name (拡張パック「XXX」 / ハイクラスパック「XXX」 等) — 任意の空白許可
    set_patterns = [
        r"(拡張パック\s*「[^」]+」)",
        r"(ハイクラスパック\s*「[^」]+」)",
        r"(スターターセット[^「」]*?「[^」]+」)",
        r"(スペシャル(?:パック|BOX|セット)[^「」]*?「[^」]+」)",
        r"(プロモカード[^「」]*?「[^」]+」)",
    ]
    for pat in set_patterns:
        m = re.search(pat, text)
        if m:
            out["set_name_official"] = re.sub(r"\s+", " ", m.group(1)).strip()
            break

    # Illustrator — HTML 内の <div class="author">...</div> から取る方が確実
    m = re.search(r'<div\s+class="author">\s*イラストレーター[\s　]*([^<]+?)\s*</div>',
                  html_decoded, re.DOTALL)
    if m:
        ill = re.sub(r"\s+", " ", m.group(1)).strip()
        if ill and len(ill) < 60:
            out["illustrator"] = ill
    else:
        # Fallback: text 上で次セクションの境界まで取る
        m = re.search(r"イラストレーター[\s　]+(\S+(?:\s\S+)?)", text)
        if m:
            ill = m.group(1).strip()
            # 次セクション語で stop
            ill = re.split(
                r"\s+(?:HP|タイプ|特性|ワザ|弱点|抵抗力|にげる|2進化|1進化|基本|たね|MEGA|VMAX|VSTAR|\d)",
                ill,
            )[0].strip()
            if ill and len(ill) < 60:
                out["illustrator"] = ill

    # Weakness / Resistance / Retreat — HTML <table> から構造的に取る
    # <th>弱点</th><th>抵抗力</th><th>にげる</th> ... <td>×2</td><td>--</td><td>icon-none × N</td>
    m_table = re.search(
        r"<th[^>]*>\s*弱点\s*</th>\s*<th[^>]*>\s*抵抗力\s*</th>\s*<th[^>]*>\s*にげる\s*</th>"
        r".*?<tr>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>",
        html_decoded,
        re.DOTALL,
    )
    if m_table:
        # weakness: extract type from icon class + ×N number
        weak_html = m_table.group(1)
        w_type = re.search(r"icon-(\w+)\s+icon", weak_html)
        w_num = re.sub(r"<[^>]+>", "", weak_html).strip()
        if w_type and w_type.group(1) != "none":
            out["weakness"] = f"{w_type.group(1)} {w_num}".strip()
        else:
            out["weakness"] = w_num.strip() if w_num else "--"

        resist_html = m_table.group(2)
        r_text = re.sub(r"<[^>]+>", "", resist_html).strip()
        out["resistance"] = r_text if r_text else "--"

        retreat_html = m_table.group(3)
        # にげる: count 'icon-' icons (excluding -none which means free retreat)
        icons = re.findall(r"icon-(\w+)\s+icon", retreat_html)
        # icon-none は無色エネルギー必要数 (実は逃げるためのコスト)
        out["retreat"] = str(len(icons)) if icons else "0"

    return out if "name" in out else None


# ============================================================================
# product_id 派生
# ============================================================================
def derive_product_id(detail: dict) -> str:
    """detail dict から product_id を派生.

    優先: '{set_code}-{card_number}' (PSA brand+card_number で lookup できる形)
    fallback: 'cardID-{cardID}' (印刷番号が抽出できないプロモ等)
    """
    set_code = detail.get("set_code") or ""
    card_number = detail.get("card_number") or ""
    if set_code and card_number:
        return f"{set_code}-{card_number}"
    cid = detail.get("cardID") or ""
    return f"cardID-{cid}" if cid else ""


# ============================================================================
# specs 構築
# ============================================================================
def build_specs(detail: dict) -> dict:
    """detail dict → DB 用 specs JSON."""
    specs: dict = {}
    for key in ("hp", "stage", "type_en", "type_jp", "weakness", "resistance",
                "retreat", "regulation", "rarity", "card_number_text",
                "card_number_total"):
        v = detail.get(key)
        if v:
            specs[key] = v
    illustrator = detail.get("illustrator")
    specs["illustrator"] = illustrator if illustrator else None
    # eBay Item Specifics 用 card_type 推定
    name = (detail.get("name") or "")
    if detail.get("hp"):
        specs["card_type"] = "Pokémon"
    elif "エネルギー" in name:
        specs["card_type"] = "Energy"
    else:
        specs["card_type"] = "Trainer"
    return specs


# ============================================================================
# 1 件分 upsert
# ============================================================================
def build_and_upsert(card_id: str | int, dry_run: bool = False) -> dict | None:
    detail = get_detail(card_id)
    if not detail:
        return None
    product_id = derive_product_id(detail)
    if not product_id:
        return None
    specs = build_specs(detail)
    set_official = detail.get("set_name_official")

    record = dict(
        category=CATEGORY,
        product_id=product_id,
        name=detail.get("name", ""),
        name_jp=detail.get("name", ""),     # サイトは JA なので name == name_jp
        set_name=set_official,
        set_name_official=set_official,
        card_set_id=None,                    # Pokemon 公式に内部 set ID は無い
        language="ja",                       # pokemon-card.com は JA
        specs=specs,
        images=[detail["image_url"]] if detail.get("image_url") else [],
        source=SOURCE,
        source_url=f"{DETAIL_BASE}/{card_id}",
    )
    if dry_run:
        print(json.dumps(record, ensure_ascii=False))
        return record
    api.upsert(**record)
    return record


# ============================================================================
# メインスクレイプ
# ============================================================================
def scrape(
    mode: str = "full",
    only_card: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict:
    started_at = datetime.now().isoformat(timespec="seconds")
    print(f"[{started_at}] Pokemon TCG scrape: mode={mode} "
          f"only_card={only_card!r} limit={limit} dry_run={dry_run}")

    # 1. card list
    if only_card:
        # Single card by global cardID
        card_ids = [str(only_card)]
    else:
        print("  fetching list (paginated) ...")
        cards = list_all_cards()
        print(f"  list: {len(cards)} cards")
        card_ids = [c.get("cardID") for c in cards if c.get("cardID")]

    if limit:
        card_ids = card_ids[:limit]

    counts = {"added": 0, "updated": 0, "skipped": 0, "total_processed": 0}
    for i, cid in enumerate(card_ids):
        if mode == "update":
            # Skip if already in DB (we use a placeholder check via cardID-lookup)
            # We need to check by some product_id, but we don't know it without detail.
            # So check if cache file exists as cheap heuristic.
            cache_path = CACHE_DIR / f"detail_{cid}.json"
            if cache_path.exists():
                # Already cached → check DB upsert via cached detail
                try:
                    detail = json.loads(cache_path.read_text(encoding="utf-8"))
                    pid = derive_product_id(detail)
                    if pid and api.lookup(CATEGORY, pid):
                        counts["skipped"] += 1
                        continue
                except Exception:
                    pass

        try:
            existing_pid = None
            try:
                cache_path = CACHE_DIR / f"detail_{cid}.json"
                if cache_path.exists():
                    d = json.loads(cache_path.read_text(encoding="utf-8"))
                    existing_pid = derive_product_id(d)
            except Exception:
                pass
            already = api.lookup(CATEGORY, existing_pid) if existing_pid else None

            result = build_and_upsert(cid, dry_run=dry_run)
            if result:
                if already:
                    counts["updated"] += 1
                else:
                    counts["added"] += 1
                counts["total_processed"] += 1
            else:
                counts["skipped"] += 1
        except Exception as e:
            print(f"  ⚠️ cardID={cid}: {e}")
            counts["skipped"] += 1

        if (i + 1) % 50 == 0:
            print(f"  ... {i+1}/{len(card_ids)} processed "
                  f"(added={counts['added']} updated={counts['updated']} "
                  f"skipped={counts['skipped']})", flush=True)

    finished_at = datetime.now().isoformat(timespec="seconds")
    print(f"[{finished_at}] done: {counts}")

    # scrape_log
    if not dry_run:
        try:
            conn = api._connect()
            try:
                conn.execute(
                    "INSERT INTO scrape_log (category, started_at, finished_at, "
                    "status, products_added, products_updated) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (CATEGORY, started_at, finished_at, "success",
                     counts["added"], counts["updated"]),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            print(f"  ⚠️ scrape_log write failed: {e}")

    return counts


# ============================================================================
# CLI
# ============================================================================
def main():
    p = argparse.ArgumentParser(description="Pokemon TCG → iMakCatalog scraper")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--full", action="store_true", help="全件 scrape")
    g.add_argument("--update", action="store_true", help="差分のみ")
    g.add_argument("--card", metavar="CARD_ID",
                   help="単一 cardID のみ (global numeric ID, 例: 50000)")
    p.add_argument("--limit", type=int, help="先頭 N 件のみ (動作確認用)")
    p.add_argument("--dry-run", action="store_true",
                   help="DB に書かず record を JSON で stdout 出力")
    args = p.parse_args()

    if args.full:
        scrape(mode="full", limit=args.limit, dry_run=args.dry_run)
    elif args.update:
        scrape(mode="update", limit=args.limit, dry_run=args.dry_run)
    elif args.card:
        scrape(mode="full", only_card=args.card, limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
