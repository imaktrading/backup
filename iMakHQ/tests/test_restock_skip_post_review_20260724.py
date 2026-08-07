# -*- coding: utf-8 -*-
"""RESTOCK Revise 時に post_psa_review(cert確認HTML)を出さない 回帰テスト (2026-07-24)。

ユーザー指摘: RESTOCK Revise は変種を確定KEYから forced 生成済み=既存出品の再出品なので、
生成後の cert確認 viewer は無関係(Revise CSV は既に確定変種で生成済)。無関係なら出すな。
対策: control_panel の post_psa_review hook 起動を restock_revise でも skip する。
GUI コードのため、skip 配線がソース上に在ることを構造で固定する。
"""
import os
import re

_CP = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "control_panel.py"))
with open(_CP, encoding="utf-8") as f:
    _SRC = f.read()


def test_restock_revise_detected_for_skip():
    """restock_revise ボタンを検出して skip 判定に入れている。"""
    assert "_is_restock_revise" in _SRC
    assert 'SCRIPTS[_ridx2].get("restock_revise")' in _SRC


def test_skip_review_combines_verify_and_restock():
    """skip 条件が verify_before_build と restock_revise の OR。"""
    assert "_skip_review = _verify_before_build or _is_restock_revise" in _SRC


def test_review_hook_gated_on_skip():
    """★本命: run_post_psa_review 起動が not _skip_review でガードされている。"""
    m = re.search(r"if _latest_csv and not _skip_review:\s*\n\s*_review_opened = bool\(run_post_psa_review",
                  _SRC)
    assert m, "post_psa_review が _skip_review でガードされていない"
