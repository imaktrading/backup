# -*- coding: utf-8 -*-
"""契約 v1.2 §CSV-削除禁止: 運用 policy の明文化担保 (2026-08-11)。

回答書: 2026-08-10_ssot_contract_cosign_snapshot_on_listing_response.md
  「CSV は削除しない を運用 policy として明文化してください。スナップショット
   原本になるため」

固定する事:
  1. `iMakHQ/csv_output/README_RETENTION.md` が存在する
  2. 「削除しない」「スナップショット原本」の中核メッセージが本文にある
  3. 契約 response file 名を明示的に参照している (追跡可能性)
"""
from __future__ import annotations

import os

_POLICY = r"C:\dev\iMak\iMakHQ\csv_output\README_RETENTION.md"


def test_retention_policy_doc_exists():
    assert os.path.isfile(_POLICY), (
        f"CSV 保管ポリシー ({_POLICY}) が無い。"
        "契約 v1.2 で明文化要求済 (削除しない = スナップショット原本)"
    )


def test_retention_policy_states_no_delete():
    with open(_POLICY, "r", encoding="utf-8") as f:
        text = f.read()
    # 中核メッセージ
    assert "削除しない" in text, "『削除しない』の明文がない"
    assert "スナップショット原本" in text, "『スナップショット原本』の位置づけがない"


def test_retention_policy_references_source_contract():
    """契約 response file 名を doc に書いてある (追跡可能性)。"""
    with open(_POLICY, "r", encoding="utf-8") as f:
        text = f.read()
    assert "2026-08-10_ssot_contract_cosign_snapshot_on_listing_response.md" in text, (
        "契約 response file を参照していない (根拠が辿れない)"
    )
