"""HIGH/LOW 並走の安全条件 (2026-08-19).

並走してよいのは「隔離できている時だけ」。具体的には LOW 専用の chrome profile が
用意できている時に限り、LOW は別 lock を使って HIGH と同時に走る。

理由:
  - 同じ profile を指す Chrome は 2 つ同時に起動できない
  - cycle 開始時の「自分の残骸 chrome の掃除」が、profile 共有だと
    相手の稼働中 Chrome を殺してしまう (= 相手の巡回が全滅する)

なので profile 未整備の状態では、従来どおり 1 本の lock で直列に戻ること。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import monitor_listings as ml  # noqa: E402
import run_cycle  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_module_globals():
    """label 別 lock / profile の選択を test 間に持ち越さない."""
    yield
    run_cycle._ACTIVE_LOCK_FILE = None
    ml._ACTIVE_PROFILE_DIRS = ()


M_DEFAULT = r"C:\x\mercari_profile"
A_DEFAULT = r"C:\x\amazon_profile"


def _patch_defaults(monkeypatch, existing_dirs=()):
    monkeypatch.setattr(ml, "_default_profile_dirs", lambda: (M_DEFAULT, A_DEFAULT))
    monkeypatch.setattr(ml.os.path, "isdir", lambda p: p in existing_dirs)


def test_profile_dirs_default_for_high(monkeypatch):
    """HIGH (既定 label) は従来の profile をそのまま使う."""
    _patch_defaults(monkeypatch)
    assert ml.resolve_profile_dirs("SHEET") == (M_DEFAULT, A_DEFAULT)
    assert ml.resolve_profile_dirs("HIGH") == (M_DEFAULT, A_DEFAULT)


def test_profile_dirs_dedicated_for_low_when_prepared(monkeypatch):
    """LOW 専用 profile が在れば、それを使う."""
    _patch_defaults(monkeypatch, existing_dirs=(M_DEFAULT + "_LOW", A_DEFAULT + "_LOW"))
    assert ml.resolve_profile_dirs("LOW") == (M_DEFAULT + "_LOW", A_DEFAULT + "_LOW")


def test_profile_dirs_fall_back_when_not_prepared(monkeypatch):
    """★ 未整備なら既定に戻る (= 中途半端な隔離で並走を始めない)."""
    _patch_defaults(monkeypatch)   # 専用 dir は存在しない
    assert ml.resolve_profile_dirs("LOW") == (M_DEFAULT, A_DEFAULT)


def test_kill_targets_follow_active_profile(monkeypatch):
    """掃除の対象は「その cycle が使う profile」に限定される (相手の Chrome を殺さない)."""
    _patch_defaults(monkeypatch, existing_dirs=(M_DEFAULT + "_LOW", A_DEFAULT + "_LOW"))
    ml.set_active_profile_dirs("LOW")
    own = ml._own_profile_dirs()

    assert own == ((M_DEFAULT + "_LOW").lower(), (A_DEFAULT + "_LOW").lower())
    assert M_DEFAULT.lower() not in own       # HIGH の profile は対象外


def test_low_gets_own_lock_only_when_isolated(monkeypatch):
    """並走 (別 lock) は隔離できている時だけ許す."""
    with patch.object(ml, "resolve_profile_dirs", return_value=("m_LOW", "a_LOW")), \
         patch.object(ml, "_default_profile_dirs", return_value=("m", "a")):
        assert run_cycle._set_active_lock("low").name == ".cycle_LOW.lock"

    with patch.object(ml, "resolve_profile_dirs", return_value=("m", "a")), \
         patch.object(ml, "_default_profile_dirs", return_value=("m", "a")):
        assert run_cycle._set_active_lock("low").name == ".cycle.lock"   # 直列に戻る


def test_high_always_uses_the_default_lock(monkeypatch):
    """HIGH 側の lock 名は変えない (他ツールが見ている)."""
    for sheet in ("both", "high"):
        assert run_cycle._set_active_lock(sheet).name == ".cycle.lock"


def test_single_sheet_id_mode_stays_serial():
    """--sheet-id 指定 (= 本番 HIGH タスクの起動形) は常に既定 lock."""
    assert run_cycle._set_active_lock("low", sheet_id="19kj8...").name == ".cycle.lock"


def test_partial_profiles_do_not_enable_parallel(monkeypatch):
    """★ 片方だけ専用 profile がある状態で並走を始めないこと.

    LOW 用に Amazon の profile だけ複製できて Mercari が未完了、という途中経過が
    実際に起きる (Chrome が掴んでいる間はコピーできないため)。この状態で並走すると
    Mercari profile を奪い合い、HIGH 側の Chrome が落ちる。
    """
    _patch_defaults(monkeypatch, existing_dirs=(A_DEFAULT + "_LOW",))   # mercari 側が無い

    assert ml.resolve_profile_dirs("LOW") == (M_DEFAULT, A_DEFAULT)
