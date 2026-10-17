"""vision_reject_cache - 写真を読んで対象外と確定した出品の永続控え.

2026-10-18 HQ依頼 (B-20261017-007追記②)。 PSA10 でない / まとめ売り / 鑑定番号が
不鮮明 等、 **写真を実際に読んで**対象外と分かった出品は、 次回また同じ写真を
課金で読み直さなくていいよう URL を覚えておく。

★残高切れ等の障害 (vision_error) はここに入れない (B-20261018-001)。
入れると、 残高を足した後の再開で「対象外確定」として永久に読まれなくなる。
`run_harvest_mercari_psa10.collect()` 側がそもそも vision_error をこの控えに
積まない設計になっている (= このモジュールは積まれた物をそのまま信用してよい)。

トレハン・キャラハンで共有 (同じ出品 URL は同じ写真なので、 軸をまたいでも有効)。
"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_PATH = Path("C:/dev/iMak_data/harvest/vision_rejected_urls.json")


def load(path: Path | None = None) -> dict[str, str]:
    """{url: reason} を読む。 無い/壊れていれば空で返す (fail-open ではなく単に「まだ無い」)."""
    p = path or DEFAULT_PATH
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 初回・壊れていても止めない
        return {}


def load_url_set(path: Path | None = None) -> set[str]:
    return set(load(path).keys())


def merge_and_save(new_entries: dict[str, str], path: Path | None = None) -> int:
    """既存の控えに今回分を足して保存する。 Returns: 新規に増えた件数."""
    p = path or DEFAULT_PATH
    current = load(p)
    added = sum(1 for u in new_entries if u not in current)
    current.update(new_entries)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(current, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)
    return added
