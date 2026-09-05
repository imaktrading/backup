# -*- coding: utf-8 -*-
"""在庫が戻っても ①を押すまで誰も気づけなかった件 (2026-09-05)。

再仕入れ待ち台帳の「待ち(供給なし)」→「復活可」の切替は `psa_resource_gate.py` の
中でしか起きず、そのスクリプトは **どのタスクにも登録されていなかった**。
夜間 23:30 のバッチが回していたのは候補のキャッシュ (`psa_hoju_fill search-restock`) だけ。
= 仕入元に在庫が戻っても、人がボタンを押すまで台帳は「在庫なし」のままだった
(実測: 84件の候補中 43件が在庫待ちで滞留)。

ユーザー指示「事故がない部分は、夜間に回して」。

夜間に回してよいのは **人の判断が要らない所だけ**:
  - 変種を目視で確定済の行の在庫再チェック
  - 再仕入れ待ち台帳の更新
夜間に回してはいけない:
  - 未確定の変種 (別変種の在庫を見て「復活可」にすると誤仕入れの入口)
  - 目視ゲート / RESTOCK視覚確証 (人が見る)
  - 不一致PDCA と カタログ依頼書 (人が理由を選んでいない)
"""
import os
import sys

_HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOOLS = os.path.join(_HQ, "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import psa_resource_gate as G  # noqa: E402

_SRC = open(os.path.join(_TOOLS, "psa_resource_gate.py"), encoding="utf-8").read()
_BAT = open(os.path.join(_TOOLS, "run_hoju_search.bat"), encoding="utf-8").read()


def test_nightly_flag_defaults_off():
    """ボタンで押した時の挙動は変えない。"""
    assert G.NIGHTLY is False


def test_nightly_skips_unconfirmed_variants():
    """未確定の変種は夜間では触らない (誤って復活させない)。"""
    assert "if NIGHTLY and todo:" in _SRC
    assert "todo = []" in _SRC


def test_nightly_opens_no_visual_confirmation():
    assert 'if not NIGHTLY and "--no-confirm" not in sys.argv' in _SRC


def test_nightly_writes_no_catalog_request():
    """人が理由を選んでいないので PDCA も依頼書も書かない。"""
    i = _SRC.index("_run_mismatch_pdca(rejected, list(auto_idx)")
    assert "if not NIGHTLY:" in _SRC[i - 60:i]


def test_batch_runs_the_nightly_recheck():
    assert "psa_resource_gate.py --nightly" in _BAT
    # 候補キャッシュ(3)の後に置く = 当日キャッシュを使って再スクレイプを減らす
    assert _BAT.index("search-restock --limit=0") < _BAT.index("psa_resource_gate.py --nightly")


def test_batch_stays_ascii_only():
    """cmd.exe は .bat を OEM コードページで読む。日本語を入れると壊れる
    (2026-07-30 に実際に壊れ、タスクは exit 0 のまま何も走らなかった)。"""
    raw = open(os.path.join(_TOOLS, "run_hoju_search.bat"), "rb").read()
    assert all(b < 128 for b in raw), "非ASCII文字が入っている"


def test_nightly_does_not_dig_for_new_candidates():
    """夜間は「新規N件見つかるまで掘る」をしない (BAN リスクを増やさない)。"""
    assert "set RESTOCK_TARGET_NEW=0" in _BAT
