"""Regression: 2026-06-16 — Description の寸法に "approx." を付ける(SNAD保護)。

中古バッグの寸法は手測りでおおよそ。Item Specifics(Bag Height/Width/Depth)は eBay フィルタ用に
数値のままにし、商品説明(Description)側だけ "approx." を明記する、とユーザー判断。

mercari_to_ebay_csv は import 時に API key 等の副作用があるため、build_description_with_specs を
直接呼ばず、source レベルで「寸法キーにのみ approx. を付ける」ロジックの存在を固定する。
"""
import re
from pathlib import Path

_SRC = (Path(__file__).resolve().parent.parent / "iMakMercari" / "mercari_to_ebay_csv.py").read_text(encoding="utf-8")


def test_build_description_prefixes_approx_for_dimensions():
    # build_description_with_specs 内に approx. 付与ロジックがある
    body = _SRC[_SRC.index("def build_description_with_specs"):]
    body = body[: body.index("\ndef ", 1)] if "\ndef " in body[1:] else body
    assert "_APPROX_KEYS" in body, "approx 対象キー集合が無い"
    for k in ("Bag Width", "Bag Height", "Bag Depth"):
        assert k in body, f"寸法キー {k} が approx 対象に無い"
    assert 'approx. {v}' in body or 'f"approx. {v}"' in body, "approx. 付与の描画が無い"
    # 非寸法に無条件 approx を付けていない(条件分岐になっている)
    assert "if k in _APPROX_KEYS" in body, "approx は寸法キー限定の条件付きであるべき"
