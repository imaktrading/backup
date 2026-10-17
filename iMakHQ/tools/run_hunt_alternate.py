# -*- coding: utf-8 -*-
"""トレハン・キャラハンを交互に1本ずつ動かす (家の job_queue が48時間おきに呼ぶ・2026-10-17 B-20261017-009)。

ユーザー確定 (2026-10-17): ハントは 2日に1回 夜に交互・1回 約400行・写真読みは月 約$45 まで。
上限・無駄読み防止・落ちた時の続きからは抽出くんの側 (8f80d4a4) が持つ。ここは「どちらの番か」だけ決める。

    前回うまく終わった方の逆を動かす。途中で PC が落ちた (running が残っている) 時は同じ方をもう一度
    → 抽出くんが自分の印 (treasure_running.flag 等) を見て続きから進む
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime

STATE = r"C:/dev/iMak_data/hq/hunt_alternate.json"
HARVEST = r"C:/dev/iMak_harvest/iMakHarvest"
KINDS = {"treasure": ("トレハン", "run_harvest_mercari_treasure.py"),
         "chara": ("キャラハン", "run_harvest_mercari_chara.py")}


def next_kind(state):
    """今回動かす方 (純関数)。落ちた途中があればそれ、無ければ前回の逆。初回はトレハン。"""
    st = state or {}
    if st.get("running") in KINDS:
        return st["running"], True
    return ("chara" if st.get("last") == "treasure" else "treasure"), False


def _load():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(st):
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)


def main():
    st = _load()
    kind, resumed = next_kind(st)
    label, script = KINDS[kind]
    print(f"🎯 ハント: 今回は {label}" + (" (前回の途中から)" if resumed else f" (前回 {KINDS.get(st.get('last'), ('なし',))[0]})"),
          flush=True)
    st.update(running=kind, started_at=datetime.now().isoformat(timespec="seconds"))
    _save(st)
    rc = subprocess.call([sys.executable, os.path.join(HARVEST, script)], cwd=HARVEST,
                         env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    st = _load()
    st.update(running=None, last=kind, last_rc=rc, last_end=datetime.now().isoformat(timespec="seconds"))
    _save(st)
    print(f"🎯 ハント: {label} が終わった rc={rc} (次は {KINDS['chara' if kind == 'treasure' else 'treasure'][0]})",
          flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
