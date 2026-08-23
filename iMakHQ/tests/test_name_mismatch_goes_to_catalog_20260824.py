# -*- coding: utf-8 -*-
"""名前の食い違いは **カタログ側の待ち行列**へ (2026-08-24 ユーザー指示)。

## 何が起きていたか
入稿前の照合が出す2つの指摘は、どちらも出品を止めるが **直す担当が違う**:

    「PSAの現物と別ゲーム」   = こちらが別カードを掴んだ (8/23 の ST02-001 ワンピ↔ガンダム) → ②
    「PSAの現物と名前が一致しない」= catalog の英名が別人/直訳                              → ①

両方とも `program修正` (= HQ が直す) に入れていたため、**カタログのデータ誤りが
HQ の修正待ちとして積み上がっていた**。実測3件 (ジニア / ポケモンごっこ / オルティガ)
は全て catalog 側の誤りで、HQ には直せない。

## 決めつけない
とはいえ「名前が違う = カタログが悪い」と断定はできない。こちらが別の版を掴んでいる
可能性もある。CLAUDE.md「安易にカタログが間違っていると判断して修正依頼を出すな」に
沿って、自動依頼の本文には **両方の可能性と、突き返してよい旨**を書く。
"""
import os
import sys

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "iMakHQ", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import csv_auditor as A  # noqa: E402

_NAME_MSG = ("PSAの現物と名前が一致しない: PSA Subject='ORTEGA SUPER' の語が "
             "CSVの名前/タイトルに1つも無い (C:Card Name='Arven')")
_GAME_MSG = ("PSAの現物と別ゲーム: PSA='one piece' (ONE PIECE JAPANESE ...) だが "
             "CSVは'gundam' (C:Game='Gundam Card Game')")


def test_name_mismatch_goes_to_catalog():
    assert A.classify_finding("ERROR", _NAME_MSG) == A.EXCLUDE_CATALOG


def test_game_mismatch_stays_with_us():
    """別ゲームを掴むのは **こちらの引き方**の誤り。カタログに投げない。"""
    assert A.classify_finding("ERROR", _GAME_MSG) == A.REPORT_PROGRAM


def test_both_still_stop_the_listing():
    """行き先を分けても、**どちらも出品は止める**こと。"""
    for msg in (_NAME_MSG, _GAME_MSG):
        assert A.should_exclude([A.classify_finding("ERROR", msg)]), msg


def test_request_does_not_assert_catalog_is_wrong(tmp_path, monkeypatch):
    """自動依頼の本文が「カタログが誤り」と決めつけていないこと。"""
    monkeypatch.setattr(A, "CATALOG_REQ_DIR", str(tmp_path))
    A.write_catalog_request("tcg", [("m1", _NAME_MSG)], dry_run=False)
    body = open(os.path.join(str(tmp_path), f"{A._today()}_audit_catalog_fix_tcg.md"),
                encoding="utf-8").read()
    assert "決めつけていません" in body
    assert "別の版" in body, "こちら側の可能性が書かれていない"
    assert "突き返して" in body, "差し戻し方が書かれていない"
    assert "出品されてはいません" in body, "実害の有無が書かれていない"


def test_note_only_when_that_finding_is_present(tmp_path, monkeypatch):
    """関係ない依頼にまで注記を付けない。"""
    monkeypatch.setattr(A, "CATALOG_REQ_DIR", str(tmp_path))
    A.write_catalog_request("tcg", [("m1", "必須Item Specific 'C:Set' が空")], dry_run=False)
    body = open(os.path.join(str(tmp_path), f"{A._today()}_audit_catalog_fix_tcg.md"),
                encoding="utf-8").read()
    assert "決めつけていません" not in body
