#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PSA TCG flip (TCG_USE_NEW_GEN=1 本番有効化) の回帰テスト (2026-06-14)。

不変条件:
  - control_panel の PSA TCG 新規ボタンは env TCG_USE_NEW_GEN=1 を渡す
    (= 出品くん PSA 実行が catalog 決定論 新生成コアを使う本番状態)。
  - ランナーが script["env"] を subprocess env に注入する配線が残っている。

flip 根拠: parity REGRESSION 0 + 91件 character_name scramble 是正完了 (検査4 91→0)。
OFF へ戻すには SCRIPTS の PSA TCG entry から "env" を外す (psa_to_csv 側は無改変)。
"""
import os
import sys

_HQ = os.path.join(os.path.dirname(__file__), "..")
if _HQ not in sys.path:
    sys.path.insert(0, _HQ)


def test_psa_tcg_button_enables_new_gen():
    import control_panel as cp
    psa = [s for s in cp.SCRIPTS if s.get("category") == "PSA TCG" and s.get("type") == "new"]
    assert psa, "PSA TCG 新規ボタンが SCRIPTS に無い"
    assert psa[0].get("env", {}).get("TCG_USE_NEW_GEN") == "1", \
        "PSA TCG ボタンが TCG_USE_NEW_GEN=1 を渡していない (flip 外れ)"


def test_runner_injects_script_env():
    # ランナーが script["env"] を env に注入する配線が残っているか (source レベル)
    with open(os.path.join(_HQ, "control_panel.py"), encoding="utf-8") as f:
        src = f.read()
    assert 'script.get("env")' in src, "ランナーの script env 注入配線が消えている"
