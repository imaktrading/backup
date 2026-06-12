"""画像 hash variant 識別 (= Phase 1m / 5/27 Phase B 実装).

catalog 各 variant の `image_phash` と新規 listing 画像の phash を比較し、
hamming distance が閾値以下なら該当 variant を特定する fail-closed logic。

POC (= 5/27 Phase A) 確定値:
- THRESHOLD = 10 bits (安全側)
  - 同 variant 別画像 実測 max = 6 bits
  - 異 variant pair 実測 min = 22-24 bits
  - margin = 16+ bits、 false positive/negative ほぼゼロ予測

使用 library:
- imagehash 4.3.2 (= pip install imagehash) — phash 64bit DCT 変換
- Pillow 12.2.0 (= imagehash 依存)
- requests (= URL fetch、 既存導入済)

catalog 側 投入 (= 別 Phase B 想定):
- products.specs.variants[variant_code].image_phash (= 16 桁 hex string)
"""

from __future__ import annotations

import io
from typing import Dict, Optional

import requests

# 遅延 import (= 一部環境で imagehash 不在時の import error 回避)
try:
    import imagehash
    from PIL import Image
    _IMAGEHASH_AVAILABLE = True
except ImportError:  # pragma: no cover
    _IMAGEHASH_AVAILABLE = False

# === POC 確定値 (= 5/27 Phase A、 false positive 0 予測) ===
_DEFAULT_THRESHOLD = 10
_FETCH_TIMEOUT = 10  # seconds


def compute_phash(image_url: str) -> Optional[str]:
    """画像 URL から perceptual hash の hex string を取得.

    Returns:
        16 桁 hex (= imagehash.phash の str repr) or None (= fail-closed)

    Failures (= None 返却):
    - imagehash library 不在
    - HTTP non-200
    - timeout / connection error
    - 画像 decode error
    """
    if not _IMAGEHASH_AVAILABLE or not image_url:
        return None
    try:
        resp = requests.get(image_url, timeout=_FETCH_TIMEOUT)
        if resp.status_code != 200:
            return None
        img = Image.open(io.BytesIO(resp.content))
        return str(imagehash.phash(img))
    except Exception:
        return None


def identify_variant_by_image(
    image_url: str,
    catalog_variants: Dict[str, Dict],
    threshold: int = _DEFAULT_THRESHOLD,
    _phash_fn=None,  # test injection 用
) -> Optional[str]:
    """catalog variant の image_phash と距離比較、 閾値以下 unique なら variant_code 返却.

    Args:
        image_url: 新規 listing 画像 URL
        catalog_variants: {variant_code: {"image_phash": "hex", ...}, ...}
            例: {"AR": {"image_phash": "abcdef0123456789", ...},
                 "SAR": {"image_phash": "fedcba9876543210", ...}}
        threshold: hamming distance 閾値 (= デフォルト 10 bits)
        _phash_fn: test 用 mock injection (= 通常は compute_phash)

    Returns:
        variant_code (= 例 "AR") / None (= fail-closed:
            - 画像取得失敗
            - 閾値以下 hit なし
            - 同 distance の hit 複数 (= tie で一意特定不能)
        )

    fail-closed の根拠:
    - tie → どの variant か判断不能 → 推測しない
    - 閾値超 → 一致なし、 None で呼出側が別 logic に fall through
    """
    if not _IMAGEHASH_AVAILABLE or not catalog_variants:
        return None

    phash_fn = _phash_fn if _phash_fn is not None else compute_phash
    candidate = phash_fn(image_url)
    if not candidate:
        return None

    try:
        cand_hash = imagehash.hex_to_hash(candidate)
    except Exception:
        return None

    best_code: Optional[str] = None
    best_dist: int = threshold + 1
    tied: bool = False
    for variant_code, meta in catalog_variants.items():
        stored = (meta or {}).get("image_phash")
        if not stored:
            continue
        try:
            stored_hash = imagehash.hex_to_hash(stored)
        except Exception:
            continue
        dist = cand_hash - stored_hash
        if dist < best_dist:
            best_dist = dist
            best_code = variant_code
            tied = False
        elif dist == best_dist and best_code is not None:
            tied = True

    if best_code is None or tied or best_dist > threshold:
        return None
    return best_code
