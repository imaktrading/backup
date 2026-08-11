# -*- coding: utf-8 -*-
"""契約 v1.2 §HQ-4: rarity 除外判定は **canonical キー only** (2026-08-11)。

回答書:
  - 2026-08-10_catalog_tcg_ssot_interface_contract_all_categories_response.md
  - 「rarity の除外判定を canonical キーで行う (印刷番号を使わない) — HQ の実装」

固定する挙動:
  1. check_csv.validate_row の rarity 判定キーは canonical PID のみ。印刷番号
     (`746/742`) を fallback で使わない (fail-closed = 判定不能なら必須のまま)
  2. csv_auditor._still_required_spec も同様に canonical only
     (printed number での偶発一致で「除外できたつもり」を作らない)
"""
from __future__ import annotations

import os
import re
import sys

_TCG = r"C:\dev\iMak\iMakTCG"
_HQ_TOOLS = r"C:\dev\iMak\iMakHQ\tools"
for _p in (_TCG, _HQ_TOOLS):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# 1. check_csv.validate_row のキーは canonical only
# ---------------------------------------------------------------------------
def test_check_csv_card_key_is_canonical_only():
    """`_card_key = _canonical_pid(cert)` 単独で、印刷番号 fallback が無い。"""
    src = _load(os.path.join(_TCG, "check_csv.py"))
    # 旧 fallback 形は消えていること
    assert '_canonical_pid(cert) or get_col(row, "C:Card Number")' not in src, (
        "check_csv がまだ印刷番号 fallback を持っている (契約 v1.2 §HQ-4 違反)"
    )
    # 単独 canonical 形が居ること
    assert re.search(r'_card_key\s*=\s*_canonical_pid\(cert\)\s*\n', src), (
        "canonical-only の代入形が見当たらない"
    )


# ---------------------------------------------------------------------------
# 2. csv_auditor._still_required_spec のキーも canonical only
# ---------------------------------------------------------------------------
def _seed_listing_common_cache(monkeypatch, mapping):
    """canonical_pid_for_cert が読む本物の cache (listing_common) を差し替える。

    csv_auditor.canonical_pid_for_item は listing_common.canonical_pid_for_cert に
    delegate している。SSOT はそちら側なので、そちらを patch する。
    """
    sys.path.insert(0, r"C:\dev\iMak\iMakeBayAPI")
    import listing_common as LC
    monkeypatch.setattr(LC, "_VERIFIED_PID_CACHE", mapping, raising=False)


def test_csv_auditor_still_required_spec_falls_back_to_required_when_no_canonical(monkeypatch):
    """canonical 未確定 → fail-closed で「必須のまま」返す (印刷番号での判定に降りない)。

    key_for_num は canonical or "" (印刷番号を渡さない)。card_type 側の除外
    (Energy Marker / Resource) は canonical 不要なので引き続き効く (別テストで担保)。
    """
    import csv_auditor as A
    _seed_listing_common_cache(monkeypatch, {})
    # 印刷番号 `mc-746` を渡しても canonical 未確定なら pokemon set prefix 除外は発火しない
    # (通常カード扱い = C:Rarity 必須のまま)
    assert A._still_required_spec("mc-746", "Weavile", "C:Rarity") is True
    # 印刷番号 `746/742` (数字/数字) を渡しても canonical 未確定なら発火しない
    assert A._still_required_spec("746/742", "Weavile", "C:Rarity") is True


def test_csv_auditor_card_type_exclusion_still_works_without_canonical(monkeypatch):
    """canonical 無しでも card_type ベース除外 (Energy Marker/Resource) は生きている。

    ★契約 v1.2 は「印刷番号を key に使わない」であって「card_type 除外を消す」ではない。
    """
    import csv_auditor as A
    _seed_listing_common_cache(monkeypatch, {})
    assert not A._still_required_spec("E-60", "Energy Marker", "C:Rarity")
    assert not A._still_required_spec("RP-029", "Resource", "C:Rarity")


def test_csv_auditor_uses_canonical_when_available(monkeypatch):
    """canonical PID が引けたらそれで判定 (mc- prefix が発火)。"""
    import csv_auditor as A
    _seed_listing_common_cache(monkeypatch,
        {"1": {"choice": "CHOSEN", "product_id": "MC-746"}})
    monkeypatch.setattr(A, "_catalog_has_spec_value", lambda pid, f: False)
    # 印刷番号を渡しても、canonical (MC-746) を引ければ除外
    assert A._still_required_spec("746/742", "Weavile", "C:Rarity", "PSA10-1") is False


def test_csv_auditor_no_key_or_fallback_pattern_in_source():
    """`key = pid or card_number` の fallback パターンが残っていないこと (回帰防止)。"""
    src = _load(os.path.join(_HQ_TOOLS, "csv_auditor.py"))
    assert "key = pid or card_number" not in src, (
        "csv_auditor がまだ `pid or card_number` fallback を持っている"
    )


# ---------------------------------------------------------------------------
# 契約 v1.2 §HQ-4 の判定不能時の挙動 (fail-closed)
# ---------------------------------------------------------------------------
def test_canonical_only_regression_pokemon_not_verified(monkeypatch):
    """cert が verified_certs に居ない Pokemon カード → C:Rarity は必須のまま。

    「MC-* prefix を印刷番号で偶発一致で消していたら本物の rarity 欠落を見逃す」を防ぐ。
    """
    import csv_auditor as A
    _seed_listing_common_cache(monkeypatch, {})
    # 印刷番号だけの状況で C:Rarity が「消せる」判定にならないこと
    assert A._still_required_spec("746/742", "Weavile", "C:Rarity") is True
    assert A._still_required_spec("001/184", "Some Card", "C:Rarity") is True
