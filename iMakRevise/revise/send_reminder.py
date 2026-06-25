# -*- coding: utf-8 -*-
"""リバイス作業 推進リマインダーメール (週1).

Gmail SMTP (SMTP_SSL) で自分宛にリマインダーを送るだけ。
revise の実行はしない (= 人手で control_panel から dry-run → 目視 → 手動UP)。

資格情報は監視くんと共有の DPAPI 暗号化 blob を共有リーダー経由で読む (二重管理なし):
    C:/dev/iMak_data/secrets/gmail_config_reader.py -> load_shared_gmail_config()
復号失敗 (別ユーザー/別マシン/blob不在) は send skip でフェイルセーフ。

Usage:
    python send_reminder.py            # 実送信
    python send_reminder.py --dry-run  # 送信せず本文を表示
"""
from __future__ import annotations

import argparse
import smtplib
import ssl
import sys
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

SHARED_SECRETS_DIR = r"C:/dev/iMak_data/secrets"
JST = timezone(timedelta(hours=9))
LOG_PATH = Path(__file__).resolve().parent.parent / "decision_log" / "reminder_send.log"

# 早朝のタスク起動時はネットワーク/DNS が未準備のことがあるためリトライ
MAX_ATTEMPTS = 5
RETRY_WAIT_SEC = 60


def _log(line: str) -> None:
    msg = f"{datetime.now(JST):%Y-%m-%d %H:%M:%S} {line}"
    print(msg)
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except OSError:
        pass


def load_config() -> dict | None:
    """共有 DPAPI blob から (sender, app_password, recipient) を読む。失敗時 None。"""
    sys.path.insert(0, SHARED_SECRETS_DIR)
    try:
        from gmail_config_reader import load_shared_gmail_config
    except ImportError:
        print(f"[reminder] 共有リーダーが見つかりません: {SHARED_SECRETS_DIR}")
        return None
    cfg = load_shared_gmail_config()
    if not cfg:
        print("[reminder] 資格情報の復号に失敗 (別ユーザー/別マシン/blob不在) → 送信 skip")
        return None
    address, app_password, to = cfg
    return {"sender": address, "app_password": app_password, "recipient": to or address}


def build_message(cfg: dict) -> EmailMessage:
    now = datetime.now(JST)
    msg = EmailMessage()
    msg["Subject"] = f"【リバイスくん】今週の価格リバイス実行リマインダー ({now:%m/%d %a})"
    msg["From"] = cfg["sender"]
    msg["To"] = cfg["recipient"]
    body = f"""\
リバイスくんからの週次リマインダーです ({now:%Y-%m-%d %H:%M} JST)。

■ 今週やること
  1. control_panel.py を起動 (sheets=HIGH,LOW,公式 / dry-run / review-xlsx)
  2. 出力された revise_review_*.xlsx を目視
       - 赤字(利益¥<0) が無いか
       - 異常検出flag が無いか
       - 大量revise (NOTICE) の中身が妥当か
  3. 問題なければ csv_output の 3本を FileExchange へ手動UP
       - revise_combined_*.csv          (single)
       - revise_variation_price_*.csv   (variation 価格)
       - revise_variation_shipping_*.csv(variation 送料)
       ※ *_diff_*.csv は確認用なのでUPしない
  4. FileExchange 結果CSV を集計し Error/Failure 0 を確認

※ このメールはリマインダーのみ。revise 自体は自動実行されません。
"""
    msg.set_content(body)
    return msg


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="送信せず本文を表示")
    args = ap.parse_args()

    cfg = load_config()

    if args.dry_run:
        cfg = cfg or {"sender": "(復号未確認)", "recipient": "(復号未確認)"}
        msg = build_message(cfg)
        print("[reminder] --dry-run (送信しません)")
        print("-" * 60)
        print(f"To: {msg['To']}\nSubject: {msg['Subject']}\n")
        print(msg.get_content())
        return 0

    if not cfg:
        return 1  # 復号失敗 = フェイルセーフで送信 skip

    msg = build_message(cfg)

    ctx = ssl.create_default_context()
    last_err = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=30) as server:
                server.login(cfg["sender"], cfg["app_password"])
                server.send_message(msg)
            _log(f"[reminder] 送信完了 → {msg['To']} (attempt {attempt}/{MAX_ATTEMPTS})")
            return 0
        except (OSError, smtplib.SMTPException) as e:
            last_err = e
            _log(f"[reminder] 送信失敗 attempt {attempt}/{MAX_ATTEMPTS}: {e}")
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_WAIT_SEC)
    _log(f"[reminder] 全 {MAX_ATTEMPTS} attempt 失敗 → 送信できず: {last_err}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
