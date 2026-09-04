# -*- coding: utf-8 -*-
"""last_writer テスト用フィクスチャ (2026-09-04)。

test_pdca_resolver_drop_20260904.py から「別モジュールの呼出し」を再現するためだけに使う。
pytest の収集対象にしない (`test_` で始まらないファイル名)。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "tools")))

import pdca_store as ps  # noqa: E402


def call_upsert(con, ts, item_id="cert1"):
    return ps.upsert_improvement(con, "tcg", item_id, "catalog_add", ts=ts)
