"""iMakCatalog resolver 越境 read-only import wrapper (= Step 4 KEY 再設計).

spec: iMak_data/KEY_REDESIGN_SPEC.md §3
greenlight: iMak_data/dedupe/requests/2026-06-10_key_redesign_BUILD_step4_single_key.md

catalog.resolver.resolve(context) → canonical KEY を dedupe 側から越境呼出.
解決の唯一の入口 (= 重複くんは consumer、 再導出禁止)。
"""

from __future__ import annotations

import sys
from typing import Optional

IMAK_CATALOG_DIR = r"C:/dev/iMak_catalog/iMakCatalog"


def _import_resolver():
    """catalog resolver の lazy import (= dedupe module-level 依存回避)."""
    if IMAK_CATALOG_DIR not in sys.path:
        sys.path.insert(0, IMAK_CATALOG_DIR)
    try:
        from resolver import resolve as _resolve
    except ImportError as exc:
        raise RuntimeError(
            f"iMakCatalog resolver import 失敗: {exc} (path={IMAK_CATALOG_DIR})"
        )
    return _resolve


def resolve(context: dict) -> str:
    """canonical KEY を返す (= catalog resolver の越境 wrapper).

    context = {
      "category": str (例: "one_piece_tcg" / "pokemon_tcg" / "don" / "" 等),
      "signals": {
        "cert": str, "brand": str, "subject": str, "card_no": str,
        "model": str, "url": str, "image": str, "title": str, ...
      },
      "purpose": str (= "listing" / "dedup" / "procurement"、 オプション),
    }

    戻り値:
      - catalog product_id (例 "OP10-049_p1")
      - 正規化 URL key (例 "item:m12345", "shops:abc-def")
      - "" (= 解決不能、 fail-closed)
    """
    fn = _import_resolver()
    return fn(context)


def resolve_csv_row(row: dict, purpose: str = "dedup") -> str:
    """CSV row dict から context を組立 → resolve() 呼出 (= 重複くん側 convenience).

    eBay File Exchange CSV の主要列 を signals に mapping。
    cert → iMakeBayAPI cache 経由 brand/subject 取得 も内部で実施。
    """
    cert = (row.get("CDA:Certification Number - (ID: 27503)") or "").strip()
    title = (row.get("*Title") or "").strip()
    card_no = (row.get("C:Card Number") or "").strip()
    pic_url = (row.get("*PicURL") or row.get("PicURL") or "").strip()
    features = (row.get("C:Features") or "").strip()
    speciality = (row.get("C:Speciality") or "").strip()
    set_val = (row.get("C:Set") or "").strip()

    brand = ""
    subject = ""
    if cert:
        from . import iMakeBayAPI_psa_io as _psa_io
        meta = _psa_io.get_cached_psa(cert)
        if meta:
            brand = (meta.get("Brand") or "").strip()
            subject = (meta.get("Subject") or "").strip()
            # PSA cache CardNumber を優先 (= catalog lookup は連番形式 "049" を期待、
            # CSV C:Card Number は "OP10-049" 形式で渡されることがあり lookup 失敗するため)
            psa_card_no = (meta.get("CardNumber") or "").strip()
            if psa_card_no:
                card_no = psa_card_no

    # G-shock 補完 (= 2026-06-12 修正 B):
    # title から G-shock 型番抽出 → signals["model"] にセット。
    # catalog resolver の cat=="gshock" dispatch で lookup_gshock(model) を呼ぶため必須。
    # PSA 系 (= cert あり) では title が "PSA10 ..." 等で extract_gshock_model 通常 hit せず影響なし。
    from .extractors import extract_gshock_model
    model = extract_gshock_model(title) or ""

    # category 推定 (= signals に詰めて resolver 側 dispatch に委ねる)
    category = _guess_category(title=title, brand=brand, set_val=set_val)

    context = {
        "category": category,
        "signals": {
            "cert": cert,
            "brand": brand,
            "subject": subject,
            "card_no": card_no,
            "model": model,  # 2026-06-12 修正 B: G-shock 型番
            "url": "",  # CSV 経路は marketplace URL 直接持たない
            "image": pic_url,
            "title": title,
            "set": set_val,
            "features": features,
            "speciality": speciality,
        },
        "purpose": purpose,
    }
    return resolve(context)


