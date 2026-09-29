#!/usr/bin/env python3
"""取った生データをそのまま残す倉庫 (2026-08-22 新設).

## なぜ
「タイプが要る」と分かってから 21,000ページ取り直す、を二度としないため。
生の HTML / JSON を残しておけば、**次に別の項目が必要になっても取り直しが要らない**
(手元のファイルを読み直すだけ)。

## 置き場所
    C:/dev/iMak_data/catalog/_raw/<category>/<key>.<ext>.gz
    C:/dev/iMak_data/catalog/_raw/<category>/_manifest.jsonl   (1行1件: key/url/取得時刻/bytes)

gzip で 1枚 9KB -> 2KB 程度。ポケモン全件で 40MB 前後。
"""
from __future__ import annotations

import gzip
import json
from datetime import datetime
from pathlib import Path

RAW_ROOT = Path(r"C:/dev/iMak_data/catalog/_raw")


def save(category: str, key: str, content: str, url: str, ext: str = "html") -> Path:
    """生データを1件保存し、manifest に1行足す。既にあれば上書き (最新を正とする)."""
    d = RAW_ROOT / category
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{key}.{ext}.gz"
    data = content.encode("utf-8")
    with gzip.open(p, "wb") as f:
        f.write(data)
    with (d / "_manifest.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"key": key, "url": url, "ext": ext, "bytes": len(data),
                            "fetched_at": datetime.now().isoformat(timespec="seconds")},
                           ensure_ascii=False) + "\n")
    return p


def load(category: str, key: str, ext: str = "html") -> str | None:
    """保存済の生データを読む (無ければ None). 取り直しの代わりにこれを使う."""
    p = RAW_ROOT / category / f"{key}.{ext}.gz"
    if not p.exists():
        return None
    with gzip.open(p, "rb") as f:
        return f.read().decode("utf-8", "replace")


def have(category: str, key: str, ext: str = "html") -> bool:
    return (RAW_ROOT / category / f"{key}.{ext}.gz").exists()
