"""G-SHOCK catalog adapter - 型番表記揺れの rescue 層.

設計原則 (Phase 3 / 2026-04-29):
  - api.lookup() を ID 完全一致で呼ぶのが原則
  - PSA/eBay/CASIO 等で型番表記が揺れるため (JF/JR suffix の有無、ハイフン位置)、
    候補を列挙して順次試行する rescue 層を 1 関数だけ提供
  - 暗黙のフォールバック禁止 (id_strict_with_explicit_rescue.md 準拠)

使用例:
    from iMakCatalog.integrations.gshock_lookup import lookup_gshock
    rec = lookup_gshock("GA-2100-1A1JF")  # JF suffix 付きでも、なしでも、ハイフン無しでも hit
    if rec:
        specs = rec["specs"]   # case_size / band_color / features / ...
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

# iMakCatalog/api を sys.path で見せる (隣同士の integrations から相対 import を避ける)
_CATALOG_ROOT = Path(__file__).resolve().parent.parent
if str(_CATALOG_ROOT) not in sys.path:
    sys.path.insert(0, str(_CATALOG_ROOT))

import api  # noqa: E402

CATEGORY = "gshock"


# ============================================================================
# 公開 API
# ============================================================================
def lookup_gshock(model: str) -> Optional[dict]:
    """G-SHOCK 型番 lookup. 表記揺れを正規化候補で順次試行 (ID 完全一致のみ).

    Args:
        model: PSA/eBay/CASIO URL/ユーザー入力など、表記が揺れた状態の型番.
               例: 'GA-2100-1A1JF' / 'GA-2100-1A1' / 'GA2100-1A1' / 'ga-2100-1a1'

    Returns:
        api.lookup 互換 dict | None
    """
    if not model:
        return None
    for cand in _generate_candidates(model):
        rec = api.lookup(CATEGORY, cand)
        if rec:
            return rec
    return None


# ============================================================================
# 候補生成 (pure function、ユニットテスト対象)
# ============================================================================
def _generate_candidates(model: str) -> list[str]:
    """型番表記揺れを正規化した候補リストを返す.

    ルール:
      1. 渡された値そのまま (大文字化前)
      2. 大文字化したもの
      3. JF/JR suffix を剥がしたもの (大文字化済)
      4. ハイフン無し → 'PREFIX-NUM' 形式に補正したもの
      5. 4 + JF/JR 剥がし

    順序保持 + 重複除去.
    """
    if not model:
        return []
    raw = model.strip()
    upper = raw.upper()

    candidates: list[str] = []

    def _add(c: str):
        if c and c not in candidates:
            candidates.append(c)

    # 1. raw (大文字化前)
    _add(raw)
    # 2. uppercase
    _add(upper)
    # 3. JF/JR suffix 剥がし (大文字化後)
    base = re.sub(r"(?:JF|JR)$", "", upper)
    _add(base)
    # 4. prefix-numeric ハイフン挿入 (例: 'GA2100-1A1' → 'GA-2100-1A1').
    #    既存ハイフンには触らない (第2ハイフン以降を破壊しないため).
    #    upper の冒頭が "PREFIX(letters)NUMBER(digits)" 形式なら間に '-' を挿入.
    formatted = re.sub(r"^([A-Z]{2,4})(\d{3,4})", r"\1-\2", upper)
    _add(formatted)
    # 5. formatted の JF/JR 剥がし
    formatted_base = re.sub(r"(?:JF|JR)$", "", formatted)
    _add(formatted_base)

    return candidates


# ============================================================================
# CLI (動作確認用)
# ============================================================================
if __name__ == "__main__":
    samples = [
        "GA-2100-1A1JF",   # JF suffix 付き
        "GA-2100-1A1",     # JF なし
        "GA2100-1A1",      # ハイフン無し
        "ga-2100-1a1",     # 小文字
        "DW-5600BB-1JF",
        "",                # 空
    ]
    print("--- _generate_candidates samples ---")
    for s in samples:
        print(f"  {s!r:25s} → {_generate_candidates(s)}")

    print("\n--- lookup_gshock samples (DB 未投入なら全 None 想定) ---")
    for s in samples:
        rec = lookup_gshock(s)
        print(f"  {s!r:25s} → {'hit: ' + rec['product_id'] if rec else 'None'}")
