# -*- coding: utf-8 -*-
"""目視の候補が「同じカードの変種」で埋まらないこと (2026-08-19 ユーザー指摘).

> CHOPPER と分かっているなら CHOPPER の日本語版を全て候補に出せば？

実害 (cert168157629 トニートニー・チョッパー / PSA brand=ONE PIECE JAPANESE PROMOS):
  候補が `EB02-003` / `_p` / `_p1` の **3件だけ**。同じカードの変種しか出ないので、
  人は「該当なし」しか押せなかった (正解は catalog 未収録の第4絵柄 ©CHOPPER's Friends)。
  原因は3つ:
    1. 番号一致 (003) が当たるとキャラ名の候補出しをスキップしていた
       → 番号は「そのカードの番号」なので、同じキャラの別セット/別promoには当たらない
    2. 12件の枠が1枚のカードの変種で埋まっていた (EB01-006_P/_PRB01/_p1/_p2…)
    3. PSA が PROMOS と言っているのに promo が後ろに並んで枠から溢れていた
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from post_psa_review import _base_pid, diversify_by_base, promo_first  # noqa: E402


class Test幹の切り出し:
    def test_変種suffixを落とす(self):
        assert _base_pid("EB01-006_PRB01_comi_dummy") == "EB01-006"
        assert _base_pid("EB02-003_p1") == "EB02-003"

    def test_suffixが無ければそのまま(self):
        assert _base_pid("P-065") == "P-065"

    def test_空でも落ちない(self):
        assert _base_pid(None) == "" and _base_pid("") == ""


class Test枠を別のカードに配る:
    PIDS = ["EB01-006", "EB01-006_P", "EB01-006_PRB01", "EB01-006_p1", "EB01-006_p2",
            "EB02-003", "EB02-003_p", "P-065", "P-089", "P-101"]

    def test_同じ幹は2件まで(self):
        got = diversify_by_base(self.PIDS, 12)
        assert got.count("EB01-006") + sum(1 for g in got if g.startswith("EB01-006_")) == 2

    def test_別のカードが並ぶ(self):
        got = diversify_by_base(self.PIDS, 12)
        bases = {_base_pid(g) for g in got}
        assert {"EB01-006", "EB02-003", "P-065", "P-089", "P-101"} <= bases

    def test_上限を守る(self):
        assert len(diversify_by_base(self.PIDS, 4)) == 4

    def test_per_baseを変えられる(self):
        got = diversify_by_base(self.PIDS, 12, per_base=1)
        assert len(got) == len({_base_pid(g) for g in got})

    def test_空でも落ちない(self):
        assert diversify_by_base([], 5) == [] and diversify_by_base(None, 5) == []


class TestPROMOSならpromoを先に:
    PIDS = ["EB01-006", "OP01-015_P", "P-065", "EB02-003", "P-089"]

    def test_素のpromoが先頭(self):
        got = promo_first(self.PIDS, True)
        assert got[0].startswith("P-") and got[1].startswith("P-")

    def test_promo刷りは素のpromoの次(self):
        got = promo_first(self.PIDS, True)
        assert got.index("OP01-015_P") < got.index("EB01-006")

    def test_PROMOSでなければ並びを変えない(self):
        assert promo_first(self.PIDS, False) == self.PIDS

    def test_落とさない(self):
        """並べ替えるだけ。候補を減らさない。"""
        assert sorted(promo_first(self.PIDS, True)) == sorted(self.PIDS)


class Test実データで直っていること:
    def test_チョッパーのpromoが候補に出る(self):
        """cert168157629 の再現。3件 → 別カードが並ぶ状態になっていること."""
        from post_psa_review import _get_candidates
        got = [p for p, _img in _get_candidates(
            "one_piece_tcg", "PROMOS", "003", brand="ONE PIECE JAPANESE PROMOS",
            expected_product_id="EB02-003",
            subject="TONY TONY CHOPPER ONE PIECE CHOPPER'S 1")]
        assert len(got) > 3, "同じカードの変種だけで終わっている"
        assert any(p.startswith("P-") for p in got), "PROMOS なのに promo が候補に無い"
