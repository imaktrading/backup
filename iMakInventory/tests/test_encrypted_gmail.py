"""auth.encrypted_gmail の regression test."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def isolated_gmail_file(tmp_path, monkeypatch):
    from auth import encrypted_gmail
    monkeypatch.setattr(encrypted_gmail, "ENCRYPTED_GMAIL_FILE", tmp_path / ".encrypted_gmail.dat")
    return encrypted_gmail


def test_save_and_load_roundtrip(isolated_gmail_file):
    g = isolated_gmail_file
    g.save_gmail_config("a@example.com", "abcdefghijklmnop", "b@example.com")
    cfg = g.load_gmail_config()
    assert cfg is not None
    address, app_pw, to = cfg
    assert address == "a@example.com"
    assert app_pw == "abcdefghijklmnop"
    assert to == "b@example.com"


def test_app_password_spaces_stripped(isolated_gmail_file):
    """Gmail 公式の表記 (4 文字 x 4 グループ、スペース区切り) を投入しても
    保存時にスペース除去される (運用安定性のため)."""
    g = isolated_gmail_file
    g.save_gmail_config("a@example.com", "abcd efgh ijkl mnop", "b@example.com")
    cfg = g.load_gmail_config()
    assert cfg is not None
    _, app_pw, _ = cfg
    assert app_pw == "abcdefghijklmnop"


def test_load_returns_none_when_file_absent(isolated_gmail_file):
    g = isolated_gmail_file
    assert g.load_gmail_config() is None
    assert g.has_gmail_config() is False


def test_delete(isolated_gmail_file):
    g = isolated_gmail_file
    g.save_gmail_config("a@example.com", "abcdefghijklmnop", "b@example.com")
    assert g.has_gmail_config()
    assert g.delete_gmail_config() is True
    assert not g.has_gmail_config()
    # 二度目の delete は False
    assert g.delete_gmail_config() is False


def test_save_rejects_empty(isolated_gmail_file):
    g = isolated_gmail_file
    with pytest.raises(ValueError):
        g.save_gmail_config("", "abcdefghijklmnop", "b@example.com")
    with pytest.raises(ValueError):
        g.save_gmail_config("a@example.com", "", "b@example.com")
    with pytest.raises(ValueError):
        g.save_gmail_config("a@example.com", "abcdefghijklmnop", "")
