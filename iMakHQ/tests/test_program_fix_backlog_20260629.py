# -*- coding: utf-8 -*-
"""program修正 backlog の閉ループ回帰テスト (2026-06-29)。

program バグ指摘も catalog と対称に improvement_queue(finding_type='program_fix')へ乗せ、
症状クラスで dedup・seen_count 集約・done で閉じる・再発で自動 reopen することを保証。
"""
import os
import sys

_TOOLS = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
sys.path.insert(0, _TOOLS)
import pdca_store as pdca
import program_fix_backlog as pfb


def _con(tmp_path):
    return pdca.connect(str(tmp_path / "pdca_test.db"))


def test_signature_classes():
    s = pfb.program_signature
    assert s("禁止ワード 'japan' がタイトルに含まれている") == "banned_word_in_title"
    assert s("タイトル形式逸脱: 必須語 '#' がタイトルに無い") == "title_missing_card_number"
    assert s("タイトル↔spec不一致: C:Color='Black' がタイトルに反映されてない") == "title_spec_mismatch:C:Color"
    assert s("タイトル↔spec不一致: C:Character='DON!! Card' がタイトルに") == "title_spec_mismatch:C:Character"
    assert s("タイトル形式逸脱: ['Reel'] のいずれもタイトルに無い") == "title_format_deviation"
    # 未知症状は安定プレフィックスで保持(取りこぼさない)
    assert s("謎のエラー").startswith("program:")


def test_diff_skus_same_class_dedup_to_seen_count(tmp_path):
    """別SKUでも同じ症状クラスなら1件に集約され seen_count が増える(=クラスの慢性度)。"""
    con = _con(tmp_path)
    for sku in ("m1", "m2", "m3"):
        pdca.upsert_improvement(con, "tcg", pfb.program_signature("禁止ワード 'japan' がタイトルに"),
                                "program_fix", "", evidence=f"{sku}: x",
                                finding_type="program_fix", ts="2026-06-29")
    con.commit()
    rows = pfb.load_open(con)
    assert len(rows) == 1
    assert rows[0]["seen_count"] == 3
    assert rows[0]["item_id"] == "banned_word_in_title"


def test_done_then_reopen_on_recurrence(tmp_path):
    con = _con(tmp_path)
    sig = pfb.program_signature("タイトル形式逸脱: 必須語 '#' がタイトルに無い")
    pdca.upsert_improvement(con, "tcg", sig, "program_fix", "", evidence="m1: x",
                            finding_type="program_fix", ts="2026-06-29")
    con.commit()
    assert len(pfb.load_open(con)) == 1
    # 実装完了 → done
    pfb._cmd_done(con, sig)
    assert len(pfb.load_open(con)) == 0
    # 直っていなければ次監査で同症状が再upsert → done→pending 自動復活
    pdca.upsert_improvement(con, "tcg", sig, "program_fix", "", evidence="m2: x",
                            finding_type="program_fix", ts="2026-06-30")
    con.commit()
    assert len(pfb.load_open(con)) == 1
