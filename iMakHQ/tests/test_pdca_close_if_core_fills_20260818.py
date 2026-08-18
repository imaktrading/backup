# -*- coding: utf-8 -*-
"""pdca_store.close_if_core_fills — 「今のコアで作り直したら埋まる」指摘を閉じる (2026-08-18).

実害:
  `close_not_redetected` は母集団を **その日のCSV1本** に絞る (別の日のCSV由来の未解決を
  全消ししないため。この絞り自体は正しい)。その代償で、別の日のCSVで見つかった指摘は
  二度と再検出されず 21日の stale 退役まで pending に残る。その間ずっと
  `emit_consolidated_request` が毎日カタログに同じ質問を出す。
  OP02-059 / OP03-001 の `C:Set` 空を **4日連続** で catalog に聞いた
  (2026-08-17 に手で close: queue_id 550/560)。

守りたいこと:
  1. 今のコアで埋まるなら、そのSKUが今日のCSVに載っていなくても閉じる。
  2. 判定不能 (None) / 例外 / まだ空 は **触らない** (fail-closed)。
  3. 閉じ方は `done`。`resolved`/`stale` は復活しない sticky な状態なので、
     再発した時に二度と上がってこなくなる (fail-OPEN) から使わない。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import pdca_store as pdca  # noqa: E402

TS = "2026-08-18"


def _con(tmp_path, monkeypatch):
    monkeypatch.setattr(pdca, "DB_PATH", str(tmp_path / "pdca.db"), raising=False)
    con = pdca.connect(str(tmp_path / "pdca.db"))
    return con


def _add(con, item_id, field, ft="必須Item Specific", source="auditor"):
    return pdca.upsert_improvement(con, "tcg", item_id, field, "",
                                   evidence=f"必須Item Specific '{field}' が空",
                                   source=source, layer="A", finding_type=ft, ts="2026-08-10")


def _status(con, qid):
    return con.execute("SELECT status FROM improvement_queue WHERE queue_id=?",
                       (qid,)).fetchone()[0]


class TestClosesWhatTheCurrentCoreFills:
    def test_closes_only_the_rows_the_core_fills(self, tmp_path, monkeypatch):
        con = _con(tmp_path, monkeypatch)
        fixed = _add(con, "PSA10-153574705", "C:Set")       # 今のコアで埋まる
        still = _add(con, "PSA10-999999999", "C:Rarity")    # まだ空
        con.commit()
        got = pdca.close_if_core_fills(
            con, "tcg", lambda iid, f: iid == "PSA10-153574705", ts=TS)
        assert got["closed"] == 1 and got["checked"] == 2
        assert _status(con, fixed) == "done"
        assert _status(con, still) == "pending"

    def test_closed_row_revives_when_it_comes_back(self, tmp_path, monkeypatch):
        """done は復活する = 再発をスルーしない (resolved/stale を使わない理由)."""
        con = _con(tmp_path, monkeypatch)
        qid = _add(con, "PSA10-153574705", "C:Set")
        con.commit()
        pdca.close_if_core_fills(con, "tcg", lambda iid, f: True, ts=TS)
        assert _status(con, qid) == "done"
        _add(con, "PSA10-153574705", "C:Set")               # 次の監査でまた出た
        con.commit()
        assert _status(con, qid) == "pending"

    def test_evidence_records_why_it_closed(self, tmp_path, monkeypatch):
        con = _con(tmp_path, monkeypatch)
        qid = _add(con, "PSA10-153574705", "C:Set")
        con.commit()
        pdca.close_if_core_fills(con, "tcg", lambda iid, f: True, ts=TS)
        ev = con.execute("SELECT evidence FROM improvement_queue WHERE queue_id=?",
                         (qid,)).fetchone()[0]
        assert "今のコアで再生成したら埋まった" in ev and TS in ev


class TestFailClosed:
    def test_unknown_verdict_is_left_alone(self, tmp_path, monkeypatch):
        con = _con(tmp_path, monkeypatch)
        qid = _add(con, "m81161788422", "C:Set")            # cert が取れない
        con.commit()
        got = pdca.close_if_core_fills(con, "tcg", lambda iid, f: None, ts=TS)
        assert got["closed"] == 0 and _status(con, qid) == "pending"

    def test_exception_is_left_alone(self, tmp_path, monkeypatch):
        con = _con(tmp_path, monkeypatch)
        qid = _add(con, "PSA10-153574705", "C:Set")
        con.commit()

        def boom(iid, f):
            raise RuntimeError("catalog DB unreachable")

        got = pdca.close_if_core_fills(con, "tcg", boom, ts=TS)
        assert got["closed"] == 0 and _status(con, qid) == "pending"

    def test_other_sources_and_types_are_untouched(self, tmp_path, monkeypatch):
        con = _con(tmp_path, monkeypatch)
        gap = _add(con, "sv1a-001", "catalog_request", ft="catalog_gap",
                   source="missing_models")
        prog = _add(con, "sig-1", "program_fix", ft="program_fix")
        con.commit()
        pdca.close_if_core_fills(con, "tcg", lambda iid, f: True, ts=TS)
        assert _status(con, gap) == "pending"
        assert _status(con, prog) == "pending"


class TestAuditorCheckerIsWiredToTheListingCore:
    """判定を監査くん側に複製していないこと (SSOT = 出品コア)."""

    def test_checker_returns_none_for_non_cert_skus(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
        import csv_auditor as ca
        assert ca._core_fills_spec("m81161788422", "C:Set") is None
        assert ca._core_fills_spec("PSA10-153574705", "Title") is None
        assert ca._core_fills_spec("", "C:Set") is None

    def test_checker_uses_build_listing_fields(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "tools",
                                "csv_auditor.py"), encoding="utf-8").read()
        assert "from tcg_listing_fields import build_listing_fields" in src, \
            "出品コアを呼ばずに判定を複製している"

    def test_accumulate_calls_it(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "tools",
                                "csv_auditor.py"), encoding="utf-8").read()
        assert "close_if_core_fills(con, project, _core_fills_spec" in src
