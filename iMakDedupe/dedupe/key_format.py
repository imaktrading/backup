"""KEY 形式パーサ (= 案B: KEー にカテゴリを持たせる、 Phase1b 読む側後方互換).

依頼: iMak_data/dedupe/requests/2026-07-27_key_category_prefix_phase1_reader.md
関連: Catalog `2026-07-27_product_id_uniqueness_feasibility_response.md`

## 背景
catalog `products` は `UNIQUE(category, product_id)` 複合一意で、product_id の
global 一意は invariant ではない (= One Piece と Gundam が独立採番で `ST02-010` を
両方持つのは正しい状態。実測 283 件重複、うち 282 件 OP×Gundam)。

KEー (= 商品管理シート AI 列) にカテゴリが無いと、dedupe から別ゲーム同番号が
同一商品に見え、Gundam を「既存KEー完全一致の真の重複」として誤除外しうる
(= 出品機会の損失。fail-closed 側だが Gundam 収録増で顕在化)。

## KEー 形式: `{category}:{product_id}` (例 `gundam_tcg:ST02-010`)
- `:` は product_id が使わない文字 (`[A-Za-z0-9_-]`) → 最初の `:` で確実に分離
- 旧形式 (カテゴリ無) との判別も「`:` を含むか」で自明
- `item:` / `shops:` で始まる url-key は **従来どおり** (= カテゴリ扱いしない)

## 移行期の原則 (= 依頼書 §3)
旧形式 (`ST02-010`) と新形式 (`gundam_tcg:ST02-010`) を **同一グループにしない**。
同一視すると「重複」判定で出品を落とす方向に倒れるため、出品機会を守る側
(= グループを分ける側) に倒す。group_key は旧=`ST02-010` / 新=`gundam_tcg:ST02-010`
と別文字列を返す (= 別グループ) ことでこれを担保。

HQ 側 `iMakHQ/tools/dup_guard.py` の `parse_key` / `group_key` と同一規約
(= 2 系統で突合結果が一致することを保証)。
"""

from __future__ import annotations

from typing import Optional, Tuple

# url-key prefix (= mercari URL key。 カテゴリ扱いしない)
_URL_KEY_PREFIXES = ("item:", "shops:")


def parse_key(k: Optional[str]) -> Tuple[Optional[str], str]:
    """KEー を (category, product_id) に分離.

    - 空 / url-key (`item:` `shops:`) → (None, k)  ← カテゴリ扱いしない
    - `:` を含む → 最初の `:` で分離 → (category, product_id)
    - `:` を含まない (= 旧形式) → (None, k)

    Returns:
        (category or None, product_id_or_rawkey)

    >>> parse_key("gundam_tcg:ST02-010")
    ('gundam_tcg', 'ST02-010')
    >>> parse_key("ST02-010")
    (None, 'ST02-010')
    >>> parse_key("item:m12345")
    (None, 'item:m12345')
    """
    k = (k or "").strip()
    if not k or k.startswith(_URL_KEY_PREFIXES):
        return (None, k)
    if ":" in k:
        cat, _, pid = k.partition(":")
        return (cat, pid)
    return (None, k)


def build_key(category: Optional[str], product_id: Optional[str]) -> str:
    """書く側 (= Phase2b): (category, product_id) から KEー を組立.

    catalog resolver `resolve_with_category` の戻り {product_id, category} を
    そのまま渡す想定。分岐は resolver の保証 (= catalog-backed なら category 非空、
    url-key / 未解決は category 空) に依拠:

    - product_id 空 → "" (= fail-closed。 KEー を書かない)
    - category 非空 → "{category}:{product_id}" (= catalog-backed → prefix)
    - category 空 → product_id そのまま (= url-key `item:`/`shops:` は prefix しない。
      `:` を含むため prefix すると読む側が category 誤認する)

    >>> build_key("gundam_tcg", "ST02-010")
    'gundam_tcg:ST02-010'
    >>> build_key("", "item:m12345")
    'item:m12345'
    >>> build_key("", "")
    ''
    """
    product_id = (product_id or "").strip()
    if not product_id:
        return ""
    category = (category or "").strip()
    return f"{category}:{product_id}" if category else product_id


def group_key(k: Optional[str]) -> str:
    """突合用の正規化 KEー (= 同一カード判定の group 単位).

    - 新形式 (category あり) → `{category}:{product_id}` (= カテゴリ込み)
    - 旧形式 / url-key / 空 → そのまま (= product_id or rawkey)

    旧 `ST02-010` と 新 `gundam_tcg:ST02-010` は別文字列 → 別グループ
    (= 移行期に混ぜない、 出品機会を守る側)。

    >>> group_key("gundam_tcg:ST02-010")
    'gundam_tcg:ST02-010'
    >>> group_key("one_piece_tcg:ST02-010")
    'one_piece_tcg:ST02-010'
    >>> group_key("ST02-010")
    'ST02-010'
    >>> group_key("item:m12345")
    'item:m12345'
    """
    cat, pid = parse_key(k)
    return f"{cat}:{pid}" if cat else pid


__all__ = ["parse_key", "group_key", "build_key"]
