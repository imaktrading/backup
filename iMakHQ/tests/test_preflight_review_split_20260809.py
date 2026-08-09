# -*- coding: utf-8 -*-
"""REVIEW の候補を「同じセット」「別セット」に割る (2026-08-09).

なぜ:
    925件 全件監査で REVIEW 7件のうち5件が、**別ゲームの同番号**を候補に出していた。
      brand='SON GOKU HEROES UGM5' (= SDBH) → 候補 FB02-017 / SB01-017 (= Fusion World)
    catalog に SDBH は **0件** (UGM/BM/HG/GM/H2 いずれも 0件と実測) なので、
    番号とキャラ名が一致しただけの別ゲームのカード。採用したら誤出品だった。

    断定はしない (fail-closed 維持)。**人が見た瞬間に区別できる形**に割るだけ。

固定する挙動:
  1. brand に候補の set 記号が出てくる → same_series (索引不備の疑い)
  2. 出てこない → other_series (別セットの疑い。採用するなと明記)
  3. 同系が1つも無い時は reason に「採用するな」を出す
  4. candidates は同系を先に並べる (人が上から見る)
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, r"C:\dev\iMak\iMakHQ\tools")
import psa_preflight as P  # noqa: E402


# ---- 1〜2. 同系 / 別系の判定 -------------------------------------------------


def test_prefix_present_in_brand_is_same_series():
    assert P._set_prefix_in_brand("FB02-017", "DRAGON BALL FB02-BLAZING AURA") is True


def test_prefix_absent_is_other_series():
    """SDBH の brand に Fusion World の記号は出てこない。"""
    assert P._set_prefix_in_brand("FB02-017", "SON GOKU HEROES UGM5") is False
    assert P._set_prefix_in_brand("SB01-017", "SON GOKU HEROES UGM5") is False


def test_case_insensitive():
    assert P._set_prefix_in_brand("op03-001", "ONE PIECE OP03 PILLARS OF STRENGTH") is True


def test_empty_inputs_are_false_not_crash():
    assert P._set_prefix_in_brand("", "BRAND") is False
    assert P._set_prefix_in_brand("FB02-017", "") is False
    assert P._set_prefix_in_brand(None, None) is False


def test_prefix_is_the_part_before_first_hyphen():
    """`DON-PRB01-027` の記号は `DON`。`PRB01` ではない (区切りは最初のハイフン)。"""
    assert P._set_prefix_in_brand("DON-PRB01-027", "ONE PIECE DON!! CARD") is True
    assert P._set_prefix_in_brand("DON-PRB01-027", "ONE PIECE PRB01") is False


# ---- 3〜4. classify が仕分けて返す -------------------------------------------


class _FakeCon:
    """catalog DB の代わり。`%-<num>` LIKE に対して固定の候補を返す。"""

    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return self

    def execute(self, sql, params):
        self._last = (sql, params)
        return self

    def fetchone(self):
        return None

    def fetchall(self):
        if "LIKE" not in self._last[0]:
            return []
        return self._rows


def _classify(brand, subject, num, rows, monkeypatch):
    monkeypatch.setattr(P, "_ensure_catalog", lambda: None)
    monkeypatch.setattr(P, "_FRANCHISE",
                        {"dragonball_scg": (lambda *a, **k: None, lambda b: None),
                         "one_piece_tcg": (lambda *a, **k: None, lambda b: None)},
                        raising=False)
    meta = {"Brand": brand, "Subject": subject, "CardNumber": num}
    return P.classify("1", meta, _FakeCon(rows))


def test_candidates_across_multiple_sets_says_do_not_use(monkeypatch):
    """候補が FB02 と SB01 に散る → 別ゲーム混在の疑い → 採用するな。

    ★2026-08-09: brand を SDBH (`...HEROES UGM5`) から Fusion World に変えた。
      SDBH は `out_of_scope_by_brand` が **classify の入口で** OUT-OF-SCOPE に落とすので、
      この分岐まで到達しなくなったため (下の `test_sdbh_never_reaches_review` で固定)。
      ここで見たいのは「候補が複数セットに散った時の扱い」であって SDBH ではない。
    """
    rows = [("FB02-017", "Son Goku", "孫悟空"), ("SB01-017", "Son Goku (Great Ape)", "大猿孫悟空")]
    res = _classify("DRAGON BALL SUPER CARD GAME FUSION WORLD JAPANESE AWAKENED PULSE",
                    "SON GOKU", "017", rows, monkeypatch)
    assert res["status"] == "REVIEW"
    assert res["risk"] == "cross-set"
    assert res["same_series"] == []
    assert set(res["other_series"]) == {"FB02-017", "SB01-017"}
    assert "採用するな" in res["reason"]


def test_candidates_within_one_set_is_variant_not_cross_game(monkeypatch):
    """`CHAMPIONSHIP SET 2023` は brand に OP03 が無いが、候補は全部 OP03 の変種。

    ここまで「採用するな」と言うと、実在する変種違いまで殺してしまう。
    版を選ぶ話なので **目視で確定** に落とす。
    """
    rows = [("OP03-001", "Portgas D. Ace", "ポートガス・D・エース"),
            ("OP03-001_p", "Portgas D. Ace", "ポートガス・D・エース"),
            ("OP03-001_P", "Portgas D. Ace", "ポートガス・D・エース")]
    res = _classify("ONE PIECE PORTGAS D. ACE CHAMPIONSHIP SET 2023", "PORTGAS D. ACE",
                    "001", rows, monkeypatch)
    assert res["risk"] == "variant"
    assert res["prefixes"] == ["OP03"]
    assert "目視" in res["reason"]
    assert "採用するな" not in res["reason"]


def test_same_series_is_reported_as_index_failure_suspicion(monkeypatch):
    rows = [("FB02-017", "Son Goku", "孫悟空")]
    res = _classify("DRAGON BALL FB02-BLAZING AURA", "SON GOKU", "017", rows, monkeypatch)
    assert res["same_series"] == ["FB02-017"]
    assert "索引不備" in res["reason"]
    assert "採用するな" not in res["reason"]


def test_candidates_list_same_series_first(monkeypatch):
    rows = [("SB01-017", "Son Goku (Great Ape)", "大猿孫悟空"), ("FB02-017", "Son Goku", "孫悟空")]
    res = _classify("DRAGON BALL FB02-BLAZING AURA", "SON GOKU", "017", rows, monkeypatch)
    assert res["candidates"][0] == "FB02-017", "同系を先に並べていない"


def test_no_candidates_is_still_gap(monkeypatch):
    """候補ゼロなら GAP のまま (★brand は SDBH でない Fusion World を使う。上と同じ理由)."""
    res = _classify("DRAGON BALL SUPER CARD GAME FUSION WORLD JAPANESE AWAKENED PULSE",
                    "SON GOKU", "017", [], monkeypatch)
    assert res["status"] == "GAP"


def test_sdbh_never_reaches_review(monkeypatch):
    """★SDBH は REVIEW/GAP に落とさず、入口で OUT-OF-SCOPE にする (2026-08-09).

    SDBH は Fusion World と別ゲームで catalog 対象外。候補が散っていようが居まいが
    「目視で確定して」と人に見せる価値が無い。REVIEW に混ぜると、
    catalog へ「追加して」と依頼し続けることになる (921本スパイラルの発生源)。
    """
    rows = [("FB02-017", "Son Goku", "孫悟空"), ("SB01-017", "Son Goku (Great Ape)", "大猿孫悟空")]
    for brand in ("DRAGON BALL SON GOKU HEROES UGM5",
                  "SUPER DRAGON BALL HEROES METEOR MISSION 2"):
        res = _classify(brand, "SON GOKU", "017", rows, monkeypatch)
        assert res["status"] == "OUT-OF-SCOPE", f"SDBH が REVIEW に落ちている: {brand}"
        assert "SDBH" in res["reason"]
