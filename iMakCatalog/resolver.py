"""KEY再設計 Step3: catalog resolver facade — canonical KEY の唯一の入口.

spec: iMak_data/KEY_REDESIGN_SPEC.md §3 / greenlight: requests/2026-06-09_key_redesign_BUILD_greenlight_phase1*.md

    resolve(context) -> canonical KEY
      = catalog product_id (catalog-backed: TCG/DON)
      | 正規化URL key       (non-catalog: marketplace 直仕入れ)
      | ""                  (判別不能/未対応 = fail-closed、推測で固有id当てない=誤出品防止)

既存の解決ロジック(integrations/psa_to_csv の lookup_*/extract_*/promo-scoring)を
**内部 dispatch で集約**するだけ(新規解決ロジックは作らない)。lookup APIの key不統一
(card_id vs product_id)は本facadeが吸収し、戻り値は **canonical product_id に統一**。

拡張性(spec §11): 新カテゴリ=_TCG_LOOKUP に1行 / 新販路=_normalize_url_key / 新識別=dispatch分岐。契約(戻り値)不変。
移行: psa_to_csv の lookup_* はそのまま残し(shim併存)、呼び出し側を順次 resolve() へ向け替え(無停止)。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

_ROOT = Path(__file__).resolve().parent
for _p in (str(_ROOT), str(_ROOT / "integrations")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import psa_to_csv as _pc  # noqa: E402

# category(正規化後) → lookup fn. TCGは統一 signature (brand, card_number, subject, verbose).
_TCG_LOOKUP = {
    "one_piece_tcg": _pc.lookup_one_piece,
    "gundam_tcg": _pc.lookup_gundam,
    "dragonball_scg": _pc.lookup_dragonball,
    "pokemon_tcg": _pc.lookup_pokemon,
    "yugioh": _pc.lookup_yugioh,
}
_CATEGORY_ALIASES = {
    "one_piece": "one_piece_tcg", "onepiece": "one_piece_tcg", "op": "one_piece_tcg", "opcg": "one_piece_tcg",
    "gundam": "gundam_tcg", "gcg": "gundam_tcg",
    "dragonball": "dragonball_scg", "dbscg": "dragonball_scg", "dbfw": "dragonball_scg",
    "pokemon": "pokemon_tcg", "pkmn": "pokemon_tcg",
    "yugioh_tcg": "yugioh", "ygo": "yugioh",
    "one_piece_don": "don", "op_don": "don",
}


def _norm_category(c: str | None) -> str:
    c = (c or "").strip().lower()
    return _CATEGORY_ALIASES.get(c, c)


# brand → category 検出 (PSA brand は game名を含む=game identity の権威).
#   番号衝突(例 ST04-013 が OP=X.Drake と Gundam=Hawk of Endymion の両方に存在)を分離する。
#   2026-06-10 HQ greenlight (II): "GUNDAM"→gundam / "DRAGON BALL"・"DB"→dragonball 等。
#   ⚠️ fail-closed: brand から確信を持って判定できない時は None (= 呼び出し側 category を尊重)。
import re as _re  # noqa: E402

_BRAND_CATEGORY_RULES = [
    (_re.compile(r"\bONE\s*PIECE\b"), "one_piece_tcg"),
    (_re.compile(r"\bGUNDAM\b"), "gundam_tcg"),
    (_re.compile(r"DRAGON\s*BALL|\bDBS?\b|FUSION\s*WORLD"), "dragonball_scg"),
    (_re.compile(r"\bYU-?GI-?OH\b"), "yugioh"),
    (_re.compile(r"\bPOKEMON\b|\bPOKÉMON\b"), "pokemon_tcg"),
]


def _detect_category_from_brand(brand: str) -> str | None:
    if not brand:
        return None
    b = brand.upper()
    hits = [cat for rx, cat in _BRAND_CATEGORY_RULES if rx.search(b)]
    # 一意に1 game のみ該当 → それを採用。複数該当(曖昧)→ None(fail-closed、呼び出し側尊重)
    uniq = set(hits)
    return hits[0] if len(uniq) == 1 else None


def _normalize_url_key(url: str) -> str:
    """non-catalog marketplace URL → 正規化 url-key (item:/shops: prefix). spec §2."""
    if not url:
        return ""
    try:
        u = urlsplit(url.strip())
    except Exception:
        return ""
    host = (u.netloc or "").lower().replace("www.", "")
    path = (u.path or "").rstrip("/")
    m = re.search(r"/item/([A-Za-z0-9]+)", path)
    if m:
        return f"item:{m.group(1)}"
    m = re.search(r"/shops/product[s]?/([A-Za-z0-9]+)", path)
    if m:
        return f"shops:{m.group(1)}"
    if not host:
        return ""
    return f"{host}{path}"  # query/fragment 除去の generic 正規化


def resolve(context: dict) -> str:
    """canonical KEY を返す。context = {category, signals{cert,brand,subject,card_no,model,url,image,...}, purpose?}.

    判別不能・未対応・名前不一致は **""** (fail-closed)。推測で固有idを当てない。
    """
    if not isinstance(context, dict):
        return ""
    signals = context.get("signals") or {}
    cat = _norm_category(context.get("category"))
    brand = signals.get("brand") or ""
    # (II) brand→category 検出: PSA brand は game identity の権威。番号衝突(ST04-013 OP/Gundam,
    #      P-024 OP/DB)を分離。確信ある時のみ override、曖昧/不明は呼び出し側 category を尊重(fail-closed)。
    _detected = _detect_category_from_brand(brand)
    if _detected:
        cat = _detected
    subject = signals.get("subject") or ""
    card_no = signals.get("card_no") or ""
    url = signals.get("url")
    image = signals.get("image")

    # 1) catalog-backed TCG (lookup_* の戻り legacy dict の "card_id" = canonical product_id)
    fn = _TCG_LOOKUP.get(cat)
    if fn is not None:
        rec = fn(brand, card_no, subject, verbose=False)
        # key不統一(card_id vs product_id)を facade が吸収 (docstring §冒頭の契約).
        # lookup_pokemon/one_piece 等は legacy dict で card_id、lookup_yugioh は
        # 生 record で product_id を返すため、両対応 (2026-06-11 yugioh resolve→'' 修正)。
        return (rec or {}).get("card_id") or (rec or {}).get("product_id") or ""
    # 2) DON (signature が異なる: brand, subject, image_url)
    if cat == "don":
        rec = _pc.lookup_don(brand, subject, image, verbose=False)
        return (rec or {}).get("card_id") or (rec or {}).get("product_id") or ""
    # 3) non-catalog marketplace URL → 正規化 url-key
    if url:
        return _normalize_url_key(url)
    # 4) 未対応 category / signal不足 → fail-closed
    #    (G-shock 等は別phaseで _TCG_LOOKUP 相当を追加。現状は "" を返す)
    return ""


__all__ = ["resolve"]
