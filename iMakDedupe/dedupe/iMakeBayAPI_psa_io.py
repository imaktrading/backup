"""iMakeBayAPI.psa_api 越境 read-only wrapper (= Phase 1q / 5/28 体系的再設計).

設計原則 (= gemini レビュー反映):
- SoC: PSA cert metadata 連携を iMakeBayAPI に集約、 重複くんは参照のみ
- SSOT: iMakeBayAPI cache = 内部 SSOT (= 外部 SSOT = PSA web)
- DRY: 出品くん書込 / 重複くん読込 で共通 caller (= psa_api 関数) 利用

撤回された旧 logic:
- CSV `C:PSA Brand` / `C:PSA Subject` 列読込 (= 5/27 Phase 1l) → 削除
- CSV `INTERNAL:KEY1` / `INTERNAL:KEY2` 列読込 (= 5/28 Phase 1p) → 削除

新 logic:
- cert → cache lookup → brand/subject 取得 → DON/YGO lookup_* 等に渡す

cache miss 時:
- 出品くん が当該 cert を scrape していない or cycle 完了前
- → None 返却、 既存 title-only fallback に flow through (= 既存通り fail-closed)
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Dict, Optional

# 越境 path (= iMakeBayAPI 本体)
_IMAK_EBAY_API_DIR = Path(r"C:/dev/iMak/iMakeBayAPI")
_PSA_API_PATH = _IMAK_EBAY_API_DIR / "psa_api.py"

_PSA_API_MODULE = None


def _import_psa_api():
    """psa_api.py を遅延 import (= 重複くん worktree 外の越境 read-only).

    importlib.util.spec_from_file_location 経由で sys.modules 汚染回避。
    """
    global _PSA_API_MODULE
    if _PSA_API_MODULE is not None:
        return _PSA_API_MODULE
    if not _PSA_API_PATH.exists():
        raise FileNotFoundError(f"iMakeBayAPI psa_api.py not found: {_PSA_API_PATH}")
    spec = importlib.util.spec_from_file_location("ihq_psa_api", _PSA_API_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"failed to load spec: {_PSA_API_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _PSA_API_MODULE = module
    return _PSA_API_MODULE


def get_cached_psa(cert: str) -> Optional[Dict]:
    """iMakeBayAPI cache から cert metadata 取得.

    Returns:
        psa_to_csv get_psa_data 戻り値同形 dict (= Brand / Subject / CardNumber / Year etc)
        None = cache miss / file 不正 / import 失敗 (= fail-closed)
    """
    if not cert:
        return None
    try:
        return _import_psa_api().get_cached(cert)
    except Exception:
        return None
