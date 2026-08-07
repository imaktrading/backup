#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""uc version_main 自動検出化の回帰テスト (master, 2026-06-14)。

横断ルール (global CLAUDE.md 2026-06-13): undetected_chromedriver の version_main に
major version を数値ハードコードしない。実 Chrome を検出して渡す / 失敗時 None。

不変条件:
  - detect_chrome_major() は int(>0) か None を返す (例外を投げない)。
  - master の listing/viewer スクリプトに `version_main=<数値>` が再混入しない
    (= driver 起動不能事故 2026-06-13 の回帰防止)。
"""
import importlib.util
import os
import re

_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_UTIL = os.path.join(_ROOT, "iMakeBayAPI", "chrome_util.py")

# numeric pin を持っていてはいけない master 上のファイル (相対パス)
_GUARDED = [
    os.path.join("iMakTCG", "psa_to_csv.py"),
    os.path.join("iMakeBayAPI", "seller_hub_view.py"),
    os.path.join("iMakeBayAPI", "chrome_util.py"),
]
_NUMERIC_PIN = re.compile(r"version_main\s*=\s*\d+")


def _load_util():
    spec = importlib.util.spec_from_file_location("imakebay_chrome_util", _UTIL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_detect_returns_int_or_none():
    mod = _load_util()
    v = mod.detect_chrome_major()
    assert v is None or (isinstance(v, int) and v > 0)


def test_no_numeric_version_main_pin_on_master():
    offenders = []
    for rel in _GUARDED:
        path = os.path.join(_ROOT, rel)
        with open(path, encoding="utf-8") as f:
            src = f.read()
        for m in _NUMERIC_PIN.finditer(src):
            offenders.append(f"{rel}: {m.group(0)}")
    assert not offenders, "numeric version_main pin 残存: " + "; ".join(offenders)


# ★2026-08-08: 名指し3本だけでは守れていなかった。Chrome が 151 に上がった日に
#   `iMakCatalog/scrapers/_phase3_diag_series.py` と `_phase3_diag_state_pollution.py` が
#   **146 固定のまま**残っているのが見つかった (2026-06-13 の一斉是正から漏れていた)。
#   名指し方式は「新しく書かれたファイル」を永久に守れないので、**リポジトリ全体**を見る。
#   ★対象は **git 管理下の .py だけ**にする。gitignore された使い捨て診断スクリプトまで
#   見ると、他 worktree の手元ファイルで **pre-commit が全部止まる**新しい blocker になる
#   (2026-08-04〜07 に重複くんが実際に止まったのと同型の事故を作らない)。
def _tracked_py():
    import subprocess
    try:
        out = subprocess.run(["git", "ls-files", "*.py"], cwd=_ROOT,
                             capture_output=True, text=True, timeout=60)
    except Exception:                                          # noqa: BLE001
        return []
    skip = os.path.join("iMakHQ", "tests").replace("\\", "/")
    return [p for p in out.stdout.splitlines() if p and not p.startswith(skip)]


def test_no_numeric_pin_anywhere_on_master():
    """git 管理下の .py 全体に numeric pin が無いこと (名指し漏れを塞ぐ)。

    テスト自身 (`iMakHQ/tests`) は正規表現の見本を持つので走査から除く。
    """
    files = _tracked_py()
    assert files, "git ls-files が空 — 走査できていない (テストが無意味になっている)"
    offenders = []
    for rel in files:
        try:
            src = open(os.path.join(_ROOT, rel), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for m in _NUMERIC_PIN.finditer(src):
            offenders.append(f"{rel}: {m.group(0)}")
    assert not offenders, (
        "numeric version_main pin 残存 (Chrome 自動更新で driver 起動不能になる): "
        + "; ".join(offenders))
