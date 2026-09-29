"""eBay フィルタマスタ catalog (= 2026-05-31 構築、 案 C + Gemini 改善 A 同梱).

依頼:
  - 構築: 2026-05-31_ebay_filter_master_catalog_tcg_phase2_api.md
  - 案 C + Gemini A: 2026-05-31_catalog_ebay_alignment_strategy_decision.md

eBay 公式 SellMetadata API (= getItemAspectsForCategory) で取得した
カテゴリ別の正規値 list を JSON で保持。 listing 側で値検証 + 空欄/FREE_TEXT 通過 fallback。

API:
  - validate_value(category, field, value) -> Optional[str]
      FREE_TEXT mode: catalog 値そのまま return (= 公式値、 不在でも投入)
      SELECTION_ONLY mode: 一致なら正規値、 不在なら None (= 空欄)
      正規化比較 (NFKC + lower + trim) で表記揺れ吸収。
  - list_required_aspects(category) -> list[str]
  - is_required(category, field) -> bool
  - get_max_length(category, field) -> Optional[int]
  - get_aspect(category, field) -> Optional[dict]
  - list_aspects(category) -> list[str]
  - all_categories() -> list[str]
"""
from __future__ import annotations

import json
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Optional

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "ebay_filter_masters"

# eBay Item Specifics の標準値長制限 (= 公式ドキュメント記載)
_EBAY_DEFAULT_MAX_LENGTH = 65


@lru_cache(maxsize=8)
def _load(category: str) -> dict:
    """category 別の master JSON 読込 (= cache 付き)."""
    f = _DATA_DIR / f"{category}.json"
    if not f.exists():
        raise FileNotFoundError(f"eBay filter master not found: {f}")
    return json.loads(f.read_text(encoding="utf-8"))


def _normalize_for_match(s: str) -> str:
    """比較用正規化 (= Gemini 改善 A).

    - Unicode 正規化 (NFKC) = 全角半角 + 合字統一
    - 前後 trim
    - 小文字化
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    return s.strip().lower()


def all_categories() -> list[str]:
    """利用可能なカテゴリ list (= ebay_filter_masters/*.json)."""
    if not _DATA_DIR.exists():
        return []
    return sorted(p.stem for p in _DATA_DIR.glob("*.json"))


def get_aspect(category: str, field: str) -> Optional[dict]:
    """指定 category/field の aspect 構造取得 (= raw)."""
    try:
        m = _load(category)
    except FileNotFoundError:
        return None
    return m.get("aspects", {}).get(field)


def _get_mode(asp: dict) -> str:
    """aspect_mode 取得 (= SELECTION_ONLY / FREE_TEXT)."""
    c = asp.get("constraint", {})
    return (c.get("aspect_mode") or c.get("aspectMode") or "FREE_TEXT").upper()


def validate_value(category: str, field: str, value: Optional[str]) -> Optional[str]:
    """値検証 (= 案 C + Gemini A).

    mode 別 logic:
      - SELECTION_ONLY: 正規化比較で一致 → 正規値 return、 不在 → None (= 空欄 fallback)
      - FREE_TEXT: 正規化比較で一致 → 正規値 return、 不在 → catalog 値そのまま return
                   (= 公式 catalog 値、 推測ではなく取得値投入)
      - aspect 不在カテゴリ/field: None
      - values list 不在 (= 完全自由入力 field): 値そのまま return
    """
    if not value:
        return None
    asp = get_aspect(category, field)
    if asp is None:
        return None
    values = asp.get("values") or []
    val_str = str(value).strip()

    # values list 不在 (= 完全自由入力、 例: Card Number / Cert# / HP) は値そのまま採用
    if not values:
        return val_str

    # 正規化比較 (= Gemini 改善 A)
    val_norm = _normalize_for_match(val_str)
    for v in values:
        if _normalize_for_match(str(v)) == val_norm:
            return v  # 正規表記を return

    # 不一致時の挙動 = mode 依存
    mode = _get_mode(asp)
    if mode == "SELECTION_ONLY":
        return None  # 空欄 fallback
    # FREE_TEXT = catalog 値そのまま return (= 公式値、 不在でも投入)
    return val_str


def list_required_aspects(category: str) -> list[str]:
    """category の必須 aspect (= aspect_required=True) を返す."""
    try:
        m = _load(category)
    except FileNotFoundError:
        return []
    out = []
    for name, asp in m.get("aspects", {}).items():
        c = asp.get("constraint", {})
        req = c.get("aspect_required") or c.get("aspectRequired") or False
        if req:
            out.append(name)
    return out


def is_required(category: str, field: str) -> bool:
    """指定 field が必須か (= HQ 改善 B 用)."""
    asp = get_aspect(category, field)
    if asp is None:
        return False
    c = asp.get("constraint", {})
    return bool(c.get("aspect_required") or c.get("aspectRequired"))


def get_max_length(category: str, field: str) -> Optional[int]:
    """指定 field の最大文字数 (= HQ 改善 B 用 truncation).

    constraint に max_length 明示があればそれを return、 なければ eBay 標準 (= 65)。
    """
    asp = get_aspect(category, field)
    if asp is None:
        return None
    c = asp.get("constraint", {})
    ml = c.get("max_length") or c.get("maxLength")
    if ml:
        return int(ml)
    return _EBAY_DEFAULT_MAX_LENGTH


def list_aspects(category: str) -> list[str]:
    """category の全 aspect 名."""
    try:
        m = _load(category)
    except FileNotFoundError:
        return []
    return list(m.get("aspects", {}).keys())
