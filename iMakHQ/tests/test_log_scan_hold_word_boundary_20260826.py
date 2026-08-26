# -*- coding: utf-8 -*-
"""`HOLD` を語の途中で拾わない (2026-08-26).

実害 (2026-08-24 の digest): HOLD もゲートも起きていないのに `HOLD/gate: 1件` が
載っていた。拾っていたのは候補行の `#087 GHOLDENGO EX SPECIAL ART` =
`G-HOLD-ENGO` の中の HOLD。相場ゲートは 2026-08-13 に停止済 (`market_lookup.enabled=false`)
なので本物の HOLD はまず出ない。常時ニセ1件が乗ると **本物が来ても見分けがつかない**
(狼少年 = fail-OPEN)。

依頼書: hq/requests/2026-08-24_act_code_proposals_tcg.md ①
回答書: hq/requests/2026-08-26_act_code_proposals_tcg_response.md (4)
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from csv_auditor import scan_log_lines  # noqa: E402


class Test語の途中は数えない:
    def test_GHOLDENGOでHOLDが立たない(self):
        assert scan_log_lines("  → #087 GHOLDENGO EX SPECIAL ART ✓") == []

    def test_HOLDを含む普通の語も数えない(self):
        for w in ("Threshold", "Household", "HOLDER", "STRONGHOLD"):
            assert scan_log_lines(f"  → #001 {w} ✓") == [], w


class Test本物のHOLDは数える:
    def test_ラベル形は拾う(self):
        assert scan_log_lines("🏁 市場ゲート: HOLD 3件") == ["HOLD/gate: 1件"]

    def test_関数名の形も拾う(self):
        assert scan_log_lines("gate_row_or_hold: 除外") == ["HOLD/gate: 1件"]
        assert scan_log_lines("csv_hold に落ちた") == ["HOLD/gate: 1件"]

    def test_0件の行は数えない(self):
        """2026-08-21 の既存規約 (0件の行は数えない) を壊していないこと。"""
        assert scan_log_lines("🏁 市場ゲート: HOLD 0件") == []


class Testエラー検出は壊れていない:
    def test_Selenium失敗は今までどおり数える(self):
        got = scan_log_lines("Error: Message: invalid session id\nStacktrace:")
        assert got == ["error: 2件"], got
