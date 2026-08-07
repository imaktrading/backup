#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""post_psa_review は「確認ブラウザを開いたか」を bool で返す (2026-06-22)。

ユーザー指摘: PSA Review(確認ブラウザ)と RESTOCK CSV が同時に開いて邪魔。
対策: run_post_psa_review が True(ブラウザ開いた=判定待ち)/False を返し、control_panel は
True の時 CSV を自動オープンしない。本テストは bool 契約(少なくとも False パス)を固定。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import post_psa_review as p  # noqa: E402


def test_missing_csv_returns_false():
    """CSV が無ければ False(ブラウザ開かない)。"""
    r = p.run_post_psa_review(os.path.join(os.path.dirname(__file__), "no_such_file_xyz.csv"),
                              lambda *_a, **_k: None)
    assert r is False


def test_return_annotation_is_bool():
    import inspect
    sig = inspect.signature(p.run_post_psa_review)
    assert sig.return_annotation in (bool, "bool"), "戻り値型注釈が bool"
