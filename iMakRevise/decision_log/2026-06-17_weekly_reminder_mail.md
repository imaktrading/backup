# 2026-06-17 週次リバイス推進リマインダーメール

## 概要
週1で「価格リバイスを実行して」というリマインダーメールを自分宛に送る仕組みを追加。
revise 自体は自動化せず、人手 dry-run → 目視 → 手動UP の運用を維持 (リマインダーのみ)。

## 記録
- 決定: リバイス作業の推進リマインダーを週1メールで通知 (毎週月曜 06:00)。内容はリマインダーのみ、revise 自動実行はしない。
- 決定: Gmail 資格情報は監視くんと共有の DPAPI 暗号化 blob を共有リーダー経由で読む (平文を置かない・二重管理しない)。依頼書経由で監視くんが共有領域に配置。
- 変更: `revise/send_reminder.py` (新規) — 共有リーダー `C:/dev/iMak_data/secrets/gmail_config_reader.py` を import、SMTP_SSL で送信。復号失敗時は送信 skip (fail-safe)。
- 変更: `tools/register_reminder_task.ps1` (新規) — Task Scheduler に `iMakRevise_WeeklyReminder` を週1 (月 06:00) 登録/削除/状態確認。
- 検証: 共有 blob 復号 OK (pw 16桁取得)。`send_reminder.py` 実送信 → 受信確認済 (ユーザー「届いた」)。
- 検証: タスク登録後 Status = Ready / NextRunTime = 2026-06-22 06:00 を確認。

## 連携
- 依頼: `iMak_data/inventory/requests/2026-06-17_shared_mail_config_for_revise_reminder.md`
- 回答: 同 `_response.md` (監視くんが DPAPI blob 共有方式で対応完了、回帰テスト27件pass)
