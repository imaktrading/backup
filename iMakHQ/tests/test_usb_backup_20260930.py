# -*- coding: utf-8 -*-
"""USB に写す一式に、クラウドに置かない鍵と復旧手順が入っていること (2026-09-30)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import usb_backup as U  # noqa: E402


def test_plan_has_secrets_and_restore_kit(tmp_path, monkeypatch):
    (tmp_path / "cred").mkdir()
    (tmp_path / "cred" / "k.txt").write_text("x")
    (tmp_path / "sa.json").write_text("{}")
    (tmp_path / "kit").mkdir()
    (tmp_path / "kit" / "README.md").write_text("r")
    (tmp_path / "daily").mkdir()
    (tmp_path / "daily" / "iMak_daily_20260930_0500.zip").write_bytes(b"")
    monkeypatch.setattr(U, "SECRETS", [str(tmp_path / "cred"), str(tmp_path / "sa.json")])
    monkeypatch.setattr(U, "RESTORE_KIT", str(tmp_path / "kit"))
    monkeypatch.setattr(U, "DAILY", str(tmp_path / "daily"))
    rels = {r.replace("\\", "/") for _, r in U.plan()}
    assert rels == {"secrets/cred/k.txt", "secrets/sa.json", "restore_kit/README.md", "iMak_daily_20260930_0500.zip"}


def test_gemini_key_is_listed():
    """監査くんの Gemini 鍵もUSBに写す (コミット文だけで入っていなかった)。"""
    assert any(p.endswith(r"iMakAudit\gemini_key.txt") for p in U.SECRETS)
