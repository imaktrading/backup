"""clone 行 (base をコピーして作った variant 行) の唯一の判定口.

2026-08-23 新設。回答書
`requests/2026-08-23_hq_go_cll_images_and_clone_hardening_response.md` §2 の [IMPLEMENT-GO]。

## 判定 (1丁目1番地): ①カタログのデータが誤り → catalog 側で直す

②は正しい。出品くんは canonical KEY (product_id) 完全一致でしか引かない。
誤りは clone 行に **親の絵が入る作り** が残っていたこと。`source_url` に親の series
ページを入れていたので、画像補完がそこを開いて親カードの画像を取ってしまう
(2026-08-22 に `OP01-077_GE` が親 `OP01-077` の絵を持ち、3日連続で「画像なし」と指摘された)。

## 決めたこと (規則は1つ。例外を作らない)

1. clone 行は `specs.cloned_from` に **base の product_id** を持つ。これが唯一の目印。
2. clone 行の `source_url` は **空**。親のページを指させない。
   出所は `source` 列 (`...+clone_<base>`) に残るので失われない。
3. 画像補完は clone 行を **必ず飛ばす**。別絵柄なのに親の絵が入ると目視照合が誤る。
   公式が別絵柄を出していない限り images は空が正しい (= 目視不能 = 出品しない)。

既存列 `alias_of` は流用しない。あちらは「同一物の別名」(gshock 243行) で意味が違う。
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

__all__ = ["SPEC_KEY", "base_from_source", "cloned_from", "is_clone"]

SPEC_KEY = "cloned_from"

# `source` 列の慣習: 'opcg_official+clone_OP01-077' / 'clone_ST13-003+psa_...'
_CLONE_TOKEN = re.compile(r"clone_([A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*)")


def _as_specs(specs: Any) -> dict:
    if isinstance(specs, dict):
        return specs
    if isinstance(specs, (str, bytes)) and specs:
        try:
            d = json.loads(specs)
        except (ValueError, TypeError):
            return {}
        return d if isinstance(d, dict) else {}
    return {}


def base_from_source(source: Optional[str]) -> Optional[str]:
    """`source` 列の `clone_<base>` から base の product_id を読む (無ければ None)."""
    if not source:
        return None
    m = _CLONE_TOKEN.search(source)
    return m.group(1) if m else None


def cloned_from(specs: Any, source: Optional[str] = None) -> Optional[str]:
    """clone 元の product_id。`specs.cloned_from` が正、無ければ `source` から読む."""
    v = _as_specs(specs).get(SPEC_KEY)
    if isinstance(v, str) and v.strip():
        return v.strip()
    return base_from_source(source)


def is_clone(specs: Any, source: Optional[str] = None) -> bool:
    """clone 行か。**画像補完はこれが True の行を必ず飛ばす**."""
    return cloned_from(specs, source) is not None
