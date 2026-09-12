# -*- coding: utf-8 -*-
"""Tシャツも 1押しで API 出品 → itemID → KEY まで行く (2026-09-12・残務 №177)。

なぜ: Tシャツだけ **CSV を人が FileExchange に上げて、itemID を人が打つ** 運用が残っており、
その2手があるせいで「出品済みの行に KEY を書く」段 (itemID が要る) に一度も届いていなかった。
実測 2026-09-12: 出品済み Tシャツ 79行の UT KEY = **0件**。

締めのチェーンは `tcg_upload_` 決め打ちだったので、Tシャツの CSV は拾われもしなかった。
商材の違いは **ボタンの定義が持つ値**で表す (共通化に if を入れない = HQ の3つの呪文)。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "iMakHQ", ROOT / "iMakHQ" / "tools", ROOT / "iMakeBayAPI"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import control_panel as CP  # noqa: E402


def _auto_entries():
    return [e for e in CP.SCRIPTS if e.get("auto_full")]


def test_tshirt_has_an_auto_button():
    hit = [e for e in _auto_entries() if e.get("category") == "Tシャツ"]
    assert hit, "Tシャツの 🤖自動 が無い (手上げ運用に戻っている)"
    assert hit[0]["auto_csv_prefix"] == "tshirt_upload_"


def test_every_auto_button_declares_its_csv_prefix():
    """既定に頼らない。宣言が無いと他商材の CSV を掴んで入稿しかねない。"""
    for e in _auto_entries():
        assert e.get("auto_csv_prefix"), f"{e.get('category')} に auto_csv_prefix が無い"


def test_tshirt_writes_key_after_itemid():
    """KEY は **itemID が入ってから**。逆だと出品前の行に KEY が付く (orphan KEY 事故)。"""
    e = [x for x in _auto_entries() if x.get("category") == "Tシャツ"][0]
    cmds = [c for _lb, c in e["auto_after_writeback"]]
    assert ["ut_key_backfill.py", "--write"] in cmds


def test_psa_chain_is_unchanged():
    e = [x for x in _auto_entries() if x.get("category") == "PSA TCG"][0]
    assert e["auto_csv_prefix"] == "tcg_upload_"
    assert not e.get("auto_after_writeback")


def test_prefix_default_and_picking(tmp_path):
    assert CP.auto_csv_prefix_of({}) == "tcg_upload_"
    assert CP.auto_csv_prefix_of({"auto_csv_prefix": "tshirt_upload_"}) == "tshirt_upload_"
    import os
    import time
    for n in ("tcg_upload_1.csv", "tshirt_upload_1.csv", "tshirt_upload_2.csv", "tshirt_upload_2.txt"):
        (tmp_path / n).write_text("x", encoding="utf-8")
        time.sleep(0.01)
    got = CP.latest_csv_with_prefix(str(tmp_path), "tshirt_upload_")
    assert os.path.basename(got) == "tshirt_upload_2.csv"
    assert CP.latest_csv_with_prefix(str(tmp_path), "gacha_upload_") == ""
    assert CP.latest_csv_with_prefix(str(tmp_path / "no-such-dir"), "tcg_upload_") == ""


def test_tshirt_auto_starts_in_verify_only():
    """★TEST段階 (2026-09-12 ユーザー「まだ、TEST段階だから、UPはやめておく」)。

    新しい商材は eBay が受理するか確かめるだけ = 出品しない。本番は True にして切り替える。
    """
    e = [x for x in _auto_entries() if x.get("category") == "Tシャツ"][0]
    assert e["auto_upload_write"] is False


def test_psa_still_uploads_for_real():
    e = [x for x in _auto_entries() if x.get("category") == "PSA TCG"][0]
    assert e.get("auto_upload_write", True) is True
