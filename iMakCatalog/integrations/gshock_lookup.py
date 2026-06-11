"""G-SHOCK catalog adapter - 型番表記揺れの rescue 層.

設計原則 (Phase 3 / 2026-04-29 → 2026-06-11 fail-closed 改訂):
  - api.lookup() を ID 完全一致で呼ぶのが原則
  - PSA/eBay/CASIO 等で表記が揺れる (大文字小文字、ハイフン位置) ため正規化はする
  - 暗黙のフォールバック禁止 (id_strict_with_explicit_rescue.md 準拠)

2026-06-11 dedupe 後の canonical 規約 (dedupe_switch_to_alias_link_B = B案):
  - 同一物理商品は **suffix 込み完全形 (例 GM-6900YRA-8JF)** を canonical とする
  - bare 形 (例 GM-6900YRA-8) は **削除せず alias として残す** (alias_of 列が canonical を指す)
  - catalog の 1,034 件 (73%) は **bare-only canonical** (suffix twin が無い唯一形)

  → alias 対応 lookup ルール (HQ 2026-06-11 B案承認、recall 重視):
    * suffix 形入力               → suffix canonical に exact 解決 (無ければ bare-only に限り fallback)
    * bare 形入力 + alias_of 在り (1:1) → canonical に解決 ("" にしない = recall 維持)
    * bare 形入力 + 独立 canonical (alias_of NULL・twin 無し) → その bare を解決
    * bare 形入力 + 真の 1:N (alias_of NULL・twin 複数) → "" 返却 (推測しない、例 GW-9400J-1B)
    * 海外 suffix (E/V/ER 等)      → canonical 化しない (現状維持、剥がさない)

  「一意に紐づく時は解決、本当に曖昧な時だけ ''」。先の削除版 verdict の
  「bare+twin→全部 ''」より recall が良い (1:1 alias は解決できる)。

  末尾 A は **色コード** であって地域コードではない (AJF = 色A + JF)。
  地域 (region) suffix は **J 始まりのみ**: JF / JR / JFS / JRS / SPCBOX / PFCT / JTC.

使用例:
    from iMakCatalog.integrations.gshock_lookup import lookup_gshock
    rec = lookup_gshock("GA-2100-1A1JF")  # suffix 形 → canonical exact
    rec = lookup_gshock("GM-700G-9A")     # bare(1:1 alias) → canonical 解決
    rec = lookup_gshock("GW-9400J-1B")    # bare(真の1:N) → None
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

# 地域 (region) suffix = J 始まりのみ。末尾 A は色コードなので含めない。
# strip 用に長い順 (JFS が JF より先にマッチするように).
REGION_SUFFIXES = ("JFS", "JRS", "SPCBOX", "PFCT", "JTC", "JF", "JR")


# ============================================================================
# 公開 API
# ============================================================================
def lookup_gshock(model: str) -> Optional[dict]:
    """G-SHOCK 型番 lookup (alias 対応 / ID 完全一致のみ).

    Args:
        model: PSA/eBay/CASIO URL/ユーザー入力など表記が揺れた型番.

    Returns:
        api.lookup 互換 dict | None
        - bare(1:1 alias) は canonical へ解決して返す
        - 真の 1:N 曖昧 bare は None (推測しない)
    """
    if not model:
        return None

    forms = _normalize_forms(model)          # 大文字化 + ハイフン補正 (剥がしはしない)
    if not forms:
        return None
    base, region = _split_region(forms[0])   # 正規化済の代表形で判定

    if region:
        # --- suffix 形入力 → suffix canonical に exact 解決 ---
        for f in forms:
            rec = api.lookup(CATEGORY, f)
            if rec:
                return _resolve_alias(rec)
        # suffix canonical が無い場合、bare が「唯一形 (twin 無し)」の時だけ fallback.
        # = bare-only canonical を suffix 形で引かれても拾う後方互換。
        if not _has_region_twin(base):
            rec = api.lookup(CATEGORY, base)
            if rec:
                return _resolve_alias(rec)
        return None

    # --- bare 形入力 ---
    for f in forms:
        rec = api.lookup(CATEGORY, f)
        if not rec:
            continue
        if rec.get("alias_of"):
            # 1:1 alias → canonical に解決 (recall 維持)
            return _resolve_alias(rec)
        # alias_of NULL = 独立 canonical or 真の 1:N
        if _has_region_twin(f):
            # 別名一意化不可な 1:N (例 GW-9400J-1B = JF/JR 両 canonical) → 推測せず None
            return None
        return rec   # 独立 canonical (例 GBX-100-2, bare-only)
    return None


def _resolve_alias(rec: Optional[dict]) -> Optional[dict]:
    """alias 行なら canonical 行を返す. canonical 自身ならそのまま.

    canonical が万一欠落していれば alias 行をそのまま返す (取りこぼし回避).
    """
    if rec and rec.get("alias_of"):
        canon = api.lookup(CATEGORY, rec["alias_of"])
        return canon or rec
    return rec


# ============================================================================
# helpers (pure / 軽量 DB 参照、ユニットテスト対象)
# ============================================================================
def _normalize_forms(model: str) -> list[str]:
    """大文字化 + prefix-numeric ハイフン補正した正規化形リスト (順序保持・重複除去).

    region suffix の剥がしは **しない** (canonical = suffix 込み完全形のため).
    """
    if not model:
        return []
    raw = model.strip().upper()
    forms: list[str] = []

    def _add(c: str):
        if c and c not in forms:
            forms.append(c)

    # 型番内スペース (title 由来: 'GA 2100-1A1' / 'DW 5600') の吸収。
    # スペース→ハイフン と スペース→除去 の両形を候補化 (exact 一致のみ採るので
    # 誤形は単にヒットしない = fail-closed を崩さない)。
    bases = [raw]
    if " " in raw:
        bases.append(re.sub(r"\s+", "-", raw))   # 'GA 2100-1A1' → 'GA-2100-1A1'
        bases.append(re.sub(r"\s+", "", raw))     # 'GA 2100' → 'GA2100'
    for b in bases:
        _add(b)
        # 'GA2100-1A1' → 'GA-2100-1A1' (冒頭 PREFIX+NUMBER のみ、既存ハイフンは触らない)
        _add(re.sub(r"^([A-Z]{2,4})(\d{3,4})", r"\1-\2", b))
    return forms


def _split_region(pid: str) -> tuple[str, Optional[str]]:
    """末尾の region suffix (J 始まり) を分離. 無ければ (pid, None).

    末尾 A は色コードなので region として剥がさない (AJF → base=...A, region=JF).
    """
    for suf in REGION_SUFFIXES:
        if pid.endswith(suf) and len(pid) > len(suf):
            return pid[: -len(suf)], suf
    return pid, None


def _has_region_twin(bare: str) -> bool:
    """bare に対し region suffix 付き canonical が DB に存在するか (1:N 曖昧判定)."""
    for suf in REGION_SUFFIXES:
        if api.lookup(CATEGORY, bare + suf):
            return True
    return False


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
    print("--- _normalize_forms / _split_region samples ---")
    for s in samples:
        forms = _normalize_forms(s)
        base, region = _split_region(forms[0]) if forms else ("", None)
        print(f"  {s!r:25s} → forms={forms} base={base!r} region={region!r}")

    print("\n--- lookup_gshock samples ---")
    for s in samples:
        rec = lookup_gshock(s)
        print(f"  {s!r:25s} → {'hit: ' + rec['product_id'] if rec else 'None'}")
