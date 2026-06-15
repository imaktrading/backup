#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PSA TCG 新コア flip 状態の回帰テスト (2026-06-14 制定 / 2026-06-15 flip 反映)。

不変条件:
  - 本番は **新コア** (PSA TCG ボタンに TCG_USE_NEW_GEN=1)。2026-06-15 ユーザー明示 go で flip。
    根拠: Gemini 条件付きGO + parity REGRESSION 0 + 旧コアが毎回再発させる defect 解消。
  - ランナーが script["env"] を subprocess env に注入する配線が残っている。

OFF 復帰 (旧コアに戻す) 時: PSA TCG entry の "env" を削除し、下の test を「is None」期待に戻す。
psa_to_csv 側は無改変 (flag OFF で完全に旧挙動)。
"""
import os
import sys

_HQ = os.path.join(os.path.dirname(__file__), "..")
if _HQ not in sys.path:
    sys.path.insert(0, _HQ)


def test_psa_tcg_button_new_gen_on():
    # 本番は新コア (2026-06-15 ユーザー明示 go で flip)。OFF 復帰時は "env" 削除 + 期待を is None に。
    import control_panel as cp
    psa = [s for s in cp.SCRIPTS if s.get("category") == "PSA TCG" and s.get("type") == "new"]
    assert psa, "PSA TCG 新規ボタンが SCRIPTS に無い"
    assert psa[0].get("env", {}).get("TCG_USE_NEW_GEN") == "1", \
        "PSA TCG ボタンに TCG_USE_NEW_GEN=1 が無い (= flip が外れている)"


def test_runner_injects_script_env():
    # ランナーが script["env"] を env に注入する配線が残っているか (source レベル)
    with open(os.path.join(_HQ, "control_panel.py"), encoding="utf-8") as f:
        src = f.read()
    assert 'script.get("env")' in src, "ランナーの script env 注入配線が消えている"
