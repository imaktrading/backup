"""gshock_to_csv.select_run_targets の回帰テスト (2026-06-12).

出品くん G-shock の「1回の実行でランダム10件処理」化 (TCG psa_to_csv 同仕様) を保証する。
- 既定: シャッフル後に先頭 max_per_run 件
- GSHOCK_NO_SHUFFLE=1 相当 (no_shuffle=True): 従来の上から順
- 件数 <= 上限: 全件
- 元リストは破壊しない

gshock_to_csv は undetected_chromedriver 等の重い import を持つため、import 不能な環境では skip。
"""
import os
import random
import sys

import pytest

_GSHOCK_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "iMakG-shock")
_GSHOCK_DIR = os.path.abspath(_GSHOCK_DIR)
if _GSHOCK_DIR not in sys.path:
    sys.path.insert(0, _GSHOCK_DIR)

try:
    _saved_argv = sys.argv
    sys.argv = ["gshock_to_csv.py"]  # argparse 暴発防止
    import gshock_to_csv  # noqa: E402
    sys.argv = _saved_argv
except Exception as e:  # pragma: no cover - import 不能環境では skip
    pytest.skip(f"gshock_to_csv import 不能: {type(e).__name__}: {e}", allow_module_level=True)


def _targets(n):
    return [(f"url{i}", f"GA-{1000 + i}-1AJF", "10000") for i in range(n)]


def test_caps_at_max_per_run():
    """20件投入 → 10件に打切られる (上限デフォルト)."""
    out = gshock_to_csv.select_run_targets(_targets(20), no_shuffle=True)
    assert len(out) == 10


def test_no_shuffle_preserves_order():
    """no_shuffle=True は従来の上から順 (先頭 max 件をそのまま)."""
    src = _targets(15)
    out = gshock_to_csv.select_run_targets(src, no_shuffle=True)
    assert out == src[:10]


def test_shuffle_reorders_but_is_subset():
    """既定(シャッフル)は max 件を返し、全て元集合の要素 (= 取りこぼし/捏造なし)."""
    src = _targets(30)
    rng = random.Random(42)  # 再現性のため seed 注入
    out = gshock_to_csv.select_run_targets(src, no_shuffle=False, rng=rng)
    assert len(out) == 10
    src_set = set(src)
    assert all(item in src_set for item in out)
    # seed 固定で「先頭10件そのまま」ではない (= 実際にシャッフルされている)
    assert out != src[:10]


def test_fewer_than_max_returns_all():
    """件数 <= 上限 なら全件 (打切りなし)."""
    src = _targets(4)
    out = gshock_to_csv.select_run_targets(src, no_shuffle=True)
    assert len(out) == 4
    assert out == src


def test_does_not_mutate_input():
    """元リストを破壊しない (コピーを返す)."""
    src = _targets(20)
    snapshot = list(src)
    gshock_to_csv.select_run_targets(src, no_shuffle=False, rng=random.Random(1))
    assert src == snapshot
