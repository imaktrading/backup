# -*- coding: utf-8 -*-
"""invoice_duty_rate — Orange Connex 請求書から実効関税率を出す。

背景 (2026-07-31):
    SpeedPAK の関税は「事前設定レート」で、**どの料金表にも率が書かれていない**
    (RATE_GUIDE L430-437 に「最終的な決済は請求金額に基づく」と明記)。
    HTS を引いても実請求は分からないため、**請求書が唯一の一次情報**。
    実測では HSコードが違っても 9.95%/9.98% と同率で、真の HTS は見られていなかった。

守りたい性質:
  1. 数値パースが通貨記号・カンマに耐える (請求書は "1,289" 形式)
  2. 実効率 = 関税 ÷ 申告価額(円) で出る
  3. 請求書の書式が変わったら **黙って0件にせず例外**にする (silent drop 禁止)
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "iMakeBayAPI"))
import invoice_duty_rate as idr  # noqa: E402

REAL = Path(r"C:\dev\iMak_data\shipping\invoices")


@pytest.mark.parametrize("raw,want", [
    ("1,289", 1289.0), ("¥4,443", 4443.0), (" 245 ", 245.0),
    (278.98, 278.98), ("", 0.0), (None, 0.0), ("abc", 0.0),
])
def test_num_parses_invoice_formats(raw, want):
    assert idr._num(raw) == want


def test_unknown_workbook_raises_not_silent(tmp_path):
    """書式が変わったら例外。0件で黙って返すと『関税ゼロ』と誤読される."""
    import openpyxl
    p = tmp_path / "wrong.xlsx"
    wb = openpyxl.Workbook()
    wb.active.title = "別の形式"
    wb.save(p)
    with pytest.raises(ValueError, match="想定のシートが無い"):
        idr.parse(str(p))


@pytest.mark.skipif(not REAL.exists() or not list(REAL.glob("*.xlsx")),
                    reason="実請求書が未配置")
def test_real_invoice_effective_rate():
    """実請求書: 実効率が 0〜100% の範囲で、処理料が関税の約2.1%であること."""
    rows = []
    for f in REAL.glob("*.xlsx"):
        rows += idr.parse(str(f))
    assert rows, "明細が取れていない"
    for r in rows:
        assert 0 <= r["duty_rate"] < 1.0, f"実効率が異常: {r}"
        assert r["declared_jpy"] > 0
        if r["duty"]:
            # PDF: 米国関税処理手数料 = 関税合計額の 2.1%
            assert 0.015 < r["proc_rate"] < 0.03, f"処理料率が2.1%から外れる: {r}"
        if r["ship"]:
            # 燃油サーチャージ 実測 15.5%
            assert 0.10 < r["fuel_rate"] < 0.25, f"燃油率が想定外: {r}"


@pytest.mark.skipif(not REAL.exists() or not list(REAL.glob("*.xlsx")),
                    reason="実請求書が未配置")
def test_hs_code_does_not_change_the_rate():
    """★HSコードが違っても同率 = Orange Connex は真のHTSを見ていない、という実測の固定.

    これが崩れた (HS別に率が変わった) なら、カテゴリ別 hts_rate の設計が
    再び意味を持つので、group 値の見直しを検討すること。
    """
    rows = [r for f in REAL.glob("*.xlsx") for r in idr.parse(str(f))]
    us = [r for r in rows if r["dest"] == "US" and r["duty"]]
    if len(us) < 2 or len({r["hs"] for r in us}) < 2:
        pytest.skip("HSコードが2種類以上ある US 明細が足りない")
    rates = [r["duty_rate"] for r in us]
    assert max(rates) - min(rates) < 0.01, (
        f"HS別に率が変わっている → group 設計を見直すこと: "
        f"{[(r['hs'], r['duty_rate']) for r in us]}")
