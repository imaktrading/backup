"""カタログの写しが、既存の行の書き換えを見落としていた (2026-10-07: 12時間 写しが止まった)。

alias_of を付ける等の書き換えは 行数・最大 rowid・本体の大きさ が変わらず、-wal の大きさも同じことがある。
書き換えた日時の最大と別名の数も「変わったか」の材料にする。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import kagoya_catalog_sync as S  # noqa: E402


def test_change_check_looks_at_updates_and_aliases():
    src = open(S.__file__, encoding="utf-8").read()
    assert "max(updated_at), count(alias_of) from products" in src
