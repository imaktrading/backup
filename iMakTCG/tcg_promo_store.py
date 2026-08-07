"""tcg_promo_store — プロモ配布元名の per-card override (HQ/TCG所有・catalog は触らない)。

catalog は公式データのみ (catalog_official_only) なので、PSA ラベル由来の promo 名は
catalog に書かず、ここ (promo_overrides.json) に product_id 単位で保存する。
新コア (tcg_listing_fields) がタイトル生成時に読む = 一度確定すれば決定論・全 cert 同一。

レビューHTMLでの確定パターン:
  - OK/編集 → set_promo(card_id, "Ichiban Kuji Purchase Bonus")
  - 消す    → set_promo(card_id, "")   ← 「レビュー済・promo無し」を意味する空文字を記録
  - 未レビュー = キー無し → needs_review が True (= 生成時フラグ対象)
"""
from __future__ import annotations

import json
import os

_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "promo_overrides.json")


def is_promo_variant(specs: dict) -> bool:
    """catalog specs がプロモ系 (配布元説明を要する other_product) か。"""
    if not specs:
        return False
    if (specs.get("variant_type") or "").strip().lower() == "other_product":
        return True
    sn = (specs.get("set_name") or "").strip().lower()
    sne = (specs.get("set_name_ebay") or "").strip().lower()
    return sn == "other product card" or sne == "promo cards"


def load_all(path: str = _STORE) -> dict:
    """{card_id: {"promo": str, ...}} を返す (失敗/不在は {})。"""
    if not os.path.exists(path):
        return {}
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:
        return {}
    items = d.get("items", d) if isinstance(d, dict) else {}
    return items if isinstance(items, dict) else {}


def is_reviewed(card_id: str, path: str = _STORE) -> bool:
    """その card_id が一度でもレビュー確定されたか (空文字確定=レビュー済 を含む)。"""
    return bool(card_id) and card_id in load_all(path)


def get_promo(card_id: str, path: str = _STORE) -> str:
    """確定済 promo 名 (未レビュー or 空確定なら '')。"""
    rec = load_all(path).get(card_id)
    if isinstance(rec, dict):
        return (rec.get("promo") or "").strip()
    return (rec or "").strip() if isinstance(rec, str) else ""


def needs_review(specs: dict, card_id: str, path: str = _STORE) -> bool:
    """プロモ系なのに未レビュー = 生成時にフラグすべき (= 「人が気づく」に頼らない検出)。"""
    return is_promo_variant(specs) and not is_reviewed(card_id, path)


def set_promo(card_id: str, promo: str, *, updated_at: str = "", path: str = _STORE) -> None:
    """promo 名を確定保存 (空文字=レビュー済・promo無し)。updated_at は呼出側で渡す。"""
    if not card_id:
        return
    items = load_all(path)
    items[card_id] = {"promo": (promo or "").strip(), "updated_at": updated_at}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"items": items}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
