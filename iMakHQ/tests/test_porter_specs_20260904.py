# -*- coding: utf-8 -*-
"""PORTER の Item Specifics を決定的に決める (2026-09-04 ユーザー確定)。

## なぜ
ポーターは1点ものでカタログに無く、値を突き合わせる相手が居ない。そのため
Claude が写真から毎回「書けそうな物」を足し引きし、**行ごとに列が変わって**いた。
2026-09-04 の15件の実測:

    C:Series       1/15   ← プロンプトは「Series 必須」と言うのに落ちている
    C:MPN          1/15   ← 中古1点ものに型番 = 同型番の新品とまとめられる (**間違い**)
    C:Type         1/15   ← バッグでは Style が正。書くと重複
    C:Description  1/15   ← eBay にこの項目は無い
    C:Size         Small(幅15.7in) > Medium(幅14.6in) と逆転 (**間違い**)

売上には効かない。**リスティングの精度**の話 (ユーザー明言)。

## 触らないもの (2026-09-04 に誤って「おかしい」と判断したので明記)
- Department の Men / Unisex Adults の割れ … プロンプトの規則どおり
- 寸法の `15.7 in (40.0 cm)` 形式 … 意図した形で eBay も受けている
  (live 358640735459 に同じ形が入っているのを実機確認)
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_MER = os.path.join(_ROOT, "iMakMercari")
if _MER not in sys.path:
    sys.path.insert(0, _MER)

import porter_specs as P                                       # noqa: E402

TITLE = "YOSHIDA PORTER Tanker Short Helmet Bag Small Black Nylon Pre-owned Japan"


def test_drops_the_fields_we_decided_not_to_emit():
    got = P.finalize({"Brand": "Porter", "Type": "Shoulder Bag", "MPN": "622-08332",
                      "Description": "x", "Country/Region of Manufacture": "Japan",
                      "Country of Origin": "Japan"}, TITLE)
    assert set(got) == {"Brand", "Country of Origin", "Series"}


def test_series_comes_from_the_title():
    assert P.series_from_title(TITLE) == "Tanker"
    assert P.series_from_title("YOSHIDA PORTER Heat Tote Bag Black Pre-owned Japan") == "Heat"
    assert P.series_from_title("PORTER Shoulder Bag Black Pre-owned Japan") == ""


def test_an_existing_series_is_not_overwritten():
    got = P.finalize({"Series": "Smoky"}, TITLE)
    assert got["Series"] == "Smoky"


def test_size_comes_from_the_measured_width():
    """★これが逆転の元。実寸が在るのに写真で判断させない。"""
    assert P.size_from_width(7.9) == "Small"
    assert P.size_from_width(9.9) == "Small"
    assert P.size_from_width(10.2) == "Medium"
    assert P.size_from_width(15.0) == "Medium"
    assert P.size_from_width(15.7) == "Large"
    assert P.size_from_width(19.7) == "Large"
    assert P.size_from_width(20.5) == "Extra Large"


def test_the_real_inversion_is_fixed():
    """2026-09-04 実測: Small(15.7in) が Medium(14.6in) より大きかった。"""
    small = P.finalize({"Size": "Small", "Bag Width": "15.7 in (40.0 cm)"}, TITLE)
    medium = P.finalize({"Size": "Medium", "Bag Width": "14.6 in (37.0 cm)"}, TITLE)
    assert small["Size"] == "Large" and medium["Size"] == "Medium"


def test_size_is_kept_when_there_is_no_measurement():
    """実寸が無い行は元の値を残す (推測を消さない)。"""
    got = P.finalize({"Size": "Medium"}, TITLE)
    assert got["Size"] == "Medium"


def test_does_not_apply_is_cleared_from_dimensions():
    got = P.finalize({"Bag Depth": "Does not apply", "Bag Height": "11.8 in (30.0 cm)"}, TITLE)
    assert got["Bag Depth"] == ""
    assert got["Bag Height"] == "11.8 in (30.0 cm)"     # 正しい寸法は触らない


def test_generation_calls_it_only_for_porter():
    import io as _io
    s = _io.open(os.path.join(_MER, "mercari_to_ebay_csv.py"), encoding="utf-8").read()
    i = s.index("porter_specs")
    seg = s[max(0, i - 400):i + 200]
    assert '== "porter"' in seg, "porter 以外にも当ててしまっている"
