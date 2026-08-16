# -*- coding: utf-8 -*-
"""キーワードPDFを「PATHに無い」だけで諦めない (2026-08-16)。

★事故: 一番くじの刷新が毎回
  `⚠️ PDF動的読込失敗(pdftotext not in PATH) → 埋め込み2026Q1 top30 にフォールバック`
  で走っていた。pdftotext は Git 同梱で **実在する** (Git Bash からは動く) のに、
  パネルから起動した python の PATH に無いだけで、タイトルが古い埋め込みリストで
  組まれていた。グローバル規約は「実行時に必ずPDFを読む / 読めなければ即報告」なので、
  黙って劣化した入力で走り続けるのは規約違反そのもの。
"""
from __future__ import annotations

import importlib.util
import os
import sys

_API = r"C:\dev\iMak\iMakeBayAPI"


def _load():
    spec = importlib.util.spec_from_file_location(
        "_hq_listing_core_pdf", os.path.join(_API, "listing_core.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    if _API not in sys.path:
        sys.path.insert(0, _API)
    spec.loader.exec_module(mod)
    return mod


LC = _load()

_GIT = r"C:\Program Files\Git\mingw64\bin\pdftotext.exe"


def test_falls_back_to_git_bundled_poppler(monkeypatch):
    """PATH に無くても Git 同梱の pdftotext を見つける。"""
    monkeypatch.setattr(LC.shutil if hasattr(LC, "shutil") else LC, "which",
                        lambda _n: None, raising=False)
    import shutil
    monkeypatch.setattr(shutil, "which", lambda _n: None)
    monkeypatch.setattr(os.path, "exists", lambda p: p == _GIT)
    assert LC.pdftotext_exe() == _GIT


def test_returns_none_when_really_absent(monkeypatch):
    """本当に無い時は None (存在しない実行ファイルを呼ばない)。"""
    import shutil
    monkeypatch.setattr(shutil, "which", lambda _n: None)
    monkeypatch.setattr(os.path, "exists", lambda _p: False)
    assert LC.pdftotext_exe() is None


def test_this_machine_can_actually_read_the_pdf():
    """この実機で PDF が読めること (読めない状態を『正常』にしない)。"""
    exe = LC.pdftotext_exe()
    assert exe, "pdftotext が見つからない — キーワードPDFを読めない状態"
    kws = LC.load_keyword_pdf("ichibankuji")
    assert kws, "Collectibles PDF から上位語が取れない"


def test_kuji_generator_uses_the_same_resolver():
    """一番くじ側も同じ解決口を使う (PATH 判定を二重実装しない)。"""
    src = open(r"C:\dev\iMak\iMak_ichibankuji\ichibankuji_to_csv.py",
               encoding="utf-8", errors="replace").read()
    assert "from listing_core import pdftotext_exe" in src
    assert 'if not _shutil.which("pdftotext")' not in src
