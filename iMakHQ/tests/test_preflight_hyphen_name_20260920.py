# -*- coding: utf-8 -*-
"""ハイフンを含むカード名でも番号+名前で catalog を引ける (2026-09-20)。

依頼書: hq/requests/2026-09-19_act_code_proposals_tcg.md 提案1 / 1b

実測 (2026-09-19): cert160479905 (FA/HO-OH GX #053) が3日連続で GAP 除外。
`_subject_tokens('HO-OH GX')` → `['HOOH']` に対し catalog 側は `Ho-Oh GX` のまま
比べていたため当たらなかった。catalog 側も `_norm_name` で均す。
1b: set_name_official は日本語しか無く英語 Brand と当たらないので specs の
set_name_ebay も照合対象に入れる。
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, r"C:\dev\iMak\iMakHQ\tools")
import psa_preflight as P  # noqa: E402

_SPECS = json.dumps({"set_name_ebay": "Sm3h: to Have Seen the Battle Rainbow"})
_BRAND = "POKEMON JAPANESE SUN & MOON TO HAVE SEEN THE BATTLE RAINBOW"


class _Con:
    """番号引き (`product_id LIKE`) にだけ SM3H-053 を返す catalog の代わり。"""

    def cursor(self):
        return self

    def execute(self, sql, params):
        self._num = "product_id LIKE" in sql
        return self

    def fetchone(self):
        return None

    def fetchall(self):
        if not self._num:
            return []
        return [("SM3H-053", "Ho-Oh GX", "ホウオウGX",
                 "SM3H 裂空のカリスマ", _SPECS)]


def test_hyphen_name_is_matched_against_normalized_catalog(monkeypatch):
    # catalog resolver は外れた状態を作る (番号+名前の照合だけを見たい)
    monkeypatch.setattr(P, "_ensure_catalog", lambda: None)
    monkeypatch.setattr(P, "_FRANCHISE",
                        {"pokemon_tcg": (lambda *a, **k: None, lambda b: None)},
                        raising=False)
    monkeypatch.setattr(P, "_confirmed_pid", lambda cert: None)
    monkeypatch.setattr(P, "_out_of_scope", lambda: {})
    res = P.classify(
        "160479905",
        {"Brand": _BRAND, "Subject": "FA/HO-OH GX TO HAVE SEEN BTL.RNBW.",
         "CardNumber": "053"},
        _Con())
    # 引けているので「未収録 (GAP)」にはしない。断定もしない = REVIEW
    assert res["status"] == "REVIEW"
    assert "SM3H-053" in json.dumps(res, ensure_ascii=False)


def test_set_name_ebay_is_compared_too():
    # 日本語の set_name_official だけでは英語 Brand と当たらない
    assert not P._brand_matches_set_name(_BRAND, "SM3H 裂空のカリスマ")
    # specs の set_name_ebay を足せば当たる
    assert P._brand_matches_set_name(
        _BRAND, "SM3H 裂空のカリスマ", "Sm3h: to Have Seen the Battle Rainbow")


def test_set_name_ebay_extracted_from_specs():
    assert P._set_name_ebay(_SPECS) == "Sm3h: to Have Seen the Battle Rainbow"
    assert P._set_name_ebay(None) == ""
    assert P._set_name_ebay("not json") == ""
