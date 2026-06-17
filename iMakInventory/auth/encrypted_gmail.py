"""encrypted_gmail - Gmail App Password を Windows DPAPI で暗号化保存 / 復号.

cycle 完了通知メール (4h おき 1日6通) のため、Gmail SMTP の認証情報を
構造的に安全に保存する。設計は auth/encrypted_passwd.py (eBay 用) と同パターン。

設計原則:
- **opt-in**: encrypted_gmail.dat ファイルが存在する場合のみメール送信。
  無ければ送信 skip (= 既存挙動完全保持)
- **同一ユーザー + 同一マシン**でのみ復号可能 (DPAPI 仕様)
- 平文で memory 上にしか持たない
- eBay 用 encrypted_passwd.dat と完全分離 (干渉しない)

ファイル仕様:
- 場所: <ROOT>/decision_log/.encrypted_gmail.dat
- フォーマット: DPAPI で暗号化された JSON {"address": ..., "app_password": ..., "to": ...}
  - address: 送信元 Gmail アドレス
  - app_password: Gmail App Password (16 文字)
  - to: 送信先 (= 通知の受け取り先、address と同じでも別でも OK)
- decision_log/ 全体が .gitignore 対象なので commit 除外済

使い方:
    from auth.encrypted_gmail import save_gmail_config, load_gmail_config, delete_gmail_config

    # 初回セットアップ (tools/setup_email.py から呼出)
    save_gmail_config("imax2303@gmail.com", "abcdefghijklmnop", "imax2303@gmail.com")

    # cycle 終了時のメール送信
    cfg = load_gmail_config()
    if cfg:
        address, app_password, to = cfg
        # smtplib で送信 ...

    # ロールバック
    delete_gmail_config()
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
ENCRYPTED_GMAIL_FILE = ROOT / "decision_log" / ".encrypted_gmail.dat"

# 共有領域 (2026-06-17 1本化): 全 worktree (監視くん / リバイスくん 等) が同一 Windows
# ユーザーで同じ Gmail App Password を共有する。 DPAPI はユーザー紐づけ (ファイル場所非依存)
# なので 暗号 blob をここに置けば 平文露出ゼロで 1 本化できる。 iMak_data は git 管理外。
SHARED_GMAIL_FILE = Path(r"C:/dev/iMak_data/secrets/.encrypted_gmail.dat")

DPAPI_DESCRIPTION = "iMakInventory Gmail SMTP credentials"


def _resolve_read_file() -> Path:
    """読取り元: 共有領域を優先、 無ければ local fallback (= 通知経路を壊さない)."""
    return SHARED_GMAIL_FILE if SHARED_GMAIL_FILE.exists() else ENCRYPTED_GMAIL_FILE


def _import_win32crypt():
    try:
        import win32crypt  # noqa: PLC0415
        return win32crypt
    except ImportError as e:
        raise RuntimeError(
            "win32crypt (pywin32) が必要です。pip install pywin32 でインストールしてください。"
        ) from e


def save_gmail_config(address: str, app_password: str, to: str) -> Path:
    """Gmail SMTP 認証情報を DPAPI 暗号化して保存。

    Args:
        address: 送信元 Gmail アドレス
        app_password: Gmail App Password (16 文字、スペース含むまま OK)
        to: 通知メールの送信先

    Returns: 保存先 Path
    """
    if not address or not app_password or not to:
        raise ValueError("address / app_password / to が空です")

    # App Password 内のスペースは Gmail 受理時に無視されるので除去して保存 (運用安定性のため)
    app_password = app_password.replace(" ", "")

    win32crypt = _import_win32crypt()
    payload = json.dumps(
        {"address": address, "app_password": app_password, "to": to},
        ensure_ascii=False,
    ).encode("utf-8")
    blob = win32crypt.CryptProtectData(
        payload,
        DPAPI_DESCRIPTION,
        None, None, None, 0,
    )
    # 共有領域を primary に書く (= App Password 再発行時、 全 worktree が新値を読む 1 本化)。
    # local にも書いて fallback を維持 (共有領域が一時的に読めなくても通知が止まらない)。
    SHARED_GMAIL_FILE.parent.mkdir(parents=True, exist_ok=True)
    SHARED_GMAIL_FILE.write_bytes(blob)
    ENCRYPTED_GMAIL_FILE.parent.mkdir(parents=True, exist_ok=True)
    ENCRYPTED_GMAIL_FILE.write_bytes(blob)
    return SHARED_GMAIL_FILE


def load_gmail_config() -> Optional[Tuple[str, str, str]]:
    """暗号化ファイルから (address, app_password, to) を復号。

    Returns:
        (address, app_password, to) のタプル。ファイル不在 / 復号失敗時は None。
    """
    read_file = _resolve_read_file()
    if not read_file.exists():
        return None
    try:
        win32crypt = _import_win32crypt()
        blob = read_file.read_bytes()
        _desc, payload = win32crypt.CryptUnprotectData(
            blob, None, None, None, 0,
        )
        d = json.loads(payload.decode("utf-8"))
        address = d.get("address")
        app_password = d.get("app_password")
        to = d.get("to")
        if not address or not app_password or not to:
            return None
        return (address, app_password, to)
    except Exception:
        return None


def has_gmail_config() -> bool:
    return load_gmail_config() is not None


def delete_gmail_config() -> bool:
    """共有 + local 両方の暗号ファイルを削除 (= 完全ロールバック)."""
    deleted = False
    for f in (SHARED_GMAIL_FILE, ENCRYPTED_GMAIL_FILE):
        if f.exists():
            f.unlink()
            deleted = True
    return deleted
