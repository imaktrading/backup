# -*- coding: utf-8 -*-
"""共有データ (iMak_data) の毎朝バックアップ (2026-09-17)。

背景: SSD 不調でブルースクリーンが続いた。iMak_data は git 管理外で複製がどこにも無かった。
守るもの: 取り直せる大物 (画像キャッシュ等) と秘密情報を入れない / 失敗と止まりを Console に出す。
"""
import datetime
import os
import sys

_HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (os.path.join(_HQ, "tools"), os.path.join(_HQ, "console")):
    if p not in sys.path:
        sys.path.insert(0, p)

import data_backup as B  # noqa: E402
import server  # noqa: E402


def test_excludes_regettable_and_secrets():
    for rel in ("secrets", "credentials", "chrome_profile_psa", r"dedupe\img_cache",
                r"catalog\_opcg_official_dumps", r"catalog\_opcg_official_dumps.bak_20260917_085550"):
        assert B._excluded_dir(rel), rel
    assert not B._excluded_dir("_backlog")
    assert not B._excluded_dir(r"hq\requests")


def test_excludes_live_db_files_and_backups():
    # DB は backup API で別に写す (使用中のファイルを zip に直接入れない)
    for n in ("products.sqlite", "products.sqlite-wal", "products.sqlite.bak_20260917", "x.jpg"):
        assert B._excluded_file(n, 10), n
    assert B._excluded_file("big.json", 60 * 1024 * 1024) == "size"
    assert B._excluded_file("2026-09-17_x_response.md", 10) == ""


def test_notice_ok_failed_stale_missing():
    now = datetime.datetime(2026, 9, 17, 12, 0)
    assert server.backup_notice({"ok": True, "at": "2026-09-17T05:00:00"}, now) == ""
    assert "失敗" in server.backup_notice({"ok": False, "error": "G: が無い"}, now)
    assert "更新されていません" in server.backup_notice({"ok": True, "at": "2026-09-15T05:00:00"}, now)
    assert "結果がありません" in server.backup_notice(None, now)
