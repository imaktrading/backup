"""Regression: 2026-09-14 act_code_proposals_mercari 提案2.

タイトルの単独 "Japan" と C:Country of Origin の矛盾チェックが LLM の多数決任せで
非決定だった (同一条件で1件BLOCK・2件PASS)。check_csv.py に決定論ルールを追加する。
"Japan Exclusive" は市場限定の表現で原産国の主張ではないため対象外にする。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MERCARI = _REPO_ROOT / "iMakMercari"

# ★module名を "check_csv" にしない: iMakTCG/check_csv.py と名前が衝突し、
# sys.modules キャッシュ経由で後続テスト(iMakHQ/tests/*)が Mercari 版を誤って
# 拾って ImportError になる (test_montbell_whitelist.py と同じ既知の罠)。
_spec = importlib.util.spec_from_file_location("mercari_check_csv", str(_MERCARI / "check_csv.py"))
_mercari_check_csv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mercari_check_csv)
japan_origin_mismatch = _mercari_check_csv.japan_origin_mismatch


def test_bare_japan_with_other_origin_is_mismatch():
    title = "Demon Slayer Tanjiro Anime Graphic Tee UNIQLO UT NWT Japan New"
    assert japan_origin_mismatch(title, "Vietnam") is not None


def test_japan_exclusive_with_other_origin_is_not_mismatch():
    """提案1の形 (Japan Exclusive) は原産国の主張ではないので矛盾扱いしない。"""
    title = "One Piece Sabo Anime Graphic Tee UNIQLO UT Japan Exclusive Navy US L (JP XL) NWT"
    assert japan_origin_mismatch(title, "Vietnam") is None


def test_origin_japan_is_never_mismatch():
    title = "Demon Slayer Tanjiro Anime Graphic Tee UNIQLO UT NWT Japan New"
    assert japan_origin_mismatch(title, "Japan") is None


def test_empty_origin_is_not_mismatch():
    title = "Demon Slayer Tanjiro Anime Graphic Tee UNIQLO UT NWT Japan New"
    assert japan_origin_mismatch(title, "") is None


def test_no_japan_word_is_not_mismatch():
    title = "One Piece Sabo Anime Graphic Tee UNIQLO UT Navy US L (JP XL) NWT"
    assert japan_origin_mismatch(title, "Vietnam") is None


def test_actual_run_log_rows_20260913():
    """2026-09-13 走行ログの3件を再現。旧実装は #7 だけ止め、行5/行8 は通していた。"""
    blocked = "Demon Slayer ... NWT Japan New"
    passed_row5 = "... NWT Japan Brand New"
    passed_row8 = "... NWT Japan New"
    assert japan_origin_mismatch(blocked, "Vietnam") is not None
    # 決定論ルールでは Japan が単独語なら行5/行8 も同じ理由で矛盾として検出される
    # (旧: LLMが見送っていたのが誤り。提案の意図は一貫した判定)
    assert japan_origin_mismatch(passed_row5, "Vietnam") is not None
    assert japan_origin_mismatch(passed_row8, "Vietnam") is not None
