#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PSA TCG 新コア flip 状態の回帰テスト (2026-06-14)。

不変条件:
  - 本番は **旧コア** (PSA TCG ボタンに TCG_USE_NEW_GEN を付けない)。新コア flip は
    ユーザー明示承認時のみ。2026-06-14 に無断 flip したため revert (本番切替は要承認)。
  - ランナーが script["env"] を subprocess env に注入する配線は残す (承認後に flip 可能な状態)。

承認して flip する時: SCRIPTS の PSA TCG entry に "env": {"TCG_USE_NEW_GEN": "1"} を足し、
上の test を「==1」期待に反転する。psa_to_csv 側は無改変 (flag OFF で完全に旧挙動)。
"""
import os
import sys

_HQ = os.path.join(os.path.dirname(__file__), "..")
if _HQ not in sys.path:
    sys.path.insert(0, _HQ)


def test_psa_tcg_button_new_gen_off_by_default():
    # 本番は旧コア (新コア flip はユーザー明示承認時のみ)。2026-06-14 無断 flip を revert。
    # 承認して flip する時はこのテストを「==1」期待に反転させる。
    import control_panel as cp
    psa = [s for s in cp.SCRIPTS if s.get("category") == "PSA TCG" and s.get("type") == "new"]
    assert psa, "PSA TCG 新規ボタンが SCRIPTS に無い"
    assert psa[0].get("env", {}).get("TCG_USE_NEW_GEN") is None, \
        "PSA TCG ボタンに TCG_USE_NEW_GEN が付いている (= 無断 flip。承認時のみ許可)"


def test_runner_injects_script_env():
    # ランナーが script["env"] を env に注入する配線が残っているか (source レベル)
    with open(os.path.join(_HQ, "control_panel.py"), encoding="utf-8") as f:
        src = f.read()
    assert 'script.get("env")' in src, "ランナーの script env 注入配線が消えている"
