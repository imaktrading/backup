# -*- coding: utf-8 -*-
"""GAP を「catalog 未収録」と断定しない (2026-08-28)。

依頼書: hq/requests/2026-08-28_act_code_proposals_tcg.md 提案2
回答書: 同 _response.md 「`GAP` は『未収録』と言い切らず、REVIEW に落として目視へ
        (fail-closed は維持)」

実測 (2026-08-28): カタログへ飛んだ層A 6行は **6行とも catalog に実在**していた。
番号やセット記号で引けなかっただけ。名前で1回引いてから言う。
"""
from __future__ import annotations

import sys

sys.path.insert(0, r"C:\dev\iMak\iMakHQ\tools")
import psa_preflight as P  # noqa: E402


class _Con:
    """catalog DB の代わり。

    `LIKE ?`+`name_en` の問い合わせ (= 名前引き) にだけ rows を返す。
    番号引き (`product_id LIKE`) には何も返さない = resolver が外れた状態を作る。
    """

    def __init__(self, by_name=()):
        self._by_name = list(by_name)

    def cursor(self):
        return self

    def execute(self, sql, params):
        self._last = sql
        return self

    def fetchone(self):
        return None

    def fetchall(self):
        if "name_en LIKE" in self._last:
            return self._by_name
        return []


def _classify(brand, subject, num, con, monkeypatch):
    monkeypatch.setattr(P, "_ensure_catalog", lambda: None)
    monkeypatch.setattr(P, "_FRANCHISE",
                        {"one_piece_tcg": (lambda *a, **k: None, lambda b: None),
                         "pokemon_tcg": (lambda *a, **k: None, lambda b: None)},
                        raising=False)
    return P.classify("1", {"Brand": brand, "Subject": subject, "CardNumber": num}, con)


def test_row_exists_by_name_is_review_not_gap(monkeypatch):
    """名前で行が在る → 未収録ではない → REVIEW (目視へ)。"""
    con = _Con([("ST17-004_p1", "Boa Hancock",
                 "プレミアムブースター ONE PIECE CARD THE BEST ストレージボックスセット")])
    res = _classify("ONE PIECE JAPANESE PREMIUM BOOSTER -ONE PIECE CARD THE BEST- "
                    "STORAGE BOX SET", "BOA HANCOCK", "004", con, monkeypatch)
    assert res["status"] == "REVIEW"
    assert res["risk"] == "unresolved"
    assert res["candidates"] == ["ST17-004_p1"]
    assert "未収録ではなく" in res["reason"]


def test_no_row_by_name_is_gap_and_name_checked(monkeypatch):
    """名前で引いても行が無い → 従来どおり GAP。確かめた印を付ける。"""
    res = _classify("ONE PIECE JAPANESE OP99-NOT EXIST", "ZZZZZTOP", "001",
                    _Con([]), monkeypatch)
    assert res["status"] == "GAP"
    assert res["name_checked"] is True
    assert "名前でも catalog に行が無い" in res["reason"]


def test_subject_without_words_is_gap_but_not_asserted(monkeypatch):
    """`DON!! CARD` は照合できる語が無い = 確かめていない → 未収録と断定しない。"""
    res = _classify("ONE PIECE JAPANESE PREMIUM CARD COLLECTION -ONE PIECE DAY'24-",
                    "DON!! CARD", None, _Con([]), monkeypatch)
    assert res["status"] == "GAP"
    assert res["name_checked"] is False
    assert res["risk"] == "unchecked"
    assert "未確認" in res["reason"]
    assert "未収録の疑い" not in res["reason"]


def test_brand_matching_set_name_is_listed_first(monkeypatch):
    con = _Con([("XX-001", "Boa Hancock", "べつのセット"),
                ("ST17-004_p1", "Boa Hancock", "ONE PIECE CARD THE BEST")])
    res = _classify("ONE PIECE JAPANESE PREMIUM BOOSTER -ONE PIECE CARD THE BEST- "
                    "STORAGE BOX SET", "BOA HANCOCK", "004", con, monkeypatch)
    assert res["candidates"][0] == "ST17-004_p1"


def test_pids_by_subject_needs_usable_tokens():
    assert P.pids_by_subject(_Con([("A", "a", "")]), "one_piece_tcg", "DON!! CARD") == []
    assert P.pids_by_subject(_Con([("A", "a", "")]), "", "BOA HANCOCK") == []


def test_db_error_does_not_crash_classify():
    class _Boom(_Con):
        def fetchall(self):
            raise RuntimeError("db gone")
    assert P.pids_by_subject(_Boom(), "one_piece_tcg", "BOA HANCOCK") == []


# ---- 積み先: 確かめた時だけカタログへ (psa_to_csv 側) ----

def _tcg():
    sys.path.insert(0, r"C:\dev\iMak\iMakTCG")
    import psa_to_csv as T
    return T


def test_gap_goes_to_catalog_only_when_name_checked():
    T = _tcg()
    assert T.gap_queue_target({"name_checked": True})[:3] == ("catalog_add", "A", "catalog_gap")


def test_unchecked_gap_goes_to_hq_queue_not_catalog():
    T = _tcg()
    fld, layer, ft, _ = T.gap_queue_target({"name_checked": False})
    assert (fld, layer, ft) == ("program_fix", "code", "program_fix")
    assert T.gap_queue_target({})[0] == "program_fix", "印が無い時もカタログへ送らない"
