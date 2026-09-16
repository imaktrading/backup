# -*- coding: utf-8 -*-
"""layer="code" (HQ が直すコード修正) を catalog のまとめ依頼に載せない (2026-09-16)。

実害: catalog/requests/2026-09-14_pdca_catalog_queue_mercari.md が 層A/B とも0件の空依頼で出た
(中身は queue_id 642 = program_fix だけ)。閉じると HQ の修正件まで done になる。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "tools")))

import pdca_store as pdca  # noqa: E402


def test_code_layer_only_emits_nothing(tmp_path):
    con = pdca.connect(":memory:")
    pdca.upsert_improvement(con, "mercari", "program:title Japan vs Country", "program_fix", "",
                            evidence="m1: x", source="auditor", layer="code",
                            finding_type="program_fix", ts="2026-09-14")
    assert pdca.emit_consolidated_request(con, "mercari", str(tmp_path), "2026-09-14") == 0
    assert not list(tmp_path.glob("*.md")), "code 層だけで catalog 依頼が出ている"


def test_code_layer_not_in_sidecar_when_mixed(tmp_path):
    con = pdca.connect(":memory:")
    qa = pdca.upsert_improvement(con, "mercari", "m2 A B", "C:Brand", "",
                                 source="auditor", layer="A", finding_type="catalog_gap",
                                 identity="X | Y | Z", ts="2026-09-14")
    pdca.upsert_improvement(con, "mercari", "program:sig", "program_fix", "",
                            evidence="m1: x", source="auditor", layer="code",
                            finding_type="program_fix", ts="2026-09-14")
    assert pdca.emit_consolidated_request(con, "mercari", str(tmp_path), "2026-09-14") == 1
    import json
    side = tmp_path / "2026-09-14_pdca_catalog_queue_mercari.queue_ids.json"
    assert json.loads(side.read_text(encoding="utf-8")) == [qa]
