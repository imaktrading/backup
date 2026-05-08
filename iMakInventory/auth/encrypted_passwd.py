"""encrypted_passwd - eBay credentials を Windows DPAPI で暗号化保存 / 復号.

事故 2026-05-04 / 2026-05-06 (eBay session 切れ silent 失敗) を構造的に
解決するため、毎 cycle 自動 login (= trabajo 同等) を実現する基盤。

設計原則:
- **opt-in**: encrypted_passwd.dat ファイルが存在する場合のみ自動入力。
  無ければ従来の手動 prompt manual_login() に fallback (= 既存挙動完全保持)
- **同一ユーザー + 同一マシン**でのみ復号可能 (DPAPI 仕様、漏洩時の最低限の保険)
- chrome の Login Data に依存しない (chrome version 跨ぎでも安定、trabajo 越え)
- 平文で memory 上にしか持たない (= 不要時に即破棄)

ファイル仕様:
- 場所: <ROOT>/decision_log/.encrypted_passwd.dat
- フォーマット: DPAPI で暗号化された JSON {"email": ..., "password": ...}
- .gitignore で commit から除外済 (**/.encrypted_passwd.dat)

使い方:
    from auth.encrypted_passwd import save_credentials, load_credentials, has_credentials, delete_credentials

    # 初回セットアップ (ユーザー手動実行)
    save_credentials("imax2303@gmail.com", "your_password_here")

    # 自動 login 時 (sell_feed_uploader から呼出)
    creds = load_credentials()
    if creds:
        email, password = creds
        # Selenium で email/password 自動入力 ...

    # ロールバック (= 即旧挙動に戻す)
    delete_credentials()
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Tuple

# ファイル保存場所 (decision_log/ 配下、.gitignore 対象)
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
ENCRYPTED_PASSWD_FILE = ROOT / "decision_log" / ".encrypted_passwd.dat"

# DPAPI description (識別用、平文で blob に埋め込まれる、機微情報含めない)
DPAPI_DESCRIPTION = "iMakInventory eBay credentials"


def _import_win32crypt():
    """win32crypt を遅延 import (Windows 以外でも import 文がエラー出さないように)."""
    try:
        import win32crypt  # noqa: PLC0415
        return win32crypt
    except ImportError as e:
        raise RuntimeError(
            "win32crypt (pywin32) が必要です。pip install pywin32 でインストールしてください。"
        ) from e


def save_credentials(email: str, password: str) -> Path:
    """email + password を DPAPI 暗号化して保存。

    Args:
        email: eBay ログイン用 email
        password: 平文パスワード (= 暗号化前)

    Returns: 保存先 Path
    """
    if not email or not password:
        raise ValueError("email / password が空です")

    win32crypt = _import_win32crypt()
    payload = json.dumps({"email": email, "password": password}, ensure_ascii=False).encode("utf-8")
    blob = win32crypt.CryptProtectData(
        payload,
        DPAPI_DESCRIPTION,
        None,    # OptionalEntropy: 追加のシード、None で OK
        None,    # Reserved
        None,    # PromptStruct
        0,       # Flags: CRYPTPROTECT_UI_FORBIDDEN なし (= UI 無し、自動)
    )
    ENCRYPTED_PASSWD_FILE.parent.mkdir(parents=True, exist_ok=True)
    ENCRYPTED_PASSWD_FILE.write_bytes(blob)
    return ENCRYPTED_PASSWD_FILE


def load_credentials() -> Optional[Tuple[str, str]]:
    """暗号化ファイルから email + password を復号。

    Returns:
        (email, password) のタプル。ファイル不在 / 復号失敗時は None。
    """
    if not ENCRYPTED_PASSWD_FILE.exists():
        return None
    try:
        win32crypt = _import_win32crypt()
        blob = ENCRYPTED_PASSWD_FILE.read_bytes()
        _desc, payload = win32crypt.CryptUnprotectData(
            blob,
            None,    # OptionalEntropy
            None,    # Reserved
            None,    # PromptStruct
            0,       # Flags
        )
        d = json.loads(payload.decode("utf-8"))
        email = d.get("email")
        password = d.get("password")
        if not email or not password:
            return None
        return (email, password)
    except Exception:
        # 復号失敗 (= 別ユーザー / 別マシン / 破損) → None で fallback
        return None


def has_credentials() -> bool:
    """credentials ファイルが存在し、かつ復号可能か。"""
    return load_credentials() is not None


def delete_credentials() -> bool:
    """credentials ファイルを削除 (= 即時ロールバック手段)。

    Returns: 削除した場合 True、ファイル不在なら False。
    """
    if ENCRYPTED_PASSWD_FILE.exists():
        ENCRYPTED_PASSWD_FILE.unlink()
        return True
    return False