def resolve_sheet_row(
    title: str,
    url: str = "",
    image_url: str = "",
    cert: str = "",
    extra_text: str = "",
    purpose: str = "dedup",
) -> str:
    """スプシ row から context 組立 → resolve() 呼出.

    HIGH/LOW 商品管理シート の row (= title + url + 写真URL + cert) から canonical KEY 解決。
    PSA cache hit があれば brand/subject/CardNumber 補完して resolver 精度上げる。
    """
    brand = ""
    subject = ""
    card_no = ""
    if cert:
        from . import iMakeBayAPI_psa_io as _psa_io
        meta = _psa_io.get_cached_psa(cert)
        if meta:
            brand = (meta.get("Brand") or "").strip()
            subject = (meta.get("Subject") or "").strip()
            # PSA cache CardNumber を渡す (= catalog lookup_* が連番形式 "049" を期待)
            card_no = (meta.get("CardNumber") or "").strip()

    # G-shock 補完 (= 2026-06-12 修正 B):
    # title から G-shock 型番抽出 → signals["model"] にセット (HIGH/LOW 既存 row 評価用).
    # catalog resolver の cat=="gshock" dispatch で lookup_gshock(model) を呼ぶため必須.
    from .extractors import extract_gshock_model
    model = extract_gshock_model(title) or ""

    category = _guess_category(title=title, brand=brand)

    context = {
        "category": category,
        "signals": {
            "cert": cert,
            "brand": brand,
            "subject": subject,
            "card_no": card_no,
            "model": model,  # 2026-06-12 修正 B: G-shock 型番
            "url": url,
            "image": image_url,
            "title": title,
            "features": extra_text,
        },
        "purpose": purpose,
    }
    return resolve(context)


def _guess_category(
    title: str = "",
    brand: str = "",
    set_val: str = "",
) -> str:
    """title / brand / set 等から resolver category 推定.

    fail-closed: 確証なき場合は "" (= resolver 側で url fallback 経路 or fail-closed)
    """
    upper_text = " ".join(
        s.upper() for s in (title, brand, set_val) if s
    )
    if not upper_text:
        return ""

    # DON カード (= 5/27 Phase 1j、 brand or title に "DON")
    if "DON" in upper_text and "DON!!" in upper_text.replace("!", "!!"):
        return "don"
    # 単純判定: brand に "DON!!" 文字列があれば
    if "DON!!" in upper_text:
        return "don"

    raw_jp = " ".join(s for s in (title, brand, set_val) if s)
    if (
        "ONE PIECE" in upper_text
        or "ONEPIECE" in upper_text
        or "OPCG" in upper_text
        or "ワンピース" in raw_jp
    ):
        return "one_piece_tcg"
    if "POKEMON" in upper_text or "PKMN" in upper_text or "ポケモン" in raw_jp:
        return "pokemon_tcg"
    if "YU-GI-OH" in upper_text or "YUGIOH" in upper_text or "遊戯王" in raw_jp:
        return "yugioh"
    if "GUNDAM" in upper_text or "GCG" in upper_text or "ガンダム" in raw_jp:
        return "gundam_tcg"
    if (
        "DRAGON BALL" in upper_text
        or "DRAGONBALL" in upper_text
        or "DBSCG" in upper_text
        or "ドラゴンボール" in raw_jp
    ):
        return "dragonball_scg"
    # G-shock 検出 (= 2026-06-12 修正 C):
    # title 内に G-shock 型番 (例 DW-5600RL-1JF / MTG-B4000-1A) があれば category="gshock".
    # 型番 regex は extractors/gshock.py の _GSHOCK_RE 経由 (= DW/GW/GA/GST/GMW/GBA/MTG/GMA prefix
    # に限定、 TCG card_id とは prefix 衝突しない設計)。
    # TCG 検出が上で先行するため、 TCG title に G-shock 型番らしき token があっても
    # ここに到達しない (= 誤検出回避)。
    from .extractors import extract_gshock_model
    if extract_gshock_model(title):
        return "gshock"
    return ""


__all__ = ["resolve", "resolve_csv_row", "resolve_sheet_row"]
