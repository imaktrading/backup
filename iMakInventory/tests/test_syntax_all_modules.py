"""全モジュール構文 smoke テスト (offline).

どのテストも import しないモジュール (run_daily.py / main.py 等) の構文エラーを
pre-commit で必ず捕まえるためのガード。

背景 (2026-06-11): 公式 run_daily.py が commit cda4126 で `lines.extend([...]` の
閉じ括弧 `)` 欠落 = SyntaxError を抱えたまま commit された。run_daily.py を import
するテストが無かったため pytest (= pre-commit gate) を通過し、 毎日 08:00 cron が
初実行でクラッシュ→公式無監視になる寸前だった。このテストがあれば commit 時に弾けた。

py_compile (= 構文チェックのみ、 module 実行はしない) なので、 gspread / creds /
network 等の副作用なしに全 .py を検査できる。
"""
import py_compile
from pathlib import Path

import pytest

pytestmark = pytest.mark.offline

# iMakInventory ルート (= tests の親)
_INV_ROOT = Path(__file__).resolve().parents[1]
# repo ルート (= iMakInventory の親) → 公式 inventory_monitor もここ配下
_REPO_ROOT = _INV_ROOT.parent
_OFFICIAL_ROOT = _REPO_ROOT / "iMakeBayAPI" / "inventory_monitor"

# 検査対象ディレクトリ (本番モジュールのある場所)
_TARGET_DIRS = [
    _INV_ROOT,                       # iMakInventory 直下
    _INV_ROOT / "scrapers",
    _INV_ROOT / "ebay_actions",
    _OFFICIAL_ROOT,                  # 公式 inventory_monitor 直下
]

_EXCLUDE_PARTS = {"__pycache__", ".git", "node_modules", "debug", "tools"}


def _collect_py_files() -> list:
    files = []
    seen = set()
    for d in _TARGET_DIRS:
        if not d.exists():
            continue
        for p in d.glob("*.py"):
            if any(part in _EXCLUDE_PARTS for part in p.parts):
                continue
            rp = p.resolve()
            if rp not in seen:
                seen.add(rp)
                files.append(p)
    return sorted(files)


_PY_FILES = _collect_py_files()


def test_target_files_discovered():
    # 主要モジュールが拾えていること (= glob が空振りしていない回帰防止)
    names = {p.name for p in _PY_FILES}
    for required in ("run_cycle.py", "monitor_listings.py", "sheet_updater.py"):
        assert required in names, f"{required} が検査対象に含まれていない"
    # 公式側 run_daily.py / main.py も対象に入っていること (= cda4126 型バグの本命)
    official_names = {p.name for p in _PY_FILES if "inventory_monitor" in str(p)}
    assert "run_daily.py" in official_names
    assert "main.py" in official_names


@pytest.mark.parametrize("py_file", _PY_FILES, ids=lambda p: str(p.relative_to(_REPO_ROOT)))
def test_module_compiles(py_file):
    """各 .py が SyntaxError 無く compile できること."""
    try:
        py_compile.compile(str(py_file), doraise=True)
    except py_compile.PyCompileError as e:
        pytest.fail(f"構文エラー: {py_file}\n{e}")
