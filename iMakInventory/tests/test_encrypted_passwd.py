"""auth.encrypted_passwd の regression test.

DPAPI を実際に使うが、暗号化された blob は同一ユーザー (= 開発機) で復号可能。
テスト中は tmp_path に保存するので本番 file には影響しない。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def isolated_passwd_file(tmp_path, monkeypatch):
    """ENCRYPTED_PASSWD_FILE を tmp に隔離し、本番 file を汚染しない."""
    from auth import encrypted_passwd
    monkeypatch.setattr(encrypted_passwd, "ENCRYPTED_PASSWD_FILE", tmp_path / ".encrypted_passwd.dat")
    return encrypted_passwd


def test_save_and_load_roundtrip(isolated_passwd_file):
    """save → load で同じ値が復元される."""
    ep = isolated_passwd_file
    ep.save_credentials("test@example.com", "p@ssw0rd!#$%")
    creds = ep.load_credentials()
    assert creds is not None
    email, password = creds
    assert email == "test@example.com"
    assert password == "p@ssw0rd!#$%"


def test_load_returns_none_when_file_absent(isolated_passwd_file):
    """ファイル不在時は None を返す (= fallback path 確保)."""
    ep = isolated_passwd_file
    assert ep.load_credentials() is None
    assert ep.has_credentials() is False


def test_save_rejects_empty_values(isolated_passwd_file):
    """空文字を渡したら ValueError."""
    ep = isolated_passwd_file
    with pytest.raises(ValueError):
        ep.save_credentials("", "password")
    with pytest.raises(ValueError):
        ep.save_credentials("email", "")


def test_has_credentials_after_save(isolated_passwd_file):
    """save 後に has_credentials が True、delete 後に False."""
    ep = isolated_passwd_file
    assert ep.has_credentials() is False
    ep.save_credentials("a@b.com", "pw")
    assert ep.has_credentials() is True
    deleted = ep.delete_credentials()
    assert deleted is True
    assert ep.has_credentials() is False


def test_delete_returns_false_when_file_absent(isolated_passwd_file):
    ep = isolated_passwd_file
    assert ep.delete_credentials() is False


def test_japanese_password(isolated_passwd_file):
    """日本語パスワードでも roundtrip が壊れない (= UTF-8 互換)."""
    ep = isolated_passwd_file
    ep.save_credentials("日本語@example.com", "パスワード123!@#")
    email, password = ep.load_credentials()
    assert email == "日本語@example.com"
    assert password == "パスワード123!@#"


def test_corrupted_file_returns_none(isolated_passwd_file, tmp_path):
    """壊れた blob を直接書込んでも、復号失敗で None を返す (= 例外漏れない)."""
    ep = isolated_passwd_file
    ep.ENCRYPTED_PASSWD_FILE.write_bytes(b"this is not a valid DPAPI blob, just garbage")
    assert ep.load_credentials() is None  # 例外漏れず None


def test_load_with_partial_payload(isolated_passwd_file):
    """payload に email or password が欠けたら None (= 防御層)."""
    ep = isolated_passwd_file
    # email だけ入れた blob を作る
    import json as _json
    import win32crypt
    payload = _json.dumps({"email": "only_email@example.com"}).encode("utf-8")
    blob = win32crypt.CryptProtectData(payload, ep.DPAPI_DESCRIPTION, None, None, None, 0)
    ep.ENCRYPTED_PASSWD_FILE.write_bytes(blob)
    assert ep.load_credentials() is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
