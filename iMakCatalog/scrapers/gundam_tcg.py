#!/usr/bin/env python3
"""Gundam Card Game scraper — Bandai TCG+ API 経由で全カードを iMakCatalog DB に投入.

データ源:
  - https://api.bandai-tcg-plus.com (game_title_id=16 EN / 15 JA)

設計:
  - list endpoint をページングで全件取得 (EN/JA 別)
  - 各カード詳細は disk cache (db/cache/) に保存して再取得を回避
  - バリアント (通常/SP/Parallel) は別レコードとして保存し、product_id に suffix
      base                : GD01-002
      Special             : GD01-002_SP
      reprint in GD04     : GD01-002_GD04 (再録)
  - JA は image_url から正規化キーで EN にマージ
  - image filename: 'batch_GD01-002_SP_dummy_EN.png' / 'batch_GD01-002_SP_dummy_JP.png'

CLI:
  python scrapers/gundam_tcg.py --full              # 全件 (約 1200 件、~1 時間)
  python scrapers/gundam_tcg.py --update            # 差分のみ (DB に無い product_id だけ)
  python scrapers/gundam_tcg.py --card GD01-002     # 単一 card_number の全バリアント
  python scrapers/gundam_tcg.py --limit 20          # 先頭 N 件のみ (動作確認用)
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
API_BASE = "https://api.bandai-tcg-plus.com/api"
GAME_ID_EN = 16
GAME_ID_JA = 15
CATEGORY = "gundam_tcg"
SOURCE = "bandai_tcg_plus"
PAGE_SIZE = 100

# 礼儀作法 (Bandai TCG+ は第三者公開 API ではないので保守的に):
#   - 各 call 後に 1.5s sleep
#   - Chrome ライクな User-Agent と Accept-Language
#   - 429 / 403 / 5xx で exponential backoff (8s → 16s → 32s → 60s)
SLEEP_BETWEEN_CALLS = 1.5
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,ja;q=0.8",
    "Origin": "https://www.bandai-tcg-plus.com",
    "Referer": "https://www.bandai-tcg-plus.com/",
}

CACHE_DIR = Path(__file__).resolve().parent.parent / "db" / "cache" / CATEGORY
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# requests Session で Keep-Alive
_session = requests.Session()
_session.headers.update(DEFAULT_HEADERS)


# ============================================================================
# HTTP
# ============================================================================
def _get_json(url: str, params: dict, retries: int = 5) -> dict:
    """API call with exponential backoff on 429 / 403 / 5xx / network errors.

    Backoff: 8s → 16s → 32s → 60s → 60s (max 5 attempts).
    """
    backoff = [8, 16, 32, 60, 60]
    last_err = None
    for attempt in range(retries):
        try:
            r = _session.get(url, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 403) or r.status_code >= 500:
                wait = backoff[min(attempt, len(backoff) - 1)]
                print(f"    ⚠️ HTTP {r.status_code} on {url} → wait {wait}s "
                      f"(attempt {attempt + 1}/{retries})", flush=True)
                last_err = f"HTTP {r.status_code}"
                time.sleep(wait)
                continue
            # その他の 4xx (404 等) は即時失敗
            return {}
        except (requests.ConnectionError, requests.Timeout) as e:
            wait = backoff[min(attempt, len(backoff) - 1)]
            print(f"    ⚠️ network error: {e} → wait {wait}s "
                  f"(attempt {attempt + 1}/{retries})", flush=True)
            last_err = str(e)
            time.sleep(wait)
    raise RuntimeError(f"GET {url} failed after {retries} retries: {last_err}")


def list_all_cards(game_id: int, card_param: str | None = None) -> list[dict]:
    """list endpoint を全ページ取得. card_param 指定で単一 card_number に絞れる."""
    all_cards: list[dict] = []
    offset = 0
    while True:
        params = {
            "game_title_id": game_id,
            "limit": PAGE_SIZE,
            "offset": offset,
            "reverse_card": 0,
        }
        if card_param:
            params["card_param"] = card_param
        data = _get_json(f"{API_BASE}/user/card/list", params).get("success", {})
        cards = data.get("cards", []) or []
        all_cards.extend(cards)
        total = int(data.get("total", 0))
        if not cards or len(all_cards) >= total:
            break
        offset += PAGE_SIZE
        time.sleep(SLEEP_BETWEEN_CALLS)
    return all_cards


def get_detail(api_id: int, language: str = "EN") -> dict | None:
    """card detail (キャッシュ付). language='EN'|'JA'"""
    cache_path = CACHE_DIR / f"detail_{language}_{api_id}.json"
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cache_path.unlink()  # corrupt cache → refetch

    game_id = GAME_ID_EN if language == "EN" else GAME_ID_JA
    country = "US" if language == "EN" else "JP"
    data = _get_json(
        f"{API_BASE}/user/card/{api_id}",
        {
            "game_title_id": game_id,
            "language_code": language,
            "app_version": "9.9.9",
            "country_code": country,
        },
    )
    detail = data.get("success", {}).get("card")
    if detail:
        cache_path.write_text(
            json.dumps(detail, ensure_ascii=False), encoding="utf-8"
        )
    time.sleep(SLEEP_BETWEEN_CALLS)
    return detail


# ============================================================================
# 解析: image_url → variant 識別子
# ============================================================================
def _normalize_image_path(image_url: str) -> tuple[str, str]:
    """image_url を (set_folder, base_name) に分解.

    例 (Gundam):
      https://.../card_image/GC-EN/GD04/batch_GD01-002_SP_dummy_EN.png → ("GD04", "GD01-002_SP")
      https://.../card_image/GC-JA/GD04/batch_GD01-002_SP_dummy_JP.png → ("GD04", "GD01-002_SP")
      https://.../card_image/GC-EN/GD01/batch_GD01-001_EN.png         → ("GD01", "GD01-001")
    """
    if not image_url:
        return "", ""
    parts = image_url.rstrip("/").split("/")
    if len(parts) < 2:
        return "", ""
    set_folder = parts[-2]
    fname = parts[-1].split(".")[0]
    fname = re.sub(r"^batch_", "", fname)
    # Gundam 特有: 末尾の placeholder/言語マーカーを順番に剥がす
    #   '_sample' (placeholder), '_dummy', '_EN' / '_JP' (言語), '_d' (下位互換)
    fname = re.sub(r"_sample$", "", fname, flags=re.IGNORECASE)
    fname = re.sub(r"_dummy(_EN|_JP)?$", "", fname)
    fname = re.sub(r"_(EN|JP)$", "", fname)
    fname = re.sub(r"_d$", "", fname)
    return set_folder, fname


def _extract_set_tag(set_folder: str, card_prefix: str) -> tuple[str, bool]:
    """folder から「セットタグ」を正規化. EN/JA で同じカードが違う folder にあるケース
    (EN "OP15-EB04" vs JA "EB04") を同一視するため、folder が card_prefix を含めば native 扱い.

    Returns: (tag, is_native)
        is_native=True の場合、tag は card_prefix そのもの → product_id に suffix 付けない.
        is_native=False の場合、tag は folder そのもの → 再録 suffix として使う.
    """
    if not set_folder:
        return "", True
    folder_up = set_folder.upper()
    prefix_up = (card_prefix or "").upper()
    if not prefix_up:
        return folder_up, False
    if folder_up == prefix_up:
        return prefix_up, True
    if prefix_up in folder_up.split("-"):
        return prefix_up, True
    return folder_up, False


def derive_product_id(card_number: str, image_url: str) -> str:
    """バリアント識別子付きの product_id を生成.

    ロジック:
      - folder が card_number prefix と一致 / または含む → native (suffix なし)
      - 不一致 → 再録と判定し folder を suffix
      - filename に card_number 末尾以降の文字 (parallel "p" / 仕上 "_LF" / "_sample" 等) → 追加 suffix
        ただし "_sample" 等の事前公開マーカーは EN/JA 同期のため除外
    """
    set_folder, base_name = _normalize_image_path(image_url)
    prefix = card_number.split("-")[0] if "-" in card_number else ""
    tag, is_native = _extract_set_tag(set_folder, prefix)

    suffix_parts: list[str] = []
    if not is_native and tag:
        suffix_parts.append(tag)

    # filename 末尾から card_number を剥がして余りを suffix に
    leftover = ""
    if base_name.startswith(card_number):
        leftover = base_name[len(card_number):].lstrip("_")
    elif card_number in base_name:
        leftover = base_name.split(card_number, 1)[1].lstrip("_")
    # "_sample" は EN/JA で片方だけ付くので除外 (variant の本質ではない)
    leftover = re.sub(r"_?sample$", "", leftover, flags=re.IGNORECASE).rstrip("_")
    if leftover:
        suffix_parts.append(leftover)

    return card_number + ("_" + "_".join(suffix_parts) if suffix_parts else "")


# ============================================================================
# specs / 正規化
# ============================================================================
SPECS_DROP = {"BlockIcon", "ブロックアイコン"}  # eBay で使わない

# JA 版 detail の config_name キーを EN 表記に正規化 (Gundam Card Game 固有スキーマ).
JA_CONFIG_KEY_TO_EN: dict[str, str] = {
    "カードタイプ":      "Card Type",
    "レアリティ":        "Rarity",
    "Lv. (レベル)":      "Lv. (Level)",
    "COST(コスト)":      "Cost",  # 半角括弧版
    "COST（コスト）":    "Cost",  # 全角括弧版
    "色":                "Color",
    "出典タイトル":      "Source Title",
    "特徴":              "Trait",
    "リンク条件":        "Link Requirement",
    "AP":                "AP",
    "HP":                "HP",
    "AP強化":            "AP Boost",
    "HP強化":            "HP Boost",
    "地形":              "Zone",
    "備考":              "Notes",
}


def card_config_to_specs(card_config: list[dict], lang: str = "EN") -> dict:
    """detail.card_config (list of {config_name, value}) を dict に.

    - 値が None / 空文字のキーは保存しない
    - SPECS_DROP のキー (BlockIcon 等) は除外
    - JA detail はキーを EN に正規化 (値は raw のまま)
    """
    specs: dict = {}
    for item in card_config or []:
        name = item.get("config_name")
        value = item.get("value")
        if not name or name in SPECS_DROP:
            continue
        if value is None or value == "":
            continue
        if lang == "JA":
            name = JA_CONFIG_KEY_TO_EN.get(name, name)
        specs[name] = value
    return specs


def detect_language(en_card: dict | None, ja_card: dict | None) -> str | None:
    """EN/JA list-card の有無から言語フラグを判定."""
    if en_card and ja_card:
        return "both"
    if en_card:
        return "en"
    if ja_card:
        return "ja"
    return None


def extract_legality(en_card: dict | None) -> dict:
    """list endpoint の is_*_legal フラグを dict に."""
    if not en_card:
        return {}
    return {
        "main": int(bool(en_card.get("is_main_legal"))),
        "extra": int(bool(en_card.get("is_extra_legal"))),
        "extra2": int(bool(en_card.get("is_extra2_legal"))),
        "side": int(bool(en_card.get("is_side_legal"))),
    }


# ============================================================================
# JA join key: (card_number, set_folder, leftover)
# ============================================================================
def _variant_key(card_number: str, image_url: str) -> tuple[str, str, str]:
    """EN/JA を join するための variant key. derive_product_id と同じロジックで揃える."""
    set_folder, base_name = _normalize_image_path(image_url)
    prefix = card_number.split("-")[0] if "-" in card_number else ""
    tag, is_native = _extract_set_tag(set_folder, prefix)
    canonical_tag = "" if is_native else tag

    leftover = ""
    if base_name.startswith(card_number):
        leftover = base_name[len(card_number):].lstrip("_")
    elif card_number in base_name:
        leftover = base_name.split(card_number, 1)[1].lstrip("_")
    leftover = re.sub(r"_?sample$", "", leftover, flags=re.IGNORECASE).rstrip("_")
    return (card_number, canonical_tag, leftover.upper())


def index_ja_by_variant(ja_list: list[dict]) -> dict[tuple, dict]:
    """JA list を variant key で index 化."""
    idx: dict[tuple, dict] = {}
    for c in ja_list:
        cn = c.get("card_number") or ""
        if not cn:
            continue
        idx[_variant_key(cn, c.get("image_url") or "")] = c
    return idx


# ============================================================================
# 1 件分の record を組み立てて upsert
# ============================================================================
def build_and_upsert(
    en_card: dict | None,
    ja_card: dict | None,
    en_detail_required: bool = True,
    dry_run: bool = False,
) -> dict | None:
    """EN list-card と JA list-card のペアから 1 record を作って upsert.

    EN が無く JA のみの場合 (JA 限定プロモ) も保存する.
    """
    primary = en_card or ja_card
    if not primary:
        return None
    card_number = primary.get("card_number") or ""
    image_url_en = (en_card or {}).get("image_url") or ""
    image_url_ja = (ja_card or {}).get("image_url") or ""
    image_url = image_url_en or image_url_ja
    if not card_number or not image_url:
        return None

    product_id = derive_product_id(card_number, image_url)

    # EN detail (specs / card_set / name_en / card_text)
    name_en = (en_card or {}).get("card_name") or ""
    set_official = ""
    specs: dict = {}
    card_text = ""
    is_division_text = False
    regulations: list[str] = []
    if en_card:
        det = get_detail(en_card["id"], "EN")
        if det:
            name_en = det.get("card_name") or name_en
            set_official = det.get("card_set") or ""
            specs = card_config_to_specs(det.get("card_config", []))
            card_text = det.get("card_text") or ""
            is_division_text = bool(det.get("is_division_text"))
            regulations = [r.get("title") for r in (det.get("regulations") or []) if r.get("title")]

    # JA detail (name_jp / fallback set / fallback card_text / fallback specs)
    name_jp = None
    card_text_jp = ""
    if ja_card:
        det_ja = get_detail(ja_card["id"], "JA")
        if det_ja:
            name_jp = det_ja.get("card_name") or None
            if not set_official:
                set_official = det_ja.get("card_set") or ""
            card_text_jp = det_ja.get("card_text") or ""
            if not regulations:
                regulations = [r.get("title") for r in (det_ja.get("regulations") or []) if r.get("title")]
            # specs が EN から取れていない (JA-only variant) → JA card_config を fallback
            if not specs:
                specs = card_config_to_specs(det_ja.get("card_config", []), lang="JA")

    # specs に追加情報を埋め込む (raw 保存方針: 変換は lookup 側)
    if card_text:
        specs["card_text"] = card_text
    if card_text_jp:
        specs["card_text_jp"] = card_text_jp
    if is_division_text:
        specs["is_division_text"] = True
    if regulations:
        specs["regulations"] = regulations
    legality = extract_legality(en_card)
    if legality:
        specs["legality"] = legality
    # illustrator は One Piece 公式が開示していないので None placeholder
    specs.setdefault("illustrator", None)

    # card_set_id (EN 優先、なければ JA)
    card_set_id = (en_card or {}).get("card_set_id") or (ja_card or {}).get("card_set_id")
    if card_set_id is not None:
        try:
            card_set_id = int(card_set_id)
        except (TypeError, ValueError):
            card_set_id = None

    images = [u for u in [image_url_en, image_url_ja] if u]
    language = detect_language(en_card, ja_card)

    record = dict(
        category=CATEGORY,
        product_id=product_id,
        name=name_en or (name_jp or card_number),
        name_jp=name_jp,
        set_name=set_official or None,            # raw 保存 (lookup 側で eBay 値変換)
        set_name_official=set_official or None,
        card_set_id=card_set_id,
        language=language,
        specs=specs,
        images=images,
        source=SOURCE,
        source_url=f"{API_BASE}/user/card/{(en_card or ja_card)['id']}",
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
    """全件 / 差分 / 単一 card_number でスクレイプ.

    Returns:
        {"added": int, "updated": int, "skipped": int, "total_processed": int}
    """
    started_at = datetime.now().isoformat(timespec="seconds")
    print(f"[{started_at}] One Piece TCG scrape: mode={mode} "
          f"only_card={only_card!r} limit={limit} dry_run={dry_run}")

    # 1. EN/JA list (only_card 指定なら API 側で絞る)
    print("  fetching EN list ...")
    en_list = list_all_cards(GAME_ID_EN, card_param=only_card)
    print(f"  EN: {len(en_list)} cards")
    print("  fetching JA list ...")
    ja_list = list_all_cards(GAME_ID_JA, card_param=only_card)
    print(f"  JA: {len(ja_list)} cards")

    # 3. JA index
    ja_idx = index_ja_by_variant(ja_list)

    # 4. EN を主軸に variant 単位で record を作る
    pairs: list[tuple[dict | None, dict | None]] = []
    seen_ja_keys: set[tuple] = set()

    for en_c in en_list:
        cn = en_c.get("card_number") or ""
        key = _variant_key(cn, en_c.get("image_url") or "")
        ja_c = ja_idx.get(key)
        if ja_c:
            seen_ja_keys.add(key)
        pairs.append((en_c, ja_c))

    # JA-only (EN に無いプロモ等) も追加
    for ja_c in ja_list:
        cn = ja_c.get("card_number") or ""
        key = _variant_key(cn, ja_c.get("image_url") or "")
        if key not in seen_ja_keys:
            pairs.append((None, ja_c))

    if limit:
        pairs = pairs[:limit]

    # 5. update モード = 既存 product_id を skip
    counts = {"added": 0, "updated": 0, "skipped": 0, "total_processed": 0}
    for i, (en_c, ja_c) in enumerate(pairs):
        primary = en_c or ja_c
        cn = (primary or {}).get("card_number") or ""
        img = ((en_c or {}).get("image_url") or (ja_c or {}).get("image_url") or "")
        pid = derive_product_id(cn, img) if cn else ""
        if not pid:
            counts["skipped"] += 1
            continue

        if mode == "update":
            existing = api.lookup(CATEGORY, pid)
            if existing:
                counts["skipped"] += 1
                continue
            counts["added"] += 1
        else:
            existing = api.lookup(CATEGORY, pid)
            if existing:
                counts["updated"] += 1
            else:
                counts["added"] += 1

        try:
            build_and_upsert(en_c, ja_c, dry_run=dry_run)
        except Exception as e:
            print(f"  ⚠️ {pid}: {e}")
            counts["skipped"] += 1
            continue
        counts["total_processed"] += 1

        if (i + 1) % 50 == 0:
            print(f"  ... {i+1}/{len(pairs)} processed (added={counts['added']} "
                  f"updated={counts['updated']} skipped={counts['skipped']})", flush=True)

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
    p = argparse.ArgumentParser(description="One Piece TCG → iMakCatalog scraper")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--full", action="store_true", help="全件 scrape (既存も上書き)")
    g.add_argument("--update", action="store_true", help="差分のみ (新規 product_id だけ)")
    g.add_argument("--card", metavar="CARD_NUMBER",
                   help="単一 card_number の全 variant のみ")
    p.add_argument("--limit", type=int, help="先頭 N 件のみ処理 (動作確認用)")
    p.add_argument("--dry-run", action="store_true",
                   help="DB に書かず record を JSON で stdout に出力")
    args = p.parse_args()

    if args.full:
        scrape(mode="full", limit=args.limit, dry_run=args.dry_run)
    elif args.update:
        scrape(mode="update", limit=args.limit, dry_run=args.dry_run)
    elif args.card:
        scrape(mode="full", only_card=args.card, limit=args.limit,
               dry_run=args.dry_run)


if __name__ == "__main__":
    main()
