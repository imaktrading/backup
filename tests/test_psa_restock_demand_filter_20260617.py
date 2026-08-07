"""Regression: 2026-06-17 — PSA再仕入れの分母に実需フィルタを追加。

RESTOCK は「impr_total>0(広告込み累計表示)だけでも入る」緩い基準のため RESTOCK∩PSA10 が
297件まで膨らみ処理が遅かった。実需(sold_qty/sales90/watch/organic impr のいずれか≥1)に絞り、
impr_total だけの薄い層を除外する(297→約85)。impr_total は広告込みなので条件に使わない。

build_input_from_funnel は I/O(funnel CSV読込+desktop書込)なので source レベルで
フィルタ条件が配線されていることを固定する。
"""
from pathlib import Path

_SRC = (Path(__file__).resolve().parent.parent / "iMakHQ" / "tools" / "mercari_psa_resource.py").read_text(encoding="utf-8")


def test_demand_filter_uses_sold_watch_organic_impr_not_impr_total():
    body = _SRC[_SRC.index("def build_input_from_funnel"):]
    body = body[: body.index("\ndef ", 1)] if "\ndef " in body[1:] else body
    # 実需4項目で絞る
    for col in ("sold_qty", "sales90", "watch", "impr"):
        assert f'"{col}"' in body, f"実需フィルタに {col} が無い"
    assert "_has_demand" in body, "実需フィルタ関数が無い"
    # impr_total は「条件として」使わない(広告込みのため)。docstring での言及はOK。
    assert '_f("impr_total")' not in body and "'impr_total'" not in body, \
        "impr_total を実需フィルタの条件に使ってはいけない(広告込み)"
    # RESTOCK + PSA10 の基本2条件も維持
    assert "RESTOCK" in body and "is_psa10" in body
