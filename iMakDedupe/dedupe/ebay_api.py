"""eBay Browse API wrapper — Phase 1e (= Item Specifics 取得).

依頼書 §4 推奨 A 案: `iMakeBayAPI` の既存関数を import 経由で reuse.
- 越境 read-only (= 5/24 リバイスくん事例同様、 関数呼出のみ)
- 越境 dir への 編集 / git 操作 は **絶対禁止**

参照する既存資産:
- `check_csv_core.py::load_ebay_keys()` (= ebay keys.txt 読込)
- `check_csv_core.py::get_oauth_token(app_id, app_secret)` (= OAuth client_credentials grant)
- `ebay_seller_store_scraper.py::fetch_listing_detail_via_api(token, item_id, ...)` (= Browse API getItem)
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

# === 越境 import パス (= 依頼書 §4 で許可済) ===
IMAK_EBAY_API_DIR = r"C:\dev\iMak\iMakeBayAPI"
if IMAK_EBAY_API_DIR not in sys.path:
    sys.path.insert(0, IMAK_EBAY_API_DIR)

# === 重複くん cache 保存先 ===
DEFAULT_CACHE_DIR = Path(r"C:\dev\iMak_data\dedupe\cache")
CACHE_FILE_PREFIX = "listing_specs_"

# === 抽出対象の Item Specifics aspect 名 (= 優先順) ===
KEY_ASPECT_PRIORITY = ("Card Number", "Model", "MPN")


def _import_imak_api():
    """iMakeBayAPI の関数を遅延 import (= unit test で mock 容易).

    `check_csv_core` は EBAY_KEYS_FILE を SCRIPT_DIR 経由の絶対 path で解決するため
    cwd 不問で機能する (= sys.path 設定だけで OK)。
    """
    from check_csv_core import load_ebay_keys, get_oauth_token  # noqa: E402
    from ebay_seller_store_scraper import fetch_listing_detail_via_api  # noqa: E402
    return load_ebay_keys, get_oauth_token, fetch_listing_detail_via_api


def get_token() -> str:
    """OAuth client_credentials grant で access token を取得.

    `ebay keys.txt` の AppID / AppSecret を使用。 期限 ~2h、 毎回新規取得が安全。
    """
    load_keys, get_token_fn, _ = _import_imak_api()
    keys = load_keys()
    app_id = keys.get("AppID")
    app_secret = keys.get("AppSecret")
    if not app_id or not app_secret:
        raise RuntimeError(
            "AppID / AppSecret が ebay keys.txt から取得できない "
            f"(path={IMAK_EBAY_API_DIR}/ebay keys.txt)"
        )
    return get_token_fn(app_id, app_secret)


def fetch_specifics(token: str, item_id: str) -> Dict[str, str]:
    """1 件 fetch → Item Specifics の {aspect_name: value} dict.

    エラー時 (= HTTP non-200 / 例外) は `{"_error": "..."}` を返却。
    呼出側で `"_error" in result` で判定する。
    """
    _, _, fetch_fn = _import_imak_api()
    raw = fetch_fn(token, item_id)
    if not isinstance(raw, dict):
        return {"_error": f"unexpected response type: {type(raw).__name__}"}
    if raw.get("error"):
        return {"_error": str(raw["error"])}
    specs: Dict[str, str] = {}
    for a in raw.get("localizedAspects") or []:
        name = (a.get("name") or "").strip()
        value = (a.get("value") or "").strip()
        if name:
            specs[name] = value
    return specs


def batch_fetch_specifics(
    token: str,
    item_ids: Iterable[str],
    output_path: Path,
    flush_every: int = 50,
    sleep_seconds: float = 0.1,
    progress: bool = True,
) -> Dict[str, Dict[str, str]]:
    """全 item ID を順次 fetch → JSON 保存. resumable (= 既存 cache 続き).

    既に cache にある item_id は skip。
    flush_every 件ごとに JSON flush (= 中断時も部分保存)。
    """
    cache = load_cache_if_exists(output_path)
    item_ids_list = [iid for iid in item_ids if iid]
    total = len(item_ids_list)
    new_count = 0
    err_count = 0

    for i, item_id in enumerate(item_ids_list, start=1):
        if item_id in cache:
            continue
        specs = fetch_specifics(token, item_id)
        if "_error" in specs:
            err_count += 1
        cache[item_id] = specs
        new_count += 1
        if new_count % flush_every == 0:
            save_cache(cache, output_path)
            if progress:
                print(
                    f"  [{i}/{total}] flushed ({new_count} new, {err_count} err)",
                    flush=True,
                )
        if sleep_seconds:
            time.sleep(sleep_seconds)

    save_cache(cache, output_path)
    if progress:
        print(
            f"  done: total={total} new={new_count} err={err_count} "
            f"cache_total={len(cache)}",
            flush=True,
        )
    return cache


def load_cache_if_exists(path: Path) -> Dict[str, Dict[str, str]]:
    """cache 既存なら読込、 無ければ空 dict。"""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cache(cache: Dict[str, Dict[str, str]], path: Path) -> None:
    """cache を JSON で保存 (= UTF-8 + indent)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def find_latest_cache(cache_dir: Path = DEFAULT_CACHE_DIR) -> Optional[Path]:
    """cache dir で 最新 (= 辞書順最後) の listing_specs_*.json を返す."""
    if not cache_dir.exists():
        return None
    candidates = sorted(cache_dir.glob(f"{CACHE_FILE_PREFIX}*.json"))
    return candidates[-1] if candidates else None


def build_cache_path(
    cache_dir: Path = DEFAULT_CACHE_DIR,
    date_str: Optional[str] = None,
) -> Path:
    """cache file path を組立 (= listing_specs_YYYY-MM-DD.json)."""
    from datetime import datetime

    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    return cache_dir / f"{CACHE_FILE_PREFIX}{date_str}.json"


def extract_key_from_specifics(
    specifics: Dict[str, str],
) -> Tuple[Optional[str], str]:
    """Item Specifics から KEY 値を 1 個抽出 (= priority order: Card Number > Model > MPN).

    Return: (key_value, aspect_name) — hit 無ければ (None, "")
    fail-closed: 値が空 / `_error` / 不在 → None
    """
    if not specifics or "_error" in specifics:
        return None, ""
    for aspect in KEY_ASPECT_PRIORITY:
        v = (specifics.get(aspect) or "").strip()
        if v:
            return v, aspect
    return None, ""
