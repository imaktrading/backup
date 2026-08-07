"""Regression: 2026-06-16 — Mercari系(1点もの)は KEY-based dedupe を skip する。

経緯: 出品くんで Porter を実行したら、生成は 10件成功したのに 重複くん(dedupe_excluder)が
全10件を「解決不能(unresolved)」として物理除外 → 最終CSV 0行 = 出品ゼロになった。
原因: Porter/montbell/tshirt/reel は Mercari の1点もの商品で catalog canonical KEY を持たない。
KEY-based dedupe は全件 unresolved になり、それを destructive に全除外していた
(= 「判定不能は破壊的動作に倒さない」原則違反)。

control_panel の dedupe hook で Mercari系プレフィックスを skip する gate を入れた。
catalog-keyed (tcg/gshock/ichibankuji) は従来どおり dedupe 実行。

GUI モジュールなので import せず source レベルで gate の存在を固定する。
"""
from pathlib import Path

_SRC = (Path(__file__).resolve().parent.parent / "iMakHQ" / "control_panel.py").read_text(encoding="utf-8")


def test_dedupe_has_mercari_skip_gate():
    # _run_dedupe_for_latest_csv に Mercari系 skip gate がある
    assert "porter_" in _SRC and "montbell_" in _SRC and "tshirt_" in _SRC and "reel_" in _SRC, \
        "Mercari系プレフィックスの skip gate が見当たらない"
    assert "KEY-based dedupe skip" in _SRC, "dedupe skip のログ/gate が見当たらない"


def test_gate_is_before_dedupe_execution():
    # skip gate が dedupe 実行(--check-csv 呼出)より前にある
    gate = _SRC.find("KEY-based dedupe skip")
    exec_call = _SRC.find('"--check-csv"')
    assert gate != -1 and exec_call != -1 and gate < exec_call, \
        "skip gate が dedupe 実行より後ろ = 全除外を防げない"
